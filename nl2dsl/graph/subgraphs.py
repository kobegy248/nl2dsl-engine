"""LangGraph subgraph builders for the NL2DSL query pipeline.

Each subgraph is a self-contained StateGraph that can be embedded into the
main pipeline graph. Subgraphs receive the same QueryState as the parent graph
and return state updates that are merged back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, END

from nl2dsl.graph.state import QueryState
from nl2dsl.graph.edges import route_after_validate

if TYPE_CHECKING:
    from nl2dsl.dsl.validator import DSLValidator
    from nl2dsl.permission.row_level import RowLevelSecurity
    from nl2dsl.permission.column_level import ColumnLevelSecurity


def _route_on_error(state: QueryState) -> str:
    """Route to END if status is error, otherwise continue to next node."""
    if state.get("status") == "error":
        return "end"
    return "continue"


def build_permission_subgraph(
    row_security: RowLevelSecurity,
    col_security: ColumnLevelSecurity,
) -> StateGraph:
    """Build the permission-check subgraph.

    Flow: inject_row_permission -> check_col_permission

    Both nodes are wrapped with error handling. If either node fails,
    the error state is set and the subgraph ends.

    Args:
        row_security: RowLevelSecurity instance for injecting row filters.
        col_security: ColumnLevelSecurity instance for checking column access.

    Returns:
        A compiled StateGraph representing the permission check pipeline.
    """
    from nl2dsl.graph.nodes import (
        _make_inject_row_permission_node,
        _make_check_col_permission_node,
    )

    builder = StateGraph(QueryState)

    inject_node = _make_inject_row_permission_node(row_security)
    check_node = _make_check_col_permission_node(col_security)

    builder.add_node("inject_row", inject_node)
    builder.add_node("check_col", check_node)

    builder.set_entry_point("inject_row")

    # Conditional routing: stop on error, continue to check_col otherwise
    builder.add_conditional_edges(
        "inject_row",
        _route_on_error,
        {
            "end": END,
            "continue": "check_col",
        },
    )

    builder.add_edge("check_col", END)

    return builder.compile()


def build_validation_subgraph(
    validator: DSLValidator,
    llm_client,
    rag_retriever,
    registry_dict: dict,
) -> StateGraph:
    """Build the DSL validation + correction loop subgraph.

    Flow:
        generate_dsl -> validate_dsl
        validate_dsl --[route_after_validate]--> correct_dsl (retry)
                                          --> END (ok or error)
        correct_dsl -> validate_dsl  (loop back)

    The ``route_after_validate`` function returns:
        - "ok"    -> END (validation passed)
        - "retry" -> correct_dsl (validation failed, attempt correction)
        - "error" -> END (exhausted retries or fatal error)

    Args:
        validator: DSLValidator instance for validating generated DSL.
        llm_client: LLM client for generating/correcting DSL (may be None).
        rag_retriever: RAG retriever for prompt enrichment (may be None).
        registry_dict: Semantic registry dictionary for mock DSL fallback.

    Returns:
        A compiled StateGraph representing the DSL generation/validation loop.
    """
    from nl2dsl.graph.nodes import (
        _make_generate_dsl_node,
        _make_validate_dsl_node,
        _make_correct_dsl_node,
        _make_mock_dsl_node,
    )

    builder = StateGraph(QueryState)

    generate_node = _make_generate_dsl_node(llm_client, rag_retriever)
    validate_node = _make_validate_dsl_node(validator)
    correct_node = _make_correct_dsl_node(llm_client, rag_retriever, registry_dict)
    mock_node = _make_mock_dsl_node(registry_dict)

    builder.add_node("generate_dsl", generate_node)
    builder.add_node("validate_dsl", validate_node)
    builder.add_node("correct_dsl", correct_node)
    builder.add_node("mock_dsl", mock_node)

    # Entry point: route to generate_dsl if LLM available, else mock_dsl
    def _route_entry(state: QueryState) -> str:
        if llm_client is not None:
            return "llm"
        return "mock"

    builder.set_conditional_entry_point(
        _route_entry,
        {
            "llm": "generate_dsl",
            "mock": "mock_dsl",
        },
    )

    # Route from generate_dsl:
    #   - on success -> validate_dsl
    #   - on error (e.g. LLM connection failure) -> mock_dsl (fallback)
    def _route_after_generate_dsl(state: QueryState) -> str:
        if state.get("status") == "error":
            # Clear error state so mock_dsl can proceed
            return "fallback"
        return "continue"

    builder.add_conditional_edges(
        "generate_dsl",
        _route_after_generate_dsl,
        {
            "fallback": "mock_dsl",
            "continue": "validate_dsl",
        },
    )

    # Mock DSL path goes directly to validation
    builder.add_edge("mock_dsl", "validate_dsl")

    # Conditional routing after validation
    builder.add_conditional_edges(
        "validate_dsl",
        route_after_validate,
        {
            "ok": END,
            "retry": "correct_dsl",
            "error": END,
        },
    )

    # After correction, loop back to validation
    builder.add_edge("correct_dsl", "validate_dsl")

    return builder.compile()
