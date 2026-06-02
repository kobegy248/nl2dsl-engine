"""意图评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer


class IntentScorer(Scorer):
    """对意图匹配进行评分。二元：1.0（匹配）或 0.0（不匹配）。"""

    def score(self, expected: str, actual: str) -> float:
        return 1.0 if expected == actual else 0.0
