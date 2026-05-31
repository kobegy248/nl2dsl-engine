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

from nl2dsl.agent.confidence import _make_confidence_node
from nl2dsl.agent.explainer import _make_explain_node
from nl2dsl.agent.planner import _make_plan_node
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
                    "trace": [
                        {
                            "step": node_name,
                            "status": "error",
                            "error_code": exc.error_code,
                            "error_message": exc.message,
                        }
                    ],
                }
            except Exception as exc:
                logger.error("[%s] Unexpected exception: %s", node_name, exc, exc_info=True)
                return {
                    "status": "error",
                    "error": str(exc),
                    "error_code": "INTERNAL_ERROR",
                    "trace": [
                        {
                            "step": node_name,
                            "status": "error",
                            "error_code": "INTERNAL_ERROR",
                            "error_message": str(exc),
                        }
                    ],
                }

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Helper functions (moved from api.py)
# ---------------------------------------------------------------------------


def _build_fallback_prompt(question: str, registry_dict: dict | None = None) -> str:
    """Build a fallback prompt without RAG context, dynamically from registry."""
    if registry_dict is None:
        registry_dict = {}

    data_sources = registry_dict.get("data_sources", {})
    metrics = registry_dict.get("metrics", {})
    dimensions = registry_dict.get("dimensions", {})

    # Build data sources section
    ds_lines = []
    for ds_name, ds_cfg in data_sources.items():
        table = ds_cfg.get("table", ds_name)
        ds_metrics = ds_cfg.get("metrics", [])
        ds_dims = ds_cfg.get("dimensions", [])
        ds_lines.append(f'- 数据源: {ds_name} (对应表 {table}), 可用指标: {ds_metrics}, 可用维度: {ds_dims}')

    # Build metrics section
    metric_lines = []
    for m_name, m_cfg in metrics.items():
        expr = m_cfg.get("expr", "")
        desc = m_cfg.get("description", "")
        metric_lines.append(f'- {m_name}: {expr}, {desc}')

    # Build dimensions section
    dim_lines = []
    for d_name, d_cfg in dimensions.items():
        desc = d_cfg.get("description", "")
        dim_lines.append(f'- {d_name}: {desc}')

    # Build data_source options
    ds_names = list(data_sources.keys())
    default_ds = ds_names[0] if ds_names else "orders"
    ds_options = ", ".join([f'"{n}"' for n in ds_names])

    # Build joins section from data_sources
    join_lines = []
    for ds_name, ds_cfg in data_sources.items():
        joins = ds_cfg.get("joins", {})
        for join_table, join_cfg in joins.items():
            on_field = join_cfg.get("on", "id")
            join_type = join_cfg.get("type", "left")
            alias = join_cfg.get("alias", join_table[0])
            join_lines.append(f'- {ds_name} 可以 {join_type.upper()} JOIN {join_table} ON {on_field}, alias={alias}')

    ds_section = "\n".join(ds_lines) if ds_lines else '- (无数据源配置)'
    metric_section = "\n".join(metric_lines) if metric_lines else '- (无指标配置)'
    dim_section = "\n".join(dim_lines) if dim_lines else '- (无维度配置)'
    join_section = "\n".join(join_lines) if join_lines else '- (无 JOIN 配置)'

    return f"""【表结构】
{ds_section}

【表关联关系】
{join_section}
- 当用户问题涉及非主表字段时，必须在 DSL 的 joins 字段中添加对应的 JOIN 定义

【可用指标】
{metric_section}

【可用维度】
{dim_section}

【重要规则】
1. data_source 必须是以下之一: {ds_options}；默认使用 "{default_ds}"
2. metrics 的 alias 必须是已注册的指标名，且必须在对应数据源的可用指标列表中
3. dimensions 必须是已注册的维度名，且必须在对应数据源的可用维度列表中（不要选其他数据源独有的维度）
4. filters 中的 field 必须是**维度名**，直接使用维度名称，不要加数据源前缀（如用 "channel_code" 而非 "transactions.channel_code"）
5. 涉及关联表维度时 joins 中必须包含对应的 JOIN 定义
6. 不要输出任何解释文字，只输出 JSON

【用户问题】
{question}

请输出 DSL JSON："""


def _parse_llm_output(raw: str) -> dict:
    """Extract JSON object from LLM response, even if surrounded by markdown / commentary.

    支持三种格式：
    1. 纯 JSON: {"metrics":[...]}
    2. Markdown 代码块: ```json\n{...}\n```
    3. 包含解释文字 + 代码块: 推理文字...\n```json\n{...}\n```\n更多解释...
    """
    text = raw.strip()

    # 优先匹配 markdown 代码块（最稳）
    fence_match = re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", text)
    if fence_match:
        return json.loads(fence_match.group(1))

    # 退而求其次：抓第一个 { 到最后一个 } 之间的内容（贪婪）
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 最后尝试：原始字符串
    return json.loads(text)


# Hard-coded metric mapping for LLM format recovery (fallback when registry unavailable)
_METRIC_MAP = {
    "sales_amount": ("sum", "order_amount"),
    "gmv": ("sum", "order_amount"),
    "order_count": ("count", "id"),
    "avg_order_value": ("avg", "order_amount"),
    "total_discount": ("sum", "discount_amount"),
    "customer_count": ("count", "customer_id"),
    "max_price": ("max", "price"),
    "avg_price": ("avg", "price"),
}


def _parse_metric_expr(expr: str) -> tuple[str, str] | None:
    """Parse a metric expression like 'SUM(order_amount)' into (func, field)."""
    expr = expr.strip()
    match = re.match(r"^([A-Z]+)\(\s*(?:DISTINCT\s+)?(.+?)\s*\)$", expr, re.IGNORECASE)
    if match:
        return match.group(1).lower(), match.group(2)
    return None


def _fix_metric_format(m: dict, metrics_config: dict | None = None) -> dict:
    """Fix LLM-generated metric dict to ensure func/field/alias exist.

    Uses domain-specific metric config (from registry) when available,
    falling back to the global _METRIC_MAP for backward compatibility.
    """
    # LLM may use 'name' or 'metric' instead of 'alias'
    alias = m.get("alias") or m.get("name") or m.get("metric")
    if alias:
        alias = alias.strip().lower().replace(" ", "_")
        # 1. Try domain-specific mapping from registry first
        parsed = None
        if metrics_config and alias in metrics_config:
            expr = metrics_config[alias].get("expr", "")
            if expr:
                parsed = _parse_metric_expr(expr)
        # 2. Fall back to hard-coded global map
        if not parsed:
            parsed = _METRIC_MAP.get(alias)
        if parsed:
            m.setdefault("func", parsed[0])
            m.setdefault("field", parsed[1])
            m["alias"] = alias  # overwrite with normalized alias
    # Ensure required fields exist
    if not m.get("func"):
        m["func"] = "sum"
    if not m.get("field"):
        m["field"] = "order_amount"
    if not m.get("alias"):
        m["alias"] = m["field"]
    return m


_CN_NUM_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _extract_top_n(question: str, default: int = 10) -> int:
    """Extract top-N number from question like '前5', 'top10', '最好的3款', '前十名'."""
    # 主正则：匹配 "前/TOP/最X的/排名前" 后接数字（含中文）
    # 关键改进：不再限定形容词字符集，允许 "最[任意形容词]的" 模式
    m = re.search(
        r"(?:前|TOP|top|最[^0-9一二三四五六七八九十]{0,3}的?|排名前)\s*(\d+|[一二三四五六七八九十])\s*(?:个|名|条|位|款|项|家)?",
        question,
    )
    if m:
        s = m.group(1)
        n = int(s) if s.isdigit() else _CN_NUM_MAP.get(s, default)
        if 1 <= n <= 100:
            return n
    if "全部" in question or "所有" in question:
        return 100
    return default


def _semantic_fix_dsl(dsl_dict: dict, question: str, llm_client=None, registry_dict: dict | None = None) -> dict:
    """Fix DSL semantics based on keywords in the user's question.

    Agentic 改造：当 llm_client 可用时，让 LLM 自己识别问题中的过滤条件；
    否则回退到硬编码兜底逻辑。

    设计原则：metrics/dimensions 的语义识别完全交给 LLM + RAG（terms 集合提供别名映射）。
    本函数只做 RAG 难以覆盖的"硬性兜底"：
    - 过滤条件：用户问句中明确出现的地区/渠道/客户类型/时间等，确保进入 filters
    - top-N 数字：从问句中提取，覆盖 LLM 的 limit
    """
    filters = dsl_dict.get("filters") or []
    if not isinstance(filters, list):
        filters = []
    existing_fields = {f.get("field") for f in filters if isinstance(f, dict)}

    # Build dynamic available fields from registry, with hardcoded defaults for backward compatibility
    _DEFAULT_DIMENSIONS = {
        "region": {"column": "region_code", "description": "地区", "value_map": {"华东": "HD", "华南": "HN", "华北": "HB", "华西": "HX"}},
        "channel": {"column": "channel_code", "description": "销售渠道", "value_map": {"线上": "online", "线下": "offline", "分销": "distribute"}},
        "customer_type": {"column": "customer_type", "description": "客户类型"},
    }
    dimensions = (registry_dict or {}).get("dimensions", {}) if registry_dict else _DEFAULT_DIMENSIONS
    dim_names = list(dimensions.keys())
    # Build value_map summaries for enum-like dimensions
    field_hints = []
    for d_name, d_cfg in dimensions.items():
        desc = d_cfg.get("description", "")
        value_map = d_cfg.get("value_map")
        if value_map and isinstance(value_map, dict):
            values = ", ".join([f"{k}({v})" for k, v in list(value_map.items())[:8]])
            field_hints.append(f"- {d_name}: {desc}（取值: {values}）")
        else:
            field_hints.append(f"- {d_name}: {desc}")
    fields_section = "\n".join(field_hints) if field_hints else "- (无维度配置)"

    # ------------------------------------------------------------------
    # Agentic path (preferred when llm_client is available)
    # ------------------------------------------------------------------
    if llm_client is not None:
        try:
            agentic_prompt = f"""你是一个查询语义分析助手。请分析用户的自然语言问题，识别其中隐含的过滤条件。

【用户问题】
{question}

【当前 DSL 已包含的 filters】
{json.dumps(filters, ensure_ascii=False, indent=2)}

【可用字段】
{fields_section}

【任务】
判断用户问题中是否包含上述字段的过滤条件，但当前 DSL 的 filters 中还没有体现。
只输出需要补充的 filters，格式为 JSON 数组。

【输出格式】
[{{"field": "region", "operator": "=", "value": "华东"}}]

如果没有需要补充的，输出空数组 []。
不要输出解释文字。只输出 JSON 数组。"""

            raw = llm_client.generate(
                agentic_prompt,
                "你是一个简洁的查询语义分析助手。只输出 JSON 数组，不要 markdown 代码块标记。",
            )
            if raw:
                text = raw.strip()
                # 尝试从 markdown 代码块中提取
                fence_match = re.search(r"```(?:json)?\s*\n?(\[[\s\S]*?\])\s*\n?```", text)
                if fence_match:
                    text = fence_match.group(1)
                # 兜底：直接找方括号包裹的内容
                if not text.startswith("["):
                    bracket_match = re.search(r"(\[[\s\S]*\])", text)
                    if bracket_match:
                        text = bracket_match.group(1)
                try:
                    suggested = json.loads(text)
                    if isinstance(suggested, list):
                        added = []
                        for f in suggested:
                            if (
                                isinstance(f, dict)
                                and f.get("field")
                                and f.get("field") not in existing_fields
                            ):
                                filters.append(f)
                                existing_fields.add(f.get("field"))
                                added.append(f)
                        if added:
                            logger.info("[semantic_fix] agentic: added filters %s", added)
                except json.JSONDecodeError:
                    logger.warning(
                        "[semantic_fix] agentic: failed to parse LLM output: %s", raw
                    )

            dsl_dict["filters"] = filters if filters else None
            dsl_dict["limit"] = _extract_top_n(question, default=dsl_dict.get("limit", 10))
            # Apply negation detection even on agentic success path
            _apply_negation_fixes(dsl_dict, question)
            return dsl_dict
        except Exception as exc:
            logger.warning("[semantic_fix] agentic failed, falling back to hardcoded: %s", exc)
            # 继续执行下面的硬编码兜底逻辑

    # ------------------------------------------------------------------
    # Fallback: keyword-based filter detection + value correction using registry
    # ------------------------------------------------------------------
    # Step A: Correct existing filter values using dimension value_map
    for f in filters:
        if not isinstance(f, dict):
            continue
        field_name = f.get("field")
        val = f.get("value")
        if field_name and val and isinstance(val, str):
            d_cfg = dimensions.get(field_name)
            if d_cfg:
                vm = d_cfg.get("value_map")
                if vm and isinstance(vm, dict):
                    # If value is a Chinese name in value_map, replace with code
                    if val in vm:
                        f["value"] = vm[val]
                    # Also handle partial matches (e.g. "线上渠道" -> "线上" -> "online")
                    for cn_name, code in vm.items():
                        if cn_name in val and val != code:
                            f["value"] = code
                            break

    # Step B: Add missing filters from value_map keywords
    # Use the Chinese name as value; SemanticResolver will map it to code later
    for d_name, d_cfg in dimensions.items():
        value_map = d_cfg.get("value_map")
        if value_map and isinstance(value_map, dict):
            for cn_name, code in value_map.items():
                if cn_name in question and d_name not in existing_fields:
                    filters.append({"field": d_name, "operator": "=", "value": cn_name})
                    existing_fields.add(d_name)
                    break

    # Step C: Generic keyword detection for common filter fields
    _FILTER_KEYWORDS = {
        "线上": ("channel", "线上"),
        "线下": ("channel", "线下"),
        "分销": ("channel", "分销"),
        "VIP": ("customer_type", "VIP"),
        "新客": ("customer_type", "新客"),
        "老客户": ("customer_type", "老客"),
    }
    for keyword, (field, value) in _FILTER_KEYWORDS.items():
        if keyword in question and field in dimensions and field not in existing_fields:
            filters.append({"field": field, "operator": "=", "value": value})
            existing_fields.add(field)

    # Step D: Negation detection (also run in fallback)
    _apply_negation_fixes(dsl_dict, question)

    dsl_dict["filters"] = filters if filters else None

    # --- Fix limit: extract top-N from question ---
    dsl_dict["limit"] = _extract_top_n(question, default=dsl_dict.get("limit", 10))

    return dsl_dict


def _apply_negation_fixes(dsl_dict: dict, question: str) -> None:
    """Convert '=' to '!=' when question contains negation for the filter value."""
    filters = dsl_dict.get("filters")
    if not filters:
        return

    negation_prefixes = ("非", "不是", "排除", "除外", "不包含")

    def _fix_node(node):
        if isinstance(node, dict) and node.get("op") in {"and", "or", "not"}:
            for child in node.get("children", []):
                _fix_node(child)
        elif isinstance(node, dict) and node.get("operator") == "=":
            val = str(node.get("value", ""))
            for neg in negation_prefixes:
                # Check direct pattern: "非手机"
                if neg + val in question:
                    node["operator"] = "!="
                    return
                # Check pattern with suffix: "非手机品类"
                if neg in question and val in question:
                    # Ensure negation appears before value in question
                    neg_idx = question.find(neg)
                    val_idx = question.find(val)
                    if 0 <= neg_idx < val_idx <= neg_idx + len(neg) + len(val) + 2:
                        node["operator"] = "!="
                        return

    if isinstance(filters, dict) and filters.get("op") in {"and", "or", "not"}:
        _fix_node(filters)
    elif isinstance(filters, list):
        for f in filters:
            _fix_node(f)


def _post_process_dsl(dsl_dict: dict, default_data_source: str = "orders", valid_data_sources: list[str] | None = None, data_sources_config: dict | None = None, metrics_config: dict | None = None) -> dict:
    """Post-process and fix common LLM-generated DSL issues."""
    valid_ds = valid_data_sources or ["orders", "products", "customers"]
    ds_cfg = data_sources_config or {}
    # Build data_source_name -> actual_table mapping
    ds_to_table = {ds_name: ds_info.get("table", ds_name) for ds_name, ds_info in ds_cfg.items()}

    # 0. Infer correct data_source from metrics + dimensions if current one is mismatched
    _auto_fix_data_source(dsl_dict, ds_cfg)

    # 1. Ensure data_source is valid
    if "data_source" not in dsl_dict or dsl_dict["data_source"] not in valid_ds:
        dsl_dict["data_source"] = default_data_source

    # 1b. Fix filter fields: strip data_source prefix (e.g. "purchase.region_id" -> "region_id")
    current_ds = dsl_dict.get("data_source")
    filters = dsl_dict.get("filters")
    if filters:
        _fix_filter_fields(filters, current_ds, valid_ds)

    # 2. Ensure metrics is a list of dicts
    metrics = dsl_dict.get("metrics")
    if isinstance(metrics, str):
        # LLM returned a string instead of array
        metrics = [{"alias": metrics}]
    if not metrics or not isinstance(metrics, list):
        metrics = [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}]
    dsl_dict["metrics"] = [_fix_metric_format(m if isinstance(m, dict) else {"alias": str(m)}, metrics_config) for m in metrics]

    # 3. Normalize metric fields: strip SUM/AVG/COUNT/MAX/MIN wrappers
    for m in dsl_dict.get("metrics", []):
        field = m.get("field", "")
        if isinstance(field, str):
            match = re.match(r"^[A-Z]+\(\s*(?:DISTINCT\s+)?(.+?)\s*\)$", field.strip(), re.IGNORECASE)
            if match:
                m["field"] = match.group(1)

    # 4. Ensure dimensions is non-empty list
    dimensions = dsl_dict.get("dimensions")
    if not dimensions or not isinstance(dimensions, list):
        dsl_dict["dimensions"] = ["product_name"]
    # Remove non-string items
    dsl_dict["dimensions"] = [d for d in dsl_dict["dimensions"] if isinstance(d, str)]
    if not dsl_dict["dimensions"]:
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

    # 7. Ensure order_by exists when metrics exist, normalize direction to lowercase
    order_by = dsl_dict.get("order_by")
    if isinstance(order_by, list):
        for ob in order_by:
            if isinstance(ob, dict):
                # LLM may use "alias" instead of "field"
                if "alias" in ob and "field" not in ob:
                    ob["field"] = ob.pop("alias")
                if ob.get("direction"):
                    ob["direction"] = str(ob["direction"]).lower()
    metrics_list = dsl_dict.get("metrics", [])
    if not order_by and metrics_list:
        first_alias = metrics_list[0].get("alias") or metrics_list[0].get("field")
        if first_alias:
            dsl_dict["order_by"] = [{"field": first_alias, "direction": "desc"}]

    # 8. Validate filters operator values (support both flat list and tree)
    valid_ops = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "between", "is_null"}
    filters = dsl_dict.get("filters")
    if filters:
        if isinstance(filters, dict) and filters.get("op") in {"and", "or", "not"}:
            # Filter tree format
            def _validate_tree(node):
                if node.get("op") in {"and", "or", "not"}:
                    for child in node.get("children", []):
                        _validate_tree(child)
                elif isinstance(node, dict) and "field" in node:
                    op = node.get("operator", "")
                    if op not in valid_ops:
                        node["operator"] = "="

            _validate_tree(filters)
        elif isinstance(filters, list):
            for f in filters:
                if isinstance(f, dict):
                    op = f.get("operator", "")
                    if op not in valid_ops:
                        f["operator"] = "="

    # 9. Fix joins format: LLM may use "type" instead of "join_type" or miss "on_field"
    # Also fix table name if LLM used data_source name instead of actual table name
    _TABLE_JOIN_FIELD_MAP = {
        "product_dim": "product_id",
        "customer_dim": "customer_id",
        "supplier_dim": "supplier_id",
        "region_dim": "region_code",
        "date_dim": "date_id",
        "warehouse_dim": "warehouse_id",
    }
    joins = dsl_dict.get("joins")
    if joins and isinstance(joins, list):
        fixed_joins = []
        for j in joins:
            if not isinstance(j, dict):
                continue
            # Fix table name: if table is a data_source name, use actual table name
            table_name = j.get("table", "")
            if table_name in ds_to_table and table_name != ds_to_table[table_name]:
                j["table"] = ds_to_table[table_name]
            # Normalize field names
            if "type" in j and "join_type" not in j:
                j["join_type"] = j.pop("type")
            if "on" in j and "on_field" not in j:
                j["on_field"] = j.pop("on")
            # Infer on_field from table name if still missing
            if not j.get("on_field"):
                table = j.get("table", "")
                j["on_field"] = _TABLE_JOIN_FIELD_MAP.get(table, "id")
            # LLM may output full join condition like "product_id = p.product_id"
            on_field = j.get("on_field", "")
            if isinstance(on_field, str) and "=" in on_field:
                j["on_field"] = on_field.split("=")[0].strip()
            # Ensure join_type is valid
            if j.get("join_type") not in {"inner", "left", "right"}:
                j["join_type"] = "inner"
            fixed_joins.append(j)
        dsl_dict["joins"] = fixed_joins

    return dsl_dict


def _auto_fix_data_source(dsl_dict: dict, ds_cfg: dict) -> None:
    """Automatically infer and fix data_source based on metrics + dimensions coverage."""
    current_ds = dsl_dict.get("data_source")
    if not current_ds or not ds_cfg:
        return

    metrics = dsl_dict.get("metrics", [])
    dims = dsl_dict.get("dimensions", [])
    metric_aliases = {m.get("alias") for m in metrics if isinstance(m, dict) and m.get("alias")}
    dim_names = set(dims) if isinstance(dims, list) else set()

    # Score each data_source by how many metrics/dimensions it covers
    best_ds = current_ds
    best_score = 0
    for ds_name, ds_info in ds_cfg.items():
        ds_metrics = set(ds_info.get("metrics", []))
        ds_dims = set(ds_info.get("dimensions", []))
        score = len(metric_aliases & ds_metrics) + len(dim_names & ds_dims)
        if score > best_score:
            best_score = score
            best_ds = ds_name

    # Only switch if current ds has zero coverage and best ds has positive coverage
    current_info = ds_cfg.get(current_ds, {})
    current_metrics = set(current_info.get("metrics", []))
    current_dims = set(current_info.get("dimensions", []))
    current_score = len(metric_aliases & current_metrics) + len(dim_names & current_dims)

    if current_score == 0 and best_score > 0 and best_ds != current_ds:
        logger.info("[post_process] auto-switch data_source: %s -> %s (score: %d)", current_ds, best_ds, best_score)
        dsl_dict["data_source"] = best_ds


def _fix_filter_fields(filters, current_ds: str | None, valid_ds: list[str]) -> None:
    """Strip data_source prefix from filter fields (e.g. 'purchase.region_id' -> 'region_id')."""
    def _fix_node(node):
        if isinstance(node, dict) and node.get("op") in {"and", "or", "not"}:
            for child in node.get("children", []):
                _fix_node(child)
        elif isinstance(node, dict) and "field" in node:
            field = node.get("field", "")
            if isinstance(field, str) and "." in field:
                parts = field.split(".", 1)
                if parts[0] in valid_ds:
                    node["field"] = parts[1]

    if isinstance(filters, dict) and filters.get("op") in {"and", "or", "not"}:
        _fix_node(filters)
    elif isinstance(filters, list):
        for f in filters:
            _fix_node(f)
    elif isinstance(filters, dict) and "field" in filters:
        # Single filter dict (not in a list, not a tree node)
        _fix_node(filters)


def _run_semantic_validation(dsl, semantic_validator) -> None:
    """Run semantic validation and raise ValidationError on errors."""
    if semantic_validator is None:
        return
    errors, warnings = semantic_validator.validate(dsl)
    for w in warnings:
        logger.warning("[semantic_validator] %s: %s", w.category, w.message)
    if errors:
        raise ValidationError(f"Semantic validation failed: {'; '.join(errors)}")


def _restore_metric_fields(dsl: DSL) -> DSL:
    """After SemanticResolver replaces metric.field with expr like SUM(col),
    restore the raw column name so SQLBuilder can look it up.
    Preserves complex expressions like SUM(CASE WHEN ...) intact.
    """
    if not dsl.metrics:
        return dsl
    restored = []
    for m in dsl.metrics:
        field = m.field
        match = re.match(r"^[A-Z]+\(\s*(?:DISTINCT\s+)?(.+?)\s*\)$", field, re.IGNORECASE)
        if match:
            inner = match.group(1)
            # Only unwrap if inner is a simple column name; preserve complex exprs
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", inner):
                field = inner
        restored.append(m.model_copy(update={"field": field}))
    return dsl.model_copy(update={"metrics": restored})


# ---------------------------------------------------------------------------
# Standalone node factories (for use in subgraphs)
# ---------------------------------------------------------------------------


def _make_inject_row_permission_node(row_security: RowLevelSecurity):
    """Create an inject_row_permission node with injected row_security."""
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
    return inject_row_permission_node


def _make_check_col_permission_node(col_security: ColumnLevelSecurity):
    """Create a check_col_permission node with injected col_security."""
    @with_error_handler("check_col_permission")
    def check_col_permission_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot check column permissions")
        col_security.check(dsl, state["user_id"])
        return {"trace": {"step": "check_col_permission", "status": "success"}}
    return check_col_permission_node


def _make_validate_dsl_node(validator: DSLValidator):
    """Create a validate_dsl node with injected validator.

    On validation failure the node appends a dsl_attempt record with
    source="validation" and valid=False so that route_after_validate can
    decide whether to retry (correct_dsl) or give up (error).
    """

    def validate_dsl_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            return {
                "status": "error",
                "error": "DSL is None, cannot validate",
                "error_code": "VALIDATION_ERROR",
                "dsl_attempts": {
                    "source": "validation",
                    "valid": False,
                    "error": "DSL is None",
                    "timestamp": time.time(),
                },
                "trace": [
                    {
                        "step": "validate_dsl",
                        "status": "error",
                        "error_code": "VALIDATION_ERROR",
                        "error_message": "DSL is None, cannot validate",
                    }
                ],
            }
        try:
            validator.validate(dsl)
            return {"trace": [{"step": "validate_dsl", "status": "success"}]}
        except ValidationError as exc:
            logger.warning("[validate_dsl] Validation failed: %s - %s", exc.error_code, exc.message)
            return {
                "status": "error",
                "error": exc.message,
                "error_code": exc.error_code,
                "dsl_attempts": {
                    "source": "validation",
                    "valid": False,
                    "error": exc.message,
                    "timestamp": time.time(),
                },
                "trace": [
                    {
                        "step": "validate_dsl",
                        "status": "error",
                        "error_code": exc.error_code,
                        "error_message": exc.message,
                    }
                ],
            }
        except Exception as exc:
            logger.error("[validate_dsl] Unexpected exception: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error": str(exc),
                "error_code": "INTERNAL_ERROR",
                "dsl_attempts": {
                    "source": "validation",
                    "valid": False,
                    "error": str(exc),
                    "timestamp": time.time(),
                },
                "trace": [
                    {
                        "step": "validate_dsl",
                        "status": "error",
                        "error_code": "INTERNAL_ERROR",
                        "error_message": str(exc),
                    }
                ],
            }

    return validate_dsl_node


def _make_generate_dsl_node(
    llm_client, rag_retriever, semantic_validator=None, llm_system_prompt: str = "", registry_dict: dict | None = None
):
    """Create a generate_dsl node with injected LLM and RAG dependencies."""

    data_sources = (registry_dict or {}).get("data_sources", {})
    ds_names = list(data_sources.keys())
    default_ds = ds_names[0] if ds_names else "orders"
    valid_ds = ds_names if ds_names else ["orders", "products", "customers"]

    @with_error_handler("generate_dsl")
    def generate_dsl_node(state: QueryState) -> dict:
        question = state["question"]
        data_source = state.get("data_source")

        if llm_client is None:
            raise ValidationError("LLM client not available")

        if rag_retriever is not None:
            prompt = rag_retriever.build_prompt(question)
        else:
            prompt = _build_fallback_prompt(question, registry_dict)

        raw = llm_client.generate(prompt, llm_system_prompt)
        if not raw:
            raise ValidationError("LLM returned empty response")
        logger.info("[generate_dsl] LLM raw output (len=%d): %s", len(raw), raw)

        dsl_dict = _parse_llm_output(raw)
        ds_config = (registry_dict or {}).get("data_sources", {})
        metrics_config = (registry_dict or {}).get("metrics", {})
        dsl_dict = _post_process_dsl(dsl_dict, data_source or default_ds, valid_ds, ds_config, metrics_config)
        dsl_dict = _semantic_fix_dsl(dsl_dict, question, llm_client, registry_dict)
        dsl = DSL.model_validate(dsl_dict)

        _run_semantic_validation(dsl, semantic_validator)

        return {
            "dsl": dsl,
            "llm_used": True,
            "dsl_attempts": {
                "source": "llm",
                "dsl": dsl.model_dump(),
                "valid": True,
                "timestamp": time.time(),
            },
            "trace": {"step": "generate_dsl", "status": "success", "source": "llm"},
        }

    return generate_dsl_node


def _make_correct_dsl_node(
    llm_client,
    rag_retriever,
    registry_dict: dict,
    semantic_validator=None,
    llm_system_prompt: str = "",
):
    """Create an agentic correct_dsl node."""
    data_sources = registry_dict.get("data_sources", {})
    ds_names = list(data_sources.keys())
    default_ds = ds_names[0] if ds_names else "orders"
    valid_ds = ds_names if ds_names else ["orders", "products", "customers"]
    """Create an agentic correct_dsl node.

    Unlike the previous "stuff error into prompt and retry" approach, this node
    asks the LLM to first decide what extra knowledge it needs (based on the
    error), retrieves that targeted context, then regenerates with it. Inspired
    by self-correcting / verify-then-answer RAG patterns.
    """

    def _decide_retrieval_query(error: str, prev_dsl: dict | None) -> str:
        """LLM Step 1: read the error, output ONE focused retrieval query.

        Returns the natural-language query to feed back into RAG. Falls back
        to the original error message if the LLM is unavailable / mis-formats.
        """
        if llm_client is None:
            return error or ""

        decide_prompt = f"""你正在修正一个失败的 DSL 查询。任务：根据错误信息，提取一个**最相关的检索关键词**，用于在业务知识库中查找正确答案。

【上一次生成的 DSL】
{json.dumps(prev_dsl, ensure_ascii=False) if prev_dsl else "(无)"}

【失败原因】
{error}

【输出规则】
- 只输出一行：最相关的中文检索关键词
- 比如错误是 "指标 'xxx' 不存在" → 输出 "xxx"
- 比如错误是 "维度 'customer_type' 取值不合法 VVIP" → 输出 "customer_type"
- 不要解释，不要 JSON，只输出关键词
"""
        try:
            raw = llm_client.generate(decide_prompt, "你是一个简洁的关键词提取助手。")
            keyword = (raw or "").strip().split("\n")[0].strip()
            # 限长，避免 LLM 输出整段话
            return keyword[:50] if keyword else (error or "")
        except Exception as exc:
            logger.warning("[correct_dsl] decide step failed, using raw error: %s", exc)
            return error or ""

    @with_error_handler("correct_dsl")
    def correct_dsl_node(state: QueryState) -> dict:
        question = state["question"]
        data_source = state.get("data_source")
        error = state.get("error") or ""
        prev_dsl_obj = state.get("dsl")
        prev_dsl = prev_dsl_obj.model_dump() if prev_dsl_obj else None

        if llm_client is not None:
            # Step 1: 让 LLM 决定要补充检索什么
            retrieval_query = _decide_retrieval_query(error, prev_dsl)

            # Step 2: 用决策结果做定向 RAG 检索
            extra_context = ""
            if rag_retriever is not None and retrieval_query:
                try:
                    extra_context = rag_retriever.build_context(retrieval_query, top_k=5)
                except Exception as exc:
                    logger.warning("[correct_dsl] retrieval failed: %s", exc)

            # Step 3: 拿着 error + 原 DSL + 定向 context + 原问题 重新生成
            feedback = f"""上一次生成的 DSL 校验失败，请修正。

【用户原始问题】
{question}

【上一次生成的 DSL】
{json.dumps(prev_dsl, ensure_ascii=False) if prev_dsl else "(无)"}

【失败原因】
{error}

【针对失败原因补充的业务知识】
{extra_context or "(无额外上下文)"}

【修正要求】
1. 不要重复上次的错误
2. 严格按补充的业务知识中的 metric alias / dimension 名称
3. 只输出修正后的 DSL JSON，不要解释

请输出修正后的 DSL JSON："""
            raw = llm_client.generate(feedback, llm_system_prompt)
            if raw:
                dsl_dict = _parse_llm_output(raw)
                ds_config = registry_dict.get("data_sources", {})
                metrics_config = registry_dict.get("metrics", {})
                dsl_dict = _post_process_dsl(dsl_dict, data_source or default_ds, valid_ds, ds_config, metrics_config)
                dsl_dict = _semantic_fix_dsl(dsl_dict, question, llm_client, registry_dict)
                dsl = DSL.model_validate(dsl_dict)

                _run_semantic_validation(dsl, semantic_validator)

                return {
                    "dsl": dsl,
                    "status": "pending",  # 清掉错误状态，让 validate 再判一次
                    "error": None,
                    "error_code": None,
                    "dsl_attempts": {
                        "source": "llm_corrected_agentic",
                        "dsl": dsl.model_dump(),
                        "valid": True,
                        "timestamp": time.time(),
                        "error_feedback": error,
                        "retrieval_query": retrieval_query,
                    },
                    "trace": {
                        "step": "correct_dsl",
                        "status": "success",
                        "source": "llm_corrected_agentic",
                        "retrieval_query": retrieval_query,
                    },
                }

        # No fallback: if LLM correction fails, return error state
        return {
            "status": "error",
            "error": f"DSL correction failed: {error}",
            "error_code": "CORRECTION_FAILED",
            "trace": {
                "step": "correct_dsl",
                "status": "error",
                "error": error,
            },
        }
    return correct_dsl_node


# ---------------------------------------------------------------------------
# Agentic helpers: decompose (rewrite complex questions) + verify (self-check)
# ---------------------------------------------------------------------------


_COMPLEX_QUESTION_PATTERNS = (
    "对比", "比较", "同比", "环比", "增长率", "占比", "比上", "相对",
    "去年", "今年", "上月", "本月", "上季度", "本季度",
    "趋势", "变化", "分组", "和", "及", "以及", "vs", "VS",
)


def _looks_complex(question: str) -> bool:
    """快速判断问题是否可能需要 decompose。

    避免对每个问题都额外调一次 LLM——只在 question 含有"对比/同比/趋势/今年"
    等明显多条件信号时才触发 decompose。其他情况直接透传。
    """
    return any(p in question for p in _COMPLEX_QUESTION_PATTERNS)


def _make_decompose_node(llm_client, llm_system_prompt: str = ""):
    """Decompose / rewrite complex questions into a single-DSL-expressible form.

    输入复杂问题（"对比今年和去年华东销售额"），让 LLM 把它改写成可以用一个
    DSL 一次性查出来的等价问题（"按年度分组统计华东销售额，只看 2024 和 2023"）。
    若问题已经足够简单，直接透传不改写。
    """

    @with_error_handler("decompose")
    def decompose_node(state: QueryState) -> dict:
        question = state["question"]

        # 没启用 LLM，或问题看着不复杂，直接跳过
        if llm_client is None or not _looks_complex(question):
            return {
                "complexity": "simple",
                "trace": {"step": "decompose", "status": "skipped", "reason": "looks_simple"},
            }

        decompose_prompt = f"""你是一个智能问数系统的查询改写助手。任务：把可能需要多次查询的复杂问题，改写成一个可以用单个 DSL 查询表达的等价问题。

【原始问题】
{question}

【判断规则】
- 如果原问题只涉及一次 SQL 聚合（一组 metrics + dimensions + filters），输出 KEEP
- 如果原问题涉及"对比 / 同比 / 环比 / 趋势 / 多个时间段并列"，把它改写成"按时间维度分组+filter 限定范围"形式
- 如果原问题涉及"多个不相关的指标用不同口径查询"，输出 SPLIT（系统会回退用原问题尽力而为）

【输出格式】
第一行: KEEP / REWRITE / SPLIT 之一
第二行（只在 REWRITE 时）: 改写后的等价问题（一句话，能用单个 DSL 表达）
不要输出 JSON，不要解释。

【示例】
输入: "对比今年和去年华东销售额"
输出:
REWRITE
按年度分组统计华东地区销售额（限定 2023 和 2024 年）

输入: "查询华东销售额"
输出:
KEEP

输入: "对比 VIP 客户的客单价和普通客户的订单量"
输出:
SPLIT
"""
        try:
            raw = llm_client.generate(decompose_prompt, "你是一个简洁的查询改写助手。")
            lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
            verdict = lines[0].upper() if lines else "KEEP"

            if verdict == "REWRITE" and len(lines) >= 2:
                new_question = lines[1]
                logger.info("[decompose] rewrite: %r -> %r", question, new_question)
                return {
                    "original_question": question,
                    "question": new_question,
                    "rewrite_reason": "complex query rewritten to single-DSL form",
                    "complexity": "complex_rewritten",
                    "trace": {
                        "step": "decompose",
                        "status": "success",
                        "verdict": "rewrite",
                        "original": question,
                        "rewritten": new_question,
                    },
                }
            if verdict == "SPLIT":
                logger.info("[decompose] split detected, keep original: %r", question)
                return {
                    "complexity": "complex",
                    "rewrite_reason": "split-style query, processing best-effort with original",
                    "trace": {
                        "step": "decompose",
                        "status": "warning",
                        "verdict": "split",
                        "note": "system does not yet support fan-out; falling back to original",
                    },
                }
            # KEEP 或无法识别
            return {
                "complexity": "simple",
                "trace": {"step": "decompose", "status": "success", "verdict": "keep"},
            }
        except Exception as exc:
            logger.warning("[decompose] LLM call failed, keeping original: %s", exc)
            return {
                "complexity": "simple",
                "trace": {"step": "decompose", "status": "warning", "error": str(exc)},
            }

    return decompose_node


def _make_verify_dsl_node(llm_client, llm_system_prompt: str = ""):
    """Verify-then-Answer: ask the LLM to self-check if the executed DSL/result
    truly answers the user's original question.

    Runs AFTER execute_sql, when we have:
      - the original (user-typed) question
      - the final DSL
      - sample data rows

    The LLM outputs PASS / WARN / FAIL with a short reason. We surface this
    in the response but do NOT block on it (warnings only). A future iteration
    can route FAIL back into correct_dsl.
    """

    @with_error_handler("verify_dsl")
    def verify_dsl_node(state: QueryState) -> dict:
        if llm_client is None:
            return {
                "verify_status": "skipped",
                "trace": {"step": "verify_dsl", "status": "skipped", "reason": "no_llm"},
            }

        # 优先用原始问题，没改写就用当前 question
        original = state.get("original_question") or state["question"]
        dsl_obj = state.get("dsl")
        data = state.get("data") or []
        if dsl_obj is None:
            return {
                "verify_status": "skipped",
                "trace": {"step": "verify_dsl", "status": "skipped", "reason": "no_dsl"},
            }

        # 只取样本数据避免 prompt 太长
        sample = data[:3]
        # 安全序列化：测试环境可能出现 MagicMock，用 default=str 兜底
        try:
            dsl_json = json.dumps(dsl_obj.model_dump(), ensure_ascii=False, indent=2, default=str)
        except Exception:
            dsl_json = str(dsl_obj)
        verify_prompt = f"""你是一个查询质量检查员。任务：判断一个 DSL 查询和它的执行结果是否真的回答了用户原始问题。

【用户原始问题】
{original}

【系统生成的 DSL】
{dsl_json}

【执行结果样本（前 3 行）】
{json.dumps(sample, ensure_ascii=False, indent=2, default=str)}
（共 {len(data)} 条）

【判断维度】
1. metrics 是否对应用户问的"指标"？（如用户问"销售额"，DSL 用 sales_amount 才对）
2. dimensions 是否对应用户问的"按什么分组"？
3. filters 是否覆盖用户问题中的具体条件（地区、时间、客户类型等）？
4. 结果数据看起来是否合理？

【输出格式】
第一行: PASS / WARN / FAIL 之一
第二行（只在 WARN 或 FAIL 时输出）: 一句话说明哪里有问题
不要 JSON，不要解释。

【判定示例】
- 用户问"销售额" → DSL 用 sales_amount → PASS
- 用户问"销售额" → DSL 用 customer_count → FAIL: 指标不匹配
- 用户问"华东销售额" → DSL 无 region filter → WARN: 缺少华东过滤
- 用户问"前 5 的产品" → DSL limit=10 → WARN: limit 与"前5"不符
"""
        try:
            raw = llm_client.generate(verify_prompt, "你是一个简洁的质量检查员。")
            lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
            verdict = (lines[0].upper() if lines else "PASS").split(":")[0].strip()
            reason = lines[1] if len(lines) >= 2 else None

            if verdict not in {"PASS", "WARN", "FAIL"}:
                verdict = "PASS"

            return {
                "verify_status": verdict.lower(),
                "verify_reason": reason,
                "trace": {
                    "step": "verify_dsl",
                    "status": "success" if verdict == "PASS" else "warning",
                    "verdict": verdict,
                    "reason": reason,
                },
            }
        except Exception as exc:
            logger.warning("[verify_dsl] LLM call failed: %s", exc)
            return {
                "verify_status": "skipped",
                "trace": {"step": "verify_dsl", "status": "warning", "error": str(exc)},
            }

    return verify_dsl_node


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
    registry_dict: dict | None = None,
    semantic_validator=None,
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
        # Skip clarification when a DSL is already provided (e.g. /query/execute)
        # or when no LLM is available (can't act on clarification responses).
        if state.get("dsl") is not None:
            return {
                "ambiguities": None,
                "trace": {"step": "clarification", "status": "skipped", "reason": "dsl_present"},
            }
        if llm_client is None:
            return {
                "ambiguities": None,
                "trace": {"step": "clarification", "status": "skipped", "reason": "no_llm"},
            }
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
    # generate_dsl_node — delegate to standalone factory for DRY
    # -----------------------------------------------------------------------
    generate_dsl_node = _make_generate_dsl_node(
        llm_client, rag_retriever, semantic_validator, llm_system_prompt, registry_dict
    )

    # -----------------------------------------------------------------------
    # validate_dsl_node — delegate to standalone factory for DRY
    # -----------------------------------------------------------------------
    validate_dsl_node = _make_validate_dsl_node(validator)

    # -----------------------------------------------------------------------
    # correct_dsl_node — see _make_correct_dsl_node (agentic version) above.
    # The validation subgraph uses _make_correct_dsl_node directly; we keep
    # this slot in create_node_functions only as a thin delegate so callers
    # can still look it up by name.
    # -----------------------------------------------------------------------
    correct_dsl_node = _make_correct_dsl_node(
        llm_client, rag_retriever, registry_dict or {}, semantic_validator, llm_system_prompt
    )

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
        # Preserve "warning" status from confidence node, but upgrade
        # "pending" / "pending_review" to "success" since execution completed.
        current_status = state.get("status")
        if current_status == "warning":
            new_status = "warning"
        else:
            new_status = "success"
        return {
            "data": data,
            "status": new_status,
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

    # -----------------------------------------------------------------------
    # plan_node (intent classification + task decomposition)
    # -----------------------------------------------------------------------
    plan_node = _make_plan_node(llm_client, {})

    # -----------------------------------------------------------------------
    # confidence_node (DSL quality scoring)
    # -----------------------------------------------------------------------
    confidence_node = _make_confidence_node(validator, llm_client)

    # -----------------------------------------------------------------------
    # explain_node (natural language explanation generation)
    # -----------------------------------------------------------------------
    explain_node = _make_explain_node(llm_client)

    # -----------------------------------------------------------------------
    # decompose_node + verify_dsl_node (agentic helpers, see factories above)
    # -----------------------------------------------------------------------
    decompose_node = _make_decompose_node(llm_client, llm_system_prompt)
    verify_dsl_node_fn = _make_verify_dsl_node(llm_client, llm_system_prompt)

    return {
        "clarification_node": clarification_node,
        "plan_node": plan_node,
        "confidence_node": confidence_node,
        "decompose_node": decompose_node,
        "generate_dsl_node": generate_dsl_node,
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
        "verify_dsl_node": verify_dsl_node_fn,
        "explain_node": explain_node,
    }
