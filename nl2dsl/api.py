from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.config import settings
from nl2dsl.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger("api")
from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import NL2DSLException, NotFoundError, ValidationError
from nl2dsl.feedback.collector import FeedbackCollector
from nl2dsl.engine import Engine
from nl2dsl.graph.state import QueryState

app = FastAPI(title="NL2DSL", version="0.1.0")

# ---------------------------------------------------------------------------
# Engine initialization
# ---------------------------------------------------------------------------
_nl2dsl_engine = Engine()

# Audit logger uses the default (ecommerce) database for backward compatibility
_audit_db = create_engine(settings.db_url, echo=False)
_audit_logger = AuditLogger(_audit_db)

# ---------------------------------------------------------------------------
# Service instances for routes
# ---------------------------------------------------------------------------
_feedback_collector = FeedbackCollector()

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str
    domain: str = Field(default="ecommerce", description="业务领域")
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
    # Agentic metadata (optional, surfaced for UI / debugging)
    original_question: str | None = None
    rewrite_reason: str | None = None
    verify_status: str | None = None  # "pass" | "warn" | "fail" | "skipped"
    verify_reason: str | None = None


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
    domain: str = Field(default="ecommerce", description="业务领域")
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
        original_question=result.get("original_question"),
        rewrite_reason=result.get("rewrite_reason"),
        verify_status=result.get("verify_status"),
        verify_reason=result.get("verify_reason"),
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
        domain=req.domain,
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
        original_question=None,
        rewrite_reason=None,
        verify_status=None,
        verify_reason=None,
    )

    config = {"configurable": {"thread_id": query_id}}
    ctx = _nl2dsl_engine.get_domain(req.domain)
    result = await ctx.graph.ainvoke(state, config)

    elapsed = int((time.time() - start) * 1000)

    # If clarification is needed and no DSL was produced, fall back to mock
    if result.get("status") == "clarification" and result.get("dsl") is None:
        from nl2dsl.graph.nodes import _mock_dsl_from_question
        mock_dsl = _mock_dsl_from_question(req.question, req.data_source)
        result = {"dsl": mock_dsl, "status": "pending"}

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
        domain=req.domain,
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
        original_question=None,
        rewrite_reason=None,
        verify_status=None,
        verify_reason=None,
    )

    config = {"configurable": {"thread_id": query_id}}

    logger.info("[query_id=%s] question=%s user=%s tenant=%s domain=%s", query_id, req.question, req.user_id, req.tenant_id, req.domain)

    try:
        ctx = _nl2dsl_engine.get_domain(req.domain)
        result = await ctx.graph.ainvoke(state, config)
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
        domain="ecommerce",
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
        original_question=None,
        rewrite_reason=None,
        verify_status=None,
        verify_reason=None,
    )

    config = {"configurable": {"thread_id": query_id}}
    ctx = _nl2dsl_engine.get_domain("ecommerce")
    result = await ctx.graph.ainvoke(state, config)

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
        domain=req.domain,
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
    ctx = _nl2dsl_engine.get_domain(req.domain)

    async def event_generator():
        import json
        async for chunk in ctx.graph.astream(state, config, stream_mode="updates"):
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
    ctx = _nl2dsl_engine.get_domain("ecommerce")
    current_state = await ctx.graph.aget_state(config)
    if current_state is None:
        raise NotFoundError(f"Query not found: query_id={req.query_id}")

    # Update state with approval/rejection
    if req.action == "approve":
        # Continue execution from human_review node
        result = await ctx.graph.ainvoke(
            None,
            config,
        )
    else:
        # Reject: mark as error and end
        result = await ctx.graph.ainvoke(
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
    ctx = _nl2dsl_engine.get_domain(domain)
    rd = ctx.registry_dict
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
    ctx = _nl2dsl_engine.get_domain(domain)
    rd = ctx.registry_dict
    metrics = [
        {"name": k, "expr": v.get("expr", ""), "description": v.get("description", "")}
        for k, v in rd.get("metrics", {}).items()
    ]
    return MetricsResponse(metrics=metrics)


@app.get("/api/v1/debug/rag")
async def debug_rag(q: str, domain: str = Query(default="ecommerce")) -> dict:
    """调试接口：查看 RAG 检索的实际内容。"""
    ctx = _nl2dsl_engine.get_domain(domain)
    rag_retriever = ctx.rag_retriever
    if rag_retriever is None:
        return {"error": "RAG not initialized"}
    results = rag_retriever.retrieve_hybrid(q, top_k=5)
    context = rag_retriever.build_context(q, top_k=5)
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
