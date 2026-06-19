"""规划器评分器 — 维度、排序、分页、关联。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


def _as_tuple(value) -> tuple | None:
    """Normalize a time_range (list or tuple) to a comparable tuple."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return None


class PlannerScorer(Scorer):
    """对规划器方面进行评分：维度、排序、分页、关联。

    各子维度独立评分后取平均值。
    """

    def __init__(self, resolver: CanonicalResolver):
        self._resolver = resolver

    def score(self, expected: dict, actual: dict) -> float:
        """对规划器匹配进行评分。

        参数：
            expected: {"dimensions": [...], "order_by": ..., "limit": ..., "joins": [...]}
            actual: 相同结构
        """
        scores = []

        # 维度
        e_dims = set(expected.get("dimensions") or [])
        a_dims = set(actual.get("dimensions") or [])
        e_canon = {self._resolver.resolve_dimension(d) for d in e_dims}
        a_canon = {self._resolver.resolve_dimension(d) for d in a_dims}
        scores.append(1.0 if e_canon == a_canon else 0.0)

        # 分页
        e_limit = expected.get("limit")
        a_limit = actual.get("limit")
        scores.append(1.0 if e_limit == a_limit else 0.0)

        # 排序
        e_order = expected.get("order_by")
        a_order = actual.get("order_by")
        scores.append(self._score_order_by(e_order, a_order))

        # 关联
        e_joins = expected.get("joins") or []
        a_joins = actual.get("joins") or []
        scores.append(self._score_joins(e_joins, a_joins))

        # 时间范围 (Week 3): only scored when the expected case declares a
        # time_range, so non-time cases are unaffected.
        if expected.get("time_range") is not None:
            scores.append(self._score_time_range(expected, actual))

        if expected.get("post_process") is not None:
            scores.append(
                1.0
                if expected.get("post_process") == actual.get("post_process")
                else 0.0
            )

        return sum(scores) / len(scores) if scores else 1.0

    def _score_time_range(self, expected: dict, actual: dict) -> float:
        """Score time_field + time_range match (normalized to tuples)."""
        e_field = expected.get("time_field")
        a_field = actual.get("time_field")
        e_range = _as_tuple(expected.get("time_range"))
        a_range = _as_tuple(actual.get("time_range"))
        if e_field != a_field:
            return 0.0
        return 1.0 if e_range == a_range else 0.0

    def _score_order_by(self, expected, actual) -> float:
        if expected is None and actual is None:
            return 1.0
        if expected is None or actual is None:
            return 0.0
        e_field = self._resolver.resolve_dimension(expected.get("field", ""))
        a_field = self._resolver.resolve_dimension(actual.get("field", ""))
        if e_field != a_field:
            return 0.0
        # 方向：如果预期有明确方向，则必须匹配
        e_dir = expected.get("direction")
        a_dir = actual.get("direction")
        if e_dir and a_dir:
            return 1.0 if e_dir == a_dir else 0.0
        # 如果预期没有明确方向，任何方向均可
        return 1.0

    def _score_joins(self, expected: list, actual: list) -> float:
        if not expected and not actual:
            return 1.0
        if not expected or not actual:
            return 0.0
        if len(expected) != len(actual):
            return 0.0
        e_canon = set()
        for j in expected:
            cj = self._resolver.resolve_join(
                j.get("table", ""), j.get("on_field", ""), j.get("join_type", "left")
            )
            e_canon.add(f"{cj.entity}:{cj.on_field}:{cj.join_type}")
        a_canon = set()
        for j in actual:
            cj = self._resolver.resolve_join(
                j.get("table", ""), j.get("on_field", ""), j.get("join_type", "left")
            )
            a_canon.add(f"{cj.entity}:{cj.on_field}:{cj.join_type}")
        return 1.0 if e_canon == a_canon else 0.0
