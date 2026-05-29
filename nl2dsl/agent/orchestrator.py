"""Agent orchestrator: coordinates the full Agent execution flow.

The AgentOrchestrator is the top-level component that wires together:
1. Planner — classifies intent and decomposes the question into sub-queries
2. Dispatcher — executes sub-queries through the LangGraph pipeline
3. Aggregator — merges sub-query results based on intent
4. Explainer — generates natural language explanations

It also emits SSE events at each step so callers can stream progress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nl2dsl.agent.aggregator import Aggregate
from nl2dsl.agent.dispatcher import dispatch_sub_queries
from nl2dsl.agent.explainer import _generate_template_explanation
from nl2dsl.agent.models import AgentResult, AgentState, Plan, QueryResult, SubQuery
from nl2dsl.agent.planner import _decompose_fallback, classify_intent
from nl2dsl.graph.state import QueryState
from nl2dsl.utils.logger import get_logger

if TYPE_CHECKING:
    from nl2dsl.domain_context import DomainContext

logger = get_logger("agent.orchestrator")


class AgentOrchestrator:
    """Orchestrates the full Agent execution flow for NL2DSL queries.

    Args:
        domains: Mapping from domain name to ``DomainContext``.
    """

    def __init__(self, domains: dict[str, "DomainContext"]) -> None:
        self._domains = domains

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_domain_context(self, domain: str) -> "DomainContext":
        """Return the ``DomainContext`` for *domain*.

        Falls back to ``"ecommerce"`` when the requested domain is not found.
        """
        if domain in self._domains:
            return self._domains[domain]
        logger.warning("[orchestrator] Domain '%s' not found, falling back to 'ecommerce'", domain)
        return self._domains["ecommerce"]

    @staticmethod
    async def _emit_event(
        callback: callable | None,
        event_type: str,
        payload: dict,
    ) -> None:
        """Emit an SSE event via *callback*, swallowing any errors.

        Supports both sync and async callbacks.
        """
        if callback is None:
            return
        try:
            import asyncio
            result = callback(event_type, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("[orchestrator] SSE callback error for event '%s': %s", event_type, exc)

    def _plan_question(self, question: str, domain_context: "DomainContext") -> Plan:
        """Classify intent and decompose *question* into a ``Plan``.

        Uses the domain's registry for richer planning when available.
        """
        intent = classify_intent(question)
        plan = _decompose_fallback(question, intent)
        logger.info(
            "[orchestrator] Plan: intent=%s, sub_queries=%d",
            plan.intent,
            len(plan.sub_queries),
        )
        return plan

    @staticmethod
    def _build_query_state(
        question: str,
        domain: str,
        user_id: str,
        tenant_id: str,
    ) -> QueryState:
        """Build a full ``QueryState`` for the LangGraph pipeline."""
        return {
            "question": question,
            "domain": domain,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "plan": None,
            "confidence": None,
            "explanation": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "",
            "started_at": 0.0,
            "llm_used": False,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        question: str,
        user_id: str,
        tenant_id: str,
        domain: str,
        sse_callback: callable | None = None,
    ) -> AgentResult:
        """Execute the full Agent flow for *question*.

        Steps:
        1. Plan — classify intent and decompose
        2. Execute — simple query path (single_query) or complex query path
        3. Aggregate — merge results (complex path only)
        4. Explain — generate natural language explanation

        Args:
            question: The user's natural language question.
            user_id: User identifier.
            tenant_id: Tenant identifier.
            domain: Domain name (e.g. "ecommerce").
            sse_callback: Optional callback ``(event_type, payload) -> None``
                for streaming progress events.

        Returns:
            An ``AgentResult`` with status, data, explanation, and plan.
        """
        domain_context = self._get_domain_context(domain)

        # ------------------------------------------------------------------
        # Step 1: Plan
        # ------------------------------------------------------------------
        try:
            plan = self._plan_question(question, domain_context)
        except Exception as exc:
            logger.error("[orchestrator] Planning failed: %s", exc, exc_info=True)
            await self._emit_event(sse_callback, "error", {"error": str(exc), "step": "plan"})
            return AgentResult(status="error", error=f"Planning failed: {exc}")

        await self._emit_event(sse_callback, "plan", {"plan": plan})

        # ------------------------------------------------------------------
        # Step 2: Execute (simple vs complex path)
        # ------------------------------------------------------------------
        if plan.intent == "single_query" and len(plan.sub_queries) == 1:
            # Simple query path: execute directly through the graph
            return await self._run_simple_path(
                question=question,
                plan=plan,
                domain_context=domain_context,
                user_id=user_id,
                tenant_id=tenant_id,
                sse_callback=sse_callback,
            )

        # Complex query path: dispatch sub-queries, aggregate, explain
        return await self._run_complex_path(
            question=question,
            plan=plan,
            domain_context=domain_context,
            user_id=user_id,
            tenant_id=tenant_id,
            sse_callback=sse_callback,
        )

    async def _run_simple_path(
        self,
        question: str,
        plan: Plan,
        domain_context: "DomainContext",
        user_id: str,
        tenant_id: str,
        sse_callback: callable | None,
    ) -> AgentResult:
        """Execute a single-query question directly through the graph."""
        sub_query = plan.sub_queries[0]

        await self._emit_event(
            sse_callback,
            "sub_query_start",
            {"sub_query_id": sub_query.id, "description": sub_query.description},
        )

        state = self._build_query_state(
            question=sub_query.description,
            domain=domain_context.domain,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        config = {"configurable": {"thread_id": f"sub_{sub_query.id}"}}

        try:
            graph_result = await domain_context.graph.ainvoke(state, config)
        except Exception as exc:
            logger.error(
                "[orchestrator] Simple query failed: %s",
                exc,
                exc_info=True,
            )
            await self._emit_event(
                sse_callback,
                "sub_query_result",
                {
                    "sub_query_id": sub_query.id,
                    "status": "error",
                    "error": str(exc),
                },
            )
            return AgentResult(
                status="error",
                error=f"Query execution failed: {exc}",
                plan=plan,
            )

        data = graph_result.get("data") or []
        status = graph_result.get("status", "success")

        await self._emit_event(
            sse_callback,
            "sub_query_result",
            {
                "sub_query_id": sub_query.id,
                "status": status,
                "data": data,
            },
        )

        if status == "error":
            error_msg = graph_result.get("error", "Unknown error")
            return AgentResult(
                status="error",
                error=error_msg,
                plan=plan,
            )

        # Generate explanation
        explanation = self._generate_explanation(plan, question, data)
        await self._emit_event(sse_callback, "explain", {"explanation": explanation})

        return AgentResult(
            status="success",
            data=data,
            explanation=explanation,
            confidence=1.0,
            plan=plan,
        )

    async def _run_complex_path(
        self,
        question: str,
        plan: Plan,
        domain_context: "DomainContext",
        user_id: str,
        tenant_id: str,
        sse_callback: callable | None,
    ) -> AgentResult:
        """Execute a complex query by dispatching sub-queries, aggregating, and explaining."""
        # Emit sub_query_start for each sub-query
        for sq in plan.sub_queries:
            await self._emit_event(
                sse_callback,
                "sub_query_start",
                {"sub_query_id": sq.id, "description": sq.description},
            )

        # Build base state for dispatcher
        base_state = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "data_source": None,
            "original_question": question,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "query_id": "",
            "started_at": 0.0,
            "llm_used": False,
        }

        # Dispatch sub-queries
        try:
            sub_results = await dispatch_sub_queries(
                sub_queries=plan.sub_queries,
                domain_context=domain_context,
                base_state=base_state,
            )
        except Exception as exc:
            logger.error(
                "[orchestrator] Dispatch failed: %s",
                exc,
                exc_info=True,
            )
            await self._emit_event(
                sse_callback,
                "error",
                {"error": str(exc), "step": "dispatch"},
            )
            return AgentResult(
                status="error",
                error=f"Dispatch failed: {exc}",
                plan=plan,
            )

        # Emit sub_query_result for each result
        for sq_id, result in sub_results.items():
            await self._emit_event(
                sse_callback,
                "sub_query_result",
                {
                    "sub_query_id": sq_id,
                    "status": result.status,
                    "data": result.data,
                    "error": result.error,
                },
            )

        # Check for failures
        failed = [r for r in sub_results.values() if r.status == "error"]
        if failed and len(failed) == len(sub_results):
            # All sub-queries failed
            errors = "; ".join(f"{r.sub_query_id}: {r.error}" for r in failed)
            logger.error("[orchestrator] All sub-queries failed: %s", errors)
            return AgentResult(
                status="error",
                error=f"All sub-queries failed: {errors}",
                plan=plan,
            )

        # Aggregate results (including successful sub-queries only)
        aggregator = Aggregate()
        aggregated = aggregator.run(sub_results, plan.intent)
        await self._emit_event(sse_callback, "aggregate", {"result": aggregated})

        # Extract rows for explanation
        rows = aggregated.get("rows", [])

        # Generate explanation
        explanation = self._generate_explanation(plan, question, rows)
        await self._emit_event(sse_callback, "explain", {"explanation": explanation})

        # Compute confidence based on success rate
        total = len(sub_results)
        success_count = sum(1 for r in sub_results.values() if r.status == "success")
        confidence = success_count / total if total > 0 else 0.0

        # Determine status: warning if partial failure, success if all succeeded
        status = "warning" if failed else "success"
        if failed:
            failed_info = "; ".join(f"{r.sub_query_id}: {r.error}" for r in failed)
            logger.warning("[orchestrator] Partial sub-query failure: %s", failed_info)

        return AgentResult(
            status=status,
            data=rows,
            explanation=explanation,
            confidence=confidence,
            plan=plan,
        )

    @staticmethod
    def _generate_explanation(plan: Plan, question: str, data: list[dict]) -> str:
        """Generate a natural language explanation for the results.

        Uses template-based explanation as the fallback.
        """
        try:
            return _generate_template_explanation(question, plan, data)
        except Exception as exc:
            logger.warning("[orchestrator] Explanation generation failed: %s", exc)
            return f"查询完成。共返回 {len(data)} 条数据。"
