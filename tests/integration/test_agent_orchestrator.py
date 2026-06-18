"""Integration tests for nl2dsl.agent.orchestrator.AgentOrchestrator."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nl2dsl.agent.models import (
    AgentResult,
    ComplexExecutionPlan,
    Entities,
    ExplorationPlan,
    Plan,
    QueryResult,
    SimpleExecutionPlan,
    SubQuery,
)
from nl2dsl.agent.orchestrator import AgentOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_domain_context():
    """Return a mock DomainContext with an async graph."""
    ctx = MagicMock()
    ctx.domain = "ecommerce"
    ctx.registry_dict = {"metrics": {}, "dimensions": {}}
    ctx.graph = MagicMock()
    ctx.graph.ainvoke = AsyncMock()
    return ctx


@pytest.fixture
def orchestrator(mock_domain_context):
    """Return an AgentOrchestrator with a single domain."""
    domains = {"ecommerce": mock_domain_context}
    return AgentOrchestrator(domains=domains)


@pytest.fixture
def sse_events():
    """Return a list to capture SSE events."""
    return []


@pytest.fixture
def sse_callback(sse_events):
    """Return an SSE callback that appends events to sse_events."""
    def callback(event_type: str, payload: dict):
        sse_events.append({"event": event_type, **payload})
    return callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan_single() -> Plan:
    """Create a single_query plan."""
    return Plan(
        intent="single_query",
        sub_queries=[SubQuery(id="sq-1", description="查询华东销售额", depends_on=[])],
        reasoning="直接回答用户问题",
    )


def _make_plan_compare() -> Plan:
    """Create a compare plan."""
    return Plan(
        intent="compare",
        sub_queries=[
            SubQuery(id="sq-1", description="华东销售额", depends_on=[]),
            SubQuery(id="sq-2", description="华南销售额", depends_on=[]),
        ],
        reasoning="对比两个地区",
    )


def _make_plan_trend() -> Plan:
    """Create a trend plan."""
    return Plan(
        intent="trend",
        sub_queries=[
            SubQuery(id="sq-1", description="销售额趋势（按时间分组）", depends_on=[]),
        ],
        reasoning="分析趋势",
    )


# ---------------------------------------------------------------------------
# Constructor / _get_domain_context
# ---------------------------------------------------------------------------


class TestConstructor:
    """Tests for AgentOrchestrator construction."""

    def test_stores_domains(self, mock_domain_context):
        """Domains are stored in the orchestrator."""
        domains = {"ecommerce": mock_domain_context, "bank": MagicMock()}
        orch = AgentOrchestrator(domains=domains)
        assert orch._domains == domains

    def test_empty_domains(self):
        """Empty domains dict is allowed."""
        orch = AgentOrchestrator(domains={})
        assert orch._domains == {}


class TestGetDomainContext:
    """Tests for _get_domain_context."""

    def test_returns_existing_domain(self, orchestrator, mock_domain_context):
        """Returns the domain context for an existing domain."""
        ctx = orchestrator._get_domain_context("ecommerce")
        assert ctx is mock_domain_context

    def test_fallback_to_ecommerce(self, orchestrator, mock_domain_context):
        """Falls back to 'ecommerce' when domain is not found."""
        ctx = orchestrator._get_domain_context("unknown")
        assert ctx is mock_domain_context

    def test_fallback_when_no_domains(self):
        """When no domains and unknown domain requested, raises RuntimeError."""
        orch = AgentOrchestrator(domains={})
        with pytest.raises(RuntimeError):
            orch._get_domain_context("anything")


# ---------------------------------------------------------------------------
# Simple query path (intent == "single_query")
# ---------------------------------------------------------------------------


class TestSimpleQueryPath:
    """Tests for the single_query execution path."""

    @pytest.mark.asyncio
    async def test_simple_query_success(self, orchestrator, sse_callback, sse_events):
        """Single query executes through graph and returns result."""
        # Mock graph to return data
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"region": "华东", "sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询华东销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert isinstance(result, AgentResult)
        assert result.status == "success"
        assert result.data == [{"region": "华东", "sales": 100}]
        assert result.plan is not None
        assert result.plan.intent == "single_query"
        assert result.explanation is not None
        assert result.confidence is not None

    @pytest.mark.asyncio
    async def test_simple_query_sse_events(self, orchestrator, sse_callback, sse_events):
        """SSE events are emitted during simple query execution."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        event_types = [e["event"] for e in sse_events]
        assert "plan" in event_types
        assert "sub_query_start" in event_types
        assert "sub_query_result" in event_types
        assert "explain" in event_types

    @pytest.mark.asyncio
    async def test_simple_query_no_sse_callback(self, orchestrator):
        """Running without SSE callback should not raise."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=None,
        )

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_simple_query_graph_error(self, orchestrator, sse_callback):
        """Graph error during simple query returns error result."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [],
            "status": "error",
            "error": "DB connection failed",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "error"
        assert result.error is not None
        assert "DB connection failed" in result.error

    @pytest.mark.asyncio
    async def test_simple_query_graph_exception(self, orchestrator, sse_callback):
        """Graph exception during simple query returns error result."""
        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = RuntimeError(
            "Unexpected error"
        )

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "error"
        assert "Unexpected error" in result.error

    @pytest.mark.asyncio
    async def test_simple_query_plan_event_payload(self, orchestrator, sse_callback, sse_events):
        """Plan event contains the plan details."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        await orchestrator.run(
            question="查询华东销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        plan_events = [e for e in sse_events if e["event"] == "plan"]
        assert len(plan_events) == 1
        assert "plan" in plan_events[0]
        assert plan_events[0]["plan"].intent == "single_query"

    @pytest.mark.asyncio
    async def test_simple_query_sub_query_start_event(self, orchestrator, sse_callback, sse_events):
        """sub_query_start event contains sub_query info."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        await orchestrator.run(
            question="查询华东销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        start_events = [e for e in sse_events if e["event"] == "sub_query_start"]
        assert len(start_events) == 1
        assert "sub_query_id" in start_events[0]

    @pytest.mark.asyncio
    async def test_simple_query_explain_event(self, orchestrator, sse_callback, sse_events):
        """explain event contains the explanation."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        await orchestrator.run(
            question="查询华东销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        explain_events = [e for e in sse_events if e["event"] == "explain"]
        assert len(explain_events) == 1
        assert "explanation" in explain_events[0]
        assert explain_events[0]["explanation"] != ""


# ---------------------------------------------------------------------------
# Complex query path (compare, trend, correlation)
# ---------------------------------------------------------------------------


class TestComplexQueryPath:
    """Tests for complex query execution paths."""

    @pytest.mark.asyncio
    async def test_compare_query(self, orchestrator, sse_callback, sse_events):
        """Compare intent dispatches multiple sub-queries."""

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "sub_sq-1":
                return {"data": [{"region": "华东", "sales": 100}], "status": "success"}
            if thread_id == "sub_sq-2":
                return {"data": [{"region": "华南", "sales": 200}], "status": "success"}
            return {"data": [], "status": "success"}

        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

        result = await orchestrator.run(
            question="对比华东和华南的销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert isinstance(result, AgentResult)
        assert result.status == "success"
        assert result.plan is not None
        assert result.plan.intent == "compare"
        assert result.data is not None
        assert len(result.data) == 2  # rows from both sub-queries
        assert result.explanation is not None

    @pytest.mark.asyncio
    async def test_compare_sse_events(self, orchestrator, sse_callback, sse_events):
        """Compare query emits all expected SSE events."""

        async def side_effect(state, config):
            return {"data": [{"sales": 100}], "status": "success"}

        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

        await orchestrator.run(
            question="对比华东和华南的销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        event_types = [e["event"] for e in sse_events]
        assert "plan" in event_types
        assert "sub_query_start" in event_types
        assert "sub_query_result" in event_types
        assert "aggregate" in event_types
        assert "explain" in event_types

        # Two sub_query_start events (one per sub-query)
        start_events = [e for e in sse_events if e["event"] == "sub_query_start"]
        assert len(start_events) == 2

        # Two sub_query_result events (one per sub-query)
        result_events = [e for e in sse_events if e["event"] == "sub_query_result"]
        assert len(result_events) == 2

    @pytest.mark.asyncio
    async def test_trend_query(self, orchestrator, sse_callback):
        """Trend intent executes single sub-query with aggregation."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [
                {"month": "2024-01", "sales": 100},
                {"month": "2024-02", "sales": 200},
                {"month": "2024-03", "sales": 300},
            ],
            "status": "success",
        }

        result = await orchestrator.run(
            question="销售额趋势",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "success"
        assert result.plan.intent == "trend"
        assert result.data is not None
        assert len(result.data) == 3

    @pytest.mark.asyncio
    async def test_correlation_query(self, orchestrator, sse_callback):
        """Correlation intent executes and aggregates."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [
                {"x": 1, "y": 2},
                {"x": 2, "y": 4},
                {"x": 3, "y": 6},
            ],
            "status": "success",
        }

        result = await orchestrator.run(
            question="销售额和订单量的关系",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "success"
        assert result.plan.intent == "correlation"

    @pytest.mark.asyncio
    async def test_complex_query_with_failed_sub_query(self, orchestrator, sse_callback, sse_events):
        """When a sub-query fails, the overall result reflects the failure."""

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "sub_sq-1":
                return {"data": [{"sales": 100}], "status": "success"}
            if thread_id == "sub_sq-2":
                return {"data": [], "status": "error", "error": "DB timeout"}
            return {"data": [], "status": "success"}

        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

        result = await orchestrator.run(
            question="对比华东和华南的销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        # Partial failure returns warning status with available data
        assert result.status == "warning"
        assert result.data is not None

        # Check that sub_query_result events include the error
        result_events = [e for e in sse_events if e["event"] == "sub_query_result"]
        assert len(result_events) == 2

    @pytest.mark.asyncio
    async def test_complex_query_all_sub_queries_fail(self, orchestrator, sse_callback):
        """When all sub-queries fail, returns error status."""

        async def side_effect(state, config):
            return {"data": [], "status": "error", "error": "DB down"}

        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

        result = await orchestrator.run(
            question="对比华东和华南的销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "error"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_aggregate_event_payload(self, orchestrator, sse_callback, sse_events):
        """Aggregate event contains the aggregated result."""

        async def side_effect(state, config):
            return {"data": [{"sales": 100}], "status": "success"}

        orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

        await orchestrator.run(
            question="对比华东和华南的销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        agg_events = [e for e in sse_events if e["event"] == "aggregate"]
        assert len(agg_events) == 1
        assert "result" in agg_events[0]
        assert "rows" in agg_events[0]["result"]


# ---------------------------------------------------------------------------
# SSE callback error handling
# ---------------------------------------------------------------------------


class TestSSECallbackErrors:
    """Tests for SSE callback error handling."""

    @pytest.mark.asyncio
    async def test_sse_callback_error_caught(self, orchestrator):
        """Errors in SSE callback are caught and logged, not propagated."""

        def bad_callback(event_type: str, payload: dict):
            raise RuntimeError("SSE callback failed")

        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        # Should not raise despite callback errors
        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=bad_callback,
        )

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_sse_callback_error_does_not_stop_execution(self, orchestrator):
        """SSE callback error does not stop the execution flow."""
        call_count = 0

        def flaky_callback(event_type: str, payload: dict):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First call fails")
            # Subsequent calls succeed

        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=flaky_callback,
        )

        assert result.status == "success"
        # Callback was called multiple times (plan, sub_query_start, sub_query_result, explain)
        assert call_count >= 3


# ---------------------------------------------------------------------------
# Domain fallback
# ---------------------------------------------------------------------------


class TestDomainFallback:
    """Tests for domain fallback behavior."""

    @pytest.mark.asyncio
    async def test_uses_fallback_domain(self, mock_domain_context):
        """When requested domain is not found, falls back to ecommerce."""
        domains = {"ecommerce": mock_domain_context}
        orchestrator = AgentOrchestrator(domains=domains)

        mock_domain_context.graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="nonexistent",  # This domain doesn't exist
            sse_callback=None,
        )

        assert result.status == "success"
        # Should have used the ecommerce domain's graph
        assert mock_domain_context.graph.ainvoke.called


# ---------------------------------------------------------------------------
# Plan requires approval
# ---------------------------------------------------------------------------


class TestRequiresApproval:
    """Tests for plans that require approval."""

    @pytest.mark.asyncio
    async def test_plan_requires_approval_flag(self, orchestrator, sse_callback):
        """Plan with requires_approval=True is still executed."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.status == "success"
        assert result.plan is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_empty_question(self, orchestrator, sse_callback):
        """Empty question still produces a plan and executes."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [],
            "status": "success",
        }

        result = await orchestrator.run(
            question="",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert isinstance(result, AgentResult)
        assert result.plan is not None

    @pytest.mark.asyncio
    async def test_result_data_is_list(self, orchestrator, sse_callback):
        """Result data should always be a list."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert isinstance(result.data, list)

    @pytest.mark.asyncio
    async def test_plan_in_result(self, orchestrator, sse_callback):
        """Result should contain the plan."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.plan is not None
        assert isinstance(result.plan, Plan)

    @pytest.mark.asyncio
    async def test_confidence_in_result(self, orchestrator, sse_callback):
        """Result should contain a confidence score."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.confidence is not None
        assert isinstance(result.confidence, float)

    @pytest.mark.asyncio
    async def test_explanation_in_result(self, orchestrator, sse_callback):
        """Result should contain an explanation."""
        orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
            "data": [{"sales": 100}],
            "status": "success",
        }

        result = await orchestrator.run(
            question="查询销售额",
            user_id="u1",
            tenant_id="t1",
            domain="ecommerce",
            sse_callback=sse_callback,
        )

        assert result.explanation is not None
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0

    @pytest.mark.asyncio
    async def test_multiple_domains(self):
        """Orchestrator with multiple domains routes correctly."""
        ecommerce_ctx = MagicMock()
        ecommerce_ctx.domain = "ecommerce"
        ecommerce_ctx.registry_dict = {}
        ecommerce_ctx.graph = MagicMock()
        ecommerce_ctx.graph.ainvoke = AsyncMock(return_value={
            "data": [{"sales": 100}],
            "status": "success",
        })

        bank_ctx = MagicMock()
        bank_ctx.domain = "bank"
        bank_ctx.registry_dict = {}
        bank_ctx.graph = MagicMock()
        bank_ctx.graph.ainvoke = AsyncMock(return_value={
            "data": [{"balance": 5000}],
            "status": "success",
        })

        orchestrator = AgentOrchestrator(domains={
            "ecommerce": ecommerce_ctx,
            "bank": bank_ctx,
        })

        result = await orchestrator.run(
            question="查询余额",
            user_id="u1",
            tenant_id="t1",
            domain="bank",
            sse_callback=None,
        )

        assert result.status == "success"
        assert result.data == [{"balance": 5000}]
        assert bank_ctx.graph.ainvoke.called
        assert not ecommerce_ctx.graph.ainvoke.called


# ---------------------------------------------------------------------------
# Controller routing integration
# ---------------------------------------------------------------------------


class TestControllerRouting:
    """Tests that AgentOrchestrator uses AgentController for routing."""

    def test_orchestrator_has_controller(self, orchestrator):
        """Orchestrator initializes an AgentController."""
        assert hasattr(orchestrator, "_controller")
        from nl2dsl.agent.controller import AgentController
        assert isinstance(orchestrator._controller, AgentController)

    def test_extract_entities_returns_entities(self, orchestrator):
        """_extract_entities returns an Entities instance."""
        entities = AgentOrchestrator._extract_entities("查询华东销售额")
        assert isinstance(entities, Entities)
        assert "销售额" in entities.metrics
        assert "华东" in entities.dimensions

    def test_extract_entities_trend_markers(self, orchestrator):
        """Trend markers are captured in time_range."""
        entities = AgentOrchestrator._extract_entities("销售额趋势")
        assert entities.time_range is not None
        assert "period" in entities.time_range.lower()

    @pytest.mark.asyncio
    async def test_orchestrator_uses_controller_for_routing(self, orchestrator, sse_callback):
        """Controller routing determines the execution path."""
        # Mock the controller to return a known SimpleExecutionPlan
        with patch.object(
            orchestrator._controller,
            "route",
            return_value=SimpleExecutionPlan(
                question="查询销售额",
                entities=Entities(metrics=["销售额"], dimensions=[], time_range=None),
            ),
        ):
            orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
                "data": [{"sales": 100}],
                "status": "success",
            }

            result = await orchestrator.run(
                question="查询销售额",
                user_id="u1",
                tenant_id="t1",
                domain="ecommerce",
                sse_callback=sse_callback,
            )

            assert result.status == "success"
            assert result.plan is not None
            assert result.plan.intent == "single_query"
            # Controller.route was called
            orchestrator._controller.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_controller_routes_to_complex_path(self, orchestrator, sse_callback):
        """Controller can route to complex path via ComplexExecutionPlan."""
        from nl2dsl.agent.planner import Planner
        planner = Planner()
        plan = await planner.plan("对比华东和华南的销售额")

        with patch.object(
            orchestrator._controller,
            "route",
            return_value=ComplexExecutionPlan(
                question="对比华东和华南的销售额",
                entities=Entities(
                    metrics=["销售额"],
                    dimensions=["华东", "华南"],
                    time_range=None,
                ),
                plan=plan,
            ),
        ):
            async def side_effect(state, config):
                return {"data": [{"sales": 100}], "status": "success"}

            orchestrator._domains["ecommerce"].graph.ainvoke.side_effect = side_effect

            result = await orchestrator.run(
                question="对比华东和华南的销售额",
                user_id="u1",
                tenant_id="t1",
                domain="ecommerce",
                sse_callback=sse_callback,
            )

            assert result.status == "success"
            orchestrator._controller.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_controller_routes_to_exploration_path(self, orchestrator, sse_callback):
        """Controller can route to exploration path via ExplorationPlan."""
        with patch.object(
            orchestrator._controller,
            "route",
            return_value=ExplorationPlan(
                question="分析一下数据",
                entities=Entities(metrics=[], dimensions=[], time_range=None),
                exploration_steps=["Step 1", "Step 2"],
            ),
        ):
            orchestrator._domains["ecommerce"].graph.ainvoke.return_value = {
                "data": [{"sales": 100}],
                "status": "success",
            }

            result = await orchestrator.run(
                question="分析一下数据",
                user_id="u1",
                tenant_id="t1",
                domain="ecommerce",
                sse_callback=sse_callback,
            )

            assert result.status == "success"
            assert result.plan is not None
            assert result.plan.intent == "exploration"
            orchestrator._controller.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_controller_routing_error_handled(self, orchestrator, sse_callback):
        """Errors from controller routing are handled gracefully."""
        with patch.object(
            orchestrator._controller,
            "route",
            side_effect=RuntimeError("Controller failed"),
        ):
            result = await orchestrator.run(
                question="查询销售额",
                user_id="u1",
                tenant_id="t1",
                domain="ecommerce",
                sse_callback=sse_callback,
            )

            assert result.status == "error"
            assert "Routing failed" in result.error
