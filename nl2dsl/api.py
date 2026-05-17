from __future__ import annotations

import time
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.config import settings
from nl2dsl.dsl.models import DSL, Aggregation, Filter, OrderBy
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import NL2DSLException
from nl2dsl.feedback.collector import FeedbackCollector
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.semantic.registry import SemanticRegistry
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner

app = FastAPI(title="NL2DSL", version="0.1.0")

# ---------------------------------------------------------------------------
# Load semantic registry
# ---------------------------------------------------------------------------
_registry = SemanticRegistry()
_metrics_yaml_path = Path(__file__).parent.parent / "configs" / "metrics.yaml"
if _metrics_yaml_path.exists():
    _registry.load(str(_metrics_yaml_path))

_registry_dict = {
    "metrics": _registry.metrics,
    "dimensions": _registry.dimensions,
    "data_sources": _registry.data_sources,
}

# ---------------------------------------------------------------------------
# Load permissions
# ---------------------------------------------------------------------------
_permissions_yaml_path = Path(__file__).parent.parent / "configs" / "permissions.yaml"
_permissions = {}
_sensitive_columns = {}
_masking_rules = {}
if _permissions_yaml_path.exists():
    _perm_data = yaml.safe_load(_permissions_yaml_path.read_text(encoding="utf-8"))
    _permissions = _perm_data.get("users", {})
    _sensitive_columns = _perm_data.get("sensitive_columns", {})
    _masking_rules_raw = _perm_data.get("masking_rules", {})
    # Compile masking rules using string format
    def _make_masker(template: str):
        def masker(x):
            try:
                return template.format(x=x)
            except Exception:
                return str(x)
        return masker

    for field, template in _masking_rules_raw.items():
        _masking_rules[field] = _make_masker(template)

# ---------------------------------------------------------------------------
# Shared services
# ---------------------------------------------------------------------------
_engine = create_engine(settings.db_url, echo=False)

# Ensure the order_fact table exists for SQLBuilder metadata reflection
# Drop and recreate to handle schema changes during development
from sqlalchemy import inspect as _inspect  # noqa: E402

_inspector = _inspect(_engine)
if "order_fact" in _inspector.get_table_names():
    from sqlalchemy import text as _text  # noqa: E402
    with _engine.connect() as _conn:
        _conn.execute(_text("DROP TABLE order_fact"))
        _conn.commit()

_metadata = MetaData()
Table(
    "order_fact", _metadata,
    Column("id", Integer, primary_key=True),
    Column("product_name", String),
    Column("region", String),
    Column("region_code", String),
    Column("order_amount", Float),
    Column("order_date", DateTime),
    Column("tenant_id", String),
)
_metadata.create_all(_engine)

_sql_builder = SQLBuilder(_engine, {k: v.get("table", k) for k, v in _registry.data_sources.items()})
_validator = DSLValidator(_registry_dict)
_resolver = SemanticResolver(_registry_dict)
_scanner = SQLScanner()
_row_security = RowLevelSecurity(_permissions)
_col_security = ColumnLevelSecurity(_sensitive_columns, _masking_rules)
_feedback_collector = FeedbackCollector()
_audit_logger = AuditLogger(_engine)

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_dsl_from_question(question: str, data_source: str | None = None) -> DSL:
    """Generate a mock DSL based on question keywords (no LLM key needed)."""
    ds = data_source or "orders"
    metrics = []
    dimensions = []
    filters = []
    order_by = []
    limit = 10

    q = question.lower()

    # Metrics
    if "销售额" in question or "sales" in q or "业绩" in question or "营收" in question:
        metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))
    elif "gmv" in q or "成交总额" in question or "交易额" in question:
        metrics.append(Aggregation(func="sum", field="order_amount", alias="gmv"))
    elif "订单量" in question or "订单数" in question or "单量" in question or "order count" in q:
        metrics.append(Aggregation(func="count", field="id", alias="order_count"))
    else:
        # Default metric
        metrics.append(Aggregation(func="sum", field="order_amount", alias="sales_amount"))

    # Dimensions
    if "产品" in question or "product" in q:
        dimensions.append("product_name")
    if "地区" in question or "区域" in question or "region" in q:
        dimensions.append("region")
    if "时间" in question or "日期" in question or "date" in q:
        dimensions.append("order_date")

    if not dimensions:
        dimensions.append("product_name")

    # Filters
    if "华东" in question:
        filters.append(Filter(field="region", operator="=", value="华东"))
    if "华南" in question:
        filters.append(Filter(field="region", operator="=", value="华南"))

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
    )


import re


def _restore_metric_fields(dsl: DSL) -> DSL:
    """After SemanticResolver replaces metric.field with expr like SUM(col),
    restore the raw column name so SQLBuilder can look it up.
    """
    if not dsl.metrics:
        return dsl
    restored = []
    for m in dsl.metrics:
        field = m.field
        # Extract column name from expressions like SUM(order_amount), COUNT(id), etc.
        match = re.match(r"^[A-Z]+\((.+?)\)$", field, re.IGNORECASE)
        if match:
            field = match.group(1)
        restored.append(m.model_copy(update={"field": field}))
    return dsl.model_copy(update={"metrics": restored})


def _build_sql(dsl: DSL) -> str:
    """Build SQL from DSL using SQLBuilder."""
    # Restore raw column names before passing to builder
    dsl_for_build = _restore_metric_fields(dsl)
    return _sql_builder.build(dsl_for_build)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/query/dsl")
async def query_dsl(req: QueryRequest) -> DSLGenerateResponse:
    start = time.time()
    dsl = _mock_dsl_from_question(req.question, req.data_source)
    elapsed = int((time.time() - start) * 1000)
    return DSLGenerateResponse(status="success", dsl=dsl.model_dump(), execution_time_ms=elapsed)


@app.post("/api/v1/query")
async def query(req: QueryRequest) -> QueryResponse:
    start = time.time()
    query_id = str(uuid.uuid4())

    try:
        # 1. Generate DSL
        dsl = _mock_dsl_from_question(req.question, req.data_source)

        # 2. Validate
        _validator.validate(dsl)

        # 3. Row-level permission injection
        dsl = _row_security.inject(dsl, req.user_id)

        # 4. Column-level permission check
        _col_security.check(dsl, req.user_id)

        # 5. Resolve semantics
        dsl = _resolver.resolve(dsl)

        # 6. Build SQL
        sql = _build_sql(dsl)

        # 7. Scan SQL
        _scanner.scan(sql)

        elapsed = int((time.time() - start) * 1000)

        # Audit log
        _audit_logger.log(
            query_id=query_id,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            question=req.question,
            dsl_json=dsl.model_dump(),
            sql_text=sql,
            status="success",
            execution_time_ms=elapsed,
        )

        return QueryResponse(
            status="success",
            data=[],
            dsl=dsl.model_dump(),
            sql=sql,
            execution_time_ms=elapsed,
        )
    except NL2DSLException as exc:
        elapsed = int((time.time() - start) * 1000)
        _audit_logger.log(
            query_id=query_id,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
            question=req.question,
            status="error",
            execution_time_ms=elapsed,
            error_code=exc.error_code,
            error_message=exc.message,
        )
        raise


@app.post("/api/v1/query/execute")
async def query_execute(req: DSLExecuteRequest) -> DSLExecuteResponse:
    start = time.time()

    dsl = DSL(**req.dsl)

    # Validate
    _validator.validate(dsl)

    # Row-level permission injection
    dsl = _row_security.inject(dsl, req.user_id)

    # Column-level permission check
    _col_security.check(dsl, req.user_id)

    # Resolve semantics
    dsl = _resolver.resolve(dsl)

    # Build SQL
    sql = _build_sql(dsl)

    # Scan SQL
    _scanner.scan(sql)

    elapsed = int((time.time() - start) * 1000)

    return DSLExecuteResponse(
        status="success",
        data=[],
        sql=sql,
        execution_time_ms=elapsed,
    )


@app.get("/api/v1/schema")
async def get_schema() -> SchemaResponse:
    data_sources = [
        {"name": k, "table": v.get("table", k), "metrics": v.get("metrics", []), "dimensions": v.get("dimensions", [])}
        for k, v in _registry.data_sources.items()
    ]
    metrics = [
        {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
        for k, v in _registry.metrics.items()
    ]
    dimensions = [
        {"name": k, "column": v.get("column", k), "description": v.get("description", "")}
        for k, v in _registry.dimensions.items()
    ]
    return SchemaResponse(data_sources=data_sources, metrics=metrics, dimensions=dimensions)


@app.get("/api/v1/metrics")
async def get_metrics() -> MetricsResponse:
    metrics = [
        {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
        for k, v in _registry.metrics.items()
    ]
    return MetricsResponse(metrics=metrics)


@app.post("/api/v1/feedback")
async def post_feedback(req: FeedbackRequest) -> FeedbackResponse:
    _feedback_collector.collect(
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


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(NL2DSLException)
async def nl2dsl_exception_handler(request: Request, exc: NL2DSLException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "error_code": exc.error_code, "message": exc.message},
    )
