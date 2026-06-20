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
from pydantic import BaseModel, Field, field_validator, ValidationError as PydanticValidationError
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


def _extract_value_maps(dimensions: dict) -> dict[str, dict]:
    """从 registry dimensions 提取 {dim_name: value_map}，供 SQLBuilder 翻译过滤值。

    SemanticResolver 保留语义值（如"华东"），由 SQLBuilder 在构建 WHERE 时翻译
    为物理编码（如"HD"）。仅收集非空 value_map。
    """
    return {
        name: cfg.get("value_map")
        for name, cfg in dimensions.items()
        if isinstance(cfg, dict) and cfg.get("value_map")
    }

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
    domain: str = Field(default="ecommerce", description="业务领域")
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
    query_id: str | None = None


class DSLExecuteRequest(BaseModel):
    dsl: dict
    user_id: str
    tenant_id: str
    domain: str = Field(default="ecommerce", description="业务领域")


class DSLExecuteResponse(BaseModel):
    status: str
    data: list[dict] | None = None
    sql: str | None = None
    execution_time_ms: int = 0
    query_id: str | None = None


class DSLGenerateResponse(BaseModel):
    status: str
    dsl: dict | None = None
    execution_time_ms: int = 0
    query_id: str | None = None


# 统一的反馈 issue_type 枚举
FEEDBACK_ISSUE_TYPES = {
    "intent", "metric", "dimension", "filter", "time", "join",
    "ranking", "proportion", "permission", "result", "other",
}


def _validate_non_blank(value: str, field_name: str) -> str:
    """通用非空白校验：返回去除首尾空白后的值，空白则抛 ValueError（→ 422）。"""
    if value is None or not str(value).strip():
        raise ValueError(f"{field_name} 不能为空")
    return str(value).strip()


def _safe_error_message(exc: Exception, max_len: int = 300) -> str:
    """对未预期异常生成安全的审计/响应信息。

    记录异常类型与截断后的信息，便于排查；同时抹除常见的密钥与数据库连接串
    模式，避免在审计日志或错误响应中泄露敏感凭据。
    """
    import re

    raw = f"{type(exc).__name__}: {exc}"
    # 抹除 `user:pass@host` 形式的连接串凭据
    raw = re.sub(r"://[^/\s:]+:[^/\s@]+@", "://***:***@", raw)
    # 抹除形如 password=xxx / api_key=xxx 的明文凭据
    raw = re.sub(r"(?i)(password|api[_-]?key|secret|token)\s*=\s*\S+", r"\1=***", raw)
    if len(raw) > max_len:
        raw = raw[:max_len] + "…"
    return raw


def _json_dumps_key(obj) -> str:
    """生成可用于去重比较的稳定 JSON 串（dict 不可哈希，用此替代集合成员判定）。"""
    import json

    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)


class FeedbackRequest(BaseModel):
    query_id: str
    user_id: str
    # tenant_id 必填且不得为空白：租户隔离不能由调用方置空绕过。
    tenant_id: str
    is_correct: bool = True
    issue_type: str | None = None
    corrected_dsl: dict | None = None
    comment: str = ""

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_non_blank(cls, v: str) -> str:
        return _validate_non_blank(v, "tenant_id")

    @field_validator("user_id")
    @classmethod
    def _user_id_non_blank(cls, v: str) -> str:
        return _validate_non_blank(v, "user_id")

    @field_validator("query_id")
    @classmethod
    def _query_id_non_blank(cls, v: str) -> str:
        return _validate_non_blank(v, "query_id")


class FeedbackResponse(BaseModel):
    status: str
    query_id: str
    feedback_id: str | None = None
    deduplicated: bool = False


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
    domain: str = Field(default="ecommerce", description="业务领域")
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
    enable_optimizer: bool = True,
    generator_mode: str | None = None,
    feedback_store=None,
    app_domain: str = "ecommerce",
) -> FastAPI:
    """Create a FastAPI app with custom configuration.

    Args:
        engine: SQLAlchemy engine. If None, creates a default SQLite engine.
        registry_dict: Semantic registry dict with metrics/dimensions/data_sources.
        permissions: User permissions dict.
        sensitive_columns: Sensitive columns config.
        masking_rules: Masking rules dict.
        enable_clarification: Whether to run clarification detection.
        llm_client: LLM client for DSL generation (may be None).
        enable_optimizer: 显式控制 Semantic Optimizer。False 时图中不注册
            ``optimize_dsl`` 节点，Trace 中也不会出现该步骤。
        generator_mode: ``"rule"`` 强制使用规则生成器（llm_client 置空）；
            ``"llm"`` 使用 llm_client；``None`` 保持兼容（有 client 用 LLM，
            无 client 静默回退规则）。评测执行器在 ``llm`` 模式无 client 时
            自行返回 unavailable，不进入此处。
        feedback_store: 可选的 :class:`FeedbackStore`。未提供时使用 JSONL
            ``FeedbackCollector``（兼容旧路径）。

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(title="NL2DSL", version="0.1.0")

    from nl2dsl.engine import Engine

    _nl2dsl_engine = Engine()

    # 是否注入了任何覆盖项。无覆盖时走“正式生产路径”，直接复用 Engine 已构建
    # 的真实 DomainContext（含 RAG / Optimizer / 权限 / checkpointer），避免
    # 重建图丢失治理与检索能力。有覆盖时走“测试/注入路径”，按注入项重建。
    _has_overrides = (
        registry_dict is not None
        or engine is not None
        or permissions is not None
        or sensitive_columns is not None
        or masking_rules is not None
    )

    # Clarification detector: real detector when enabled, otherwise no-op.
    class _NoOpClarificationDetector:
        def detect(self, question: str) -> list:
            return []

    if enable_clarification:
        clarification_detector = ClarificationDetector()
    else:
        clarification_detector = _NoOpClarificationDetector()

    # Cache AgentController to avoid re-loading intents.yaml on every request
    _agent_controller = AgentController()

    # Services used directly by routes
    feedback_collector = FeedbackCollector()

    if not _has_overrides:
        # ------------------------------------------------------------------
        # 正式生产路径：复用 Engine 真实 DomainContext
        # ------------------------------------------------------------------
        _db_engine = _nl2dsl_engine.registry.get("db_engine")
        audit_logger = AuditLogger(_db_engine)
        _route_registry = _nl2dsl_engine.registry.get("registry_dict") or {}
        # 正式 API 默认使用数据库 FeedbackStore（与 Audit 共用 Engine）。
        from nl2dsl.feedback.store import FeedbackStore
        if feedback_store is None:
            feedback_store = FeedbackStore(_db_engine, audit_logger)
        elif feedback_store is False:
            feedback_store = None

        _graph_llm_client = llm_client

        def _get_domain_graph(domain: str):
            ctx = _nl2dsl_engine._domains.get(domain)
            if ctx is None:
                raise NotFoundError(f"未知业务领域：domain={domain}")
            return ctx.graph

        def _build_domains_dict() -> dict[str, DomainContext]:
            return dict(_nl2dsl_engine._domains)

        def _domain_registry(domain: str) -> dict:
            ctx = _nl2dsl_engine._domains.get(domain)
            if ctx is None:
                raise NotFoundError(f"未知业务领域：domain={domain}")
            return ctx.registry_dict or {}

        query_graph = _get_domain_graph("ecommerce")  # 默认引用，部分路由直接使用
    else:
        # ------------------------------------------------------------------
        # 测试 / 注入路径：按注入项重建图与组件
        # ------------------------------------------------------------------
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
                registry_dict.get("metrics", {}),
                _extract_value_maps(registry_dict.get("dimensions", {})),
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
                    _default_registry.get("metrics", {}),
                    _extract_value_maps(_default_registry.get("dimensions", {})),
                ))

        # Override permission components
        _nl2dsl_engine.register("row_security", RowLevelSecurity(permissions or {}))
        _nl2dsl_engine.register("col_security", ColumnLevelSecurity(sensitive_columns or {}, masking_rules or {}))
        _nl2dsl_engine.register("clarification_detector", clarification_detector)

        # Registry used for registry-aware entity extraction in the agent route.
        _route_registry = registry_dict or _nl2dsl_engine.registry.get("registry_dict") or {}

        _db_engine = engine or _nl2dsl_engine.registry.get("db_engine")
        audit_logger = AuditLogger(_db_engine)

        # 正式 API 默认使用数据库 FeedbackStore（与 Audit 共用 Engine）。
        from nl2dsl.feedback.store import FeedbackStore
        if feedback_store is None:
            feedback_store = FeedbackStore(_db_engine, audit_logger)
        elif feedback_store is False:
            # 显式禁用数据库存储，回退到 JSONL 兼容路径
            feedback_store = None

        # Build a fresh LangGraph StateGraph with the overridden components.
        _validator = _nl2dsl_engine.registry.get("validator")
        _resolver = _nl2dsl_engine.registry.get("resolver")
        _sql_builder = _nl2dsl_engine.registry.get("sql_builder")
        _row_security = _nl2dsl_engine.registry.get("row_security")
        _col_security = _nl2dsl_engine.registry.get("col_security")
        _scanner = SQLScanner()
        _sandbox = QuerySandbox(_db_engine)
        _executor = SQLExecutor(_db_engine)

        # Build SemanticConfig for the optimizer from the registry dict.
        # enable_optimizer=False 时显式关闭：不传 semantic config → 图中不注册
        # optimize_dsl 节点 → Trace 中不会出现该步骤。
        _optimizer_config = None
        if registry_dict and enable_optimizer:
            from nl2dsl.optimizer.context import SemanticConfig
            _optimizer_config = SemanticConfig.from_registry_dict(registry_dict)

        # generator_mode="rule" 强制使用规则生成器（即使传入了 llm_client）。
        _graph_llm_client = llm_client
        if generator_mode == "rule":
            _graph_llm_client = None

        # 注入路径只服务于单一业务领域（其 registry 即 app_domain）。
        _app_domain = app_domain

        query_graph = build_graph(
            llm_client=_graph_llm_client,
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

        def _get_domain_graph(domain: str):
            if domain != _app_domain:
                raise NotFoundError(f"未知业务领域：domain={domain}（当前 app 仅服务 {_app_domain}）")
            return query_graph

        def _domain_registry(domain: str) -> dict:
            if domain != _app_domain:
                raise NotFoundError(f"未知业务领域：domain={domain}（当前 app 仅服务 {_app_domain}）")
            return registry_dict or {}

        # Build DomainContext for AgentOrchestrator（仅 app_domain）
        def _get_or_build_domain_context(domain: str = "ecommerce") -> DomainContext:
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
            """注入路径仅构建 app_domain 对应的 DomainContext。"""
            return {_app_domain: _get_or_build_domain_context(_app_domain)}

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
                query_id=query_id,
            )

        if status == "error":
            raise ValidationError(result.get("error", "Unknown error"))

        if status == "warning":
            return QueryResponse(
                status="warning",
                data=result.get("data"),
                dsl=result.get("dsl").model_dump() if result.get("dsl") else None,
                sql=result.get("sql"),
                execution_time_ms=elapsed,
                explanation=result.get("explanation"),
                confidence=result.get("confidence"),
                query_id=query_id,
            )

        if status == "pending_review":
            return QueryResponse(
                status="pending_review",
                data=[],
                dsl=result.get("dsl").model_dump() if result.get("dsl") else None,
                sql=result.get("sql"),
                execution_time_ms=elapsed,
                query_id=query_id,
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
            query_id=query_id,
        )

    def _build_trace(result: dict) -> list[dict]:
        """Extract trace entries from graph result state."""
        trace = result.get("trace")
        if trace is None:
            return []
        if isinstance(trace, list):
            return trace
        return [trace] if trace else []

    def _merge_update_chunks(chunks: list) -> dict:
        """将 ``stream_mode="updates"`` 产生的多个 chunk 合并为最终状态。

        每个 chunk 形如 ``{node_name: {field: value, ...}}``（部分版本也可能是
        扁平的 state dict）。按“后写覆盖”合并标量字段；``trace`` /
        ``dsl_attempts`` 作为列表累加。这样不必依赖 checkpointer 的
        ``aget_state``（注入/测试路径无 checkpointer），也能拿到真实的最终状态，
        而不是把最后一个 update chunk 当成完整状态。
        """
        merged: dict = {"trace": [], "dsl_attempts": []}

        def _append_list(field: str, v) -> None:
            """累加 trace / dsl_attempts：v 可能是单个 dict、list 或 None。

            节点在 updates 模式下返回的 trace 可能是单个 dict（如
            ``{"step": "build_sql", ...}``）也可能是 list，统一收进列表并按
            JSON 串去重（dict 不可哈希，不能直接用 set）。
            """
            if v is None:
                return
            if isinstance(v, dict):
                v = [v]
            elif not isinstance(v, list):
                return
            bucket = merged.setdefault(field, [])
            seen = {_json_dumps_key(e) for e in bucket}
            for entry in v:
                key = _json_dumps_key(entry)
                if key not in seen:
                    bucket.append(entry)
                    seen.add(key)

        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            # 兼容两种 chunk 形态：{node: update} 或 扁平 update
            if len(chunk) == 1:
                only_value = next(iter(chunk.values()))
                if isinstance(only_value, dict):
                    items = only_value.items()
                else:
                    items = chunk.items()
            else:
                items = chunk.items()
            for k, v in items:
                if v is None:
                    continue
                if k in ("trace", "dsl_attempts"):
                    _append_list(k, v)
                else:
                    merged[k] = v
        return merged

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
        result = await _get_domain_graph(req.domain).ainvoke(state, config)

        elapsed = int((time.time() - start) * 1000)
        dsl = result.get("dsl")
        # 审计：/query/dsl 同样记录，便于反馈关联
        audit_logger.log(
            query_id=query_id,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            question=req.question,
            dsl_json=dsl.model_dump() if dsl else None,
            status=result.get("status", "success"),
            execution_time_ms=elapsed,
            trace_json=_build_trace(result),
        )
        return DSLGenerateResponse(
            status="success",
            dsl=dsl.model_dump() if dsl else None,
            execution_time_ms=elapsed,
            query_id=query_id,
        )

    @app.post("/api/v1/query")
    async def query(req: QueryRequest) -> QueryResponse:
        start = time.time()
        query_id = str(uuid.uuid4())
        # 领域校验：未知 domain 立即失败，不静默回退 ecommerce。
        _get_domain_graph(req.domain)

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
                        query_id=query_id,
                    )

            # Step 1: Route via AgentController (intent classification + routing)
            from nl2dsl.agent.orchestrator import AgentOrchestrator
            entities = AgentOrchestrator._extract_entities(req.question, _route_registry)
            execution_plan = await _agent_controller.route(req.question, entities)

            # Step 2: Dispatch based on execution plan type
            if isinstance(execution_plan, (ComplexExecutionPlan, ExplorationPlan)):
                # Complex query: use AgentOrchestrator
                domains = _build_domains_dict()
                orchestrator = AgentOrchestrator(domains=domains, llm_client=_graph_llm_client)

                agent_result = await orchestrator.run(
                    question=req.question,
                    user_id=req.user_id,
                    tenant_id=req.tenant_id,
                    domain=req.domain,
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
                    trace_json=agent_result.trace or [{"step": "agent", "status": agent_result.status, "intent": getattr(getattr(execution_plan, 'plan', None), 'intent', 'exploration')}],
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
                    query_id=query_id,
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
            result = await _get_domain_graph(req.domain).ainvoke(state, config)
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
    async def query_execute(req: DSLExecuteRequest):
        """执行已构建的 DSL。

        第二轮审阅 P1：整个执行流程（领域解析 → DSL 解析 → graph 执行 → SQL
        构建扫描执行）统一用 try/except/finally 覆盖，确保成功 / clarification
        / 业务错误 / 未预期异常都写入同一条 query_id 对应的 error Audit，不再
        有“异常跳过审计”的盲区。失败响应体携带 query_id，便于客户端关联审计
        与反馈。
        """
        start = time.time()
        query_id = str(uuid.uuid4())

        # 贯穿 try/except/finally 的状态变量，保证 finally 能写出准确审计。
        status: str = "error"
        error_code: str | None = None
        error_message: str | None = None
        result_dsl = None
        parsed_dsl: DSL | None = None
        sql: str | None = None
        data = None
        trace_entries: list = []
        # 错误响应状态码：业务错误默认 400，按异常类型调整。
        http_status = 400

        try:
            # 领域校验：未知 domain 立即失败（NotFoundError → 404）。
            graph = _get_domain_graph(req.domain)

            # DSL Schema 解析：非法结构抛 pydantic ValidationError → 422。
            parsed_dsl = DSL(**req.dsl)

            state = QueryState(
                question="",
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                data_source=None,
                ambiguities=None,
                dsl=parsed_dsl,
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
            result = await graph.ainvoke(state, config)

            trace_entries = _build_trace(result)
            status = result.get("status", "error")
            result_dsl = result.get("dsl")
            sql = result.get("sql")
            data = result.get("data")
            error_code = result.get("error_code")
            error_message = result.get("error")

            if status == "clarification":
                # clarification 不是错误，但仍需审计（status=clarification）。
                pass
            elif status == "error":
                # graph 返回 error 状态：业务错误，400。
                http_status = 400
                if not error_message:
                    error_message = "Query execution failed"
        except NL2DSLException as exc:
            status = "error"
            error_code = exc.error_code
            error_message = exc.message
            http_status = exc.status_code
        except PydanticValidationError as exc:
            # DSL Schema 解析失败：客户端错误，422。仍写 error Audit。
            status = "error"
            error_code = "DSL_SCHEMA_ERROR"
            error_message = _safe_error_message(exc)
            http_status = 422
        except Exception as exc:  # noqa: BLE001 — 兜底：任何未预期异常都要审计
            status = "error"
            error_code = "INTERNAL_ERROR"
            error_message = _safe_error_message(exc)
            http_status = 500
        finally:
            elapsed = int((time.time() - start) * 1000)
            # 成功时优先用最终 dsl；解析/执行失败回退到已解析的 dsl（若有）。
            dsl_for_audit = result_dsl if result_dsl is not None else parsed_dsl
            audit_logger.log(
                query_id=query_id,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                question="(execute)",
                dsl_json=dsl_for_audit.model_dump() if dsl_for_audit else None,
                sql_text=sql,
                status=status,
                execution_time_ms=elapsed,
                rows_returned=len(data) if data else 0,
                trace_json=trace_entries,
                error_code=error_code,
                error_message=error_message,
            )

        if status == "error":
            # 失败响应体携带 query_id，便于客户端关联审计 / 提交反馈。
            return JSONResponse(
                status_code=http_status,
                content={
                    "status": "error",
                    "error_code": error_code,
                    "message": error_message,
                    "query_id": query_id,
                },
            )

        return DSLExecuteResponse(
            status="success",
            data=data,
            sql=sql,
            execution_time_ms=int((time.time() - start) * 1000),
            query_id=query_id,
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
        # 领域校验：未知 domain 立即失败。
        graph = _get_domain_graph(req.domain)
        start = time.time()

        # Step 1: Route via AgentController (intent classification + routing)
        from nl2dsl.agent.orchestrator import AgentOrchestrator
        entities = AgentOrchestrator._extract_entities(req.question, _route_registry)
        execution_plan = await _agent_controller.route(req.question, entities)

        if isinstance(execution_plan, (ComplexExecutionPlan, ExplorationPlan)):
            # Complex query: use AgentOrchestrator with real-time SSE streaming
            domains = _build_domains_dict()
            orchestrator = AgentOrchestrator(domains=domains, llm_client=_graph_llm_client)

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
                            domain=req.domain,
                            sse_callback=sse_callback,
                        )
                        elapsed = int((time.time() - start) * 1000)
                        # 审计：SSE 复杂查询最终结果，使用同一 query_id。
                        audit_logger.log(
                            query_id=query_id,
                            user_id=req.user_id,
                            tenant_id=req.tenant_id,
                            question=req.question,
                            dsl_json=agent_result.dsl,
                            sql_text=agent_result.sql,
                            status=agent_result.status,
                            execution_time_ms=elapsed,
                            rows_returned=len(agent_result.data) if agent_result.data else 0,
                            trace_json=agent_result.trace or [{"step": "agent", "status": agent_result.status}],
                            error_message=agent_result.error,
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
                                "trace": agent_result.trace,
                                "query_id": query_id,
                            },
                        })
                    except Exception as exc:
                        elapsed = int((time.time() - start) * 1000)
                        audit_logger.log(
                            query_id=query_id,
                            user_id=req.user_id,
                            tenant_id=req.tenant_id,
                            question=req.question,
                            status="error",
                            execution_time_ms=elapsed,
                            error_message=str(exc),
                            trace_json=[],
                        )
                        await queue.put({"event": "error", "data": {"error": str(exc), "query_id": query_id}})
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

                # 最终 done 事件必须携带 query_id，便于客户端关联审计/反馈。
                yield f"event: done\ndata: {json.dumps({'query_id': query_id})}\n\n"

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
            chunks: list = []
            stream_error: str | None = None
            stream_error_code: str | None = None
            try:
                async for chunk in graph.astream(state, config, stream_mode="updates"):
                    chunks.append(chunk)
                    yield f"event: update\ndata: {json.dumps(chunk, default=str)}\n\n"
            except Exception as exc:  # noqa: BLE001 — astream 抛异常必须输出 error 事件并审计
                stream_error = _safe_error_message(exc)
                stream_error_code = "INTERNAL_ERROR"

            elapsed = int((time.time() - start) * 1000)

            if stream_error is not None:
                # astream 抛异常：写 error Audit，输出结构化 error 事件，正常结束流。
                audit_logger.log(
                    query_id=query_id,
                    user_id=req.user_id,
                    tenant_id=req.tenant_id,
                    question=req.question,
                    status="error",
                    execution_time_ms=elapsed,
                    error_code=stream_error_code,
                    error_message=stream_error,
                    trace_json=[],
                )
                yield f"event: error\ndata: {json.dumps({'query_id': query_id, 'error': stream_error, 'error_code': stream_error_code}, default=str, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'query_id': query_id})}\n\n"
                return

            # 合并所有 update chunk 得到真实最终状态，而不是用最后一个 chunk。
            final_state = _merge_update_chunks(chunks)
            status = final_state.get("status") or "success"
            dsl_obj = final_state.get("dsl")
            dsl_out = dsl_obj.model_dump() if hasattr(dsl_obj, "model_dump") else dsl_obj
            sql_out = final_state.get("sql")
            data_out = final_state.get("data")
            trace_out = _build_trace(final_state)
            error_out = final_state.get("error")
            error_code_out = final_state.get("error_code")

            # 审计：SSE 简单查询最终结果（成功 / clarification / error 均记录）。
            audit_logger.log(
                query_id=query_id,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                question=req.question,
                dsl_json=dsl_out,
                sql_text=sql_out,
                status=status,
                execution_time_ms=elapsed,
                rows_returned=len(data_out) if data_out else 0,
                trace_json=trace_out,
                error_code=error_code_out,
                error_message=error_out,
            )

            # result 事件至少包含 query_id / status / dsl / sql / data / error。
            result_payload = {
                "query_id": query_id,
                "status": status,
                "dsl": dsl_out,
                "sql": sql_out,
                "data": data_out,
                "rows_returned": len(data_out) if data_out else 0,
            }
            if status == "error":
                result_payload["error"] = error_out
                result_payload["error_code"] = error_code_out
            yield f"event: result\ndata: {json.dumps(result_payload, default=str, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'query_id': query_id})}\n\n"

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
    async def get_schema(domain: str = Query(default="ecommerce")) -> SchemaResponse:
        rd = _domain_registry(domain)
        data_sources = [
            {"name": k, "table": v.get("table", k), "metrics": v.get("metrics", []), "dimensions": v.get("dimensions", [])}
            for k, v in rd.get("data_sources", {}).items()
        ]
        metrics = [
            {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
            for k, v in rd.get("metrics", {}).items()
        ]
        dimensions = [
            {"name": k, "column": v.get("column", k), "description": v.get("description", "")}
            for k, v in rd.get("dimensions", {}).items()
        ]
        return SchemaResponse(data_sources=data_sources, metrics=metrics, dimensions=dimensions)

    @app.get("/api/v1/metrics")
    async def get_metrics(domain: str = Query(default="ecommerce")) -> MetricsResponse:
        rd = _domain_registry(domain)
        metrics = [
            {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
            for k, v in rd.get("metrics", {}).items()
        ]
        return MetricsResponse(metrics=metrics)

    @app.post("/api/v1/feedback")
    async def post_feedback(req: FeedbackRequest) -> FeedbackResponse:
        # 默认走数据库 FeedbackStore：校验 Audit 关联 + 去重。
        if feedback_store is not None:
            feedback_id, deduplicated = feedback_store.submit(
                query_id=req.query_id,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                is_correct=req.is_correct,
                issue_type=req.issue_type,
                corrected_dsl=req.corrected_dsl,
                comment=req.comment,
            )
            return FeedbackResponse(
                status="received",
                query_id=req.query_id,
                feedback_id=feedback_id,
                deduplicated=deduplicated,
            )
        # 兼容路径：JSONL collector（无校验、无去重）
        feedback_collector.collect(
            query_id=req.query_id,
            user_id=req.user_id,
            corrected_dsl=req.corrected_dsl,
            comment=req.comment,
        )
        return FeedbackResponse(status="received", query_id=req.query_id)

    @app.get("/api/v1/admin/feedback")
    async def list_feedback(
        tenant_id: str | None = None,
        user_id: str | None = None,
        query_id: str | None = None,
        review_status: str | None = None,
        is_correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        if feedback_store is None:
            return {"status": "success", "total": 0, "limit": limit, "offset": offset, "items": []}
        # 管理 API 必须限定租户范围，禁止未限定 tenant 的全量查询。
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("管理接口必须提供 tenant_id 以限定租户范围")
        if not (1 <= limit <= 200):
            raise ValidationError("limit must be between 1 and 200")
        records, total = feedback_store.list(
            user_id=user_id, tenant_id=tenant_id, query_id=query_id,
            review_status=review_status, is_correct=is_correct,
            limit=limit, offset=offset,
        )
        items = []
        for rec in records:
            item = rec.to_dict(include_dsl=False)
            # 关联审计摘要（不复制 SQL/Trace，仅必要元数据）
            audit = audit_logger.get_query(rec.query_id) or {}
            item["audit_summary"] = {
                "question": audit.get("question"),
                "status": audit.get("status"),
                "execution_time_ms": audit.get("execution_time_ms"),
            }
            items.append(item)
        return {"status": "success", "total": total, "limit": limit, "offset": offset, "items": items}

    @app.get("/api/v1/admin/feedback/{feedback_id}")
    async def get_feedback(feedback_id: str, tenant_id: str | None = None):
        # 详情接口必须要求非空 tenant_id，与列表接口保持一致的租户边界。
        # 未提供或空白一律拒绝（400），不泄露记录是否存在。
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("管理接口必须提供 tenant_id 以限定租户范围")
        tenant_id = tenant_id.strip()
        if feedback_store is None:
            raise NotFoundError(f"feedback not found: {feedback_id}")
        # 租户校验下沉到 Store：跨租户记录直接当作不存在，返回 404。
        rec = feedback_store.get(feedback_id, tenant_id=tenant_id)
        if rec is None:
            raise NotFoundError(f"feedback not found: {feedback_id}")
        item = rec.to_dict()
        # 审计摘要同样按同一 tenant_id 过滤，杜绝跨租户数据进入响应。
        audit = audit_logger.get_query(rec.query_id, tenant_id=tenant_id) or {}
        # 返回原始问题与原始 DSL 便于联合排查；SQL/Trace 仍以审计接口为来源。
        item["audit_summary"] = {
            "question": audit.get("question"),
            "status": audit.get("status"),
            "dsl": audit.get("dsl"),
            "execution_time_ms": audit.get("execution_time_ms"),
        }
        return {"status": "success", "item": item}

    @app.get("/api/v1/admin/enums")
    async def get_enums() -> EnumsResponse:
        return EnumsResponse(enums=[])

    @app.post("/api/v1/admin/enums/refresh")
    async def refresh_enums() -> RefreshEnumsResponse:
        return RefreshEnumsResponse(status="refreshed")

    @app.get("/api/v1/admin/audit/queries/{query_id}")
    async def get_audit_query(query_id: str, tenant_id: str | None = None) -> AuditQueryDetailResponse:
        # 详情接口必须要求非空 tenant_id，与列表接口保持一致的租户边界。
        # 未提供或空白一律拒绝（400），不泄露记录是否存在。
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("管理接口必须提供 tenant_id 以限定租户范围")
        tenant_id = tenant_id.strip()
        # 租户校验下沉到 Logger：跨租户记录直接当作不存在，返回 404。
        row = audit_logger.get_query(query_id, tenant_id=tenant_id)
        if row is None:
            raise NotFoundError(f"audit record not found: query_id={query_id}")
        row["created_at"] = str(row.get("created_at") or "")
        return AuditQueryDetailResponse(item=AuditQueryDetailItem(**row))

    @app.get("/api/v1/admin/audit/queries")
    async def list_audit_queries(
        tenant_id: str | None = None,
        user_id: str | None = None,
        status_: str | None = Query(None, alias="status"),
        start_time: str | None = None,
        end_time: str | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> AuditQueryListResponse:
        # 管理 API 必须限定租户范围，禁止未限定 tenant 的全量查询。
        if not tenant_id or not tenant_id.strip():
            raise ValidationError("管理接口必须提供 tenant_id 以限定租户范围")
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
