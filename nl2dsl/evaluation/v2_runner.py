"""V2 基准测试运行器。"""

from __future__ import annotations

import time
from typing import Any, Callable

from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown, CanonicalQuery
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.v2_runner")

# 默认权重
DEFAULT_WEIGHTS: dict[str, float] = {
    "intent": 0.20,
    "metric": 0.30,
    "filter": 0.20,
    "planner": 0.20,
    "governance": 0.10,
}


class V2BenchmarkRunner:
    """运行 V2 语义基准测试。"""

    def __init__(
        self,
        scorers: dict[str, Scorer],
        weights: dict[str, float] | None = None,
        threshold: float = 0.8,
    ):
        self.scorers = scorers
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.threshold = threshold

    def run_single(
        self,
        test_case: V2TestCase,
        actual_dsl: dict[str, Any],
        resolver: CanonicalResolver,
    ) -> dict:
        """评估单个测试用例。"""
        start = time.time()

        expected = test_case.expected
        scores = V2ScoreBreakdown()

        # 意图
        if "intent" in expected and "intent_scorer" in self.scorers:
            scores.intent = self.scorers["intent_scorer"].score(
                expected["intent"], actual_dsl.get("intent", "")
            )

        # 指标
        if "metric" in expected and "metric_scorer" in self.scorers:
            metrics = actual_dsl.get("metrics", [])
            if metrics:
                scores.metric = self.scorers["metric_scorer"].score(
                    expected["metric"],
                    metrics[0].get("alias", metrics[0].get("field", "")),
                    metrics[0].get("func"),
                )
            else:
                scores.metric = 0.0

        # 过滤条件
        if "filters" in expected and "filter_scorer" in self.scorers:
            scores.filter = self.scorers["filter_scorer"].score(
                expected["filters"], actual_dsl.get("filters", [])
            )

        # 规划器
        if "planner" in expected and "planner_scorer" in self.scorers:
            scores.planner = self.scorers["planner_scorer"].score(
                expected["planner"], self._extract_planner(actual_dsl)
            )

        # 治理
        if "governance" in expected and "governance_scorer" in self.scorers:
            scores.governance = self.scorers["governance_scorer"].score(
                expected["governance"], actual_dsl.get("governance", {})
            )

        scores.overall = scores.compute_overall(self.weights)
        passed = scores.overall >= self.threshold

        elapsed = int((time.time() - start) * 1000)

        return {
            "test_case": test_case,
            "passed": passed,
            "scores": scores,
            "actual_dsl": actual_dsl,
            "execution_time_ms": elapsed,
        }

    def _extract_planner(self, dsl: dict) -> dict:
        """从 DSL 中提取规划器信息。"""
        return {
            "dimensions": dsl.get("dimensions", []),
            "order_by": dsl.get("order_by"),
            "limit": dsl.get("limit"),
            "joins": dsl.get("joins", []),
        }

    def run_batch(
        self,
        cases: list[V2TestCase],
        api_client,
        resolver: CanonicalResolver,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        """批量运行测试用例。"""
        results: list[dict] = []
        total = len(cases)

        for i, case in enumerate(cases):
            # 调用 API 获取实际 DSL
            try:
                response = api_client.post("/api/v1/query", json={
                    "question": case.query,
                    "domain": "ecommerce",
                })
                actual_dsl = response.json().get("dsl", {})
            except Exception as exc:
                logger.error("[%s] API 调用失败：%s", case.id, exc)
                actual_dsl = {}

            result = self.run_single(case, actual_dsl, resolver)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results
