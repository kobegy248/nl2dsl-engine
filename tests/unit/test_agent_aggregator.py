"""Unit tests for the agent aggregator node."""

from __future__ import annotations

import math

import pytest

from nl2dsl.agent.aggregator import Aggregate, _find_numeric_value
from nl2dsl.agent.models import QueryResult


# ---------------------------------------------------------------------------
# _find_numeric_value
# ---------------------------------------------------------------------------


def test_find_numeric_value_with_preferred_key():
    row = {"sales": 100, "count": 50}
    assert _find_numeric_value(row, "sales") == 100


def test_find_numeric_value_fallback_to_any_numeric():
    row = {"name": "A", "count": 50}
    assert _find_numeric_value(row, "sales") == 50


def test_find_numeric_value_no_numeric():
    row = {"name": "A", "label": "B"}
    assert _find_numeric_value(row, "sales") is None


def test_find_numeric_value_empty_row():
    assert _find_numeric_value({}, "sales") is None


def test_find_numeric_value_string_number():
    row = {"sales": "123.45"}
    assert _find_numeric_value(row, "sales") == 123.45


def test_find_numeric_value_prefers_int_over_str():
    row = {"sales": 100, "other": "200"}
    assert _find_numeric_value(row, "sales") == 100


# ---------------------------------------------------------------------------
# Aggregate — single_query (default)
# ---------------------------------------------------------------------------


def test_single_query_pass_through():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"a": 1}, {"a": 2}]),
    }
    out = agg.run(results, intent="single_query")
    rows = out["rows"]
    assert len(rows) == 2
    assert rows[0]["a"] == 1
    assert rows[1]["a"] == 2
    # Rows are annotated with __sub_query_id for provenance tracking
    assert rows[0]["__sub_query_id"] == "sq-1"
    assert rows[1]["__sub_query_id"] == "sq-1"
    assert "comparison" not in out
    assert "trend" not in out
    assert "correlation" not in out


def test_single_query_empty():
    agg = Aggregate()
    results = {"sq-1": QueryResult(sub_query_id="sq-1", data=[])}
    out = agg.run(results, intent="single_query")
    assert out["rows"] == []


def test_single_query_unknown_intent_defaults():
    """Unknown intents fall back to single_query behaviour."""
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"x": 1}]),
    }
    out = agg.run(results, intent="unknown_intent")
    rows = out["rows"]
    assert len(rows) == 1
    assert rows[0]["x"] == 1
    assert rows[0]["__sub_query_id"] == "sq-1"


# ---------------------------------------------------------------------------
# Aggregate — compare
# ---------------------------------------------------------------------------


def test_compare_combines_rows():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"product": "A", "sales": 100}]),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[{"product": "B", "sales": 200}]),
    }
    out = agg.run(results, intent="compare")
    assert len(out["rows"]) == 2
    assert out["comparison"]["diff"] == 100
    assert out["comparison"]["growth_rate"] == "100.00%"


def test_compare_with_string_numbers():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"sales": "100"}]),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[{"sales": "150"}]),
    }
    out = agg.run(results, intent="compare")
    assert out["comparison"]["diff"] == 50
    assert out["comparison"]["growth_rate"] == "50.00%"


def test_compare_first_result_zero():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"sales": 0}]),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[{"sales": 50}]),
    }
    out = agg.run(results, intent="compare")
    assert out["comparison"]["diff"] == 50
    # Division by zero → growth_rate should be "N/A"
    assert out["comparison"]["growth_rate"] == "N/A"


def test_compare_only_one_result():
    """With only one sub-query there is nothing to compare against."""
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"sales": 100}]),
    }
    out = agg.run(results, intent="compare")
    assert len(out["rows"]) == 1
    # One group → no diff can be computed
    assert out["comparison"]["diff"] is None
    assert out["comparison"]["growth_rate"] == "N/A"
    # Per-group total is still reported
    assert out["comparison"]["totals"]["sq-1"] == 100.0


def test_compare_no_numeric_values():
    """When rows have no numeric values, each group totals to 0.0."""
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"name": "A"}]),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[{"name": "B"}]),
    }
    out = agg.run(results, intent="compare")
    # Two groups both sum to 0 → diff = 0.0, growth_rate = N/A (0/0)
    assert out["comparison"]["diff"] == 0.0
    assert out["comparison"]["growth_rate"] == "N/A"
    assert out["comparison"]["totals"]["sq-1"] == 0.0
    assert out["comparison"]["totals"]["sq-2"] == 0.0


def test_compare_empty_results():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[]),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[]),
    }
    out = agg.run(results, intent="compare")
    assert out["rows"] == []
    assert out["comparison"]["diff"] is None
    assert out["comparison"]["growth_rate"] == "N/A"


# ---------------------------------------------------------------------------
# Aggregate — trend
# ---------------------------------------------------------------------------


def test_trend_sorts_by_month():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"month": "2024-03", "sales": 300},
                {"month": "2024-01", "sales": 100},
                {"month": "2024-02", "sales": 200},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    # Rows should be sorted by month ascending
    months = [r["month"] for r in out["rows"]]
    assert months == ["2024-01", "2024-02", "2024-03"]


def test_trend_direction_up():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"month": "2024-01", "sales": 100},
                {"month": "2024-02", "sales": 200},
                {"month": "2024-03", "sales": 300},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    assert out["trend"] == "up"


def test_trend_direction_down():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"month": "2024-01", "sales": 300},
                {"month": "2024-02", "sales": 200},
                {"month": "2024-03", "sales": 100},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    assert out["trend"] == "down"


def test_trend_direction_flat():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"month": "2024-01", "sales": 100},
                {"month": "2024-02", "sales": 100},
                {"month": "2024-03", "sales": 100},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    assert out["trend"] == "flat"


def test_trend_direction_insufficient_data():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"month": "2024-01", "sales": 100}]),
    }
    out = agg.run(results, intent="trend")
    assert out["trend"] == "flat"


def test_trend_no_time_column():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[{"region": "A", "sales": 100}, {"region": "B", "sales": 200}],
        ),
    }
    out = agg.run(results, intent="trend")
    # No time column → rows stay as-is; numeric values exist so trend is
    # inferred from first vs last row (100 → 200 → "up")
    assert out["trend"] == "up"


def test_trend_sorts_by_date():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"date": "2024-03-15", "sales": 300},
                {"date": "2024-01-10", "sales": 100},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    dates = [r["date"] for r in out["rows"]]
    assert dates == ["2024-01-10", "2024-03-15"]


def test_trend_sorts_by_year():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"year": 2023, "sales": 100},
                {"year": 2022, "sales": 50},
                {"year": 2024, "sales": 200},
            ],
        ),
    }
    out = agg.run(results, intent="trend")
    years = [r["year"] for r in out["rows"]]
    assert years == [2022, 2023, 2024]


def test_trend_empty():
    agg = Aggregate()
    results = {"sq-1": QueryResult(sub_query_id="sq-1", data=[])}
    out = agg.run(results, intent="trend")
    assert out["rows"] == []
    assert out["trend"] == "flat"


# ---------------------------------------------------------------------------
# Aggregate — correlation
# ---------------------------------------------------------------------------


def test_correlation_pearson():
    agg = Aggregate()
    # Perfect positive correlation
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"x": 1, "y": 2},
                {"x": 2, "y": 4},
                {"x": 3, "y": 6},
                {"x": 4, "y": 8},
                {"x": 5, "y": 10},
            ],
        ),
    }
    out = agg.run(results, intent="correlation")
    assert math.isclose(out["correlation"], 1.0, abs_tol=1e-9)


def test_correlation_negative():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"x": 1, "y": 10},
                {"x": 2, "y": 8},
                {"x": 3, "y": 6},
                {"x": 4, "y": 4},
                {"x": 5, "y": 2},
            ],
        ),
    }
    out = agg.run(results, intent="correlation")
    assert math.isclose(out["correlation"], -1.0, abs_tol=1e-9)


def test_correlation_insufficient_data():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[{"x": 1, "y": 2}],
        ),
    }
    out = agg.run(results, intent="correlation")
    assert out["correlation"] is None


def test_correlation_no_numeric_pairs():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[{"name": "A", "label": "X"}, {"name": "B", "label": "Y"}],
        ),
    }
    out = agg.run(results, intent="correlation")
    assert out["correlation"] is None


def test_correlation_empty():
    agg = Aggregate()
    results = {"sq-1": QueryResult(sub_query_id="sq-1", data=[])}
    out = agg.run(results, intent="correlation")
    assert out["rows"] == []
    assert out["correlation"] is None


def test_correlation_multiple_subqueries():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"x": 1, "y": 2},
                {"x": 2, "y": 4},
            ],
        ),
        "sq-2": QueryResult(
            sub_query_id="sq-2",
            data=[
                {"x": 3, "y": 6},
                {"x": 4, "y": 8},
                {"x": 5, "y": 10},
            ],
        ),
    }
    out = agg.run(results, intent="correlation")
    assert math.isclose(out["correlation"], 1.0, abs_tol=1e-9)


def test_correlation_zero_variance():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(
            sub_query_id="sq-1",
            data=[
                {"x": 5, "y": 1},
                {"x": 5, "y": 2},
                {"x": 5, "y": 3},
            ],
        ),
    }
    out = agg.run(results, intent="correlation")
    # Zero variance in x → correlation is None
    assert out["correlation"] is None


# ---------------------------------------------------------------------------
# Aggregate — edge cases
# ---------------------------------------------------------------------------


def test_run_with_no_results():
    agg = Aggregate()
    out = agg.run({}, intent="single_query")
    assert out["rows"] == []


def test_run_skips_error_results():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[{"a": 1}], status="success"),
        "sq-2": QueryResult(sub_query_id="sq-2", data=[], status="error", error="boom"),
        "sq-3": QueryResult(sub_query_id="sq-3", data=[{"a": 2}], status="success"),
    }
    out = agg.run(results, intent="single_query")
    rows = out["rows"]
    assert len(rows) == 2
    assert rows[0]["a"] == 1
    assert rows[0]["__sub_query_id"] == "sq-1"
    assert rows[1]["a"] == 2
    assert rows[1]["__sub_query_id"] == "sq-3"


def test_run_all_error_results():
    agg = Aggregate()
    results = {
        "sq-1": QueryResult(sub_query_id="sq-1", data=[], status="error", error="boom"),
    }
    out = agg.run(results, intent="single_query")
    assert out["rows"] == []
