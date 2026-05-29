"""Unit tests for nl2dsl.agent.dispatcher."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nl2dsl.agent.dispatcher import (
    MAX_PARALLEL_SUB_QUERIES,
    _execute_sub_query,
    dispatch_sub_queries,
)
from nl2dsl.agent.models import QueryResult, SubQuery
from nl2dsl.graph.state import QueryState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_domain_context():
    """Return a mock DomainContext with an async graph."""
    ctx = MagicMock()
    ctx.domain = "test_domain"
    ctx.graph = MagicMock()
    # ainvoke is async
    ctx.graph.ainvoke = AsyncMock()
    return ctx


@pytest.fixture
def base_query_state() -> dict[str, Any]:
    """Return base QueryState fields."""
    return {
        "question": "test question",
        "domain": "test_domain",
        "user_id": "u123",
        "tenant_id": "t001",
        "data_source": "orders",
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
        "query_id": "q-1",
        "started_at": 0.0,
        "llm_used": False,
    }


# ---------------------------------------------------------------------------
# Tests for _execute_sub_query
# ---------------------------------------------------------------------------


class TestExecuteSubQuery:
    """Tests for _execute_sub_query."""

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_domain_context, base_query_state):
        """Successful execution returns QueryResult with data."""
        mock_domain_context.graph.ainvoke.return_value = {
            "data": [{"total": 100}],
            "status": "success",
        }

        sub_query = SubQuery(id="sq-1", description="Get total sales")
        result = await _execute_sub_query(
            sub_query=sub_query,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert isinstance(result, QueryResult)
        assert result.sub_query_id == "sq-1"
        assert result.data == [{"total": 100}]
        assert result.status == "success"
        assert result.error is None

        # Verify graph was called with correct state
        call_args = mock_domain_context.graph.ainvoke.call_args
        state = call_args[0][0]
        config = call_args[0][1]

        assert state["question"] == "Get total sales"
        assert state["domain"] == "test_domain"
        assert config == {"configurable": {"thread_id": "sub_sq-1"}}

    @pytest.mark.asyncio
    async def test_execute_with_prebuilt_dsl(self, mock_domain_context, base_query_state):
        """Sub-query with pre-built DSL passes it in the state."""
        mock_domain_context.graph.ainvoke.return_value = {
            "data": [{"region": "华东", "sales": 500}],
            "status": "success",
        }

        dsl = {"data_source": "orders", "metrics": [{"alias": "sales_amount"}]}
        sub_query = SubQuery(id="sq-1", description="Get sales", dsl=dsl)
        result = await _execute_sub_query(
            sub_query=sub_query,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert result.status == "success"
        call_args = mock_domain_context.graph.ainvoke.call_args
        state = call_args[0][0]
        assert state["dsl"] == dsl

    @pytest.mark.asyncio
    async def test_execute_error(self, mock_domain_context, base_query_state):
        """Graph raises exception -> QueryResult with error status."""
        mock_domain_context.graph.ainvoke.side_effect = RuntimeError("DB connection failed")

        sub_query = SubQuery(id="sq-1", description="Get total sales")
        result = await _execute_sub_query(
            sub_query=sub_query,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert isinstance(result, QueryResult)
        assert result.sub_query_id == "sq-1"
        assert result.data == []
        assert result.status == "error"
        assert "DB connection failed" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_data_field(self, mock_domain_context, base_query_state):
        """Graph result without 'data' field returns empty data."""
        mock_domain_context.graph.ainvoke.return_value = {
            "status": "success",
            # no 'data' key
        }

        sub_query = SubQuery(id="sq-1", description="Get total sales")
        result = await _execute_sub_query(
            sub_query=sub_query,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert result.data == []
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_execute_preserves_base_state_fields(self, mock_domain_context, base_query_state):
        """Base state fields are preserved in the QueryState passed to graph.

        Note: domain comes from domain_context.domain, not base_state.
        """
        mock_domain_context.graph.ainvoke.return_value = {"data": [], "status": "success"}

        base_query_state["user_id"] = "user-42"
        base_query_state["tenant_id"] = "tenant-99"
        base_query_state["domain"] = "ecommerce"

        sub_query = SubQuery(id="sq-1", description="Test")
        await _execute_sub_query(
            sub_query=sub_query,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        call_args = mock_domain_context.graph.ainvoke.call_args
        state = call_args[0][0]
        assert state["user_id"] == "user-42"
        assert state["tenant_id"] == "tenant-99"
        # domain comes from domain_context, not base_state
        assert state["domain"] == "test_domain"


# ---------------------------------------------------------------------------
# Tests for dispatch_sub_queries
# ---------------------------------------------------------------------------


class TestDispatchSubQueries:
    """Tests for dispatch_sub_queries."""

    @pytest.mark.asyncio
    async def test_single_independent_query(self, mock_domain_context, base_query_state):
        """Single independent sub-query executes and returns result."""
        mock_domain_context.graph.ainvoke.return_value = {
            "data": [{"total": 100}],
            "status": "success",
        }

        sub_queries = [SubQuery(id="sq-1", description="Get total sales")]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == 1
        assert "sq-1" in results
        assert results["sq-1"].status == "success"
        assert results["sq-1"].data == [{"total": 100}]

    @pytest.mark.asyncio
    async def test_multiple_independent_queries(self, mock_domain_context, base_query_state):
        """Multiple independent sub-queries execute in parallel."""

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "sub_sq-1":
                return {"data": [{"region": "华东", "sales": 100}], "status": "success"}
            if thread_id == "sub_sq-2":
                return {"data": [{"region": "华南", "sales": 200}], "status": "success"}
            return {"data": [], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="华东销售额"),
            SubQuery(id="sq-2", description="华南销售额"),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == 2
        assert results["sq-1"].data == [{"region": "华东", "sales": 100}]
        assert results["sq-2"].data == [{"region": "华南", "sales": 200}]

    @pytest.mark.asyncio
    async def test_dependent_query_executes_after_dependency(self, mock_domain_context, base_query_state):
        """Dependent sub-query waits for dependency to complete."""
        call_order = []

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            call_order.append(thread_id)
            if thread_id == "sub_sq-1":
                return {"data": [{"total": 1000}], "status": "success"}
            if thread_id == "sub_sq-2":
                # sq-2 depends on sq-1, so sq-1 should have been called first
                return {"data": [{"ratio": 0.5}], "status": "success"}
            return {"data": [], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="Get total sales", depends_on=[]),
            SubQuery(id="sq-2", description="Calculate ratio", depends_on=["sq-1"]),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == 2
        assert results["sq-1"].status == "success"
        assert results["sq-2"].status == "success"
        # sq-1 must be called before sq-2
        assert call_order.index("sub_sq-1") < call_order.index("sub_sq-2")

    @pytest.mark.asyncio
    async def test_dependent_query_skipped_on_dependency_error(self, mock_domain_context, base_query_state):
        """Dependent sub-query is skipped if dependency fails."""

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "sub_sq-1":
                return {"data": [], "status": "error", "error": "DB timeout"}
            if thread_id == "sub_sq-2":
                return {"data": [{"ratio": 0.5}], "status": "success"}
            return {"data": [], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="Get total sales", depends_on=[]),
            SubQuery(id="sq-2", description="Calculate ratio", depends_on=["sq-1"]),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert results["sq-1"].status == "error"
        # sq-2 should be skipped because sq-1 failed
        assert results["sq-2"].status == "error"
        assert "dependency failed" in results["sq-2"].error.lower()

    @pytest.mark.asyncio
    async def test_chain_of_dependencies(self, mock_domain_context, base_query_state):
        """Chain: sq-1 -> sq-2 -> sq-3 executes in order."""
        call_order = []

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            call_order.append(thread_id)
            return {"data": [{"val": 1}], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="Step 1", depends_on=[]),
            SubQuery(id="sq-2", description="Step 2", depends_on=["sq-1"]),
            SubQuery(id="sq-3", description="Step 3", depends_on=["sq-2"]),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == 3
        assert all(r.status == "success" for r in results.values())
        assert call_order == ["sub_sq-1", "sub_sq-2", "sub_sq-3"]

    @pytest.mark.asyncio
    async def test_mixed_independent_and_dependent(self, mock_domain_context, base_query_state):
        """Mix of independent and dependent queries."""
        call_order = []

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            call_order.append(thread_id)
            return {"data": [{"val": 1}], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="Independent A", depends_on=[]),
            SubQuery(id="sq-2", description="Independent B", depends_on=[]),
            SubQuery(id="sq-3", description="Depends on A", depends_on=["sq-1"]),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == 3
        assert all(r.status == "success" for r in results.values())
        # sq-1 and sq-2 can be in any order (parallel), but sq-3 must come after sq-1
        sq1_idx = call_order.index("sub_sq-1")
        sq2_idx = call_order.index("sub_sq-2")
        sq3_idx = call_order.index("sub_sq-3")
        assert sq3_idx > sq1_idx
        # sq-2 is independent so it can be before or after sq-1

    @pytest.mark.asyncio
    async def test_multiple_dependencies_all_must_succeed(self, mock_domain_context, base_query_state):
        """Sub-query with multiple dependencies is skipped if any fails."""

        async def side_effect(state, config):
            thread_id = config["configurable"]["thread_id"]
            if thread_id == "sub_sq-1":
                return {"data": [{"a": 1}], "status": "success"}
            if thread_id == "sub_sq-2":
                return {"data": [], "status": "error", "error": "DB error"}
            if thread_id == "sub_sq-3":
                return {"data": [{"c": 1}], "status": "success"}
            return {"data": [], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = side_effect

        sub_queries = [
            SubQuery(id="sq-1", description="Query A", depends_on=[]),
            SubQuery(id="sq-2", description="Query B", depends_on=[]),
            SubQuery(id="sq-3", description="Depends on A and B", depends_on=["sq-1", "sq-2"]),
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert results["sq-1"].status == "success"
        assert results["sq-2"].status == "error"
        assert results["sq-3"].status == "error"
        assert "dependency failed" in results["sq-3"].error.lower()

    @pytest.mark.asyncio
    async def test_empty_sub_queries(self, mock_domain_context, base_query_state):
        """Empty sub-queries list returns empty dict."""
        results = await dispatch_sub_queries(
            sub_queries=[],
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )
        assert results == {}

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, mock_domain_context, base_query_state):
        """Concurrency is limited to MAX_PARALLEL_SUB_QUERIES."""
        concurrent_count = 0
        max_concurrent = 0

        async def slow_side_effect(state, config):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)  # Small delay to allow overlap
            concurrent_count -= 1
            return {"data": [{"val": 1}], "status": "success"}

        mock_domain_context.graph.ainvoke.side_effect = slow_side_effect

        # Create more sub-queries than the limit
        sub_queries = [
            SubQuery(id=f"sq-{i}", description=f"Query {i}", depends_on=[])
            for i in range(MAX_PARALLEL_SUB_QUERIES + 2)
        ]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert len(results) == len(sub_queries)
        assert max_concurrent <= MAX_PARALLEL_SUB_QUERIES

    @pytest.mark.asyncio
    async def test_graph_exception_handled(self, mock_domain_context, base_query_state):
        """Exceptions from graph are caught and converted to error results."""
        mock_domain_context.graph.ainvoke.side_effect = ValueError("Invalid state")

        sub_queries = [SubQuery(id="sq-1", description="Test")]
        results = await dispatch_sub_queries(
            sub_queries=sub_queries,
            domain_context=mock_domain_context,
            base_state=base_query_state,
        )

        assert results["sq-1"].status == "error"
        assert "Invalid state" in results["sq-1"].error


# ---------------------------------------------------------------------------
# Tests for constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module constants."""

    def test_max_parallel(self):
        """MAX_PARALLEL_SUB_QUERIES should be 3."""
        assert MAX_PARALLEL_SUB_QUERIES == 3
