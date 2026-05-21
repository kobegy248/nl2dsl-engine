"""LangGraph conditional edge routing functions for the NL2DSL query pipeline.

Each routing function is a pure function that inspects the current state
and returns a string label used by StateGraph.add_conditional_edges().
"""

from __future__ import annotations

from nl2dsl.graph.state import QueryState


# ---------------------------------------------------------------------------
# Clarification routing
# ---------------------------------------------------------------------------


def route_after_clarification(state: QueryState) -> str:
    """Route after clarification_node.

    Returns "clarification" if ambiguities were detected (user needs to respond),
    otherwise "continue" to proceed with DSL generation.
    """
    ambiguities = state.get("ambiguities")
    if ambiguities:
        return "clarification"
    return "continue"


# ---------------------------------------------------------------------------
# LLM availability routing
# ---------------------------------------------------------------------------


def route_llm_availability(state: QueryState, llm_client) -> str:
    """Route based on whether an LLM client is available.

    Returns "llm" if the LLM client is present and functional,
    otherwise "mock" to use the rule-based mock generator.

    Note: llm_client is passed explicitly (not from state) because
    the client instance is not serializable and should not be stored in state.
    """
    if llm_client is not None:
        return "llm"
    return "mock"


# ---------------------------------------------------------------------------
# Validation routing
# ---------------------------------------------------------------------------


def route_after_validate(state: QueryState) -> str:
    """Route after validate_dsl_node.

    Returns:
        - "error"  if the current status is "error" (validation failed fatally)
        - "retry"  if the last validation attempt failed but we have retry attempts left
        - "ok"     if validation passed
    """
    status = state.get("status")
    if status == "error":
        return "error"

    dsl_attempts = state.get("dsl_attempts")
    if not dsl_attempts:
        return "ok"

    last_attempt = dsl_attempts[-1]
    if last_attempt.get("valid") is False:
        # Validation failed, check retry limit
        attempt_count = len(dsl_attempts)
        max_retries = 3
        if attempt_count >= max_retries:
            return "error"
        return "retry"

    return "ok"


# ---------------------------------------------------------------------------
# Complexity detection
# ---------------------------------------------------------------------------


def detect_complexity(state: QueryState) -> str:
    """Detect whether the query is simple or complex.

    Simple queries: single metric, single dimension, no joins, no complex filters.
    Complex queries: multiple metrics, multiple dimensions, joins, subqueries,
    or complex filter patterns.

    Returns "simple" or "complex".
    """
    dsl = state.get("dsl")
    if dsl is None:
        # No DSL yet — treat as simple to avoid unnecessary overhead
        return "simple"

    # Any join makes it complex
    if dsl.joins:
        return "complex"

    # Multiple metrics
    metrics = dsl.metrics
    if metrics and len(metrics) > 1:
        return "complex"

    # Multiple dimensions
    dimensions = dsl.dimensions
    if dimensions and len(dimensions) > 1:
        return "complex"

    # Complex filters (more than 2)
    filters = dsl.filters
    if filters and len(filters) > 2:
        return "complex"

    # Time range queries
    if dsl.time_range:
        return "complex"

    # Subquery indicators in the question
    question = state.get("question", "")
    subquery_keywords = ["子查询", "嵌套", "subquery", "nested", " correlated"]
    if any(kw in question.lower() for kw in subquery_keywords):
        return "complex"

    return "simple"


# ---------------------------------------------------------------------------
# Sandbox routing
# ---------------------------------------------------------------------------


def route_after_sandbox(state: QueryState) -> str:
    """Route after sandbox_check_node.

    Returns "review" if the sandbox detected risks (requires human review),
    otherwise "execute" to proceed with SQL execution.
    """
    sandbox_result = state.get("sandbox_result")
    if sandbox_result is None:
        # No sandbox result — proceed to execute (defensive)
        return "execute"

    if not sandbox_result.passed:
        return "review"
    return "execute"


# ---------------------------------------------------------------------------
# Execution routing
# ---------------------------------------------------------------------------


def route_after_execute(state: QueryState) -> str:
    """Route after execute_sql_node.

    Returns "retry" if execution failed and we can retry with a simplified DSL,
    otherwise "end" to finish the pipeline.
    """
    status = state.get("status")
    if status == "error":
        # Check if we have retry attempts left
        dsl_attempts = state.get("dsl_attempts")
        attempt_count = len(dsl_attempts) if dsl_attempts else 0
        max_execution_retries = 1

        if attempt_count <= max_execution_retries:
            return "retry"
        return "end"

    # Success or other terminal status
    return "end"


# ---------------------------------------------------------------------------
# Error routing
# ---------------------------------------------------------------------------


def route_on_error(state: QueryState) -> str:
    """Route when an error is encountered.

    Returns "end" if the error is fatal (no recovery possible),
    otherwise "continue" to attempt recovery (e.g., retry with mock).
    """
    error_code = state.get("error_code")
    fatal_error_codes = {
        "PERMISSION_DENIED",
        "UNAUTHORIZED",
        "INTERNAL_ERROR",
    }

    if error_code in fatal_error_codes:
        return "end"

    # Check if we've exhausted retries
    dsl_attempts = state.get("dsl_attempts")
    attempt_count = len(dsl_attempts) if dsl_attempts else 0
    if attempt_count >= 3:
        return "end"

    return "continue"
