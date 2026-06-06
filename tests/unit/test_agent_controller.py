"""Unit tests for nl2dsl.agent.controller."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nl2dsl.agent.controller import AgentController
from nl2dsl.agent.models import (
    ComplexExecutionPlan,
    Entities,
    ExplorationPlan,
    Plan,
    SimpleExecutionPlan,
    SubQuery,
)
from nl2dsl.agent.planner import Planner


class TestAgentControllerRoute:
    """Tests for AgentController.route()."""

    @pytest.fixture
    def mock_planner(self):
        """Return a mock Planner with an async plan() method."""
        planner = MagicMock(spec=Planner)
        planner.plan = AsyncMock()
        return planner

    @pytest.fixture
    def controller_with_mock(self, mock_planner):
        """Return an AgentController using the mock planner."""
        return AgentController(planner=mock_planner)

    @pytest.mark.asyncio
    async def test_routes_simple_query(self, controller_with_mock, mock_planner):
        """single_query intent + metric + dimension -> SimpleExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="single_query",
            sub_queries=[SubQuery(id="sq-1", description="revenue by region")],
            reasoning="Simple query",
        )

        entities = Entities(
            metrics=["revenue"],
            dimensions=["region"],
        )
        result = await controller_with_mock.route(
            "What is the revenue by region?",
            entities,
        )
        assert isinstance(result, SimpleExecutionPlan)
        assert result.question == "What is the revenue by region?"
        assert result.entities.metrics == ["revenue"]
        assert result.entities.dimensions == ["region"]
        mock_planner.plan.assert_awaited_once_with(
            "What is the revenue by region?"
        )

    @pytest.mark.asyncio
    async def test_routes_proportion_intent(self, controller_with_mock, mock_planner):
        """proportion intent (e.g. '占比') -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="proportion",
            sub_queries=[
                SubQuery(id="sq-1", description="total sales"),
                SubQuery(id="sq-2", description="sales by category"),
            ],
            reasoning="Break down into total and groups",
        )

        entities = Entities(
            metrics=["sales"],
            dimensions=["category"],
        )
        result = await controller_with_mock.route(
            "各品类销售额占比",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.question == "各品类销售额占比"
        assert result.plan.intent == "proportion"
        mock_planner.plan.assert_awaited_once_with("各品类销售额占比")

    @pytest.mark.asyncio
    async def test_routes_trend_intent(self, controller_with_mock, mock_planner):
        """trend intent (e.g. '趋势') -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="trend",
            sub_queries=[SubQuery(id="sq-1", description="sales trend")],
            reasoning="Time-series trend analysis",
        )

        entities = Entities(
            metrics=["sales"],
            dimensions=[],
        )
        result = await controller_with_mock.route(
            "销售额趋势",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.plan.intent == "trend"
        mock_planner.plan.assert_awaited_once_with("销售额趋势")

    @pytest.mark.asyncio
    async def test_routes_ranking_intent(self, controller_with_mock, mock_planner):
        """ranking intent (e.g. '排名') -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="ranking",
            sub_queries=[SubQuery(id="sq-1", description="top 5 sales")],
            reasoning="Ranking query",
        )

        entities = Entities(
            metrics=["sales"],
            dimensions=["product"],
        )
        result = await controller_with_mock.route(
            "销售额排名前5",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.plan.intent == "ranking"
        mock_planner.plan.assert_awaited_once_with("销售额排名前5")

    @pytest.mark.asyncio
    async def test_routes_compare_intent(self, controller_with_mock, mock_planner):
        """compare intent -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="compare",
            sub_queries=[
                SubQuery(id="sq-1", description="East region sales"),
                SubQuery(id="sq-2", description="South region sales"),
            ],
            reasoning="Region comparison",
        )

        entities = Entities(
            metrics=["sales"],
            dimensions=["region"],
        )
        result = await controller_with_mock.route(
            "对比华东和华南的销售额",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.plan.intent == "compare"
        mock_planner.plan.assert_awaited_once_with("对比华东和华南的销售额")

    @pytest.mark.asyncio
    async def test_routes_correlation_intent(self, controller_with_mock, mock_planner):
        """correlation intent -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="correlation",
            sub_queries=[
                SubQuery(id="sq-1", description="sales"),
                SubQuery(id="sq-2", description="orders"),
            ],
            reasoning="Correlation analysis",
        )

        entities = Entities(
            metrics=["sales", "orders"],
            dimensions=[],
        )
        result = await controller_with_mock.route(
            "销售额和订单量的关系",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.plan.intent == "correlation"
        mock_planner.plan.assert_awaited_once_with("销售额和订单量的关系")

    @pytest.mark.asyncio
    async def test_routes_sequential_intent(self, controller_with_mock, mock_planner):
        """sequential intent -> ComplexExecutionPlan."""
        mock_planner.plan.return_value = Plan(
            intent="sequential",
            sub_queries=[
                SubQuery(id="sq-1", description="Query A"),
                SubQuery(id="sq-2", description="Query B", depends_on=["sq-1"]),
            ],
            reasoning="Sequential execution",
        )

        entities = Entities(
            metrics=["sales"],
            dimensions=["region"],
        )
        result = await controller_with_mock.route(
            "先查华东销售额，再查华南销售额",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.plan.intent == "sequential"
        mock_planner.plan.assert_awaited_once_with("先查华东销售额，再查华南销售额")

    @pytest.mark.asyncio
    async def test_routes_exploration_no_metrics(self, controller_with_mock, mock_planner):
        """single_query intent but no metrics -> ExplorationPlan."""
        mock_planner.plan.return_value = Plan(
            intent="single_query",
            sub_queries=[SubQuery(id="sq-1", description="Explore data")],
            reasoning="Open-ended exploration",
        )

        entities = Entities(
            metrics=[],
            dimensions=["region"],
        )
        result = await controller_with_mock.route(
            "Tell me about regional data",
            entities,
        )
        assert isinstance(result, ExplorationPlan)
        assert result.question == "Tell me about regional data"
        assert result.entities.metrics == []
        assert len(result.exploration_steps) > 0
        mock_planner.plan.assert_awaited_once_with("Tell me about regional data")

    @pytest.mark.asyncio
    async def test_routes_exploration_no_dimensions(self, controller_with_mock, mock_planner):
        """single_query intent but no dimensions -> ExplorationPlan."""
        mock_planner.plan.return_value = Plan(
            intent="single_query",
            sub_queries=[SubQuery(id="sq-1", description="Total revenue")],
            reasoning="Simple aggregation",
        )

        entities = Entities(
            metrics=["revenue"],
            dimensions=[],
        )
        result = await controller_with_mock.route(
            "What is the total revenue?",
            entities,
        )
        assert isinstance(result, ExplorationPlan)
        assert result.entities.dimensions == []
        assert len(result.exploration_steps) > 0
        mock_planner.plan.assert_awaited_once_with("What is the total revenue?")

    @pytest.mark.asyncio
    async def test_routes_exploration_empty_entities(self, controller_with_mock, mock_planner):
        """single_query intent with empty entities -> ExplorationPlan."""
        mock_planner.plan.return_value = Plan(
            intent="single_query",
            sub_queries=[SubQuery(id="sq-1", description="Explore")],
            reasoning="Open-ended",
        )

        entities = Entities(
            metrics=[],
            dimensions=[],
        )
        result = await controller_with_mock.route(
            "What data do we have?",
            entities,
        )
        assert isinstance(result, ExplorationPlan)
        assert result.entities.metrics == []
        assert result.entities.dimensions == []
        assert len(result.exploration_steps) > 0
        mock_planner.plan.assert_awaited_once_with("What data do we have?")

    @pytest.mark.asyncio
    async def test_default_planner_initialization(self):
        """AgentController lazily creates a default Planner when none is provided."""
        controller = AgentController()
        # Lazy init: _planner is None until _ensure_planner() is called
        assert controller._planner is None
        planner = controller._ensure_planner()
        assert planner is not None
        assert isinstance(planner, Planner)
        # Second call returns cached instance
        assert controller._ensure_planner() is planner

    @pytest.mark.asyncio
    async def test_custom_planner_passed_in(self, mock_planner):
        """AgentController uses the provided planner instance."""
        controller = AgentController(planner=mock_planner)
        assert controller._planner is mock_planner
        assert controller._ensure_planner() is mock_planner
