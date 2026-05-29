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
from nl2dsl.agent.planner import classify_intent, _decompose_fallback
from nl2dsl.domain_context import DomainContext
from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from langgraph.checkpoint.memory import InMemorySaver


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

    # Use no-op clarification detector to preserve pre-LangGraph behavior
    class _NoOpClarificationDetector:
        def detect(self, question: str) -> list:
            return []

    clarification_detector = _NoOpClarificationDetector()
    _nl2dsl_engine.register("clarification_detector", clarification_detector)

    # Services used directly by routes
    feedback_collector = FeedbackCollector()
    _db_engine = engine or _nl2dsl_engine.registry.get("db_engine")
    audit_logger = AuditLogger(_db_engine)

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

    query_graph = build_graph(
        llm_client=None,
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
        llm_system_prompt="",
        checkpointer=None,
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

            # Step 1: Plan / intent classification
            intent = classify_intent(req.question)
            plan = _decompose_fallback(req.question, intent)

            # Step 2: Route based on intent
            if plan.intent != "single_query":
                # Complex query: use AgentOrchestrator
                domains = _build_domains_dict()
                orchestrator = AgentOrchestrator(domains=domains)

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
                    trace_json=[{"step": "agent", "status": agent_result.status, "intent": plan.intent}],
                    error_code=None,
                    error_message=agent_result.error,
                )

                if agent_result.status == "error":
                    raise ValidationError(agent_result.error or "Agent execution failed")

                return QueryResponse(
                    status="success",
                    data=agent_result.data,
                    dsl=None,
                    sql=None,
                    execution_time_ms=elapsed,
                    explanation=agent_result.explanation,
                    confidence=agent_result.confidence,
                )

            # Simple query: continue with existing graph flow
            # Pass the pre-computed plan to avoid double-planning in graph.
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

        # Step 1: Plan / intent classification
        intent = classify_intent(req.question)
        plan = _decompose_fallback(req.question, intent)

        if plan.intent != "single_query":
            # Complex query: use AgentOrchestrator with real-time SSE streaming
            domains = _build_domains_dict()
            orchestrator = AgentOrchestrator(domains=domains)

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
        current_state = await query_graph.aget_state(config)
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
