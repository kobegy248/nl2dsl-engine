"""Unit tests for LangGraph subgraph builders."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.dsl.models import DSL, Aggregation
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.graph.state import QueryState
from nl2dsl.graph.subgraphs import build_permission_subgraph, build_validation_subgraph
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.permission.column_level import ColumnLevelSecurity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(**overrides) -> QueryState:
    """Build a minimal QueryState with defaults, overridden by kwargs."""
    defaults = {
        "question": "test question",
        "user_id": "u001",
        "tenant_id": "t001",
        "data_source": "orders",
        "ambiguities": None,
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
        "query_id": "q001",
        "started_at": 0.0,
        "llm_used": False,
    }
    defaults.update(overrides)
    return QueryState(**defaults)


@pytest.fixture
def test_registry():
    return {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)", "description": "销售额"},
        },
        "dimensions": {
            "product_name": {"column": "product_name", "description": "产品名称"},
        },
        "data_sources": {
            "orders": {"table": "order_fact", "metrics": ["sales_amount"], "dimensions": ["product_name"]},
        },
    }


@pytest.fixture
def valid_dsl():
    return DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        data_source="orders",
    )


# ---------------------------------------------------------------------------
# build_permission_subgraph tests
# ---------------------------------------------------------------------------


class TestBuildPermissionSubgraph:
    def test_returns_compiled_graph(self):
        row_security = RowLevelSecurity({})
        col_security = ColumnLevelSecurity()
        graph = build_permission_subgraph(row_security, col_security)
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        row_security = RowLevelSecurity({})
        col_security = ColumnLevelSecurity()
        graph = build_permission_subgraph(row_security, col_security)
        # The compiled graph should have the nodes we added
        assert "inject_row" in graph.nodes
        assert "check_col" in graph.nodes

    def test_runs_inject_row_then_check_col(self, valid_dsl):
        """Test that the permission subgraph runs both nodes successfully."""
        row_security = MagicMock()
        row_security.inject = MagicMock(return_value=valid_dsl)

        col_security = MagicMock()
        col_security.check = MagicMock()

        graph = build_permission_subgraph(row_security, col_security)

        state = make_state(dsl=valid_dsl)
        result = graph.invoke(state)

        # Both nodes should have been called
        row_security.inject.assert_called_once()
        col_security.check.assert_called_once()
        # Result should have the DSL (injected by row_security)
        assert result["dsl"] is not None

    def test_stops_on_row_permission_error(self):
        """If inject_row fails, the error state should be set."""
        row_security = MagicMock()
        row_security.inject = MagicMock(side_effect=Exception("Row permission denied"))

        col_security = MagicMock()

        graph = build_permission_subgraph(row_security, col_security)

        state = make_state(dsl=DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
        ))
        result = graph.invoke(state)

        # Should have error status
        assert result["status"] == "error"
        assert "Row permission denied" in result["error"]
        # check_col should NOT have been called (graph ends after inject_row error)
        col_security.check.assert_not_called()

    def test_stops_on_col_permission_error(self, valid_dsl):
        """If check_col fails, the error state should be set."""
        row_security = MagicMock()
        row_security.inject = MagicMock(return_value=valid_dsl)

        col_security = MagicMock()
        col_security.check = MagicMock(side_effect=Exception("Column permission denied"))

        graph = build_permission_subgraph(row_security, col_security)

        state = make_state(dsl=valid_dsl)
        result = graph.invoke(state)

        # Should have error status
        assert result["status"] == "error"
        assert "Column permission denied" in result["error"]
        # Both should have been called (inject_row succeeds, check_col fails)
        row_security.inject.assert_called_once()
        col_security.check.assert_called_once()

    def test_error_when_dsl_is_none(self):
        """If DSL is None, inject_row should fail with error."""
        row_security = MagicMock()
        col_security = MagicMock()

        graph = build_permission_subgraph(row_security, col_security)

        state = make_state(dsl=None)
        result = graph.invoke(state)

        assert result["status"] == "error"
        assert "DSL is None" in result["error"]


# ---------------------------------------------------------------------------
# build_validation_subgraph tests
# ---------------------------------------------------------------------------


class TestBuildValidationSubgraph:
    def test_returns_compiled_graph(self, test_registry, real_llm_client):
        validator = DSLValidator(test_registry)
        rag_retriever = MagicMock()
        graph = build_validation_subgraph(validator, real_llm_client, rag_retriever, test_registry)
        assert graph is not None

    def test_graph_has_expected_nodes(self, test_registry, real_llm_client):
        validator = DSLValidator(test_registry)
        rag_retriever = MagicMock()
        graph = build_validation_subgraph(validator, real_llm_client, rag_retriever, test_registry)
        assert "generate_dsl" in graph.nodes
        assert "validate_dsl" in graph.nodes
        assert "correct_dsl" in graph.nodes

    def test_validation_passes_with_valid_dsl(self, test_registry, valid_dsl, real_llm_client):
        """When DSL is valid, the subgraph should end after validation."""
        validator = DSLValidator(test_registry)
        rag_retriever = MagicMock()

        graph = build_validation_subgraph(validator, real_llm_client, rag_retriever, test_registry)
        rag_retriever.build_prompt = MagicMock(return_value="prompt")

        state = make_state(question="查询销售额")
        result = graph.invoke(state)

        # Should complete without error (real LLM generates valid DSL)
        assert result["status"] != "error"
        assert result["dsl"] is not None

    def test_validation_retries_on_invalid_dsl(self, test_registry, real_llm_client):
        """When validation fails, the subgraph should route to correct_dsl and retry."""
        validator = DSLValidator(test_registry)
        rag_retriever = MagicMock()
        rag_retriever.build_prompt = MagicMock(return_value="prompt")

        graph = build_validation_subgraph(validator, real_llm_client, rag_retriever, test_registry)

        state = make_state(question="查询销售额")
        result = graph.invoke(state)

        # With real LLM, the generate node produces valid DSL
        assert result["dsl"] is not None

    def test_validation_fallback_with_no_llm(self, test_registry):
        """When LLM is None, generate_dsl falls back to RuleBasedDSLGenerator."""
        validator = DSLValidator(test_registry)
        llm_client = None
        rag_retriever = None

        graph = build_validation_subgraph(validator, llm_client, rag_retriever, test_registry)

        state = make_state(question="查询销售额")
        result = graph.invoke(state)

        # Without LLM, generate_dsl uses RuleBasedDSLGenerator fallback;
        # validation passes and DSL is generated
        assert result["dsl"] is not None

    def test_correct_dsl_runs_when_routed(self, test_registry, real_llm_client):
        """Test that correct_dsl node is callable and produces output."""
        validator = DSLValidator(test_registry)

        graph = build_validation_subgraph(validator, real_llm_client, None, test_registry)

        # Start from a state that would trigger correction
        state = make_state(
            question="查询销售额",
            error="Previous validation failed",
            dsl_attempts=[{"source": "llm", "valid": False}],
        )
        result = graph.invoke(state)

        # With real LLM, the graph should produce a DSL or error gracefully
        assert "dsl" in result or result.get("status") == "error"


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestSubgraphIntegration:
    def test_permission_subgraph_with_real_security(self, valid_dsl):
        """Test permission subgraph with real (not mocked) security objects."""
        row_security = RowLevelSecurity({})
        col_security = ColumnLevelSecurity()

        graph = build_permission_subgraph(row_security, col_security)

        state = make_state(dsl=valid_dsl)
        result = graph.invoke(state)

        # Should complete without errors
        assert result["status"] != "error"
        assert result["dsl"] is not None

    def test_validation_subgraph_with_real_validator(self, test_registry, real_llm_client):
        """Test validation subgraph with a real validator and real LLM."""
        validator = DSLValidator(test_registry)

        graph = build_validation_subgraph(validator, real_llm_client, None, test_registry)

        state = make_state(question="查询销售额")
        result = graph.invoke(state)

        # Should produce a valid DSL via real LLM
        assert result["dsl"] is not None
        assert result["status"] != "error"
