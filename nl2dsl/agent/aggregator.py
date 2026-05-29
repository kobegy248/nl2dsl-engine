"""Aggregate node: merges sub-query results based on intent type.

The aggregator combines data from multiple sub-query executions and produces
a unified result enriched with intent-specific analysis:

- compare   → diff + growth_rate between first two results
- trend     → sort by time-like columns, detect direction
- correlation → Pearson correlation coefficient
- single_query → pass-through (default)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nl2dsl.utils.logger import get_logger

if TYPE_CHECKING:
    from nl2dsl.agent.models import QueryResult

logger = get_logger("agent.aggregator")

_TIME_KEYS = ("month", "date", "year", "quarter", "week", "day")


def _find_numeric_value(row: dict, prefer_key: str | None = None) -> float | None:
    """Extract a numeric value from a dict row.

    If ``prefer_key`` is provided and its value is numeric (or a string that
    can be parsed as a number), that value is returned.  Otherwise the first
    numeric value found in the row is returned.  Returns ``None`` when no
    numeric value exists.
    """
    if prefer_key is not None:
        val = row.get(prefer_key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass

    for key in row:
        val = row[key]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass
    return None


def _collect_rows(results: dict[str, "QueryResult"]) -> list[dict]:
    """Collect all rows from successful sub-query results."""
    rows: list[dict] = []
    for res in results.values():
        if res.status == "success":
            rows.extend(res.data)
    return rows


def _aggregate_single(rows: list[dict]) -> dict:
    """Default pass-through aggregation."""
    return {"rows": rows}


def _aggregate_compare(rows: list[dict]) -> dict:
    """Compare aggregation: diff and growth rate between first two results."""
    comparison: dict = {"diff": None, "growth_rate": "N/A"}

    if not rows:
        return {"rows": rows, "comparison": comparison}

    # Try to find numeric values in the first two rows
    first = _find_numeric_value(rows[0])
    second = _find_numeric_value(rows[1]) if len(rows) >= 2 else None

    if first is not None and second is not None:
        comparison["diff"] = second - first
        if first != 0:
            growth = (second - first) / first * 100
            comparison["growth_rate"] = f"{growth:.2f}%"
        else:
            comparison["growth_rate"] = "N/A"
    elif first is not None:
        comparison["diff"] = 0
        comparison["growth_rate"] = "N/A"

    return {"rows": rows, "comparison": comparison}


def _detect_time_key(row: dict) -> str | None:
    """Return the first time-like key present in the row, or None."""
    for key in _TIME_KEYS:
        if key in row:
            return key
    return None


def _aggregate_trend(rows: list[dict]) -> dict:
    """Trend aggregation: sort by time-like columns, detect direction."""
    if not rows:
        return {"rows": rows, "trend": "flat"}

    time_key = _detect_time_key(rows[0])
    if time_key is not None:
        try:
            rows = sorted(rows, key=lambda r: r.get(time_key, ""))
        except TypeError:
            # Mixed types that can't be sorted — leave as-is
            pass

    # Detect trend direction from numeric values
    numeric_vals = [_find_numeric_value(r) for r in rows]
    numeric_vals = [v for v in numeric_vals if v is not None]

    if len(numeric_vals) < 2:
        return {"rows": rows, "trend": "flat"}

    first_val = numeric_vals[0]
    last_val = numeric_vals[-1]

    if last_val > first_val:
        trend = "up"
    elif last_val < first_val:
        trend = "down"
    else:
        trend = "flat"

    return {"rows": rows, "trend": trend}


def _aggregate_correlation(rows: list[dict]) -> dict:
    """Correlation aggregation: compute Pearson correlation coefficient."""
    if len(rows) < 2:
        return {"rows": rows, "correlation": None}

    # Collect all numeric pairs from rows (rows with at least 2 numeric values)
    xs: list[float] = []
    ys: list[float] = []

    for row in rows:
        nums = []
        for val in row.values():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                nums.append(float(val))
            elif isinstance(val, str):
                try:
                    nums.append(float(val))
                except ValueError:
                    pass
        if len(nums) >= 2:
            xs.append(nums[0])
            ys.append(nums[1])

    if len(xs) < 2:
        return {"rows": rows, "correlation": None}

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    if var_x == 0 or var_y == 0:
        return {"rows": rows, "correlation": None}

    correlation = cov / math.sqrt(var_x * var_y)
    return {"rows": rows, "correlation": correlation}


class Aggregate:
    """Result merger that combines sub-query results based on intent type."""

    _STRATEGIES: dict[str, callable] = {
        "compare": _aggregate_compare,
        "trend": _aggregate_trend,
        "correlation": _aggregate_correlation,
        "single_query": _aggregate_single,
    }

    def run(self, results: dict[str, "QueryResult"], intent: str) -> dict:
        """Merge sub-query results according to the intent.

        Args:
            results: Mapping from ``sub_query_id`` to ``QueryResult``.
            intent: One of ``compare``, ``trend``, ``correlation``,
                ``single_query``, or any other string (falls back to
                ``single_query``).

        Returns:
            A dictionary with at least a ``"rows"`` key, plus intent-specific
            enrichment keys.
        """
        rows = _collect_rows(results)
        strategy = self._STRATEGIES.get(intent, _aggregate_single)
        return strategy(rows)
