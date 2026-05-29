"""Unit tests for nl2dsl.agent.confidence."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nl2dsl.agent.confidence import _make_confidence_node
from nl2dsl.dsl.models import DSL, Aggregation
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import ValidationError


def _make_valid_dsl() -> DSL:
    """Create a valid DSL for testing."""
    return DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["region"],
        data_source="orders",
        limit=10,
    )


def _make_base_state(dsl: DSL | None = None) -> dict:
    """Create a base state dict for confidence node tests."""
    return {
        "question": "查询华东销售额",
        "domain": "ecommerce",
        "user_id": "u1",
        "tenant_id": "t1",
        "data_source": None,
        "original_question": None,
        "rewrite_reason": None,
        "verify_status": None,
        "verify_reason": None,
        "ambiguities": None,
        "plan": None,
        "dsl": dsl,
        "dsl_attempts": None,
        "sql": None,
        "sandbox_result": None,
        "complexity": None,
        "data": None,
        "status": "pending",
        "error": None,
        "error_code": None,
        "trace": None,
        "query_id": "q1",
        "started_at": 0.0,
        "llm_used": False,
        "confidence": None,
        "explanation": None,
    }


class TestSyntaxConfidence:
    """Tests for syntax confidence (rule-based via validator)."""

    def test_syntax_confidence_pass(self):
        """Valid DSL should get 100.0 syntax confidence."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert "confidence" in result
        # syntax=100, semantic=50 (no LLM), history=1.0 -> min(100,50)*1.0 = 50.0
        assert result["confidence"] == 50.0
        assert "syntax_score" in result["trace"]["details"]
        assert result["trace"]["details"]["syntax_score"] == 100.0

    def test_syntax_confidence_fail(self):
        """Invalid DSL should get 0.0 syntax confidence."""
        registry = {
            "metrics": {},
            "dimensions": {},
            "data_sources": {},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # Syntax fails -> overall confidence = 0.0
        assert result["confidence"] == 0.0
        assert result["trace"]["details"]["syntax_score"] == 0.0

    def test_syntax_confidence_invalid_metric(self):
        """DSL with unknown metric should get 0.0 syntax confidence."""
        registry = {
            "metrics": {"other_metric": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 0.0
        assert result["trace"]["details"]["syntax_score"] == 0.0

    def test_syntax_confidence_invalid_dimension(self):
        """DSL with unknown dimension should get 0.0 syntax confidence."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"other_dim": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 0.0
        assert result["trace"]["details"]["syntax_score"] == 0.0


class TestSemanticConfidence:
    """Tests for semantic confidence (LLM-based)."""

    def test_semantic_no_llm_returns_neutral(self):
        """When no LLM is available, semantic confidence is 50.0 (neutral)."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=50, history=1.0 -> min(100,50)*1.0 = 50.0
        assert result["confidence"] == 50.0
        assert result["trace"]["details"]["semantic_score"] == 50.0
        assert result["trace"]["details"]["semantic_source"] == "neutral_no_llm"

    def test_semantic_with_llm_high_score(self):
        """LLM returning high score should produce high semantic confidence."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "85"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=85, history=1.0 -> min(100,85)*1.0 = 85.0
        assert result["confidence"] == 85.0
        assert result["trace"]["details"]["semantic_score"] == 85.0
        assert result["trace"]["details"]["semantic_source"] == "llm"
        llm_client.generate.assert_called_once()

    def test_semantic_with_llm_low_score(self):
        """LLM returning low score should produce low semantic confidence."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "30"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=30, history=1.0 -> min(100,30)*1.0 = 30.0
        assert result["confidence"] == 30.0
        assert result["trace"]["details"]["semantic_score"] == 30.0

    def test_semantic_with_llm_markdown_response(self):
        """LLM returning score in markdown should be parsed correctly."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "The score is 90"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 90.0
        assert result["trace"]["details"]["semantic_score"] == 90.0

    def test_semantic_llm_exception_falls_back(self):
        """When LLM raises exception, semantic falls back to neutral (50)."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.side_effect = Exception("LLM timeout")

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=50 (fallback), history=1.0 -> 50.0
        assert result["confidence"] == 50.0
        assert result["trace"]["details"]["semantic_score"] == 50.0
        assert result["trace"]["details"]["semantic_source"] == "neutral_fallback"

    def test_semantic_llm_invalid_number_falls_back(self):
        """When LLM returns non-numeric, semantic falls back to neutral (50)."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "not a number"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 50.0
        assert result["trace"]["details"]["semantic_score"] == 50.0
        assert result["trace"]["details"]["semantic_source"] == "neutral_fallback"

    def test_semantic_llm_score_clamped_to_100(self):
        """LLM score above 100 should be clamped to 100."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "150"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 100.0
        assert result["trace"]["details"]["semantic_score"] == 100.0

    def test_semantic_llm_negative_score_clamped_to_0(self):
        """LLM score below 0 should be clamped to 0."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "-10"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=0, history=1.0 -> 0.0
        assert result["confidence"] == 0.0
        assert result["trace"]["details"]["semantic_score"] == 0.0


class TestHistoryConfidence:
    """Tests for history confidence."""

    def test_history_always_one(self):
        """History confidence is always 1.0 in MVP."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["trace"]["details"]["history_score"] == 1.0


class TestConfidenceFormula:
    """Tests for the overall confidence formula."""

    def test_formula_min_syntax_semantic_times_history(self):
        """confidence = min(syntax, semantic) * history."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "70"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=100, semantic=70, history=1.0 -> min(100,70)*1.0 = 70.0
        assert result["confidence"] == 70.0

    def test_formula_syntax_limits_overall(self):
        """When syntax is low, it limits the overall confidence."""
        registry = {
            "metrics": {},
            "dimensions": {},
            "data_sources": {},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "95"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        # syntax=0, semantic=95, history=1.0 -> min(0,95)*1.0 = 0.0
        assert result["confidence"] == 0.0


class TestRoutingDecisions:
    """Tests for routing threshold logic."""

    def test_routing_continue_above_80(self):
        """Confidence >= 80 should route to 'continue'."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "90"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 90.0
        assert result["trace"]["routing"] == "continue"
        assert "status" not in result  # unchanged when routing is "continue"

    def test_routing_warning_between_60_and_79(self):
        """Confidence 60-79 should route to 'warning' and set status."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "70"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 70.0
        assert result["trace"]["routing"] == "warning"
        assert result["status"] == "warning"

    def test_routing_clarify_below_60(self):
        """Confidence < 60 should route to 'clarify' and set status."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "40"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 40.0
        assert result["trace"]["routing"] == "clarify"
        assert result["status"] == "clarification"

    def test_routing_boundary_80(self):
        """Confidence exactly 80 should route to 'continue'."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "80"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 80.0
        assert result["trace"]["routing"] == "continue"

    def test_routing_boundary_60(self):
        """Confidence exactly 60 should route to 'warning'."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "60"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert result["confidence"] == 60.0
        assert result["trace"]["routing"] == "warning"
        assert result["status"] == "warning"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_no_dsl_returns_error(self):
        """When DSL is None, should return error state."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(dsl=None)
        result = node(state)

        assert result["status"] == "error"
        assert "DSL is None" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"

    def test_explanation_field_present(self):
        """Result should include an explanation field."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        assert "explanation" in result
        assert isinstance(result["explanation"], str)
        assert result["explanation"] != ""

    def test_trace_structure(self):
        """Trace should have correct structure."""
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        llm_client = MagicMock()
        llm_client.generate.return_value = "75"

        node = _make_confidence_node(validator, llm_client=llm_client)

        state = _make_base_state(_make_valid_dsl())
        result = node(state)

        trace = result["trace"]
        assert trace["step"] == "confidence"
        assert trace["status"] == "success"
        assert "confidence" in trace
        assert "routing" in trace
        assert "details" in trace
        details = trace["details"]
        assert "syntax_score" in details
        assert "semantic_score" in details
        assert "history_score" in details

    def test_error_handler_catches_validation_error(self):
        """Error handler should catch ValidationError from validator."""
        # This is implicitly tested by the decorator, but we verify the
        # error state format matches expectations.
        registry = {
            "metrics": {"sales_amount": {}},
            "dimensions": {"region": {}},
            "data_sources": {"orders": {}},
        }
        validator = DSLValidator(registry)
        node = _make_confidence_node(validator, llm_client=None)

        # DSL is None triggers ValidationError
        state = _make_base_state(dsl=None)
        result = node(state)

        assert result["status"] == "error"
        assert "trace" in result
        assert result["trace"][0]["step"] == "confidence"
        assert result["trace"][0]["status"] == "error"
