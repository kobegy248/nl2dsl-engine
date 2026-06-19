"""Query result post-processing.

Handles cases that are hard to express in a single SQL, like
"TOP-1 per group" which would need window functions.
"""

from __future__ import annotations

from itertools import groupby
from typing import Any

from nl2dsl.dsl.models import DSL, PostProcess


def should_post_process(dsl: DSL) -> bool:
    """Check if the DSL explicitly or compatibly requires post-processing."""
    if dsl.post_process is not None:
        return True

    # Backward compatibility for the legacy implicit TOP-1 representation.
    dims = dsl.dimensions or []
    has_multiple_dims = len(dims) >= 2
    limit_is_one = dsl.limit == 1
    has_order = dsl.order_by is not None and len(dsl.order_by) > 0
    return has_multiple_dims and limit_is_one and has_order


def extract_top_per_group(
    data: list[dict[str, Any]],
    group_key: str,
    order_key: str,
    order_desc: bool = True,
) -> list[dict[str, Any]]:
    """From sorted/grouped data, take the first row per group.

    Args:
        data: Query result rows (list of dicts)
        group_key: Field name to group by (typically the first dimension)
        order_key: Field name to sort within each group
        order_desc: True for descending (highest first), False for ascending

    Returns:
        One row per unique group_key value, the one with max/min order_key.
    """
    if not data:
        return []

    def sort_key(row: dict[str, Any]) -> tuple:
        grp = row.get(group_key)
        val = row.get(order_key, 0)
        try:
            numeric_val = float(val) if val is not None else 0
        except (TypeError, ValueError):
            numeric_val = 0
        sort_val = -numeric_val if order_desc else numeric_val
        return (grp, sort_val)

    sorted_data = sorted(data, key=sort_key)

    result = []
    for _, group in groupby(sorted_data, key=lambda r: r.get(group_key)):
        result.append(next(group))

    return result


def extract_top_n_per_group(
    data: list[dict[str, Any]],
    group_keys: list[str],
    order_key: str,
    top_n: int = 1,
    order_desc: bool = True,
) -> list[dict[str, Any]]:
    """Return the top N rows inside every group."""
    if not data:
        return []

    def numeric_value(row: dict[str, Any]) -> float:
        value = row.get(order_key)
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for row in data:
        key = tuple(row.get(field) for field in group_keys)
        grouped.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for rows in grouped.values():
        ordered = sorted(rows, key=numeric_value, reverse=order_desc)
        result.extend(ordered[:top_n])
    return result


def calculate_proportion(
    data: list[dict[str, Any]],
    metric: str,
    output_field: str | None = None,
) -> list[dict[str, Any]]:
    """Add each row's contribution to the metric total.

    The derived value is a 0-1 ratio. The denominator is the sum of the
    returned grouped metric values, so the calculation remains auditable.
    """
    output = output_field or f"{metric}_proportion"
    values: list[float] = []
    for row in data:
        try:
            values.append(float(row.get(metric) or 0))
        except (TypeError, ValueError):
            values.append(0.0)

    total = sum(values)
    result = []
    for row, value in zip(data, values):
        enriched = dict(row)
        enriched[output] = round(value / total, 6) if total else 0.0
        result.append(enriched)
    return result


def apply_post_process(
    data: list[dict[str, Any]],
    spec: PostProcess,
) -> list[dict[str, Any]]:
    """Apply one validated post-processing operation."""
    if spec.type == "group_top_n":
        return extract_top_n_per_group(
            data,
            group_keys=spec.group_by or [],
            order_key=spec.metric,
            top_n=spec.top_n or 1,
            order_desc=spec.direction == "desc",
        )
    if spec.type == "proportion":
        return calculate_proportion(data, spec.metric, spec.output_field)
    return data
