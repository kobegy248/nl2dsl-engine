from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, insert, text

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.config import settings
from nl2dsl.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger("api")
from nl2dsl.dsl.models import DSL
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import NL2DSLException, NotFoundError, ValidationError
from nl2dsl.query.clarification import ClarificationDetector
from nl2dsl.query.sandbox import QuerySandbox
from nl2dsl.feedback.collector import FeedbackCollector
from nl2dsl.llm.client import LLMClient
from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.rag.embedder import BGEEmbedder
from nl2dsl.rag.retriever import RAGRetriever
from nl2dsl.rag.store import MilvusLiteStore
from nl2dsl.semantic.registry import SemanticRegistry
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.engine import Engine
from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from langgraph.checkpoint.memory import InMemorySaver

app = FastAPI(title="NL2DSL", version="0.1.0")

# ---------------------------------------------------------------------------
# Engine initialization
# ---------------------------------------------------------------------------
_nl2dsl_engine = Engine()
_db_engine = _nl2dsl_engine.registry.get("db_engine")

# ---------------------------------------------------------------------------
# Load semantic registry (for route compatibility)
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

# Re-register permission components with loaded permissions
_nl2dsl_engine.register("row_security", RowLevelSecurity(_permissions))
_nl2dsl_engine.register("col_security", ColumnLevelSecurity(_sensitive_columns, _masking_rules))

# ---------------------------------------------------------------------------
# Ensure tables exist for SQLBuilder metadata reflection
# ---------------------------------------------------------------------------
_metadata = MetaData()

Table(
    "order_fact", _metadata,
    Column("id", Integer, primary_key=True),
    Column("product_id", Integer),
    Column("product_name", String),
    Column("brand", String),
    Column("category", String),
    Column("region", String),
    Column("region_code", String),
    Column("channel", String),
    Column("customer_id", Integer),
    Column("customer_type", String),
    Column("order_amount", Float),
    Column("discount_amount", Float),
    Column("pay_amount", Float),
    Column("quantity", Integer),
    Column("order_date", String),
    Column("tenant_id", String),
)

Table(
    "product_dim", _metadata,
    Column("product_id", Integer, primary_key=True),
    Column("product_name", String),
    Column("brand", String),
    Column("category", String),
    Column("price", Float),
)

Table(
    "customer_dim", _metadata,
    Column("customer_id", Integer, primary_key=True),
    Column("customer_name", String),
    Column("customer_type", String),
    Column("register_date", String),
    Column("region", String),
)

_metadata.create_all(_db_engine)

# Insert mock data if tables are empty
with _db_engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM order_fact"))
    count = result.scalar()
    if count == 0:
        # Insert products
        products = [
            {"product_id": 1, "product_name": "iPhone 15 Pro", "brand": "苹果", "category": "手机", "price": 7999.0},
            {"product_id": 2, "product_name": "华为 Mate 60 Pro", "brand": "华为", "category": "手机", "price": 6999.0},
            {"product_id": 3, "product_name": "小米 14", "brand": "小米", "category": "手机", "price": 3999.0},
            {"product_id": 4, "product_name": "联想拯救者 Y9000P", "brand": "联想", "category": "电脑", "price": 8999.0},
            {"product_id": 5, "product_name": "MacBook Pro 14", "brand": "苹果", "category": "电脑", "price": 14999.0},
            {"product_id": 6, "product_name": "海尔冰箱 500L", "brand": "海尔", "category": "家电", "price": 3999.0},
            {"product_id": 7, "product_name": "美的空调 1.5匹", "brand": "美的", "category": "家电", "price": 2699.0},
            {"product_id": 8, "product_name": "Nike Air Max", "brand": "Nike", "category": "服饰", "price": 899.0},
            {"product_id": 9, "product_name": "索尼电视 65寸", "brand": "索尼", "category": "家电", "price": 5999.0},
            {"product_id": 10, "product_name": "优衣库羽绒服", "brand": "优衣库", "category": "服饰", "price": 499.0},
        ]
        conn.execute(insert(_metadata.tables["product_dim"]), products)

        # Insert customers
        customers = [
            {"customer_id": 1, "customer_name": "张三", "customer_type": "VIP", "register_date": "2023-01-15", "region": "华东"},
            {"customer_id": 2, "customer_name": "李四", "customer_type": "老客", "register_date": "2023-03-20", "region": "华东"},
            {"customer_id": 3, "customer_name": "王五", "customer_type": "新客", "register_date": "2024-01-05", "region": "华南"},
            {"customer_id": 4, "customer_name": "赵六", "customer_type": "VIP", "register_date": "2022-08-10", "region": "华北"},
            {"customer_id": 5, "customer_name": "孙七", "customer_type": "老客", "register_date": "2023-06-18", "region": "西南"},
        ]
        conn.execute(insert(_metadata.tables["customer_dim"]), customers)

        # Insert orders
        import random
        random.seed(42)
        regions = ["华东", "华南", "华北", "西南"]
        order_records = []
        for i in range(50):
            pid = random.randint(1, 10)
            cid = random.randint(1, 5)
            region = regions[i % 4]
            qty = random.randint(1, 5)
            price = products[pid - 1]["price"]
            amount = round(price * qty, 2)
            discount = round(amount * random.choice([0, 0.05, 0.10, 0.15]), 2)
            order_records.append({
                "id": i + 1,
                "product_id": pid,
                "product_name": products[pid - 1]["product_name"],
                "brand": products[pid - 1]["brand"],
                "category": products[pid - 1]["category"],
                "region": region,
                "region_code": region[:2],
                "channel": random.choice(["线上", "线下", "分销"]),
                "customer_id": cid,
                "customer_type": random.choice(["VIP", "老客", "新客"]),
                "order_amount": amount,
                "discount_amount": discount,
                "pay_amount": round(amount - discount, 2),
                "quantity": qty,
                "order_date": f"2024-01-{random.randint(1, 31):02d}",
                "tenant_id": "t001" if random.random() < 0.6 else "t002",
            })
        conn.execute(insert(_metadata.tables["order_fact"]), order_records)
        conn.commit()

# Re-register sql_builder after mock data (tables now exist)
_sql_builder = SQLBuilder(_db_engine, {k: v.get("table", k) for k, v in _registry.data_sources.items()})
_nl2dsl_engine.register("sql_builder", _sql_builder)

# ---------------------------------------------------------------------------
# Service instances for routes
# ---------------------------------------------------------------------------
_feedback_collector = FeedbackCollector()
_audit_logger = AuditLogger(_db_engine)

# No-op clarification detector to preserve pre-LangGraph behavior
class _NoOpClarificationDetector:
    def detect(self, question: str) -> list:
        return []

_clarification_detector = _NoOpClarificationDetector()
_nl2dsl_engine.register("clarification_detector", _clarification_detector)

# ---------------------------------------------------------------------------
# LLM client and RAG (use Engine's components; Engine._load_defaults + auto_sync
# is the single source of truth for RAG data — do NOT manually write here)
# ---------------------------------------------------------------------------
_llm_client = _nl2dsl_engine.registry.get("llm") if _nl2dsl_engine.registry.has("llm") else None
_rag_retriever = (
    _nl2dsl_engine.registry.get("rag_retriever")
    if _nl2dsl_engine.registry.has("rag_retriever")
    else None
)

if _llm_client is not None:
    logger.info("LLM client initialized: model=%s, base_url=%s", settings.llm_model, settings.llm_base_url)
    if _rag_retriever is not None:
        logger.info("RAG retriever ready (data synced from configs/*.yaml via auto_sync)")
    else:
        logger.warning("LLM available but RAG retriever missing — auto_sync may have failed")
else:
    logger.warning("LLM API key not configured, using mock DSL generation only")

# ---------------------------------------------------------------------------
# Build LangGraph StateGraph
# ---------------------------------------------------------------------------
_query_graph = _nl2dsl_engine.build()
logger.info("LangGraph StateGraph built and compiled successfully")

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
# Helpers
# ---------------------------------------------------------------------------


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

    if status == "warning" or status == "pending_review" or status == "pending":
        return QueryResponse(
            status="pending_review" if status == "pending" else status,
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
    )


def _build_trace(result: dict) -> list[dict]:
    """Extract trace entries from graph result state."""
    trace = result.get("trace")
    if trace is None:
        return []
    if isinstance(trace, list):
        return trace
    return [trace] if trace else []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


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
    result = await _query_graph.ainvoke(state, config)

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

    logger.info("[query_id=%s] question=%s user=%s tenant=%s", query_id, req.question, req.user_id, req.tenant_id)

    try:
        result = await _query_graph.ainvoke(state, config)
        elapsed = int((time.time() - start) * 1000)

        trace_entries = _build_trace(result)

        # Audit log
        dsl = result.get("dsl")
        sql = result.get("sql")
        status = result.get("status", "error")
        data = result.get("data")

        _audit_logger.log(
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
        logger.error("[query_id=%s] error=%s message=%s time=%dms", query_id, exc.error_code, exc.message, elapsed)
        _audit_logger.log(
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
    result = await _query_graph.ainvoke(state, config)

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
    """Stream query execution updates via SSE."""
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
        started_at=time.time(),
        llm_used=False,
    )

    config = {"configurable": {"thread_id": query_id}}

    async def event_generator():
        import json
        async for chunk in _query_graph.astream(state, config, stream_mode="updates"):
            yield f"data: {json.dumps(chunk, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.post("/api/v1/query/resume")
async def query_resume(req: ResumeRequest):
    """Resume a paused query (human-in-the-loop approval/rejection)."""
    config = {"configurable": {"thread_id": req.query_id}}

    # Get current state
    current_state = await _query_graph.aget_state(config)
    if current_state is None:
        raise NotFoundError(f"Query not found: query_id={req.query_id}")

    # Update state with approval/rejection
    if req.action == "approve":
        # Continue execution from human_review node
        result = await _query_graph.ainvoke(
            None,
            config,
        )
    else:
        # Reject: mark as error and end
        result = await _query_graph.ainvoke(
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


@app.get("/api/v1/debug/rag")
async def debug_rag(q: str) -> dict:
    """调试接口：查看 RAG 检索的实际内容。"""
    if _rag_retriever is None:
        return {"error": "RAG not initialized"}
    results = _rag_retriever.retrieve_hybrid(q, top_k=5)
    context = _rag_retriever.build_context(q, top_k=5)
    return {
        "query": q,
        "schema": [
            {"name": r.get("name"), "text": r.get("text"), "distance": r.get("distance")}
            for r in results.get("schema", [])
        ],
        "metrics": [
            {"name": r.get("name"), "text": r.get("text"), "distance": r.get("distance")}
            for r in results.get("metrics", [])
        ],
        "terms": [
            {"name": r.get("name"), "text": r.get("text"), "distance": r.get("distance")}
            for r in results.get("terms", [])
        ],
        "history": [
            {"name": r.get("name"), "text": r.get("text"), "distance": r.get("distance")}
            for r in results.get("history", [])
        ],
        "context": context,
    }


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


@app.get("/api/v1/admin/audit/queries/{query_id}")
async def get_audit_query(query_id: str) -> AuditQueryDetailResponse:
    row = _audit_logger.get_query(query_id)
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

    items, total = _audit_logger.list_queries(
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


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(NL2DSLException)
async def nl2dsl_exception_handler(request: Request, exc: NL2DSLException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "error_code": exc.error_code, "message": exc.message},
    )


# ---------------------------------------------------------------------------
# Static files (frontend)
# ---------------------------------------------------------------------------

from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

_frontend_dir = Path(__file__).parent.parent / "web" / "dist"

if _frontend_dir.exists():
    # Serve static assets (JS/CSS/fonts)
    app.mount("/assets", StaticFiles(directory=str(_frontend_dir / "assets")), name="assets")

    class SPAFallbackMiddleware(BaseHTTPMiddleware):
        """Return index.html for non-API routes to support React Router SPA."""

        async def dispatch(self, request, call_next):
            response = await call_next(request)
            if response.status_code == 404:
                path = request.url.path
                # Only serve index.html for non-API, non-static paths
                if not path.startswith("/api/") and not path.startswith("/health") and not path.startswith("/assets/"):
                    index_file = _frontend_dir / "index.html"
                    if index_file.exists():
                        return FileResponse(str(index_file))
            return response

    app.add_middleware(SPAFallbackMiddleware)
