"""Unit tests for LangGraph conditional edge routing functions."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.graph.edges import (
    detect_complexity,
    route_after_clarification,
    route_after_execute,
    route_after_sandbox,
    route_after_validate,
    route_llm_availability,
    route_on_error,
)
from nl2dsl.graph.state import QueryState
from nl2dsl.dsl.models import DSL, Aggregation, Filter, Join
from nl2dsl.query.sandbox import SandboxResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(**overrides) -> QueryState:
    """Build a minimal QueryState with defaults, overridden by kwargs."""
    defaults = {
        "question": "test question",
        "user_id": "u001",
        "tenant_id": "t001",
        "data_source": None,
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


# ---------------------------------------------------------------------------
# route_after_clarification
# ---------------------------------------------------------------------------


class TestRouteAfterClarification:
    def test_returns_clarification_when_ambiguities_present(self):
        state = make_state(
            ambiguities=[
                {"type": "vague", "question": "Which region?", "options": ["华东", "华南"]}
            ]
        )
        assert route_after_clarification(state) == "clarification"

    def test_returns_continue_when_no_ambiguities(self):
        state = make_state(ambiguities=None)
        assert route_after_clarification(state) == "continue"

    def test_returns_continue_when_empty_ambiguities_list(self):
        state = make_state(ambiguities=[])
        # Empty list is falsy, so should continue
        assert route_after_clarification(state) == "continue"


# ---------------------------------------------------------------------------
# route_llm_availability
# ---------------------------------------------------------------------------


class TestRouteLLMAvailability:
    def test_returns_llm_when_client_present(self):
        state = make_state()
        llm_client = MagicMock()
        assert route_llm_availability(state, llm_client) == "llm"

    def test_returns_mock_when_client_none(self):
        state = make_state()
        assert route_llm_availability(state, None) == "mock"


# ---------------------------------------------------------------------------
# route_after_validate
# ---------------------------------------------------------------------------


class TestRouteAfterValidate:
    def test_returns_error_when_status_is_error(self):
        state = make_state(status="error", dsl_attempts=None)
        assert route_after_validate(state) == "error"

    def test_returns_ok_when_no_attempts_yet(self):
        state = make_state(status="pending", dsl_attempts=None)
        assert route_after_validate(state) == "ok"

    def test_returns_ok_when_attempts_within_limit(self):
        state = make_state(
            status="pending",
            dsl_attempts=[{"source": "llm"}],
        )
        assert route_after_validate(state) == "ok"

    def test_returns_error_when_exceeded_max_retries(self):
        state = make_state(
            status="pending",
            dsl_attempts=[
                {"source": "llm"},
                {"source": "mock"},
                {"source": "llm"},
            ],
        )
        assert route_after_validate(state) == "error"


# ---------------------------------------------------------------------------
# detect_complexity
# ---------------------------------------------------------------------------


class TestDetectComplexity:
    def test_returns_simple_when_no_dsl(self):
        state = make_state(dsl=None)
        assert detect_complexity(state) == "simple"

    def test_returns_simple_for_single_metric_single_dimension(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "simple"

    def test_returns_complex_for_multiple_metrics(self):
        dsl = DSL(
            metrics=[
                Aggregation(func="sum", field="order_amount", alias="sales_amount"),
                Aggregation(func="count", field="id", alias="order_count"),
            ],
            dimensions=["product_name"],
            data_source="orders",
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "complex"

    def test_returns_complex_for_multiple_dimensions(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name", "region", "category"],
            data_source="orders",
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "complex"

    def test_returns_complex_for_joins(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            joins=[Join(table="customer_dim", on_field="customer_id", join_type="left")],
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "complex"

    def test_returns_complex_for_many_filters(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            filters=[
                Filter(field="region", operator="=", value="华东"),
                Filter(field="channel", operator="=", value="线上"),
                Filter(field="brand", operator="=", value="Apple"),
            ],
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "complex"

    def test_returns_simple_for_few_filters(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            filters=[
                Filter(field="region", operator="=", value="华东"),
            ],
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "simple"

    def test_returns_complex_for_time_range(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
            time_range=("2024-01-01", "2024-01-31"),
        )
        state = make_state(dsl=dsl)
        assert detect_complexity(state) == "complex"

    def test_returns_complex_for_subquery_keywords(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
        )
        state = make_state(dsl=dsl, question="查询嵌套子查询的销售额")
        assert detect_complexity(state) == "complex"

    def test_returns_simple_for_basic_question(self):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name"],
            data_source="orders",
        )
        state = make_state(dsl=dsl, question="查询销售额")
        assert detect_complexity(state) == "simple"


# ---------------------------------------------------------------------------
# route_after_sandbox
# ---------------------------------------------------------------------------


class TestRouteAfterSandbox:
    def test_returns_execute_when_sandbox_passed(self):
        result = SandboxResult(passed=True, risks=[], sample_rows=[{"a": 1}])
        state = make_state(sandbox_result=result)
        assert route_after_sandbox(state) == "execute"

    def test_returns_review_when_sandbox_failed(self):
        result = SandboxResult(
            passed=False,
            risks=["预估扫描 150,000 行，超过阈值 100,000"],
            sample_rows=[],
        )
        state = make_state(sandbox_result=result)
        assert route_after_sandbox(state) == "review"

    def test_returns_execute_when_no_sandbox_result(self):
        state = make_state(sandbox_result=None)
        assert route_after_sandbox(state) == "execute"


# ---------------------------------------------------------------------------
# route_after_execute
# ---------------------------------------------------------------------------


class TestRouteAfterExecute:
    def test_returns_end_on_success(self):
        state = make_state(status="success", dsl_attempts=None)
        assert route_after_execute(state) == "end"

    def test_returns_retry_on_error_with_no_attempts(self):
        state = make_state(status="error", dsl_attempts=None)
        assert route_after_execute(state) == "retry"

    def test_returns_retry_on_error_within_retry_limit(self):
        state = make_state(
            status="error",
            dsl_attempts=[{"source": "llm"}],
        )
        assert route_after_execute(state) == "retry"

    def test_returns_end_on_error_when_exhausted(self):
        state = make_state(
            status="error",
            dsl_attempts=[
                {"source": "llm"},
                {"source": "simplified"},
            ],
        )
        assert route_after_execute(state) == "end"

    def test_returns_end_on_pending_review(self):
        state = make_state(status="pending_review")
        assert route_after_execute(state) == "end"


# ---------------------------------------------------------------------------
# route_on_error
# ---------------------------------------------------------------------------


class TestRouteOnError:
    def test_returns_end_for_permission_denied(self):
        state = make_state(error_code="PERMISSION_DENIED")
        assert route_on_error(state) == "end"

    def test_returns_end_for_unauthorized(self):
        state = make_state(error_code="UNAUTHORIZED")
        assert route_on_error(state) == "end"

    def test_returns_end_for_internal_error(self):
        state = make_state(error_code="INTERNAL_ERROR")
        assert route_on_error(state) == "end"

    def test_returns_continue_for_recoverable_error(self):
        state = make_state(error_code="VALIDATION_ERROR")
        assert route_on_error(state) == "continue"

    def test_returns_continue_when_no_error_code(self):
        state = make_state(error_code=None)
        assert route_on_error(state) == "continue"

    def test_returns_end_when_too_many_attempts(self):
        state = make_state(
            error_code="VALIDATION_ERROR",
            dsl_attempts=[
                {"source": "llm"},
                {"source": "mock"},
                {"source": "simplified"},
            ],
        )
        assert route_on_error(state) == "end"

    def test_returns_continue_when_attempts_under_limit(self):
        state = make_state(
            error_code="VALIDATION_ERROR",
            dsl_attempts=[{"source": "llm"}],
        )
        assert route_on_error(state) == "continue"
