"""StateGraph builder for the NL2DSL query pipeline.

Assembles nodes, edges, subgraphs, and optional checkpointer into a compiled
LangGraph StateGraph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, END

from nl2dsl.graph.state import QueryState
from nl2dsl.graph.nodes import create_node_functions
from nl2dsl.graph.edges import (
    route_after_clarification,
    route_after_sandbox,
    route_after_execute,
    detect_complexity,
)
from nl2dsl.graph.subgraphs import build_permission_subgraph, build_validation_subgraph

if TYPE_CHECKING:
    from nl2dsl.dsl.validator import DSLValidator
    from nl2dsl.permission.row_level import RowLevelSecurity
    from nl2dsl.permission.column_level import ColumnLevelSecurity
    from nl2dsl.semantic.resolver import SemanticResolver
    from nl2dsl.sql_engine.builder import SQLBuilder
    from nl2dsl.sql_engine.scanner import SQLScanner
    from nl2dsl.sql_engine.executor import SQLExecutor
    from nl2dsl.query.sandbox import QuerySandbox
    from nl2dsl.query.clarification import ClarificationDetector


def build_graph(
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
    registry_dict: dict,
    llm_system_prompt: str = "",
    checkpointer=None,
):
    """Build and compile the NL2DSL query pipeline StateGraph.

    Graph structure::

        START -> clarification -> [clarification] END
                             |--[continue] -> decompose -> validation
                             -> permission_check -> resolve_semantic
                             -> build_sql -> scan_sql -> sandbox_check
                                                       |--[review] -> human_review
                                                       |              |--[rebuild] -> build_sql
                                                       |              |--[execute] -> execute_sql
                                                       |--[execute] -> execute_sql
                                                                       |--[retry] -> simplify_dsl -> build_sql
                                                                       |--[end] -> verify_dsl -> END

    Agentic enhancements:
    - ``decompose`` (NEW): for questions with complexity markers (对比/同比/趋势/今年...),
      asks LLM to rewrite into a single-DSL-expressible form. No-op for simple
      questions so latency cost is bounded.
    - ``correct_dsl`` (in validation subgraph): on validation failure, LLM picks a
      retrieval keyword, RAG searches targeted context, then regenerates.
    - ``verify_dsl`` (NEW): after execute_sql succeeds, LLM self-checks whether
      DSL/result actually answers the original question. Currently warning-only.

    Args:
        llm_client: LLM client for DSL generation (may be None).
        rag_retriever: RAG retriever for prompt enrichment (may be None).
        validator: DSLValidator instance.
        row_security: RowLevelSecurity instance.
        col_security: ColumnLevelSecurity instance.
        resolver: SemanticResolver instance.
        sql_builder: SQLBuilder instance.
        scanner: SQLScanner instance.
        sandbox: QuerySandbox instance.
        executor: SQLExecutor instance.
        clarification_detector: ClarificationDetector instance.
        registry_dict: Semantic registry dictionary for mock DSL fallback.
        llm_system_prompt: Optional system prompt for LLM generation.
        checkpointer: Optional checkpointer for persistence (e.g. MemorySaver).
            If None, no checkpointing is enabled and human_review will not
            interrupt.

    Returns:
        A compiled StateGraph ready for ``invoke()`` / ``ainvoke()``.
    """
    # -----------------------------------------------------------------------
    # Create node functions with injected dependencies
    # -----------------------------------------------------------------------
    nodes = create_node_functions(
        llm_client=llm_client,
        rag_retriever=rag_retriever,
        validator=validator,
        row_security=row_security,
        col_security=col_security,
        resolver=resolver,
        sql_builder=sql_builder,
        scanner=scanner,
        sandbox=sandbox,
        executor=executor,
        clarification_detector=clarification_detector,
        llm_system_prompt=llm_system_prompt,
    )

    # -----------------------------------------------------------------------
    # Build subgraphs
    # -----------------------------------------------------------------------
    permission_subgraph = build_permission_subgraph(row_security, col_security)
    validation_subgraph = build_validation_subgraph(
        validator, llm_client, rag_retriever, registry_dict
    )

    # -----------------------------------------------------------------------
    # Assemble main graph
    # -----------------------------------------------------------------------
    builder = StateGraph(QueryState)

    # Add nodes
    builder.add_node("clarification", nodes["clarification_node"])
    builder.add_node("decompose", nodes["decompose_node"])
    builder.add_node("validation", validation_subgraph)
    builder.add_node("permission_check", permission_subgraph)
    builder.add_node("resolve_semantic", nodes["resolve_semantic_node"])
    builder.add_node("build_sql", nodes["build_sql_node"])
    builder.add_node("scan_sql", nodes["scan_sql_node"])
    builder.add_node("sandbox_check", nodes["sandbox_check_node"])
    builder.add_node("human_review", nodes["human_review_node"])
    builder.add_node("execute_sql", nodes["execute_sql_node"])
    builder.add_node("simplify_dsl", nodes["simplify_dsl_node"])
    builder.add_node("verify_dsl", nodes["verify_dsl_node"])

    # Entry point
    builder.set_entry_point("clarification")

    # 1. clarification -> END (needs clarification) or decompose (continue)
    builder.add_conditional_edges(
        "clarification",
        route_after_clarification,
        {
            "clarification": END,
            "continue": "decompose",
        },
    )

    # 1b. decompose -> validation (always; decompose only rewrites or no-ops)
    builder.add_edge("decompose", "validation")

    # 2. validation -> permission_check
    builder.add_edge("validation", "permission_check")

    # 3. permission_check -> resolve_semantic
    builder.add_edge("permission_check", "resolve_semantic")

    # 4. resolve_semantic -> build_sql
    builder.add_edge("resolve_semantic", "build_sql")

    # 5. build_sql -> scan_sql (with complexity routing, or end on error)
    def _route_after_build_sql(state: QueryState) -> str:
        if state.get("status") == "error":
            return "end"
        return detect_complexity(state)

    builder.add_conditional_edges(
        "build_sql",
        _route_after_build_sql,
        {
            "simple": "scan_sql",
            "complex": "scan_sql",
            "end": END,
        },
    )

    # 6. scan_sql -> sandbox_check
    builder.add_edge("scan_sql", "sandbox_check")

    # 7. sandbox_check -> human_review (needs review) or execute_sql (pass)
    builder.add_conditional_edges(
        "sandbox_check",
        route_after_sandbox,
        {
            "review": "human_review",
            "execute": "execute_sql",
        },
    )

    # 8. human_review -> execute_sql (approved) or END (rejected/error)
    def _route_after_human_review(state: QueryState) -> str:
        status = state.get("status")
        if status == "error":
            return "end"
        if status == "rejected":
            return "end"
        # After human review approval, proceed to execute
        return "execute"

    builder.add_conditional_edges(
        "human_review",
        _route_after_human_review,
        {
            "execute": "execute_sql",
            "end": END,
        },
    )

    # 9. execute_sql -> simplify_dsl (retry) or verify_dsl (success path)
    builder.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "retry": "simplify_dsl",
            "end": "verify_dsl",
        },
    )

    # 10. simplify_dsl -> build_sql (loop back)
    builder.add_edge("simplify_dsl", "build_sql")

    # 11. verify_dsl -> END (currently warning-only; future: route FAIL back to correct_dsl)
    builder.add_edge("verify_dsl", END)

    # -----------------------------------------------------------------------
    # Compile
    # -----------------------------------------------------------------------
    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
        compile_kwargs["interrupt_before"] = ["human_review"]

    return builder.compile(**compile_kwargs)
