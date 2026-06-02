"""过滤条件评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


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
            value = self._resolver.resolve_value(f.get("field", ""), f.get("value"))
            result.add(f"{field} {op} {value}")
        return result
