"""Domain context: per-domain container for all pipeline components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DomainContext:
    """All components needed to execute a query for a single domain.

    Each domain gets its own database, semantic registry, validator,
    SQL builder, sandbox, executor, and RAG retriever.
    LLM client and embedder are shared across domains.
    """

    domain: str
    registry_dict: dict
    validator: "DSLValidator"
    resolver: "SemanticResolver"
    sql_builder: "SQLBuilder"
    sandbox: "QuerySandbox"
    executor: "SQLExecutor"
    row_security: "RowLevelSecurity"
    col_security: "ColumnLevelSecurity"
    rag_retriever: "RAGRetriever | None"
    graph: "CompiledGraph"
