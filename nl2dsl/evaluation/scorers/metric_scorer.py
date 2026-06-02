"""指标评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


class MetricScorer(Scorer):
    """使用规范化解析器对指标匹配进行评分。

    预期值：metric_id 字符串
    实际值：metric_id 字符串，或 (field, func) 元组
    """

    def __init__(self, resolver: MetricResolver):
        self._resolver = resolver

    def score(self, expected: str, actual: str, func: str | None = None) -> float:
        """对指标匹配进行评分。

        参数：
            expected: 预期的 metric_id
            actual: 实际的 metric_id 或字段名
            func: 实际的聚合函数（用于反向查找）
        """
        canonical_expected = self._resolver.resolve(expected)
        canonical_actual = self._resolver.resolve(actual, func)
        return 1.0 if canonical_expected == canonical_actual else 0.0
