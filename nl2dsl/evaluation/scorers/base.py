"""评分器抽象基类。"""

from abc import ABC, abstractmethod


class Scorer(ABC):
    """所有评分器的抽象基类。

    评分器执行二元评估：1.0（通过）或 0.0（不通过）。
    不存在部分得分。
    """

    @abstractmethod
    def score(self, expected, actual) -> float:
        """对预期值与实际值进行评分。

        参数：
            expected: 预期的规范化值
            actual: 实际的规范化值

        返回：
            匹配返回 1.0，否则返回 0.0
        """
        pass
