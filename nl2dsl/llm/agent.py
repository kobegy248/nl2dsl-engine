from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nl2dsl.llm.client import LLMClient
from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT, build_user_prompt
from nl2dsl.dsl.models import DSL
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.audit.logger import AuditLogger
from nl2dsl.rag.retriever import RAGRetriever


@dataclass
class QueryResult:
    status: str
    data: list[dict] | None = None
    dsl: dict | None = None
    sql: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    execution_time_ms: int = 0


class QueryAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        retriever: RAGRetriever,
        validator: DSLValidator,
        resolver: SemanticResolver,
        row_level: RowLevelSecurity,
        sql_builder: SQLBuilder,
        sql_scanner: SQLScanner,
        sql_executor: SQLExecutor,
        audit_logger: AuditLogger,
    ):
        self._llm = llm_client
        self._retriever = retriever
        self._validator = validator
        self._resolver = resolver
        self._rls = row_level
        self._builder = sql_builder
        self._scanner = sql_scanner
        self._executor = sql_executor
        self._audit = audit_logger

    def query(self, question: str, user_id: str, tenant_id: str) -> QueryResult:
        # TODO: implement full pipeline
        return QueryResult(status="success")
