"""Top-level routing agent that analyzes query characteristics and decides execution path.

Uses Planner-based intent classification for routing.  All queries go through
the Planner first so that intent keywords (compare, trend, proportion, etc.)
from ``configs/intents.yaml`` are respected.
"""

from __future__ import annotations

from nl2dsl.agent.models import (
    ComplexExecutionPlan,
    Entities,
    ExplorationPlan,
    ExecutionPlan,
    Plan,
    SimpleExecutionPlan,
    SubQuery,
)
from nl2dsl.agent.planner import Planner, classify_intent


class AgentController:
    """Top-level routing agent for query execution path selection.

    Routes every query through :class:`Planner` for intent classification
    first, then dispatches to the appropriate execution plan based on the
    detected intent.

    Args:
        planner: Optional Planner instance. Defaults to a new Planner().
    """

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner
        self._planner_initialized = planner is not None

    def _ensure_planner(self) -> Planner:
        """Lazy-init the Planner.  If intents.yaml is missing, returns None."""
        if self._planner_initialized:
            return self._planner
        try:
            self._planner = Planner()
        except Exception as exc:
            from nl2dsl.utils.logger import get_logger
            logger = get_logger("agent.controller")
            logger.warning("[controller] Planner init failed: %s. Falling back to entity-based routing.", exc)
            self._planner = None
        self._planner_initialized = True
        return self._planner

    async def route(self, question: str, entities: Entities) -> ExecutionPlan:
        """Route query to appropriate execution path.

        Routing logic:
        1. Ask Planner to classify intent (using IntentRegistry keywords).
        2. Any non-single_query intent → ComplexExecutionPlan.
        3. single_query + at least 1 metric + at least 1 dimension → SimpleExecutionPlan.
        4. Everything else → ExplorationPlan.

        If Planner initialization fails (e.g. intents.yaml not found),
        falls back to entity-count-based deterministic routing.

        Args:
            question: The user's natural language question.
            entities: Extracted entities (metrics, dimensions, time_range).

        Returns:
            An ExecutionPlan subclass instance appropriate for the query.
        """
        # ------------------------------------------------------------------
        # Step 1: Intent classification via Planner (with fallback)
        # ------------------------------------------------------------------
        plan: Plan | None = None
        planner = self._ensure_planner()
        if planner is not None:
            try:
                plan = await planner.plan(question)
                intent = plan.intent
            except Exception as exc:
                from nl2dsl.utils.logger import get_logger
                logger = get_logger("agent.controller")
                logger.warning("[controller] Planner failed: %s. Falling back to entity-based routing.", exc)
                intent = self._fallback_intent(question, entities)
        else:
            intent = self._fallback_intent(question, entities)

        # ------------------------------------------------------------------
        # Step 2: Complex path — any non-trivial intent
        # ------------------------------------------------------------------
        if intent != "single_query":
            if plan is None:
                plan = Plan(
                    intent=intent,
                    sub_queries=[SubQuery(id="sq-1", description=question, depends_on=[])],
                    reasoning=f"Fallback routing: intent='{intent}'",
                )
            return ComplexExecutionPlan(
                question=question,
                entities=entities,
                plan=plan,
            )

        # ------------------------------------------------------------------
        # Step 3: Simple path — single_query with explicit metric + dimension
        # ------------------------------------------------------------------
        if entities.metrics and entities.dimensions:
            return SimpleExecutionPlan(
                question=question,
                entities=entities,
            )

        # ------------------------------------------------------------------
        # Step 4: Exploration — no metrics, no dimensions, or open-ended
        # ------------------------------------------------------------------
        return ExplorationPlan(
            question=question,
            entities=entities,
            exploration_steps=[
                f"Analyze query: '{question}'",
                "Identify relevant metrics and dimensions",
                "Explore available data sources",
            ],
        )

    @staticmethod
    def _fallback_intent(question: str, entities: Entities) -> str:
        """Entity-count-based deterministic routing when Planner is unavailable.

        Mirrors the pre-Planner structural guards:
        - Multi-metric / multi-dimension → compare
        - Time keywords → trend
        - Open-ended (no metrics, no dimensions) → exploration (single_query)
        """
        if len(entities.metrics) > 1 or len(entities.dimensions) > 1:
            return "compare"
        if entities.time_range:
            return "trend"
        return "single_query"
