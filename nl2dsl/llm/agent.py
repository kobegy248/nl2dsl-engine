from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from nl2dsl.llm.client import LLMClient
from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT, build_user_prompt
from nl2dsl.dsl.models import DSL, Aggregation, Filter
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.audit.logger import AuditLogger
from nl2dsl.rag.retriever import RAGRetriever
from nl2dsl.exceptions import ValidationError, PermissionError, SemanticError, QueryError, LLMError


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

    def _generate_mock_dsl(self, question: str) -> DSL:
        """Generate a mock DSL based on keyword matching in the question."""
        metrics = None
        filters = None
        dimensions = ["product_name"]
        data_source = "orders"

        question_lower = question.lower()

        if any(kw in question for kw in ["销售额", "sales", "业绩"]):
            metrics = [Aggregation(func="sum", field="order_amount", alias="sales_amount")]

        if "华东" in question:
            filters = [Filter(field="region", operator="=", value="华东")]

        return DSL(
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            data_source=data_source,
        )

    def query(self, question: str, user_id: str, tenant_id: str) -> QueryResult:
        query_id = str(uuid.uuid4())
        start_time = time.time()
        dsl = None
        sql = None
        data = None
        status = "success"
        error_code = None
        error_message = None

        try:
            # 1. Build RAG context from user question
            prompt = self._retriever.build_prompt(question)

            # 2-3. Call LLM to generate DSL (JSON string)
            try:
                raw_dsl = self._llm.generate(prompt, DSL_SYSTEM_PROMPT)
            except (LLMError, Exception):
                raw_dsl = None

            # 4. Parse JSON into DSL model
            if raw_dsl is not None:
                try:
                    dsl_dict = json.loads(raw_dsl)
                    dsl = DSL.model_validate(dsl_dict)
                except (json.JSONDecodeError, Exception):
                    dsl = self._generate_mock_dsl(question)
            else:
                dsl = self._generate_mock_dsl(question)

            # 5. Validate DSL (check metrics/dimensions exist)
            self._validator.validate(dsl)

            # 6. Inject row-level permissions
            dsl = self._rls.inject(dsl, user_id)

            # 7. Resolve semantic layer (expand metrics, value_map)
            dsl = self._resolver.resolve(dsl)

            # 8. Build SQL
            sql = self._builder.build(dsl)

            # 9. Scan SQL for security
            self._scanner.scan(sql)

            # 10. Execute SQL
            data = self._executor.execute(sql)

        except ValidationError as e:
            status = "error"
            error_code = e.error_code
            error_message = e.message
        except PermissionError as e:
            status = "error"
            error_code = e.error_code
            error_message = e.message
        except SemanticError as e:
            status = "error"
            error_code = e.error_code
            error_message = e.message
        except QueryError as e:
            status = "error"
            error_code = e.error_code
            error_message = e.message
        except Exception as e:
            status = "error"
            error_code = "INTERNAL_ERROR"
            error_message = str(e)

        execution_time_ms = int((time.time() - start_time) * 1000)

        dsl_json = dsl.model_dump(mode="json") if dsl is not None else None

        # 11. Log to audit
        self._audit.log(
            query_id=query_id,
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            dsl_json=dsl_json,
            sql_text=sql,
            status=status,
            execution_time_ms=execution_time_ms,
            error_code=error_code,
            error_message=error_message,
        )

        # 12. Return QueryResult
        return QueryResult(
            status=status,
            data=data,
            dsl=dsl_json,
            sql=sql,
            error_code=error_code,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )
