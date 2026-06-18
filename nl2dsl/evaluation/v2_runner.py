"""V2 基准测试运行器。"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown, CanonicalQuery
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.base import Scorer
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.v2_runner")

# Pinned reference date for deterministic relative-time evaluation (本月/最近7天).
# Test cases encode absolute dates against this date.
_EVAL_REFERENCE_DATE = date(2026, 6, 18)

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
        # 跟踪哪些维度被实际评分了（用于动态权重调整）
        active_dimensions: set[str] = set()

        # 意图
        if "intent" in expected and "intent_scorer" in self.scorers:
            scores.intent = self.scorers["intent_scorer"].score(
                expected["intent"], actual_dsl.get("intent", "")
            )
            active_dimensions.add("intent")
        else:
            scores.intent = 1.0  # N/A → pass

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
            active_dimensions.add("metric")
        else:
            scores.metric = 1.0  # N/A → pass

        # 过滤条件
        if "filters" in expected and "filter_scorer" in self.scorers:
            scores.filter = self.scorers["filter_scorer"].score(
                expected["filters"], actual_dsl.get("filters", [])
            )
            active_dimensions.add("filter")
        else:
            scores.filter = 1.0  # N/A → pass

        # 规划器
        if "planner" in expected and "planner_scorer" in self.scorers:
            scores.planner = self.scorers["planner_scorer"].score(
                expected["planner"], self._extract_planner(actual_dsl)
            )
            active_dimensions.add("planner")
        else:
            scores.planner = 1.0  # N/A → pass

        # 治理
        if "governance" in expected and "governance_scorer" in self.scorers:
            scores.governance = self.scorers["governance_scorer"].score(
                expected["governance"], actual_dsl.get("governance", {})
            )
            active_dimensions.add("governance")
        else:
            scores.governance = 1.0  # N/A → pass

        # 动态权重：仅用参与评分的维度计算总分
        if active_dimensions:
            active_weights = {k: v for k, v in self.weights.items() if k in active_dimensions}
            total_weight = sum(active_weights.values())
            if total_weight > 0:
                # 归一化
                active_weights = {k: v / total_weight for k, v in active_weights.items()}
            scores.overall = scores.compute_overall(active_weights)
        else:
            scores.overall = 1.0

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
            "time_field": dsl.get("time_field"),
            "time_range": dsl.get("time_range"),
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

    def run_batch_with_optimizer(
        self,
        cases: list[V2TestCase],
        config: dict,
        resolver: CanonicalResolver,
        *,
        use_optimizer: bool = False,
        enabled_rules: list[str] | None = None,
        disabled_rules: list[str] | None = None,
        verbose_optimizer: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        """批量运行测试用例，可选启用 Semantic Optimizer。"""
        from nl2dsl.optimizer import optimize
        from nl2dsl.optimizer.context import SemanticConfig

        semantic_config = SemanticConfig.from_registry_dict(config) if use_optimizer else None
        results: list[dict] = []
        total = len(cases)

        for i, case in enumerate(cases):
            # Build a mock DSL from the test case's expected values for scoring
            actual_dsl = self._build_dsl_from_case(case)

            optimizer_report = None
            if use_optimizer and semantic_config:
                optimized_dsl, opt_report = optimize(
                    actual_dsl,
                    semantic_config=semantic_config,
                    original_question=case.query,
                    enabled_rules=enabled_rules,
                    disabled_rules=disabled_rules,
                    reference_date=_EVAL_REFERENCE_DATE,
                )
                actual_dsl = optimized_dsl
                optimizer_report = opt_report

            result = self.run_single(case, actual_dsl, resolver)
            if optimizer_report:
                result["optimizer"] = optimizer_report.to_dict() if verbose_optimizer else {
                    "fixes_applied": len(optimizer_report.fixes_applied),
                    "warnings_issued": len(optimizer_report.warnings_issued),
                    "rejections": len(optimizer_report.rejections),
                    "fix_rate": optimizer_report.fix_rate,
                    "elapsed_ms": optimizer_report.elapsed_ms,
                }
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results

    def _build_dsl_from_case(self, case: V2TestCase) -> dict:
        """从测试用例的预期值构建一个可用于评分和优化的 DSL dict。"""
        expected = case.expected
        # data_source: ecommerce cases target the "orders" source so the
        # optimizer (T003/P001) can resolve time fields and JOINs. intent may
        # be a plain string ("aggregate"), so default safely.
        intent = expected.get("intent")
        if isinstance(intent, dict):
            data_source = intent.get("data_source", "orders")
        else:
            data_source = "orders"
        dsl: dict = {"data_source": data_source}

        # Metric (may be a string alias like "sales_amount" or a dict)
        metric_info = expected.get("metric")
        if metric_info:
            if isinstance(metric_info, dict):
                dsl["metrics"] = [{
                    "func": metric_info.get("func", "sum"),
                    "field": metric_info.get("field", metric_info.get("alias", "")),
                    "alias": metric_info.get("alias", ""),
                }]
            else:
                dsl["metrics"] = [{"func": "sum", "field": "order_amount", "alias": metric_info}]

        # Dimensions
        if "dimensions" in expected:
            dsl["dimensions"] = expected["dimensions"]

        # Filters
        filters_info = expected.get("filters", [])
        if filters_info:
            dsl["filters"] = []
            for f in filters_info:
                if isinstance(f, dict):
                    dsl["filters"].append({
                        "field": f.get("field", ""),
                        "operator": f.get("operator", "="),
                        "value": f.get("value"),
                    })

        # Planner info
        planner_info = expected.get("planner", {})
        if planner_info:
            if "limit" in planner_info:
                dsl["limit"] = planner_info["limit"]
            if "order_by" in planner_info:
                dsl["order_by"] = planner_info["order_by"]
            if "joins" in planner_info:
                dsl["joins"] = planner_info["joins"]
            if "time_field" in planner_info:
                dsl["time_field"] = planner_info["time_field"]
            if "time_range" in planner_info:
                dsl["time_range"] = planner_info["time_range"]

        return dsl
