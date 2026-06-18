"""Factory for creating NL2DSL FastAPI app with custom configuration.

This allows E2E tests to inject mock data, test-specific registries,
and custom database engines without modifying the main api.py module.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Engine, MetaData, Table, Column, Integer, String, Float, DateTime

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.dsl.generator import RuleBasedDSLGenerator
from nl2dsl.dsl.models import DSL, ClarificationResponse
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import NL2DSLException, NotFoundError, ValidationError
from nl2dsl.feedback.collector import FeedbackCollector
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.semantic.registry import SemanticRegistry
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.query.clarification import ClarificationDetector
from nl2dsl.query.sandbox import QuerySandbox
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.agent.orchestrator import AgentOrchestrator
from nl2dsl.agent.controller import AgentController
from nl2dsl.agent.models import ComplexExecutionPlan, ExplorationPlan, SimpleExecutionPlan
from nl2dsl.agent.planner import classify_intent, _decompose_fallback
from nl2dsl.domain_context import DomainContext
from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT
from langgraph.checkpoint.memory import InMemorySaver


# ---------------------------------------------------------------------------
# Domain-specific system prompt builder
# ---------------------------------------------------------------------------

def _build_domain_system_prompt(registry_dict: dict | None) -> str:
    """Build a domain-specific system prompt from registry configuration.

    Replaces hardcoded metric/dimension/data_source lists with dynamic
    content derived from the registry_dict, keeping the universal rules
    (operator mapping, filter format, HAVING, joins, etc.) intact.
    """
    if registry_dict is None:
        return ""

    metrics = registry_dict.get("metrics", {})
    dimensions = registry_dict.get("dimensions", {})
    data_sources = registry_dict.get("data_sources", {})

    # Build metric alias list
    metric_aliases = list(metrics.keys())

    # Build dimension names
    dim_names = list(dimensions.keys())

    # Build data source options
    ds_options = list(data_sources.keys())
    default_ds = ds_options[0] if ds_options else "orders"
    ds_options_str = ", ".join([f'"{n}"' for n in ds_options])

    # Build metric descriptions for the prompt
    metric_lines = []
    for m_name, m_cfg in metrics.items():
        desc = m_cfg.get("description", "")
        expr = m_cfg.get("expr", "")
        metric_lines.append(f"- `{m_name}`: {desc} (表达式: {expr})")

    # Build dimension descriptions
    dim_lines = []
    for d_name, d_cfg in dimensions.items():
        desc = d_cfg.get("description", "")
        value_map = d_cfg.get("value_map")
        if value_map and isinstance(value_map, dict):
            values = ", ".join([f"{k}({v})" for k, v in list(value_map.items())[:8]])
            dim_lines.append(f"- `{d_name}`: {desc}（取值: {values}）")
        else:
            dim_lines.append(f"- `{d_name}`: {desc}")

    # Build data source descriptions
    ds_lines = []
    for ds_name, ds_cfg in data_sources.items():
        table = ds_cfg.get("table", ds_name)
        ds_metrics = ds_cfg.get("metrics", [])
        ds_dims = ds_cfg.get("dimensions", [])
        time_field = ds_cfg.get("time_field", "")
        joins = ds_cfg.get("joins", {})
        join_desc = ""
        if joins:
            join_parts = []
            for j_table, j_cfg in joins.items():
                on_field = j_cfg.get("on", "id")
                j_type = j_cfg.get("type", "left")
                alias = j_cfg.get("alias", j_table[0])
                join_parts.append(f"{j_type.upper()} JOIN {j_table} ON {on_field}, alias={alias}")
            join_desc = "; JOINs: " + "; ".join(join_parts)
        tf_desc = f"; time_field={time_field}" if time_field else ""
        ds_lines.append(
            f'- `{ds_name}` (主表: `{table}`): 可用指标: {ds_metrics}; 可用维度: {ds_dims}{tf_desc}{join_desc}'
        )

    metric_section = "\n".join(metric_lines) if metric_lines else "(无)"
    dim_section = "\n".join(dim_lines) if dim_lines else "(无)"
    ds_section = "\n".join(ds_lines) if ds_lines else "(无)"

    return f"""你是一个数据查询助手。请根据提供的信息将用户问题转换为 DSL（JSON 格式）。

你必须遵循以下规则，不要参考任何示例，只根据规则理解用户意图。

## 思维链检查步骤（执行这9步后再输出JSON）

1. **识别指标**：用户问的是哪个数值？ → 映射到 metrics
2. **识别维度**：用户说"按XX统计"？ → 映射到 dimensions
3. **识别过滤条件**：用户提到的所有具体限制条件 → 映射到 filters
4. **识别时间条件**：是否有年份、月份、最近N天等？ → 映射到 time_field + time_range
5. **识别排序**：是否有"最高""最低""前N"？ → 映射到 order_by + limit
6. **识别隐含JOIN**：是否涉及非主表字段？ → 映射到 joins
7. **识别聚合后过滤**：是否有对聚合结果的过滤？ → 映射到 having
8. **识别否定**：是否有"非""不是""排除"？ → 用 not 操作符
9. **遗漏检查**：重新读用户问题，确认没有遗漏任何条件

## 可用数据源
{ds_section}

## 可用指标
{metric_section}

## 可用维度
{dim_section}

## 过滤条件规则（核心）

### 操作符映射表
| 用户表达 | operator | value 格式 |
|---------|----------|-----------|
| 等于 / 是 | `=` | 字符串或数字 |
| 不等于 / 非 / 不是 / 排除 | `!=` | 字符串或数字 |
| 大于 / 超过 | `>` | 数字 |
| 小于 / 低于 | `<` | 数字 |
| 大于等于 | `>=` | 数字 |
| 小于等于 | `<=` | 数字 |
| 在...之间 / 从...到 | `between` | `[min, max]` 数组 |
| 在...之中 / 包含于 | `in` | `["a", "b"]` 数组 |
| 包含 / 像 | `like` | 字符串（自动加 % 通配符） |
| 为空 / NULL | `is_null` | 省略 value 字段 |

### 复合条件树结构
当用户问题包含多个条件时，必须用条件树（tree）格式：
```json
{{
  "op": "and",
  "children": [
    {{"field": "region", "operator": "=", "value": "华东"}},
    {{"field": "channel", "operator": "=", "value": "线上"}}
  ]
}}
```
支持 `and`（全部满足）、`or`（任一满足）、`not`（取反）。

### filter 字段格式规则（重要）
- `field` 必须是**维度名**，直接使用维度名称，**不要加数据源前缀**
- ❌ 错误: `{{"field": "transactions.channel_code", ...}}`
- ✅ 正确: `{{"field": "channel_code", ...}}`

### 数值处理规则
- "金额大于5000" → `{{"field": "pay_amount", "operator": ">", "value": 5000}}`
- "价格在5000到20000之间" → `{{"field": "pay_amount", "operator": "between", "value": [5000, 20000]}}`
- 数值不要加引号

### 否定处理规则（重要，常见错误）
- **"非""不是""排除""除外" → 必须使用 `!=` 或 `not` 条件树**
- "非手机品类" → `{{"field": "category", "operator": "!=", "value": "手机"}}`
- "排除华东地区" → `{{"field": "region", "operator": "!=", "value": "华东"}}`
- 当否定与其他条件并存时，必须用条件树包裹：
  ```json
  {{
    "op": "and",
    "children": [
      {{"field": "category", "operator": "!=", "value": "手机"}},
      {{"field": "pay_amount", "operator": ">", "value": 3000}}
    ]
  }}
  ```
- **注意**: "非" 不要用 `=`，必须用 `!=` 或 `not` 条件树

### 时间处理规则
- 可以用 time_field + time_range，也可以直接用 filters 中的 between

### HAVING 使用规则
当用户问题包含对聚合结果的过滤时，用 having（不是 filters）：
- having 的 field 必须是 metrics 中的某个 alias
- having 必须与 metrics 同时出现

## 字段格式要求

### metrics（指标，必填）
- 必须是数组，每个元素包含：
  - `func`: 聚合函数，只能是 "sum" | "avg" | "count" | "min" | "max"
  - `field`: 原始字段名（不要带 SUM/AVG/COUNT 等函数前缀）
  - `alias`: 指标别名，**必须是已注册的指标名**

### dimensions（维度，必填）
- 必须是字符串数组，不能为空数组 []
- **用户说"按XX统计"，dimensions 就必须包含 XX 对应的维度名**
- 如果用户没有指定分组维度，默认使用第一个可用维度

### filters（过滤条件，可选但重要）
- 可以是条件树（dict with op+children），也可以是旧格式的数组
- **用户提到的任何具体条件都必须出现在这里**
- 不要自己添加 tenant_id 过滤，系统会自动注入

### data_source（数据源，必填）
- 必须是以下之一: {ds_options_str}
- 默认使用 `"{default_ds}"`

### joins（多表关联，可选）
- 只有当查询涉及非主表字段时才需要
- 格式: `{{"table": "dim_name", "on_field": "join_key", "join_type": "left", "alias": "x"}}`

### limit（返回条数，必填）
- 必须是整数，默认 10，最多 100

## 输出规则
1. 只输出 JSON，不要输出任何解释文字
2. 不要输出 markdown 代码块标记
3. 所有字符串值用双引号
4. 数值不要用引号包裹
5. 确保所有用户提到的条件都在 DSL 中体现
"""


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str
    user_id: str
    tenant_id: str
    data_source: str | None = None


class QueryResponse(BaseModel):
    status: str
    data: list[dict] | None = None
    dsl: dict | None = None
    sql: str | None = None
    execution_time_ms: int = 0
    clarification: dict | None = None
    explanation: str | None = None
    confidence: float | None = None


class DSLExecuteRequest(BaseModel):
    dsl: dict
    user_id: str
    tenant_id: str


class DSLExecuteResponse(BaseModel):
    status: str
    data: list[dict] | None = None
    sql: str | None = None
    execution_time_ms: int = 0


class DSLGenerateResponse(BaseModel):
    status: str
    dsl: dict | None = None
    execution_time_ms: int = 0


class FeedbackRequest(BaseModel):
    query_id: str
    user_id: str
    corrected_dsl: dict | None = None
    comment: str = ""


class FeedbackResponse(BaseModel):
    status: str
    query_id: str


class SchemaResponse(BaseModel):
    data_sources: list[dict]
    metrics: list[dict]
    dimensions: list[dict]


class MetricsResponse(BaseModel):
    metrics: list[dict]


class EnumsResponse(BaseModel):
    enums: list[dict]


class RefreshEnumsResponse(BaseModel):
    status: str


class AuditQueryDetailItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str | None = None
    question: str
    dsl: dict | None = None
    sql: str | None = None
    status: str
    execution_time_ms: int | None = None
    rows_scanned: int | None = None
    rows_returned: int | None = None
    trace: list[dict] = []
    error_code: str | None = None
    error_message: str | None = None
    created_at: str


class AuditQueryDetailResponse(BaseModel):
    status: str = "success"
    item: AuditQueryDetailItem


class AuditQueryListItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str | None = None
    question: str
    status: str
    execution_time_ms: int | None = None
    rows_returned: int | None = None
    error_code: str | None = None
    created_at: str


class AuditQueryListResponse(BaseModel):
    status: str = "success"
    total: int
    limit: int
    offset: int
    items: list[AuditQueryListItem]


class StreamRequest(BaseModel):
    question: str
    user_id: str
    tenant_id: str
    data_source: str | None = None


class ResumeRequest(BaseModel):
    query_id: str
    action: str = "approve"  # "approve" | "reject"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app(
    engine: Engine | None = None,
    registry_dict: dict | None = None,
    permissions: dict | None = None,
    sensitive_columns: dict | None = None,
    masking_rules: dict | None = None,
    enable_clarification: bool = False,
    llm_client=None,
) -> FastAPI:
    """Create a FastAPI app with custom configuration.

    Args:
        engine: SQLAlchemy engine. If None, creates a default SQLite engine.
        registry_dict: Semantic registry dict with metrics/dimensions/data_sources.
        permissions: User permissions dict.
        sensitive_columns: Sensitive columns config.
        masking_rules: Masking rules dict.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(title="NL2DSL", version="0.1.0")

    from nl2dsl.engine import Engine

    _nl2dsl_engine = Engine()

    # Override db_engine if provided
    if engine is not None:
        _nl2dsl_engine.register("db_engine", engine)

    # Override registry and dependent components if provided
    if registry_dict is not None:
        _nl2dsl_engine.register("registry_dict", registry_dict)
        _nl2dsl_engine.register("validator", DSLValidator(registry_dict))
        _nl2dsl_engine.register("resolver", SemanticResolver(registry_dict))
        _db_engine = engine or _nl2dsl_engine.registry.get("db_engine")
        _nl2dsl_engine.register("sql_builder", SQLBuilder(
            _db_engine,
            {k: v.get("table", k) for k, v in registry_dict.get("data_sources", {}).items()},
            registry_dict.get("data_sources", {}),
            {k: v.get("column", k) for k, v in registry_dict.get("dimensions", {}).items()},
        ))
    elif engine is not None:
        # Engine was provided but registry_dict was not — rebuild sql_builder
        # with the new engine so metadata reflects the test database.
        _default_registry = _nl2dsl_engine.registry.get("registry_dict")
        if _default_registry:
            _nl2dsl_engine.register("sql_builder", SQLBuilder(
                engine,
                {k: v.get("table", k) for k, v in _default_registry.get("data_sources", {}).items()},
                _default_registry.get("data_sources", {}),
                {k: v.get("column", k) for k, v in _default_registry.get("dimensions", {}).items()},
            ))

    # Override permission components
    _nl2dsl_engine.register("row_security", RowLevelSecurity(permissions or {}))
    _nl2dsl_engine.register("col_security", ColumnLevelSecurity(sensitive_columns or {}, masking_rules or {}))

    # Clarification detector: real detector when enabled (so trend/growth
    # queries missing time context clarify on the api_factory/E2E path too),
    # otherwise a no-op to preserve pre-LangGraph behavior.
    class _NoOpClarificationDetector:
        def detect(self, question: str) -> list:
            return []

    if enable_clarification:
        clarification_detector = ClarificationDetector()
    else:
        clarification_detector = _NoOpClarificationDetector()
    _nl2dsl_engine.register("clarification_detector", clarification_detector)

    # Registry used for registry-aware entity extraction in the agent route.
    _route_registry = registry_dict or _nl2dsl_engine.registry.get("registry_dict") or {}

    # Services used directly by routes
    feedback_collector = FeedbackCollector()
    _db_engine = engine or _nl2dsl_engine.registry.get("db_engine")
    audit_logger = AuditLogger(_db_engine)

    # Cache AgentController to avoid re-loading intents.yaml on every request
    _agent_controller = AgentController()

    # Build a fresh LangGraph StateGraph with the overridden components.
    # Do NOT use _nl2dsl_engine.build() which returns a pre-built graph
    # using default components from _load_defaults().
    _validator = _nl2dsl_engine.registry.get("validator")
    _resolver = _nl2dsl_engine.registry.get("resolver")
    _sql_builder = _nl2dsl_engine.registry.get("sql_builder")
    _row_security = _nl2dsl_engine.registry.get("row_security")
    _col_security = _nl2dsl_engine.registry.get("col_security")
    _scanner = SQLScanner()
    _sandbox = QuerySandbox(_db_engine)
    _executor = SQLExecutor(_db_engine)

    # Build SemanticConfig for the optimizer from the registry dict
    _optimizer_config = None
    if registry_dict:
        from nl2dsl.optimizer.context import SemanticConfig
        _optimizer_config = SemanticConfig.from_registry_dict(registry_dict)

    query_graph = build_graph(
        llm_client=llm_client,
        rag_retriever=None,
        validator=_validator,
        row_security=_row_security,
        col_security=_col_security,
        resolver=_resolver,
        sql_builder=_sql_builder,
        scanner=_scanner,
        sandbox=_sandbox,
        executor=_executor,
        clarification_detector=clarification_detector,
        registry_dict=registry_dict or {},
        llm_system_prompt=DSL_SYSTEM_PROMPT,
        checkpointer=None,
        optimizer_semantic_config=_optimizer_config,
    )

    # Build DomainContext for AgentOrchestrator
    def _get_or_build_domain_context(domain: str = "ecommerce") -> DomainContext:
        """Build a DomainContext for the given domain.

        Uses the same components as the query_graph for consistency.
        """
        return DomainContext(
            domain=domain,
            registry_dict=registry_dict or {},
            validator=_validator,
            resolver=_resolver,
            sql_builder=_sql_builder,
            sandbox=_sandbox,
            executor=_executor,
            row_security=_row_security,
            col_security=_col_security,
            rag_retriever=None,
            graph=query_graph,
        )

    def _build_domains_dict() -> dict[str, DomainContext]:
        """Build domains dict using the app's configured components.

        Always builds fresh DomainContexts from the components configured in
        create_app to ensure test-injected overrides are respected.
        """
        domains: dict[str, DomainContext] = {}
        # Use the domain names discovered by the engine, but build fresh
        # DomainContexts with the overridden components from this create_app call.
        domain_names = ["ecommerce"]
        if hasattr(_nl2dsl_engine, '_domains') and _nl2dsl_engine._domains:
            domain_names = list(_nl2dsl_engine._domains.keys())
        for domain_name in domain_names:
            domains[domain_name] = _get_or_build_domain_context(domain_name)
        return domains

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_query_response(result: dict, elapsed: int, query_id: str, question: str) -> QueryResponse:
        """Build QueryResponse from graph result state."""
        status = result.get("status", "error")

        if status == "clarification":
            ambiguities = result.get("ambiguities")
            return QueryResponse(
                status="clarification",
                clarification={
                    "message": "查询存在歧义，请确认以下信息",
                    "items": [a.model_dump() for a in ambiguities] if ambiguities else [],
                },
                execution_time_ms=elapsed,
            )

        if status == "error":
            raise ValidationError(result.get("error", "Unknown error"))

        if status == "warning" or status == "pending_review":
            return QueryResponse(
                status=status,
                data=[],
                dsl=result.get("dsl").model_dump() if result.get("dsl") else None,
                sql=result.get("sql"),
                execution_time_ms=elapsed,
            )

        # success
        dsl = result.get("dsl")
        return QueryResponse(
            status="success",
            data=result.get("data"),
            dsl=dsl.model_dump() if dsl else None,
            sql=result.get("sql"),
            execution_time_ms=elapsed,
            explanation=result.get("explanation"),
            confidence=result.get("confidence"),
        )

    def _build_trace(result: dict) -> list[dict]:
        """Extract trace entries from graph result state."""
        trace = result.get("trace")
        if trace is None:
            return []
        if isinstance(trace, list):
            return trace
        return [trace] if trace else []

    # -----------------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/query/dsl")
    async def query_dsl(req: QueryRequest) -> DSLGenerateResponse:
        start = time.time()
        query_id = str(uuid.uuid4())

        state = QueryState(
            question=req.question,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            data_source=req.data_source,
            ambiguities=None,
            dsl=None,
            dsl_attempts=None,
            sql=None,
            sandbox_result=None,
            complexity=None,
            data=None,
            status="pending",
            error=None,
            error_code=None,
            trace=None,
            query_id=query_id,
            started_at=start,
            llm_used=False,
        )

        config = {"configurable": {"thread_id": query_id}}
        result = await query_graph.ainvoke(state, config)

        elapsed = int((time.time() - start) * 1000)
        dsl = result.get("dsl")
        return DSLGenerateResponse(
            status="success",
            dsl=dsl.model_dump() if dsl else None,
            execution_time_ms=elapsed,
        )

    @app.post("/api/v1/query")
    async def query(req: QueryRequest) -> QueryResponse:
        start = time.time()
        query_id = str(uuid.uuid4())

        try:
            # Step 0: Clarification check (only when enabled)
            if enable_clarification:
                t = time.time()
                ambiguities = clarification_detector.detect(req.question)
                if ambiguities:
                    trace = [{"step": "clarification", "status": "success", "duration_ms": int((time.time() - t) * 1000)}]
                    audit_logger.log(
                        query_id=query_id,
                        user_id=req.user_id,
                        tenant_id=req.tenant_id,
                        question=req.question,
                        status="clarification",
                        execution_time_ms=int((time.time() - start) * 1000),
                        trace_json=trace,
                    )
                    return QueryResponse(
                        status="clarification",
                        clarification={
                            "message": "查询存在歧义，请确认以下信息",
                            "items": [a.model_dump() for a in ambiguities],
                        },
                        execution_time_ms=int((time.time() - start) * 1000),
                    )

            # Step 1: Route via AgentController (intent classification + routing)
            from nl2dsl.agent.orchestrator import AgentOrchestrator
            entities = AgentOrchestrator._extract_entities(req.question, _route_registry)
            execution_plan = await _agent_controller.route(req.question, entities)

            # Step 2: Dispatch based on execution plan type
            if isinstance(execution_plan, (ComplexExecutionPlan, ExplorationPlan)):
                # Complex query: use AgentOrchestrator
                domains = _build_domains_dict()
                orchestrator = AgentOrchestrator(domains=domains, llm_client=llm_client)

                agent_result = await orchestrator.run(
                    question=req.question,
                    user_id=req.user_id,
                    tenant_id=req.tenant_id,
                    domain="ecommerce",
                    sse_callback=None,
                )

                elapsed = int((time.time() - start) * 1000)

                # Audit log with agent status
                audit_logger.log(
                    query_id=query_id,
                    user_id=req.user_id,
                    tenant_id=req.tenant_id,
                    question=req.question,
                    status=agent_result.status,
                    execution_time_ms=elapsed,
                    rows_returned=len(agent_result.data) if agent_result.data else 0,
                    trace_json=[{"step": "agent", "status": agent_result.status, "intent": getattr(getattr(execution_plan, 'plan', None), 'intent', 'exploration')}],
                    error_code=None,
                    error_message=agent_result.error,
                )

                if agent_result.status == "error":
                    raise ValidationError(agent_result.error or "Agent execution failed")

                # Surface agent status as-is (success / warning / clarification)
                response_status = agent_result.status if agent_result.status != "error" else "success"

                return QueryResponse(
                    status=response_status,
                    data=agent_result.data,
                    dsl=agent_result.dsl,
                    sql=agent_result.sql,
                    execution_time_ms=elapsed,
                    explanation=agent_result.explanation,
                    confidence=agent_result.confidence,
                )

            # Simple query: continue with existing graph flow
            # Build a single-query plan for the graph.
            plan = _decompose_fallback(req.question, "single_query")
            state = QueryState(
                question=req.question,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                data_source=req.data_source,
                ambiguities=None,
                plan=plan,
                dsl=None,
                dsl_attempts=None,
                sql=None,
                sandbox_result=None,
                complexity=None,
                data=None,
                status="pending",
                error=None,
                error_code=None,
                trace=None,
                query_id=query_id,
                started_at=start,
                llm_used=False,
            )

            config = {"configurable": {"thread_id": query_id}}
            result = await query_graph.ainvoke(state, config)
            elapsed = int((time.time() - start) * 1000)

            trace_entries = _build_trace(result)

            # Audit log
            dsl = result.get("dsl")
            sql = result.get("sql")
            status = result.get("status", "error")
            data = result.get("data")

            audit_logger.log(
                query_id=query_id,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                question=req.question,
                dsl_json=dsl.model_dump() if dsl else None,
                sql_text=sql,
                status=status,
                execution_time_ms=elapsed,
                rows_returned=len(data) if data else 0,
                trace_json=trace_entries,
                error_code=result.get("error_code"),
                error_message=result.get("error"),
            )

            return _build_query_response(result, elapsed, query_id, req.question)
        except NL2DSLException as exc:
            elapsed = int((time.time() - start) * 1000)
            audit_logger.log(
                query_id=query_id,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                question=req.question,
                status="error",
                execution_time_ms=elapsed,
                error_code=exc.error_code,
                error_message=exc.message,
                trace_json=[],
            )
            raise

    @app.post("/api/v1/query/execute")
    async def query_execute(req: DSLExecuteRequest) -> DSLExecuteResponse:
        start = time.time()
        query_id = str(uuid.uuid4())

        dsl = DSL(**req.dsl)

        state = QueryState(
            question="",
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            data_source=None,
            ambiguities=None,
            dsl=dsl,
            dsl_attempts=None,
            sql=None,
            sandbox_result=None,
            complexity=None,
            data=None,
            status="pending",
            error=None,
            error_code=None,
            trace=None,
            query_id=query_id,
            started_at=start,
            llm_used=False,
        )

        config = {"configurable": {"thread_id": query_id}}
        result = await query_graph.ainvoke(state, config)

        elapsed = int((time.time() - start) * 1000)

        status = result.get("status", "error")
        if status == "error":
            raise ValidationError(result.get("error", "Query execution failed"))

        return DSLExecuteResponse(
            status="success",
            data=result.get("data"),
            sql=result.get("sql"),
            execution_time_ms=elapsed,
        )

    @app.post("/api/v1/query/stream")
    async def query_stream(req: StreamRequest):
        """Stream query execution updates via SSE.

        For simple queries (single_query intent), emits standard graph updates.
        For complex queries (compare/trend/correlation), uses AgentOrchestrator
        with SSE callback to emit structured agent events.
        """
        query_id = str(uuid.uuid4())
        import json

        # Step 1: Route via AgentController (intent classification + routing)
        from nl2dsl.agent.orchestrator import AgentOrchestrator
        entities = AgentOrchestrator._extract_entities(req.question, _route_registry)
        execution_plan = await _agent_controller.route(req.question, entities)

        if isinstance(execution_plan, (ComplexExecutionPlan, ExplorationPlan)):
            # Complex query: use AgentOrchestrator with real-time SSE streaming
            domains = _build_domains_dict()
            orchestrator = AgentOrchestrator(domains=domains, llm_client=llm_client)

            async def agent_event_generator():
                import asyncio
                queue: asyncio.Queue = asyncio.Queue()

                async def sse_callback(event_type: str, payload: dict):
                    await queue.put({"event": event_type, "data": payload})

                async def run_agent():
                    try:
                        agent_result = await orchestrator.run(
                            question=req.question,
                            user_id=req.user_id,
                            tenant_id=req.tenant_id,
                            domain="ecommerce",
                            sse_callback=sse_callback,
                        )
                        await queue.put({
                            "event": "result",
                            "data": {
                                "status": agent_result.status,
                                "data": agent_result.data,
                                "dsl": agent_result.dsl,
                                "sql": agent_result.sql,
                                "explanation": agent_result.explanation,
                                "confidence": agent_result.confidence,
                            },
                        })
                    except Exception as exc:
                        await queue.put({"event": "error", "data": {"error": str(exc)}})
                    finally:
                        await queue.put(None)  # sentinel

                # Start orchestrator in background
                asyncio.create_task(run_agent())

                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    event_type = event.get("event", "data")
                    payload = event.get("data", {})
                    yield f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"

                yield "event: done\ndata: {}\n\n"

            return StreamingResponse(
                agent_event_generator(),
                media_type="text/event-stream",
            )

        # Simple query: emit standard graph updates
        state = QueryState(
            question=req.question,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            data_source=req.data_source,
            ambiguities=None,
            dsl=None,
            dsl_attempts=None,
            sql=None,
            sandbox_result=None,
            complexity=None,
            data=None,
            status="pending",
            error=None,
            error_code=None,
            trace=None,
            query_id=query_id,
            started_at=time.time(),
            llm_used=False,
        )

        config = {"configurable": {"thread_id": query_id}}

        async def event_generator():
            async for chunk in query_graph.astream(state, config, stream_mode="updates"):
                yield f"event: update\ndata: {json.dumps(chunk, default=str)}\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    @app.post("/api/v1/query/resume")
    async def query_resume(req: ResumeRequest):
        """Resume a paused query (human-in-the-loop approval/rejection)."""
        config = {"configurable": {"thread_id": req.query_id}}

        # Get current state
        try:
            current_state = await query_graph.aget_state(config)
        except ValueError as exc:
            if "No checkpointer set" in str(exc):
                raise NotFoundError(f"Query not found: query_id={req.query_id}")
            raise
        if current_state is None:
            raise NotFoundError(f"Query not found: query_id={req.query_id}")

        # Update state with approval/rejection
        if req.action == "approve":
            # Continue execution from human_review node
            result = await query_graph.ainvoke(
                None,
                config,
            )
        else:
            # Reject: mark as error and end
            result = await query_graph.ainvoke(
                {"status": "error", "error": "Human review rejected", "error_code": "REJECTED"},
                config,
            )

        return QueryResponse(
            status=result.get("status", "error"),
            data=result.get("data"),
            dsl=result.get("dsl").model_dump() if result.get("dsl") else None,
            sql=result.get("sql"),
            execution_time_ms=0,
        )

    @app.get("/api/v1/schema")
    async def get_schema() -> SchemaResponse:
        data_sources = [
            {"name": k, "table": v.get("table", k), "metrics": v.get("metrics", []), "dimensions": v.get("dimensions", [])}
            for k, v in registry_dict.get("data_sources", {}).items()
        ]
        metrics = [
            {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
            for k, v in registry_dict.get("metrics", {}).items()
        ]
        dimensions = [
            {"name": k, "column": v.get("column", k), "description": v.get("description", "")}
            for k, v in registry_dict.get("dimensions", {}).items()
        ]
        return SchemaResponse(data_sources=data_sources, metrics=metrics, dimensions=dimensions)

    @app.get("/api/v1/metrics")
    async def get_metrics() -> MetricsResponse:
        metrics = [
            {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
            for k, v in registry_dict.get("metrics", {}).items()
        ]
        return MetricsResponse(metrics=metrics)

    @app.post("/api/v1/feedback")
    async def post_feedback(req: FeedbackRequest) -> FeedbackResponse:
        feedback_collector.collect(
            query_id=req.query_id,
            user_id=req.user_id,
            corrected_dsl=req.corrected_dsl,
            comment=req.comment,
        )
        return FeedbackResponse(status="received", query_id=req.query_id)

    @app.get("/api/v1/admin/enums")
    async def get_enums() -> EnumsResponse:
        return EnumsResponse(enums=[])

    @app.post("/api/v1/admin/enums/refresh")
    async def refresh_enums() -> RefreshEnumsResponse:
        return RefreshEnumsResponse(status="refreshed")

    @app.get("/api/v1/admin/audit/queries/{query_id}")
    async def get_audit_query(query_id: str) -> AuditQueryDetailResponse:
        row = audit_logger.get_query(query_id)
        if row is None:
            raise NotFoundError(f"audit record not found: query_id={query_id}")
        row["created_at"] = str(row.get("created_at") or "")
        return AuditQueryDetailResponse(item=AuditQueryDetailItem(**row))

    @app.get("/api/v1/admin/audit/queries")
    async def list_audit_queries(
        user_id: str | None = None,
        tenant_id: str | None = None,
        status_: str | None = Query(None, alias="status"),
        start_time: str | None = None,
        end_time: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> AuditQueryListResponse:
        if not (1 <= limit <= 100):
            raise ValidationError("limit must be between 1 and 100")
        if offset < 0:
            raise ValidationError("offset must be >= 0")

        items, total = audit_logger.list_queries(
            user_id=user_id,
            tenant_id=tenant_id,
            status=status_,
            start_time=start_time,
            end_time=end_time,
            question_like=q,
            limit=limit,
            offset=offset,
        )
        for it in items:
            it["created_at"] = str(it.get("created_at") or "")
        return AuditQueryListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[AuditQueryListItem(**r) for r in items],
        )

    @app.exception_handler(NL2DSLException)
    async def nl2dsl_exception_handler(request: Request, exc: NL2DSLException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": "error", "error_code": exc.error_code, "message": exc.message},
        )

    # Static files (frontend)
    _frontend_dir = Path(__file__).parent.parent / "web" / "dist"
    if _frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="static")

    return app
