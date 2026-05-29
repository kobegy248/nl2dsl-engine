"""Unit tests for nl2dsl.agent.models."""

from __future__ import annotations

import pytest

from nl2dsl.agent.models import AgentResult, AgentState, Plan, QueryResult, SubQuery


class TestSubQuery:
    """Tests for SubQuery model."""

    def test_defaults(self):
        sq = SubQuery(id="sq-1", description="Get total sales")
        assert sq.id == "sq-1"
        assert sq.description == "Get total sales"
        assert sq.dsl is None
        assert sq.depends_on == []

    def test_with_dsl(self):
        sq = SubQuery(
            id="sq-2",
            description="Filter by region",
            dsl={"data_source": "orders", "filters": [{"field": "region", "operator": "=", "value": "US"}]},
            depends_on=["sq-1"],
        )
        assert sq.dsl is not None
        assert sq.dsl["data_source"] == "orders"
        assert sq.depends_on == ["sq-1"]

    def test_multiple_dependencies(self):
        sq = SubQuery(
            id="sq-3",
            description="Aggregate results",
            depends_on=["sq-1", "sq-2"],
        )
        assert sq.depends_on == ["sq-1", "sq-2"]


class TestPlan:
    """Tests for Plan model."""

    def test_defaults(self):
        plan = Plan(
            intent="sales_summary",
            sub_queries=[SubQuery(id="sq-1", description="Get sales")],
            reasoning="User wants sales data",
        )
        assert plan.intent == "sales_summary"
        assert len(plan.sub_queries) == 1
        assert plan.reasoning == "User wants sales data"
        assert plan.requires_approval is False

    def test_requires_approval(self):
        plan = Plan(
            intent="delete_data",
            sub_queries=[SubQuery(id="sq-1", description="Delete old records")],
            reasoning="Destructive operation",
            requires_approval=True,
        )
        assert plan.requires_approval is True

    def test_single_query_intent(self):
        plan = Plan(
            intent="single_query",
            sub_queries=[
                SubQuery(id="sq-1", description="Get total revenue"),
            ],
            reasoning="Simple single query",
        )
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1

    def test_multiple_sub_queries(self):
        plan = Plan(
            intent="complex_analysis",
            sub_queries=[
                SubQuery(id="sq-1", description="Step 1"),
                SubQuery(id="sq-2", description="Step 2", depends_on=["sq-1"]),
                SubQuery(id="sq-3", description="Step 3", depends_on=["sq-1", "sq-2"]),
            ],
            reasoning="Multi-step analysis",
        )
        assert len(plan.sub_queries) == 3
        assert plan.sub_queries[2].depends_on == ["sq-1", "sq-2"]


class TestQueryResult:
    """Tests for QueryResult model."""

    def test_defaults(self):
        qr = QueryResult(sub_query_id="sq-1", data=[{"total": 100}])
        assert qr.sub_query_id == "sq-1"
        assert qr.data == [{"total": 100}]
        assert qr.status == "success"
        assert qr.error is None

    def test_row_count_empty(self):
        qr = QueryResult(sub_query_id="sq-1", data=[])
        assert qr.row_count == 0

    def test_row_count_single(self):
        qr = QueryResult(sub_query_id="sq-1", data=[{"total": 100}])
        assert qr.row_count == 1

    def test_row_count_multiple(self):
        qr = QueryResult(
            sub_query_id="sq-1",
            data=[{"id": 1}, {"id": 2}, {"id": 3}],
        )
        assert qr.row_count == 3

    def test_error_state(self):
        qr = QueryResult(
            sub_query_id="sq-1",
            data=[],
            status="error",
            error="Table not found",
        )
        assert qr.status == "error"
        assert qr.error == "Table not found"
        assert qr.row_count == 0


class TestAgentResult:
    """Tests for AgentResult model."""

    def test_defaults(self):
        ar = AgentResult(status="success")
        assert ar.status == "success"
        assert ar.data is None
        assert ar.explanation is None
        assert ar.confidence is None
        assert ar.plan is None
        assert ar.error is None

    def test_full_construction(self):
        plan = Plan(
            intent="sales_summary",
            sub_queries=[SubQuery(id="sq-1", description="Get sales")],
            reasoning="User wants sales",
        )
        ar = AgentResult(
            status="success",
            data=[{"total": 1000}],
            explanation="Total sales is 1000",
            confidence=0.95,
            plan=plan,
        )
        assert ar.status == "success"
        assert ar.data == [{"total": 1000}]
        assert ar.explanation == "Total sales is 1000"
        assert ar.confidence == 0.95
        assert ar.plan is not None
        assert ar.plan.intent == "sales_summary"
        assert ar.error is None

    def test_error_result(self):
        ar = AgentResult(
            status="error",
            error="Failed to generate plan",
        )
        assert ar.status == "error"
        assert ar.error == "Failed to generate plan"
        assert ar.data is None


class TestAgentState:
    """Tests for AgentState TypedDict."""

    def test_construction(self):
        state = AgentState(
            question="What are total sales?",
            user_id="u123",
            tenant_id="t001",
            domain="ecommerce",
            plan=None,
            sub_results={},
            final_result=None,
            confidence=0.0,
            explanation=None,
            status="planning",
            trace=[],
        )
        assert state["question"] == "What are total sales?"
        assert state["user_id"] == "u123"
        assert state["tenant_id"] == "t001"
        assert state["domain"] == "ecommerce"
        assert state["plan"] is None
        assert state["sub_results"] == {}
        assert state["final_result"] is None
        assert state["confidence"] == 0.0
        assert state["explanation"] is None
        assert state["status"] == "planning"
        assert state["trace"] == []

    def test_with_plan_and_results(self):
        plan = Plan(
            intent="sales_summary",
            sub_queries=[SubQuery(id="sq-1", description="Get sales")],
            reasoning="User wants sales",
        )
        sub_results = {
            "sq-1": QueryResult(sub_query_id="sq-1", data=[{"total": 100}]),
        }
        state = AgentState(
            question="What are total sales?",
            user_id="u123",
            tenant_id="t001",
            domain="ecommerce",
            plan=plan,
            sub_results=sub_results,
            final_result={"total": 100},
            confidence=0.95,
            explanation="Found total sales",
            status="done",
            trace=[{"step": "plan", "status": "success"}],
        )
        assert state["plan"] == plan
        assert state["sub_results"]["sq-1"].row_count == 1
        assert state["final_result"] == {"total": 100}
        assert state["confidence"] == 0.95
        assert state["status"] == "done"

    def test_status_values(self):
        for status in ("planning", "executing", "aggregating", "done", "error"):
            state = AgentState(
                question="test",
                user_id="u1",
                tenant_id="t1",
                domain="test",
                plan=None,
                sub_results={},
                final_result=None,
                confidence=0.0,
                explanation=None,
                status=status,
                trace=[],
            )
            assert state["status"] == status
