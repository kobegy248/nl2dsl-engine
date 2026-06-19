"""Aggregate node: merges sub-query results based on intent type.

The aggregator combines data from multiple sub-query executions and produces
a unified result enriched with intent-specific analysis:

- compare   → diff + growth_rate between sub-query totals
- trend     → sort by time-like columns, detect direction
- correlation → Pearson correlation coefficient
- single_query → pass-through (default)
"""

from __future__ import annotations

import math
from collections import defaultdict
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
    """Collect all rows from successful or warning sub-query results.

    Injects ``__sub_query_id`` so downstream code can distinguish which
    sub-query each row came from.
    """
    rows: list[dict] = []
    for sq_id, res in results.items():
        if res.status in ("success", "warning"):
            for row in res.data:
                row_copy = dict(row)
                row_copy["__sub_query_id"] = sq_id
                rows.append(row_copy)
    return rows


def _aggregate_single(rows: list[dict]) -> dict:
    """Default pass-through aggregation."""
    return {"rows": rows}


def _aggregate_compare(rows: list[dict]) -> dict:
    """Compare aggregation: diff and growth rate between sub-query totals.

    When rows carry ``__sub_query_id`` (injected by ``_collect_rows``),
    they are grouped by that id, summed per group, and the first two
    group totals are compared.

    When no ``__sub_query_id`` is present (e.g. direct unit-test calls or
    single-query path), the function falls back to the legacy behaviour:
    compare the numeric values in the first two rows.
    """
    comparison: dict = {"diff": None, "growth_rate": "N/A"}

    if not rows:
        return {"rows": rows, "comparison": comparison}

    # Check whether rows have sub-query provenance markers
    has_provenance = any("__sub_query_id" in row for row in rows)

    if has_provenance:
        # Group rows by sub_query_id
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            sq_id = row.get("__sub_query_id", "unknown")
            groups[sq_id].append(row)

        # Sum numeric values per group
        totals: dict[str, float] = {}
        for sq_id, group_rows in groups.items():
            total = sum(
                (_find_numeric_value(r) or 0.0)
                for r in group_rows
            )
            totals[sq_id] = total

        # Include per-group totals in the result for the explainer
        comparison["totals"] = {
            sq_id: round(total, 2)
            for sq_id, total in totals.items()
        }

        # Compute diff and growth rate
        if len(totals) == 2:
            # Two-way comparison: keep legacy behaviour
            values = list(totals.values())
            first = values[0]
            second = values[1]
            comparison["diff"] = round(second - first, 2)
            if first != 0:
                growth = (second - first) / first * 100
                comparison["growth_rate"] = f"{growth:.2f}%"
            else:
                comparison["growth_rate"] = "N/A"
        elif len(totals) > 2:
            # N-way comparison: diff = max - min, growth_rate = N/A
            values_list = list(totals.values())
            comparison["diff"] = round(max(values_list) - min(values_list), 2)
            comparison["growth_rate"] = "N/A"
            # Build pairwise comparisons
            pairwise = []
            ids = list(totals.keys())
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    va, vb = totals[a], totals[b]
                    gr = f"{((vb - va) / va * 100):.2f}%" if va != 0 else "N/A"
                    pairwise.append({
                        "from": a,
                        "to": b,
                        "diff": round(vb - va, 2),
                        "growth_rate": gr,
                    })
            comparison["pairwise"] = pairwise
    else:
        # Legacy fallback: compare first two rows directly
        first = _find_numeric_value(rows[0])
        second = _find_numeric_value(rows[1]) if len(rows) >= 2 else None

        if first is not None and second is not None:
            comparison["diff"] = round(second - first, 2)
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


def _find_numeric_key(rows: list[dict]) -> str | None:
    """Find the first stable numeric result field, excluding internal keys."""
    for row in rows:
        for key, value in row.items():
            if key.startswith("__"):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return key
            if isinstance(value, str):
                try:
                    float(value)
                    return key
                except ValueError:
                    continue
    return None


def _aggregate_proportion(rows: list[dict]) -> dict:
    """Calculate grouped contribution ratios from successful result rows.

    For the configured total-plus-groups plan, prefer the sub-query containing
    the most rows as the grouped detail. The denominator is recomputed from
    those detail rows, avoiding dependence on a potentially duplicated total
    query shape.
    """
    if not rows:
        return {"rows": [], "total": 0.0}

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row.get("__sub_query_id", "sq-1")].append(row)
    def detail_score(group_rows: list[dict]) -> tuple[int, int]:
        # Prefer more rows; on ties prefer rows carrying more descriptive
        # fields (a grouped-detail row has a dimension + metric, while the
        # total row usually has only the metric).
        visible_fields = max(
            (
                sum(1 for key in row if not key.startswith("__"))
                for row in group_rows
            ),
            default=0,
        )
        return len(group_rows), visible_fields

    detail_rows = max(groups.values(), key=detail_score)

    metric_key = _find_numeric_key(detail_rows)
    if metric_key is None:
        return {"rows": detail_rows, "total": 0.0}

    values = [_find_numeric_value(row, metric_key) or 0.0 for row in detail_rows]
    total = sum(values)
    output_field = f"{metric_key}_proportion"
    enriched = []
    for row, value in zip(detail_rows, values):
        item = dict(row)
        item[output_field] = round(value / total, 6) if total else 0.0
        enriched.append(item)
    return {
        "rows": enriched,
        "total": round(total, 6),
        "metric": metric_key,
        "proportion_field": output_field,
    }


def _aggregate_ranking(rows: list[dict]) -> dict:
    """Sort ranking results by their first numeric metric descending."""
    metric_key = _find_numeric_key(rows)
    if metric_key is None:
        return {"rows": rows, "ranking_metric": None}
    ranked = sorted(
        rows,
        key=lambda row: _find_numeric_value(row, metric_key) or 0.0,
        reverse=True,
    )
    return {"rows": ranked, "ranking_metric": metric_key}


class Aggregate:
    """Result merger that combines sub-query results based on intent type."""

    _STRATEGIES: dict[str, callable] = {
        "compare": _aggregate_compare,
        "trend": _aggregate_trend,
        "correlation": _aggregate_correlation,
        "proportion": _aggregate_proportion,
        "ranking": _aggregate_ranking,
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
