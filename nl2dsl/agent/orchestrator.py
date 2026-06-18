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
from nl2dsl.agent.controller import AgentController
from nl2dsl.agent.dispatcher import dispatch_sub_queries
from nl2dsl.agent.explainer import _generate_template_explanation
from nl2dsl.agent.models import (
    AgentResult,
    AgentState,
    ComplexExecutionPlan,
    Entities,
    ExecutionPlan,
    ExplorationPlan,
    Plan,
    QueryResult,
    SimpleExecutionPlan,
    SubQuery,
)
from nl2dsl.agent.planner import classify_intent
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

    def __init__(self, domains: dict[str, "DomainContext"], llm_client=None) -> None:
        self._domains = domains
        from nl2dsl.agent.planner import Planner
        planner = Planner(llm_client=llm_client) if llm_client else None
        self._controller = AgentController(planner=planner)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_domain_context(self, domain: str) -> "DomainContext":
        """Return the ``DomainContext`` for *domain*.

        Falls back to ``"ecommerce"`` when the requested domain is not found.
        If ``"ecommerce"`` is also missing, returns the first available domain.
        """
        if domain in self._domains:
            return self._domains[domain]
        logger.warning("[orchestrator] Domain '%s' not found, falling back to 'ecommerce'", domain)
        if "ecommerce" in self._domains:
            return self._domains["ecommerce"]
        # Last resort: return the first available domain
        fallback = next(iter(self._domains.values()), None)
        if fallback is None:
            raise RuntimeError("No domains configured in AgentOrchestrator")
        return fallback

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

    @staticmethod
    def _extract_entities(question: str, registry_dict: dict | None = None) -> Entities:
        """Extract entities from *question* using keyword + registry matching.

        Uses hardcoded keyword lists as a baseline, then augments with the
        semantic registry: any registered dimension/metric whose description
        or id appears in the question is also counted. This lets queries like
        "按供应商统计销售额" (供应商 → supplier_name) be recognized as having a
        dimension so they route to the simple path instead of falling through
        to the exploration path. Time ranges are detected via common temporal
        markers.
        """
        # Simple keyword lists for MVP entity extraction
        _METRIC_KEYWORDS = {
            "销售额", "sales", "订单量", "orders", "用户数", "users",
            "转化率", "conversion", "客单价", "aov", "利润", "profit",
            "收入", "revenue", "成本", "cost", "库存", "inventory",
            "访问量", "pv", "浏览量", "views", "点击量", "clicks",
        }
        _DIMENSION_KEYWORDS = {
            "地区", "region", "华东", "华南", "华北", "华西",
            "城市", "city", "省份", "province",
            "品类", "category", "商品", "product",
            "渠道", "channel", "平台", "platform",
            "时间", "time", "日期", "date", "月份", "month", "年份", "year",
            "用户", "user", "客户", "customer",
            "品牌", "brand",
        }
        _TIME_RANGE_KEYWORDS = {
            "今年": "this year",
            "去年": "last year",
            "本月": "this month",
            "上月": "last month",
            "本周": "this week",
            "上周": "last week",
            "今天": "today",
            "昨天": "yesterday",
            "同比": "yoy",
            "环比": "mom",
            "yoy": "yoy",
            "mom": "mom",
            "最近": "recent period",
            "过去": "past period",
            "近": "recent period",
            "趋势": "trend period",
            "走势": "trend period",
            "变化": "change period",
            "增长": "growth period",
            "下降": "decline period",
        }

        metrics = [kw for kw in _METRIC_KEYWORDS if kw in question]
        dimensions = [kw for kw in _DIMENSION_KEYWORDS if kw in question]

        # Registry augmentation: a registered dim/metric is "mentioned" if its
        # description (Chinese label) or id appears in the question. This catches
        # domain-specific terms (供应商→supplier_name, 城市等级→city_level) that
        # the hardcoded lists don't cover, so the query routes correctly.
        # Match if the full description is in the question, the id is in the
        # question, or the description shares any ≥2-char Chinese substring with
        # the question (so "按供应商统计" matches the dim described as
        # "供应商名称" via the shared substring "供应商").
        def _mentions(question_text: str, desc: str) -> bool:
            if not desc:
                return False
            if desc in question_text:
                return True
            # Slide a ≥2 window over the description; descriptions are short.
            for i in range(len(desc) - 1):
                for j in range(i + 2, len(desc) + 1):
                    if desc[i:j] in question_text:
                        return True
            return False

        if registry_dict:
            for dim_id, dim_cfg in (registry_dict.get("dimensions") or {}).items():
                if not isinstance(dim_cfg, dict):
                    continue
                if _mentions(question, dim_cfg.get("description", "")) or dim_id in question:
                    if dim_id not in dimensions:
                        dimensions.append(dim_id)
            for m_id, m_cfg in (registry_dict.get("metrics") or {}).items():
                if not isinstance(m_cfg, dict):
                    continue
                if _mentions(question, m_cfg.get("description", "")) or m_id in question:
                    if m_id not in metrics:
                        metrics.append(m_id)

        time_range = None
        for kw, val in _TIME_RANGE_KEYWORDS.items():
            if kw in question:
                time_range = val
                break

        return Entities(
            metrics=metrics,
            dimensions=dimensions,
            time_range=time_range,
        )

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
        # Step 1: Extract entities
        # ------------------------------------------------------------------
        try:
            entities = self._extract_entities(question)
        except Exception as exc:
            logger.error("[orchestrator] Entity extraction failed: %s", exc, exc_info=True)
            await self._emit_event(sse_callback, "error", {"error": str(exc), "step": "entity_extraction"})
            return AgentResult(status="error", error=f"Entity extraction failed: {exc}")

        # ------------------------------------------------------------------
        # Step 2: Route via AgentController
        # ------------------------------------------------------------------
        try:
            execution_plan = await self._controller.route(question, entities)
        except Exception as exc:
            logger.error("[orchestrator] Controller routing failed: %s", exc, exc_info=True)
            await self._emit_event(sse_callback, "error", {"error": str(exc), "step": "route"})
            return AgentResult(status="error", error=f"Routing failed: {exc}")

        # ------------------------------------------------------------------
        # Step 3: Dispatch based on execution plan type
        # ------------------------------------------------------------------
        if isinstance(execution_plan, SimpleExecutionPlan):
            # Build a simple single-query plan for the simple path
            plan = Plan(
                intent="single_query",
                sub_queries=[SubQuery(id="sq-1", description=question, depends_on=[])],
                reasoning="Simple execution plan: single metric + single dimension",
            )
            await self._emit_event(sse_callback, "plan", {"plan": plan})
            return await self._run_simple_path(
                question=question,
                plan=plan,
                domain_context=domain_context,
                user_id=user_id,
                tenant_id=tenant_id,
                sse_callback=sse_callback,
            )

        if isinstance(execution_plan, ComplexExecutionPlan):
            # Use the plan embedded in the ComplexExecutionPlan
            plan = execution_plan.plan
            await self._emit_event(sse_callback, "plan", {"plan": plan})
            return await self._run_complex_path(
                question=question,
                plan=plan,
                domain_context=domain_context,
                user_id=user_id,
                tenant_id=tenant_id,
                sse_callback=sse_callback,
            )

        # ExplorationPlan (and any other): delegate to simple path as MVP placeholder
        plan = Plan(
            intent="exploration",
            sub_queries=[SubQuery(id="sq-1", description=question, depends_on=[])],
            reasoning="Exploration plan: delegated to simple path (MVP)",
        )
        await self._emit_event(sse_callback, "plan", {"plan": plan})
        return await self._run_exploration_path(
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
        confidence = graph_result.get("confidence") or 0.0
        # Surface the generated DSL/SQL so the API response carries them.
        # graph_result["dsl"] is a DSL pydantic model; serialize to dict.
        dsl_model = graph_result.get("dsl")
        dsl_dict = dsl_model.model_dump() if dsl_model is not None else None
        sql = graph_result.get("sql")

        await self._emit_event(
            sse_callback,
            "sub_query_result",
            {
                "sub_query_id": sub_query.id,
                "status": status,
                "data": data,
                "confidence": confidence,
            },
        )

        if status == "error":
            error_msg = graph_result.get("error", "Unknown error")
            return AgentResult(
                status="error",
                error=error_msg,
                plan=plan,
                confidence=confidence,
            )

        if status == "clarification":
            clarification = graph_result.get("clarification", {})
            clarification_msg = (
                clarification.get("question", "需要澄清")
                if isinstance(clarification, dict)
                else "需要澄清"
            )
            return AgentResult(
                status="clarification",
                error=clarification_msg,
                plan=plan,
                confidence=confidence,
            )

        # Generate explanation
        explanation = self._generate_explanation(plan, question, data)
        await self._emit_event(sse_callback, "explain", {"explanation": explanation})

        return AgentResult(
            status=status,
            data=data,
            dsl=dsl_dict,
            sql=sql,
            explanation=explanation,
            confidence=confidence,
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

        # Categorize sub-query results
        failed = [r for r in sub_results.values() if r.status == "error"]
        clarified = [r for r in sub_results.values() if r.status == "clarification"]
        warnings = [r for r in sub_results.values() if r.status == "warning"]
        non_executable = failed + clarified

        if non_executable and len(non_executable) == len(sub_results):
            # All sub-queries failed or were blocked
            messages = "; ".join(
                f"{r.sub_query_id}: {r.error or r.explanation or 'blocked'}"
                for r in non_executable
            )
            logger.error("[orchestrator] All sub-queries blocked: %s", messages)
            return AgentResult(
                status="error",
                error=f"All sub-queries blocked: {messages}",
                plan=plan,
            )

        # Aggregate results (including success and warning sub-queries)
        aggregator = Aggregate()
        aggregated = aggregator.run(sub_results, plan.intent)
        await self._emit_event(sse_callback, "aggregate", {"result": aggregated})

        # Extract rows for explanation
        rows = aggregated.get("rows", [])

        # Generate explanation with quality annotations
        explanation = self._generate_explanation(plan, question, rows, sub_results)
        await self._emit_event(sse_callback, "explain", {"explanation": explanation})

        # Compute confidence from sub-query confidence scores (weighted average)
        confidences = [
            r.confidence for r in sub_results.values() if r.confidence is not None
        ]
        confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Determine status based on sub-query health
        if failed or clarified:
            status = "warning"
            blocked_info = "; ".join(
                f"{r.sub_query_id}: {r.error or r.explanation or 'blocked'}"
                for r in non_executable
            )
            logger.warning("[orchestrator] Partial sub-query blocked: %s", blocked_info)
        elif warnings:
            status = "warning"
        else:
            status = "success"

        return AgentResult(
            status=status,
            data=rows,
            explanation=explanation,
            confidence=confidence,
            plan=plan,
        )

    async def _run_exploration_path(
        self,
        question: str,
        plan: Plan,
        domain_context: "DomainContext",
        user_id: str,
        tenant_id: str,
        sse_callback: callable | None,
    ) -> AgentResult:
        """Execute an exploration query — MVP placeholder delegating to simple path."""
        logger.info("[orchestrator] Exploration path: delegating to simple path (MVP)")
        return await self._run_simple_path(
            question=question,
            plan=plan,
            domain_context=domain_context,
            user_id=user_id,
            tenant_id=tenant_id,
            sse_callback=sse_callback,
        )

    @staticmethod
    def _generate_explanation(
        plan: Plan,
        question: str,
        data: list[dict],
        sub_results: dict[str, "QueryResult"] | None = None,
    ) -> str:
        """Generate a natural language explanation for the results.

        Uses template-based explanation as the fallback.
        When sub_results is provided, appends quality annotations for
        clarification or warning sub-queries.
        """
        try:
            explanation = _generate_template_explanation(
                question, plan, data, sub_results=sub_results
            )
        except Exception as exc:
            logger.warning("[orchestrator] Explanation generation failed: %s", exc)
            explanation = f"查询完成。共返回 {len(data)} 条数据。"

        # Append quality annotations for non-success sub-queries
        if sub_results:
            quality_notes: list[str] = []
            for sq_id, result in sub_results.items():
                if result.status == "clarification":
                    reason = result.explanation or result.error or "置信度不足"
                    quality_notes.append(f"[{sq_id}] 未执行: {reason}")
                elif result.status == "warning" and result.explanation:
                    quality_notes.append(f"[{sq_id}] 置信度偏低: {result.explanation}")

            if quality_notes:
                explanation += "\n\n子查询质量提示:\n" + "\n".join(quality_notes)

        return explanation
