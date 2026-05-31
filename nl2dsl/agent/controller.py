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
    SimpleExecutionPlan,
)
from nl2dsl.agent.planner import Planner


class AgentController:
    """Top-level routing agent for query execution path selection.

    Routes every query through :class:`Planner` for intent classification
    first, then dispatches to the appropriate execution plan based on the
    detected intent.

    Args:
        planner: Optional Planner instance. Defaults to a new Planner().
    """

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner or Planner()

    async def route(self, question: str, entities: Entities) -> ExecutionPlan:
        """Route query to appropriate execution path.

        Routing logic:
        1. Ask Planner to classify intent (using IntentRegistry keywords).
        2. Any non-single_query intent → ComplexExecutionPlan.
        3. single_query + at least 1 metric + at least 1 dimension → SimpleExecutionPlan.
        4. Everything else → ExplorationPlan.

        Args:
            question: The user's natural language question.
            entities: Extracted entities (metrics, dimensions, time_range).

        Returns:
            An ExecutionPlan subclass instance appropriate for the query.
        """
        # ------------------------------------------------------------------
        # Step 1: Intent classification via Planner
        # ------------------------------------------------------------------
        plan = await self._planner.plan(question)
        intent = plan.intent

        # ------------------------------------------------------------------
        # Step 2: Complex path — any non-trivial intent
        # ------------------------------------------------------------------
        if intent != "single_query":
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
