"""治理评分器。"""

from nl2dsl.evaluation.scorers.base import Scorer


class GovernanceScorer(Scorer):
    """对治理匹配进行评分。

    对于治理类用例，权限匹配为二元判定。
    """

    def score(self, expected: dict, actual: dict) -> float:
        """对治理匹配进行评分。

        参数：
            expected: {"permission": "allow" | "deny", ...}
            actual: {"permission": "allow" | "deny", ...}
        """
        e_perm = expected.get("permission", "allow")
        a_perm = actual.get("permission", "allow")
        return 1.0 if e_perm == a_perm else 0.0
