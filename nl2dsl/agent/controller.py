"""Top-level routing agent that analyzes query characteristics and decides execution path.

Uses CODE-BASED rules (not LLM) for deterministic routing.
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

    Analyzes extracted entities from a natural language question and routes
    the query to the appropriate execution plan type using deterministic,
    code-based rules (no LLM involved in routing).

    Args:
        planner: Optional Planner instance. Defaults to a new Planner().
    """

    def __init__(self, planner: Planner | None = None):
        self._planner = planner or Planner()

    async def route(self, question: str, entities: Entities) -> ExecutionPlan:
        """Route query to appropriate execution path.

        Routing logic:
        - Single metric + single dimension + no comparison: SimpleExecutionPlan
        - Multiple metrics/dimensions or comparison markers: ComplexExecutionPlan
        - Everything else: ExplorationPlan

        Args:
            question: The user's natural language question.
            entities: Extracted entities (metrics, dimensions, time_range).

        Returns:
            An ExecutionPlan subclass instance appropriate for the query.
        """
        metric_count = len(entities.metrics)
        dimension_count = len(entities.dimensions)
        has_comparison = entities.has_comparison_marker()

        # Complex: multiple metrics, multiple dimensions, or comparison
        if metric_count > 1 or dimension_count > 1 or has_comparison:
            plan = await self._planner.plan(question)
            return ComplexExecutionPlan(
                question=question,
                entities=entities,
                plan=plan,
            )

        # Simple: exactly 1 metric + 1 dimension + no comparison
        if metric_count == 1 and dimension_count == 1 and not has_comparison:
            return SimpleExecutionPlan(
                question=question,
                entities=entities,
            )

        # Exploration: everything else (no metrics, no dimensions, etc.)
        return ExplorationPlan(
            question=question,
            entities=entities,
            exploration_steps=[
                f"Analyze query: '{question}'",
                "Identify relevant metrics and dimensions",
                "Explore available data sources",
            ],
        )
