"""Dispatch node: sub-query scheduler for the NL2DSL agent.

The dispatcher executes sub-queries from a Plan using the existing LangGraph
pipeline. Independent sub-queries run in parallel (up to a concurrency limit),
while dependent sub-queries execute serially after their dependencies complete.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nl2dsl.agent.models import Plan, QueryResult, SubQuery
from nl2dsl.graph.state import QueryState
from nl2dsl.utils.logger import get_logger

if TYPE_CHECKING:
    from nl2dsl.domain_context import DomainContext

logger = get_logger("agent.dispatcher")

MAX_PARALLEL_SUB_QUERIES = 3


async def _execute_sub_query(
    sub_query: SubQuery,
    domain_context: "DomainContext",
    base_state: dict,
) -> QueryResult:
    """Execute a single sub-query through the LangGraph pipeline.

    Builds a ``QueryState`` from the sub-query description and invokes the
    domain's compiled graph. If the sub-query carries a pre-built ``dsl``,
    it is forwarded in the state so the graph can skip generation.

    Args:
        sub_query: The sub-query to execute.
        domain_context: Domain context containing the compiled graph.
        base_state: Base state fields (user_id, tenant_id, domain, etc.).

    Returns:
        A ``QueryResult`` with the execution data or an error description.
    """
    state: QueryState = {
        "question": sub_query.description,
        "domain": domain_context.domain,
        "user_id": base_state["user_id"],
        "tenant_id": base_state["tenant_id"],
        "data_source": base_state.get("data_source"),
        "original_question": base_state.get("original_question"),
        "rewrite_reason": base_state.get("rewrite_reason"),
        "verify_status": base_state.get("verify_status"),
        "verify_reason": base_state.get("verify_reason"),
        "ambiguities": None,
        # Set a single-query plan to prevent graph plan_node from re-classifying
        # the sub-query description (which is already a decomposed fragment).
        "plan": Plan(
            intent="single_query",
            sub_queries=[SubQuery(id=sub_query.id, description=sub_query.description)],
            reasoning="Sub-query from AgentOrchestrator decomposition",
        ),
        "confidence": None,
        "explanation": None,
        "dsl": sub_query.dsl,
        "dsl_attempts": None,
        "sql": None,
        "sandbox_result": None,
        "complexity": None,
        "data": None,
        "status": "pending",
        "error": None,
        "error_code": None,
        "trace": None,
        "query_id": base_state.get("query_id", ""),
        "started_at": base_state.get("started_at", 0.0),
        "llm_used": base_state.get("llm_used", False),
    }

    config = {"configurable": {"thread_id": f"sub_{sub_query.id}"}}

    try:
        result = await domain_context.graph.ainvoke(state, config)
        raw_data = result.get("data")
        status = result.get("status", "success")
        # Preserve non-terminal statuses (clarification, warning, pending_review)
        valid_statuses = {"success", "error", "clarification", "warning", "pending_review"}
        if status not in valid_statuses:
            status = "success"

        # Normalize data to a list without silent loss
        data: list[dict]
        if raw_data is None:
            data = []
        elif isinstance(raw_data, list):
            data = raw_data
        elif isinstance(raw_data, dict):
            # Some graph nodes return {"rows": [...]} — extract the rows
            if "rows" in raw_data and isinstance(raw_data["rows"], list):
                data = raw_data["rows"]
            else:
                data = [raw_data]
        else:
            logger.warning(
                "[dispatcher] Unexpected data type %s from sub-query %s, wrapping in list",
                type(raw_data).__name__,
                sub_query.id,
            )
            data = [raw_data]  # type: ignore[list-item]

        return QueryResult(
            sub_query_id=sub_query.id,
            data=data,
            status=status,
        )
    except Exception as exc:
        logger.error(
            "[dispatcher] Sub-query %s failed: %s",
            sub_query.id,
            exc,
            exc_info=True,
        )
        return QueryResult(
            sub_query_id=sub_query.id,
            data=[],
            status="error",
            error=str(exc),
        )


async def dispatch_sub_queries(
    sub_queries: list[SubQuery],
    domain_context: "DomainContext",
    base_state: dict,
) -> dict[str, QueryResult]:
    """Dispatch all sub-queries, respecting dependency order.

    Independent sub-queries (``depends_on == []``) are executed in parallel
    with a concurrency limit of ``MAX_PARALLEL_SUB_QUERIES``. Dependent
    sub-queries execute serially after all their dependencies have completed.
    If any dependency fails, the dependent sub-query is skipped with an error
    result.

    Args:
        sub_queries: List of sub-queries from a Plan.
        domain_context: Domain context containing the compiled graph.
        base_state: Base state fields shared across all sub-queries.

    Returns:
        Dictionary mapping ``sub_query_id`` to ``QueryResult``.
    """
    if not sub_queries:
        return {}

    results: dict[str, QueryResult] = {}
    semaphore = asyncio.Semaphore(MAX_PARALLEL_SUB_QUERIES)

    # Separate independent and dependent sub-queries
    independent = [sq for sq in sub_queries if not sq.depends_on]
    dependent = [sq for sq in sub_queries if sq.depends_on]

    # ------------------------------------------------------------------
    # Phase 1: Execute independent sub-queries in parallel
    # ------------------------------------------------------------------
    async def _run_with_limit(sq: SubQuery) -> QueryResult:
        async with semaphore:
            return await _execute_sub_query(sq, domain_context, base_state)

    if independent:
        logger.info(
            "[dispatcher] Executing %d independent sub-queries (max_parallel=%d)",
            len(independent),
            MAX_PARALLEL_SUB_QUERIES,
        )
        independent_results = await asyncio.gather(
            *(_run_with_limit(sq) for sq in independent)
        )
        for res in independent_results:
            results[res.sub_query_id] = res

    # ------------------------------------------------------------------
    # Phase 2: Execute dependent sub-queries serially
    # ------------------------------------------------------------------
    # Track which dependent queries have been processed
    processed_dependent_ids: set[str] = set()
    remaining = list(dependent)

    while remaining:
        # Find sub-queries whose dependencies are all satisfied
        ready = []
        still_waiting = []

        for sq in remaining:
            deps_satisfied = all(dep_id in results for dep_id in sq.depends_on)
            if deps_satisfied:
                ready.append(sq)
            else:
                still_waiting.append(sq)

        if not ready:
            # Dependencies cannot be satisfied (missing or circular)
            for sq in still_waiting:
                missing = [d for d in sq.depends_on if d not in results]
                logger.error(
                    "[dispatcher] Sub-query %s has unsatisfied dependencies: %s",
                    sq.id,
                    missing,
                )
                results[sq.id] = QueryResult(
                    sub_query_id=sq.id,
                    data=[],
                    status="error",
                    error=f"Unsatisfied dependencies: {missing}",
                )
            break

        for sq in ready:
            if sq.id in processed_dependent_ids:
                continue
            processed_dependent_ids.add(sq.id)

            # Check if all dependencies succeeded
            failed_deps = [
                dep_id
                for dep_id in sq.depends_on
                if results.get(dep_id) and results[dep_id].status == "error"
            ]

            if failed_deps:
                logger.warning(
                    "[dispatcher] Skipping sub-query %s due to failed dependencies: %s",
                    sq.id,
                    failed_deps,
                )
                results[sq.id] = QueryResult(
                    sub_query_id=sq.id,
                    data=[],
                    status="error",
                    error=f"Dependency failed: {failed_deps}",
                )
                continue

            # Execute the dependent sub-query
            result = await _execute_sub_query(sq, domain_context, base_state)
            results[sq.id] = result

        remaining = still_waiting

    return results
