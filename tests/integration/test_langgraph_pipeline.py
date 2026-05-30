"""Integration tests for the LangGraph query pipeline."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from nl2dsl.dsl.models import DSL


def _make_mock_llm_client():
    """Create a mock LLM client that returns valid DSL JSON."""
    llm_client = MagicMock()
    llm_client.generate = MagicMock(return_value=(
        '{"data_source": "orders", "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}], "dimensions": ["product_name"]}'
    ))
    return llm_client


@pytest.fixture
def mock_services():
    """Create mock services for graph testing."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value = [
        MagicMock(_mapping={"product_name": "iPhone", "sales_amount": 1000.0})
    ]

    return {
        "clarification_detector": MagicMock(),
        "validator": MagicMock(),
        "row_security": MagicMock(),
        "col_security": MagicMock(),
        "resolver": MagicMock(),
        "sql_builder": MagicMock(return_value="SELECT product_name, SUM(order_amount) FROM order_fact GROUP BY product_name LIMIT 10"),
        "scanner": MagicMock(),
        "sandbox": MagicMock(),
        "executor": engine,
        "llm_client": _make_mock_llm_client(),
        "rag_retriever": None,
        "registry_dict": {},
    }


class TestFullPipeline:
    def test_simple_query_success(self, mock_services):
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["sandbox"].check.return_value = MagicMock(passed=True, risks=[], sample_rows=[])
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl

        graph = build_graph(**mock_services)

        result = graph.invoke({
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        assert result["status"] == "success"
        assert result["sql"] is not None
        assert result["data"] is not None

    def test_clarification_returns_early(self, mock_services):
        mock_services["clarification_detector"].detect.return_value = [
            MagicMock(model_dump=lambda: {"type": "metric", "question": "Which metric?", "options": ["a", "b"]})
        ]
        # Provide a mock LLM so clarification is not skipped
        mock_llm = MagicMock()
        mock_services["llm_client"] = mock_llm

        graph = build_graph(**mock_services)

        result = graph.invoke({
            "question": "查询",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        assert result["status"] == "clarification"
        assert result["ambiguities"] is not None

    def test_sandbox_review_routes_through_human_review(self, mock_services):
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["sandbox"].check.return_value = MagicMock(
            passed=False,
            risks=["Full table scan detected"],
            sample_rows=[],
        )

        graph = build_graph(**mock_services)

        result = graph.invoke({
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        # Without checkpointer/interrupt, human_review node runs directly
        # but the graph continues to execute_sql afterwards
        trace = result.get("trace", [])
        steps = [t["step"] for t in trace if isinstance(t, dict)]
        assert "human_review" in steps
        # Final status is success because graph continues after human_review
        assert result["status"] == "success"

    def test_trace_accumulates(self, mock_services):
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["sandbox"].check.return_value = MagicMock(passed=True, risks=[], sample_rows=[])
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl

        graph = build_graph(**mock_services)

        result = graph.invoke({
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        trace = result.get("trace", [])
        assert len(trace) > 0
        steps = [t["step"] for t in trace if isinstance(t, dict)]
        assert "clarification" in steps
        assert "generate_dsl" in steps
