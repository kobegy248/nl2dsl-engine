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
        """1 metric, 1 dimension, no comparison -> SimpleExecutionPlan."""
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
        # Planner should NOT be called for simple queries
        mock_planner.plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_routes_complex_query_multiple_metrics(
        self, controller_with_mock, mock_planner
    ):
        """Multiple metrics -> ComplexExecutionPlan."""
        mock_plan = Plan(
            intent="aggregate",
            sub_queries=[SubQuery(id="sq-1", description="Get metrics")],
            reasoning="Multiple metrics",
        )
        mock_planner.plan.return_value = mock_plan

        entities = Entities(
            metrics=["revenue", "profit", "cost"],
            dimensions=["region"],
        )
        result = await controller_with_mock.route(
            "What are revenue, profit and cost by region?",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.question == "What are revenue, profit and cost by region?"
        assert result.entities.metrics == ["revenue", "profit", "cost"]
        assert result.plan == mock_plan
        mock_planner.plan.assert_awaited_once_with(
            "What are revenue, profit and cost by region?"
        )

    @pytest.mark.asyncio
    async def test_routes_complex_query_multiple_dimensions(
        self, controller_with_mock, mock_planner
    ):
        """Multiple dimensions -> ComplexExecutionPlan."""
        mock_plan = Plan(
            intent="aggregate",
            sub_queries=[SubQuery(id="sq-1", description="Get by dims")],
            reasoning="Multiple dimensions",
        )
        mock_planner.plan.return_value = mock_plan

        entities = Entities(
            metrics=["revenue"],
            dimensions=["region", "quarter"],
        )
        result = await controller_with_mock.route(
            "What is revenue by region and quarter?",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.entities.dimensions == ["region", "quarter"]
        assert result.plan == mock_plan
        mock_planner.plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_comparison_query(self, controller_with_mock, mock_planner):
        """Has comparison marker (YoY) -> ComplexExecutionPlan."""
        mock_plan = Plan(
            intent="compare",
            sub_queries=[
                SubQuery(id="sq-1", description="Current period"),
                SubQuery(id="sq-2", description="Previous period"),
            ],
            reasoning="Year-over-year comparison",
        )
        mock_planner.plan.return_value = mock_plan

        entities = Entities(
            metrics=["revenue"],
            dimensions=["region"],
            time_range="YoY 2023 vs 2024",
        )
        result = await controller_with_mock.route(
            "What is revenue by region YoY?",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        assert result.entities.has_comparison_marker() is True
        assert result.plan == mock_plan
        mock_planner.plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_comparison_query_mom(self, controller_with_mock, mock_planner):
        """Has comparison marker (MoM) -> ComplexExecutionPlan."""
        mock_plan = Plan(
            intent="compare",
            sub_queries=[SubQuery(id="sq-1", description="Compare")],
            reasoning="Month-over-month",
        )
        mock_planner.plan.return_value = mock_plan

        entities = Entities(
            metrics=["sales"],
            dimensions=["channel"],
            time_range="MoM",
        )
        result = await controller_with_mock.route(
            "Compare sales by channel MoM",
            entities,
        )
        assert isinstance(result, ComplexExecutionPlan)
        mock_planner.plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_exploration_query_no_metrics(
        self, controller_with_mock, mock_planner
    ):
        """No metrics -> ExplorationPlan."""
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
        mock_planner.plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_routes_exploration_query_no_dimensions(
        self, controller_with_mock, mock_planner
    ):
        """No dimensions -> ExplorationPlan."""
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
        mock_planner.plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_routes_exploration_query_empty_entities(
        self, controller_with_mock, mock_planner
    ):
        """No metrics, no dimensions -> ExplorationPlan."""
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
        mock_planner.plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_default_planner_initialization(self):
        """AgentController creates a default Planner when none is provided."""
        controller = AgentController()
        assert controller._planner is not None
        assert isinstance(controller._planner, Planner)

    @pytest.mark.asyncio
    async def test_custom_planner_passed_in(self, mock_planner):
        """AgentController uses the provided planner instance."""
        controller = AgentController(planner=mock_planner)
        assert controller._planner is mock_planner
