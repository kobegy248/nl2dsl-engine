"""LangGraph node functions for the NL2DSL query pipeline.

Each node is a pure function: QueryState -> dict (returns only fields it modifies).
The @with_error_handler decorator catches exceptions and converts them to error states.
"""

from __future__ import annotations

import functools
import json
import re
import time
from typing import Callable

from nl2dsl.dsl.models import DSL, Aggregation, Filter, Join, OrderBy
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import NL2DSLException, ValidationError
from nl2dsl.graph.state import QueryState
from nl2dsl.query.clarification import ClarificationDetector
from nl2dsl.query.sandbox import QuerySandbox
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.utils.logger import get_logger

logger = get_logger("graph.nodes")


# ---------------------------------------------------------------------------
# Error handler decorator
# ---------------------------------------------------------------------------


def with_error_handler(node_name: str):
    """Decorator that catches NL2DSLException and generic Exception,
    converting them to error state dicts.
    """

    def decorator(func: Callable[[QueryState], dict]) -> Callable[[QueryState], dict]:
        @functools.wraps(func)
        def wrapper(state: QueryState) -> dict:
            try:
                return func(state)
            except NL2DSLException as exc:
                logger.error("[%s] NL2DSLException: %s - %s", node_name, exc.error_code, exc.message)
                return {
                    "status": "error",
                    "error": exc.message,
                    "error_code": exc.error_code,
                    "trace": {
                        "step": node_name,
                        "status": "error",
                        "error_code": exc.error_code,
                        "error_message": exc.message,
                    },
                }
            except Exception as exc:
                logger.error("[%s] Unexpected exception: %s", node_name, exc, exc_info=True)
                return {
                    "status": "error",
                    "error": str(exc),
                    "error_code": "INTERNAL_ERROR",
                    "trace": {
                        "step": node_name,
                        "status": "error",
                        "error_code": "INTERNAL_ERROR",
                        "error_message": str(exc),
                    },
                }

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Helper functions (moved from api.py)
# ---------------------------------------------------------------------------


def _build_fallback_prompt(question: str) -> str:
    """Build a fallback prompt without RAG context."""
    return f"""【表结构】
- 数据源: orders (对应表 order_fact), 字段: id, product_id, product_name, brand, category, region, channel, customer_id, customer_type, order_amount, discount_amount, pay_amount, quantity, order_date, tenant_id
- 数据源: products (对应表 product_dim), 字段: product_id, product_name, brand, category, price
- 数据源: customers (对应表 customer_dim), 字段: customer_id, customer_name, customer_type, register_date, region

【可用指标】
- sales_amount: SUM(pay_amount), 销售额（实付金额合计）
- gmv: SUM(order_amount), 成交总额
- order_count: COUNT(id), 订单数量
- avg_order_value: AVG(pay_amount), 客单价
- total_discount: SUM(discount_amount), 优惠总额

【可用维度】
- product_name, brand, category, region, channel, customer_type, order_date, customer_name

【重要规则】
1. data_source 必须是 "orders"，不要写表名
2. metrics 的 alias 必须是已注册的指标名（如 sales_amount, gmv 等）
3. 不要输出任何解释文字，只输出 JSON

【用户问题】
{question}

请输出 DSL JSON："""


def _parse_llm_output(raw: str) -> dict:
    """Clean up LLM response (remove markdown code fences) and parse JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[cleaned.find("\n") + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("\n")]
    cleaned = cleaned.replace("json\n", "").strip()
    return json.loads(cleaned)


def _post_process_dsl(dsl_dict: dict, default_data_source: str = "orders") -> dict:
    """Post-process and fix common LLM-generated DSL issues."""
    # 1. Ensure data_source is valid
    if "data_source" not in dsl_dict or dsl_dict["data_source"] not in ["orders", "products", "customers"]:
        dsl_dict["data_source"] = default_data_source

    # 2. Ensure metrics is non-empty list
    metrics = dsl_dict.get("metrics")
    if not metrics:
        dsl_dict["metrics"] = [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}]

    # 3. Normalize metric fields: strip SUM/AVG/COUNT/MAX/MIN wrappers
    for m in dsl_dict.get("metrics", []):
        field = m.get("field", "")
        if isinstance(field, str):
            match = re.match(r"^[A-Z]+\((.+)\)$", field.strip())
            if match:
                m["field"] = match.group(1)

    # 4. Ensure dimensions is non-empty list
    dimensions = dsl_dict.get("dimensions")
    if not dimensions:
        dsl_dict["dimensions"] = ["product_name"]

    # 5. Ensure limit is reasonable
    limit = dsl_dict.get("limit")
    if limit is None or not isinstance(limit, int) or limit <= 0:
        dsl_dict["limit"] = 10
    elif limit > 100:
        dsl_dict["limit"] = 100

    # 6. Ensure offset exists
    if "offset" not in dsl_dict:
        dsl_dict["offset"] = 0

    # 7. Ensure order_by exists when metrics exist
    order_by = dsl_dict.get("order_by")
    metrics_list = dsl_dict.get("metrics", [])
    if not order_by and metrics_list:
        first_alias = metrics_list[0].get("alias") or metrics_list[0].get("field")
        if first_alias:
            dsl_dict["order_by"] = [{"field": first_alias, "direction": "desc"}]

    # 8. Validate filters operator values
    valid_ops = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "between", "is_null"}
    for f in dsl_dict.get("filters", []):
        op = f.get("operator", "")
        if op not in valid_ops:
            f["operator"] = "="

    return dsl_dict


def _mock_dsl_from_question(question: str, data_source: str | None = None) -> DSL:
    """Generate a mock DSL based on question keywords (no LLM key needed).

    Supports multi-table joins and handles vague semantic queries.
    """
    ds = data_source or "orders"
    metrics = []
    dimensions = []
    filters = []
    order_by = []
    joins = []
    limit = 10

    q = question.lower()

    # Detect join intent (vague semantic patterns)
    join_indicators = {
        "customer_dim": ["客户", "customer", "用户", "user", "买家", "高价值", "VIP", "会员"],
        "product_dim": ["品牌", "brand", "品类", "category", "产品详情", "单价", "price"],
    }

    for table_name, indicators in join_indicators.items():
        if any(kw in question for kw in indicators):
            if table_name == "customer_dim":
                joins.append(Join(table="customer_dim", on_field="customer_id", join_type="left", alias="c"))
            elif table_name == "product_dim":
                joins.append(Join(table="product_dim", on_field="product_id", join_type="inner", alias="p"))

    # Metrics (handle vague semantic queries)
    if any(kw in question for kw in ["销售额", "sales", "业绩", "营收", "收入"]):
        metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))
    elif any(kw in q for kw in ["gmv", "成交总额", "交易额"]):
        metrics.append(Aggregation(func="sum", field="order_amount", alias="gmv"))
    elif any(kw in q for kw in ["订单量", "订单数", "单量", "order count"]):
        metrics.append(Aggregation(func="count", field="id", alias="order_count"))
    elif any(kw in q for kw in ["客单价", "平均订单", "avg order"]):
        metrics.append(Aggregation(func="avg", field="pay_amount", alias="avg_order_value"))
    elif any(kw in q for kw in ["客户数", "用户数", "人数", "customer count"]):
        metrics.append(Aggregation(func="count", field="customer_id", alias="customer_count"))
    elif any(kw in q for kw in ["优惠", "折扣", "discount"]):
        metrics.append(Aggregation(func="sum", field="discount_amount", alias="total_discount"))
    else:
        # Vague query: default to sales
        metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))

    # Dimensions (with cross-table support)
    if "品牌" in question or "brand" in q:
        dimensions.append("brand")
    if "品类" in question or "category" in q:
        dimensions.append("category")
    if "产品" in question or "product" in q:
        dimensions.append("product_name")
    if "地区" in question or "区域" in question or "region" in q:
        dimensions.append("region")
    if "时间" in question or "日期" in question or "date" in q:
        dimensions.append("order_date")
    if "渠道" in question or "channel" in q or "销售方式" in question:
        dimensions.append("channel")
    if any(kw in question for kw in ["客户", "customer", "用户", "user", "买家"]):
        if not any(j.table == "customer_dim" for j in joins):
            joins.append(Join(table="customer_dim", on_field="customer_id", join_type="left", alias="c"))
        if "客户名" in question or "customer_name" in q or "名称" in question:
            dimensions.append("customer_name")
        else:
            dimensions.append("customer_type")

    if not dimensions:
        dimensions.append("product_name")

    # Filters
    if "华东" in question:
        filters.append(Filter(field="region", operator="=", value="华东"))
    if "华南" in question:
        filters.append(Filter(field="region", operator="=", value="华南"))
    if "华北" in question:
        filters.append(Filter(field="region", operator="=", value="华北"))
    if "西南" in question:
        filters.append(Filter(field="region", operator="=", value="西南"))
    if "线上" in question:
        filters.append(Filter(field="channel", operator="=", value="线上"))
    if "线下" in question:
        filters.append(Filter(field="channel", operator="=", value="线下"))
    if "分销" in question:
        filters.append(Filter(field="channel", operator="=", value="分销"))

    # Vague semantic filter: "高价值" -> filter for VIP + high amount
    if "高价值" in question or "高价值" in q:
        filters.append(Filter(field="customer_type", operator="=", value="VIP"))
        filters.append(Filter(field="pay_amount", operator=">=", value=5000))

    # Vague semantic filter: "新客" / "老客" / "VIP"
    if "新客" in question or "新客户" in question:
        filters.append(Filter(field="customer_type", operator="=", value="新客"))
    elif "老客" in question or "老客户" in question:
        filters.append(Filter(field="customer_type", operator="=", value="老客"))
    elif "VIP" in question.upper():
        filters.append(Filter(field="customer_type", operator="=", value="VIP"))

    # Order by
    if metrics:
        order_by.append(OrderBy(field=metrics[0].alias or metrics[0].field, direction="desc"))

    # Limit
    if "top" in q or "最高" in question or "最多" in question:
        limit = 10
    elif "全部" in question or "所有" in question:
        limit = 100

    return DSL(
        metrics=metrics,
        dimensions=dimensions,
        filters=filters or None,
        order_by=order_by or None,
        limit=limit,
        data_source=ds,
        joins=joins or None,
    )


def _restore_metric_fields(dsl: DSL) -> DSL:
    """After SemanticResolver replaces metric.field with expr like SUM(col),
    restore the raw column name so SQLBuilder can look it up.
    """
    if not dsl.metrics:
        return dsl
    restored = []
    for m in dsl.metrics:
        field = m.field
        match = re.match(r"^[A-Z]+\((.+?)\)$", field, re.IGNORECASE)
        if match:
            field = match.group(1)
        restored.append(m.model_copy(update={"field": field}))
    return dsl.model_copy(update={"metrics": restored})


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------


def create_node_functions(
    *,
    llm_client,
    rag_retriever,
    validator: DSLValidator,
    row_security: RowLevelSecurity,
    col_security: ColumnLevelSecurity,
    resolver: SemanticResolver,
    sql_builder: SQLBuilder,
    scanner: SQLScanner,
    sandbox: QuerySandbox,
    executor: SQLExecutor,
    clarification_detector: ClarificationDetector,
    llm_system_prompt: str = "",
) -> dict[str, Callable[[QueryState], dict]]:
    """Factory that creates all node functions with injected dependencies.

    Each node returns a dict of state fields to update.
    """

    # -----------------------------------------------------------------------
    # clarification_node
    # -----------------------------------------------------------------------
    @with_error_handler("clarification")
    def clarification_node(state: QueryState) -> dict:
        ambiguities = clarification_detector.detect(state["question"])
        if ambiguities:
            return {
                "ambiguities": ambiguities,
                "status": "clarification",
                "trace": {"step": "clarification", "status": "success", "items_count": len(ambiguities)},
            }
        return {
            "ambiguities": None,
            "trace": {"step": "clarification", "status": "success", "items_count": 0},
        }

    # -----------------------------------------------------------------------
    # generate_dsl_node (LLM path - does NOT fallback to mock on failure)
    # -----------------------------------------------------------------------
    @with_error_handler("generate_dsl")
    def generate_dsl_node(state: QueryState) -> dict:
        question = state["question"]
        data_source = state.get("data_source")

        if llm_client is None:
            raise ValidationError("LLM client not available")

        if rag_retriever is not None:
            prompt = rag_retriever.build_prompt(question)
        else:
            prompt = _build_fallback_prompt(question)

        raw = llm_client.generate(prompt, llm_system_prompt)
        if not raw:
            raise ValidationError("LLM returned empty response")

        dsl_dict = _parse_llm_output(raw)
        dsl_dict = _post_process_dsl(dsl_dict, data_source or "orders")
        dsl = DSL.model_validate(dsl_dict)

        return {
            "dsl": dsl,
            "llm_used": True,
            "dsl_attempts": {
                "source": "llm",
                "dsl": dsl.model_dump(),
                "timestamp": time.time(),
            },
            "trace": {"step": "generate_dsl", "status": "success", "source": "llm"},
        }

    # -----------------------------------------------------------------------
    # mock_dsl_node (separate mock path)
    # -----------------------------------------------------------------------
    @with_error_handler("mock_dsl")
    def mock_dsl_node(state: QueryState) -> dict:
        dsl = _mock_dsl_from_question(state["question"], state.get("data_source"))
        return {
            "dsl": dsl,
            "llm_used": False,
            "dsl_attempts": {
                "source": "mock",
                "dsl": dsl.model_dump(),
                "timestamp": time.time(),
            },
            "trace": {"step": "mock_dsl", "status": "success", "source": "mock"},
        }

    # -----------------------------------------------------------------------
    # validate_dsl_node
    # -----------------------------------------------------------------------
    @with_error_handler("validate_dsl")
    def validate_dsl_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot validate")
        validator.validate(dsl)
        return {"trace": {"step": "validate_dsl", "status": "success"}}

    # -----------------------------------------------------------------------
    # correct_dsl_node (regenerates with error feedback)
    # -----------------------------------------------------------------------
    @with_error_handler("correct_dsl")
    def correct_dsl_node(state: QueryState) -> dict:
        """Regenerate DSL with error feedback from previous attempts.

        Uses LLM if available, otherwise falls back to mock with a warning.
        """
        question = state["question"]
        data_source = state.get("data_source")
        error = state.get("error")

        if llm_client is not None:
            feedback = f"""Previous generation failed with error: {error}

Please fix the errors and generate a correct DSL JSON.

【用户问题】
{question}

请输出 DSL JSON："""
            raw = llm_client.generate(feedback, llm_system_prompt)
            if raw:
                dsl_dict = _parse_llm_output(raw)
                dsl_dict = _post_process_dsl(dsl_dict, data_source or "orders")
                dsl = DSL.model_validate(dsl_dict)
                return {
                    "dsl": dsl,
                    "dsl_attempts": {
                        "source": "llm_corrected",
                        "dsl": dsl.model_dump(),
                        "timestamp": time.time(),
                        "error_feedback": error,
                    },
                    "trace": {"step": "correct_dsl", "status": "success", "source": "llm_corrected"},
                }

        # Fallback: try mock with a note that it was corrected
        dsl = _mock_dsl_from_question(question, data_source)
        return {
            "dsl": dsl,
            "dsl_attempts": {
                "source": "mock_corrected",
                "dsl": dsl.model_dump(),
                "timestamp": time.time(),
                "error_feedback": error,
            },
            "trace": {"step": "correct_dsl", "status": "success", "source": "mock_corrected"},
        }

    # -----------------------------------------------------------------------
    # inject_row_permission_node
    # -----------------------------------------------------------------------
    @with_error_handler("inject_row_permission")
    def inject_row_permission_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot inject row permissions")
        dsl = row_security.inject(dsl, state["user_id"])
        return {
            "dsl": dsl,
            "trace": {"step": "inject_row_permission", "status": "success"},
        }

    # -----------------------------------------------------------------------
    # check_col_permission_node
    # -----------------------------------------------------------------------
    @with_error_handler("check_col_permission")
    def check_col_permission_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot check column permissions")
        col_security.check(dsl, state["user_id"])
        return {"trace": {"step": "check_col_permission", "status": "success"}}

    # -----------------------------------------------------------------------
    # resolve_semantic_node
    # -----------------------------------------------------------------------
    @with_error_handler("resolve_semantic")
    def resolve_semantic_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot resolve semantics")
        dsl = resolver.resolve(dsl)
        return {
            "dsl": dsl,
            "trace": {"step": "resolve_semantic", "status": "success"},
        }

    # -----------------------------------------------------------------------
    # build_sql_node
    # -----------------------------------------------------------------------
    @with_error_handler("build_sql")
    def build_sql_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot build SQL")
        dsl_for_build = _restore_metric_fields(dsl)
        sql = sql_builder.build(dsl_for_build)
        return {
            "sql": sql,
            "trace": {"step": "build_sql", "status": "success"},
        }

    # -----------------------------------------------------------------------
    # scan_sql_node
    # -----------------------------------------------------------------------
    @with_error_handler("scan_sql")
    def scan_sql_node(state: QueryState) -> dict:
        sql = state.get("sql")
        if sql is None:
            raise ValidationError("SQL is None, cannot scan")
        scanner.scan(sql)
        return {"trace": {"step": "scan_sql", "status": "success"}}

    # -----------------------------------------------------------------------
    # sandbox_check_node
    # -----------------------------------------------------------------------
    @with_error_handler("sandbox_check")
    def sandbox_check_node(state: QueryState) -> dict:
        sql = state.get("sql")
        if sql is None:
            raise ValidationError("SQL is None, cannot run sandbox check")
        result = sandbox.check(sql)
        return {
            "sandbox_result": result,
            "trace": {
                "step": "sandbox_check",
                "status": "success" if result.passed else "warning",
                "passed": result.passed,
                "risks": result.risks,
            },
        }

    # -----------------------------------------------------------------------
    # human_review_node
    # -----------------------------------------------------------------------
    @with_error_handler("human_review")
    def human_review_node(state: QueryState) -> dict:
        """Mark query as pending human review.

        This is a placeholder node that sets the status to 'pending_review'.
        In a production system, this would trigger a notification/approval workflow.
        """
        sandbox_result = state.get("sandbox_result")
        risks = sandbox_result.risks if sandbox_result else ["Unknown risk"]
        return {
            "status": "pending_review",
            "trace": {
                "step": "human_review",
                "status": "pending_review",
                "reason": "sandbox_warnings",
                "risks": risks,
            },
        }

    # -----------------------------------------------------------------------
    # execute_sql_node
    # -----------------------------------------------------------------------
    @with_error_handler("execute_sql")
    def execute_sql_node(state: QueryState) -> dict:
        sql = state.get("sql")
        if sql is None:
            raise ValidationError("SQL is None, cannot execute")
        data = executor.execute(sql)
        return {
            "data": data,
            "status": "success",
            "trace": {"step": "execute_sql", "status": "success", "rows_returned": len(data)},
        }

    # -----------------------------------------------------------------------
    # simplify_dsl_node
    # -----------------------------------------------------------------------
    @with_error_handler("simplify_dsl")
    def simplify_dsl_node(state: QueryState) -> dict:
        """Simplify a complex DSL for re-attempt.

        Removes optional fields (joins, complex filters) to create a simpler
        DSL that is more likely to pass validation.
        """
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot simplify")

        # Create a simplified version: keep only first metric, first dimension
        simplified_metrics = dsl.metrics[:1] if dsl.metrics else None
        simplified_dimensions = dsl.dimensions[:1] if dsl.dimensions else None
        simplified_joins = None
        simplified_filters = None

        simplified = dsl.model_copy(
            update={
                "metrics": simplified_metrics,
                "dimensions": simplified_dimensions,
                "joins": simplified_joins,
                "filters": simplified_filters,
                "order_by": None,
                "limit": min(dsl.limit or 10, 10),
            }
        )

        return {
            "dsl": simplified,
            "dsl_attempts": {
                "source": "simplified",
                "dsl": simplified.model_dump(),
                "timestamp": time.time(),
                "original_dsl": dsl.model_dump() if dsl else None,
            },
            "trace": {"step": "simplify_dsl", "status": "success"},
        }

    return {
        "clarification_node": clarification_node,
        "generate_dsl_node": generate_dsl_node,
        "mock_dsl_node": mock_dsl_node,
        "validate_dsl_node": validate_dsl_node,
        "correct_dsl_node": correct_dsl_node,
        "inject_row_permission_node": inject_row_permission_node,
        "check_col_permission_node": check_col_permission_node,
        "resolve_semantic_node": resolve_semantic_node,
        "build_sql_node": build_sql_node,
        "scan_sql_node": scan_sql_node,
        "sandbox_check_node": sandbox_check_node,
        "human_review_node": human_review_node,
        "execute_sql_node": execute_sql_node,
        "simplify_dsl_node": simplify_dsl_node,
    }
