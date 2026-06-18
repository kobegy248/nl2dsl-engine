"""Tests for the optimize_dsl node's trace detail (Item 5, Week 3).

Verifies that the full optimizer report detail (fixes/warnings/rejections/diff)
is attached to the trace, not just counts — so JOIN injection, time injection,
and clarification signals are visible in the audit trace.
"""

import importlib
from datetime import date

import pytest

from nl2dsl.dsl.models import DSL
from nl2dsl.graph.nodes import _make_optimize_dsl_node
from nl2dsl.optimizer.context import SemanticConfig
from nl2dsl.optimizer.rules import (
    structural,
    intent,
    metric,
    dimension,
    filter as filter_rules,
    governance,
    planning,
    time,
    ambiguity,
)


@pytest.fixture(autouse=True)
def _full_rule_registry():
    """Ensure the global RuleRegistry is fully populated.

    Other rule test modules use an autouse ``clear_registry`` fixture that
    wipes the registry after their tests; when this file runs later in the
    suite, the registry would be empty and ``optimize()`` would apply no rules.
    Reloading the rule modules re-runs the ``@RuleRegistry.register``
    decorators and repopulates it.
    """
    for mod in (structural, intent, metric, dimension, filter_rules, governance, planning, time, ambiguity):
        importlib.reload(mod)
    yield


def _config() -> SemanticConfig:
    return SemanticConfig(
        metrics={"sales_amount": {"expr": "SUM(order_amount)"}},
        dimensions={
            "order_date": {"column": "order_date", "type": "date"},
            "supplier_name": {"column": "supplier_name", "type": "string"},
        },
        data_sources={
            "orders": {
                "table": "order_fact",
                "metrics": ["sales_amount"],
                "dimensions": ["order_date"],
                "joins": {
                    "product_dim": {True: "product_id", "type": "inner", "alias": "p"},
                    "supplier_dim": {True: "p.supplier_id", "type": "left", "alias": "s"},
                },
            },
            "suppliers": {"table": "supplier_dim", "metrics": [], "dimensions": ["supplier_name"]},
        },
    )


def _state(question: str, dsl_dict: dict) -> dict:
    return {
        "question": question,
        "original_question": question,
        "dsl": DSL.model_validate(dsl_dict),
        "reference_date": date(2026, 6, 18),
    }


def test_trace_carries_full_fix_detail_for_join_and_time():
    node = _make_optimize_dsl_node(_config())
    dsl = {
        "data_source": "orders",
        "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
        "dimensions": ["supplier_name"],
        "limit": 100,
    }
    result = node(_state("本月按供应商统计销售额", dsl))
    trace = result["trace"]

    assert trace["step"] == "optimize_dsl"
    assert trace["status"] == "success"
    assert "report_id" in trace

    # Full fix list (not just a count) with per-fix detail.
    fixes = trace["fixes"]
    codes = {f["error_code"] for f in fixes}
    assert "P001" in codes  # join injection
    assert "T003" in codes  # time injection
    p001 = next(f for f in fixes if f["error_code"] == "P001")
    assert p001["after"] is not None  # before/after present
    assert p001["location"] == "joins"

    # Diff summarizes changed fields.
    diff_text = " ".join(trace["diff"])
    assert "time_range" in diff_text
    assert "joins" in diff_text

    # The optimized DSL reflects both injections.
    out = result["dsl"]
    assert out.time_range == ("2026-06-01", "2026-06-30")
    assert [j.table for j in out.joins] == ["product_dim", "supplier_dim"]


def test_trace_carries_warning_detail_when_only_vague_time():
    node = _make_optimize_dsl_node(_config())
    dsl = {
        "data_source": "orders",
        "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
        "dimensions": ["order_date"],
        "limit": 100,
    }
    result = node(_state("近期销售额", dsl))
    trace = result["trace"]
    # F003 warns on vague time; T003 yields (unresolvable).
    warning_codes = [w["error_code"] for w in trace["warnings_detail"]]
    assert "F003" in warning_codes
    # No fix applied for the vague case.
    assert all(f["error_code"] != "T003" for f in trace["fixes"])


def test_trace_skipped_when_no_dsl():
    node = _make_optimize_dsl_node(_config())
    result = node({"question": "x", "original_question": "x", "dsl": None})
    assert result["trace"]["status"] == "skipped"
