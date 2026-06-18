"""过滤条件评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


def _sort_key(value):
    """Sort key that tolerates mixed numeric / string between bounds.

    Numeric bounds are sorted by magnitude; non-numeric bounds fall back to
    string ordering so the sort never crashes on heterogeneous values.
    """
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


class FilterScorer(Scorer):
    """使用规范化解析器对过滤条件匹配进行评分。

    比较过滤条件的规范化表示。
    """

    def __init__(self, resolver: CanonicalResolver):
        self._resolver = resolver

    def score(self, expected: list[dict], actual: list[dict]) -> float:
        """对过滤条件匹配进行评分。

        参数：
            expected: 预期过滤条件字典列表
            actual: 实际过滤条件字典列表
        """
        e_canonical = self._canonicalize_filters(expected or [])
        a_canonical = self._canonicalize_filters(actual or [])

        if not e_canonical and not a_canonical:
            return 1.0
        if not e_canonical or not a_canonical:
            return 0.0
        if len(e_canonical) != len(a_canonical):
            return 0.0

        return 1.0 if set(e_canonical) == set(a_canonical) else 0.0

    def _canonicalize_filters(self, filters: list[dict]) -> set[str]:
        """将过滤条件列表转换为规范化字符串集合。"""
        result: set[str] = set()
        for f in filters:
            field = self._resolver.resolve_dimension(f.get("field", ""))
            op = f.get("operator", "=")
            raw_value = f.get("value")
            # Normalize `between` bounds BEFORE resolve_value (which stringifies
            # lists), so [5000, 20000] == [20000, 5000].
            if op == "between" and isinstance(raw_value, (list, tuple)) and len(raw_value) == 2:
                sorted_vals = sorted(raw_value, key=_sort_key)
                value = [
                    self._resolver.resolve_value(f.get("field", ""), v) for v in sorted_vals
                ]
            else:
                value = self._resolver.resolve_value(f.get("field", ""), raw_value)
            result.add(f"{field} {op} {value}")
        return result
