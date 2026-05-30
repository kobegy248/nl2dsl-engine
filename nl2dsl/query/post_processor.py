"""Query result post-processing.

Handles cases that are hard to express in a single SQL, like
"TOP-1 per group" which would need window functions.
"""

from __future__ import annotations

from itertools import groupby
from typing import Any

from nl2dsl.dsl.models import DSL


def should_post_process(dsl: DSL) -> bool:
    """Check if the DSL requires post-processing.

    Trigger: dimensions >= 2 AND limit == 1 AND order_by exists.
    This typically means "top-1 per group" semantics.
    """
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
