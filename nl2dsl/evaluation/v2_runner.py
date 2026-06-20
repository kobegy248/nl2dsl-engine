"""V2 基准测试运行器。

Phase 0 重构：actual DSL 不再从测试用例 ``expected`` 构造，而是由
:class:`EvaluationExecutor` 调用真实查询链路产出 :class:`EvaluationObservation`，
评分器只读取 Observation 中的最终 DSL 与治理信息。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

from nl2dsl.evaluation.execution import EvaluationExecutor, EvaluationObservation
from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown
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

# 不可评分的状态：不参与准确率分子，且强制不通过。
_NON_RUNNABLE_STATUSES = {"error", "clarification", "unavailable"}


def _stable_value(value) -> str:
    """将 filter value 规范化为可哈希的稳定字符串。"""
    if isinstance(value, (list, tuple)):
        return "list:" + ",".join(str(v) for v in value)
    return f"v:{value}"


def _derive_intent(dsl: dict) -> str:
    """从真实 DSL 结构推导粗粒度意图（DSL 本身不携带 intent 字段）。

    规则生成器对所有带指标的查询都会追加默认 order_by，因此 order_by 不能
    作为 rank 的判据；仅 ``post_process.group_top_n`` 视为 rank。

    - post_process.group_top_n → rank
    - 其余（含 proportion、普通聚合、纯排序 TopN）→ aggregate
    """
    post = dsl.get("post_process")
    if isinstance(post, dict) and post.get("type") == "group_top_n":
        return "rank"
    return "aggregate"


class V2BenchmarkRunner:
    """运行 V2 语义基准测试。

    actual DSL 必须来自真实查询链路（:class:`EvaluationExecutor`），
    严禁从 ``expected`` 构造。
    """

    def __init__(
        self,
        scorers: dict[str, Scorer],
        weights: dict[str, float] | None = None,
        threshold: float = 0.8,
        injected_filters: list[dict] | None = None,
    ):
        self.scorers = scorers
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.threshold = threshold
        # 治理注入的过滤条件（tenant_id + 行级权限），评分前从 actual DSL 剥离。
        self.injected_filters = injected_filters or []

    def run_single(
        self,
        test_case: V2TestCase,
        actual_dsl: dict[str, Any],
        resolver: CanonicalResolver,
        injected_filters: list[dict] | None = None,
    ) -> dict:
        """评估单个测试用例（给定 actual DSL）。

        保留该方法用于直接评分场景；生产评测路径应使用
        :meth:`run_matrix` + :meth:`score_observation`。
        """
        start = time.time()

        expected = test_case.expected
        scores = V2ScoreBreakdown()
        active_dimensions: set[str] = set()

        # 评分前剥离治理注入的过滤条件（tenant_id / 行级权限），避免把权限
        # 注入误判为语义过滤偏差。仅处理 flat list 形式；条件树不剥离。
        filters_to_strip = injected_filters if injected_filters is not None else self.injected_filters
        actual_dsl = self._strip_injected_filters(actual_dsl, filters_to_strip)

        # 意图：真实 DSL 不携带 intent 字段，按结构推导（group_top_n / 排序 → rank，
        # proportion / 聚合 → aggregate）。
        if "intent" in expected and "intent_scorer" in self.scorers:
            scores.intent = self.scorers["intent_scorer"].score(
                expected["intent"], _derive_intent(actual_dsl)
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
            "post_process": dsl.get("post_process"),
        }

    def _strip_injected_filters(self, dsl: dict, injected_filters: list[dict] | None = None) -> dict:
        """剥离治理注入的过滤条件（不修改原 dict）。

        注入过滤器以规范化签名匹配（field + operator + value）。
        条件树（dict with op+children）不剥离，返回原样。
        """
        filters_to_strip = injected_filters if injected_filters is not None else self.injected_filters
        if not filters_to_strip:
            return dsl
        filters = dsl.get("filters")
        if not isinstance(filters, list):
            return dsl

        def _sig(f: dict) -> tuple:
            return (f.get("field", ""), f.get("operator", "="), _stable_value(f.get("value")))

        injected_sigs = {_sig(f) for f in filters_to_strip}
        kept = [f for f in filters if isinstance(f, dict) and _sig(f) not in injected_sigs]
        new_dsl = dict(dsl)
        new_dsl["filters"] = kept
        return new_dsl

    # ------------------------------------------------------------------
    # 真实评测路径（Phase 0+）
    # ------------------------------------------------------------------

    def score_observation(
        self,
        case: V2TestCase,
        observation: EvaluationObservation,
        resolver: CanonicalResolver,
    ) -> dict:
        """根据真实 Observation 评分。

        - 不可评分状态（error/clarification/unavailable）：分数全 0、不通过，
          但不崩溃。
        - success/warning：使用最终 DSL 走 :meth:`run_single`。
        """
        if observation.status in _NON_RUNNABLE_STATUSES:
            scores = V2ScoreBreakdown()  # 全 0
            result = {
                "test_case": case,
                "passed": False,
                "scores": scores,
                "actual_dsl": observation.final_dsl,
                "execution_time_ms": observation.execution_time_ms,
                "status": observation.status,
            }
        else:
            result = self.run_single(
                case, observation.final_dsl, resolver,
                injected_filters=observation.injected_filters,
            )
            result["status"] = observation.status

        result["observation"] = observation.to_dict()
        result["generator_mode"] = observation.generator_mode
        result["optimizer_enabled"] = observation.optimizer_enabled
        result["domain"] = observation.domain
        result["optimizer"] = self._extract_optimizer_stats(observation)
        return result

    @staticmethod
    def _extract_optimizer_stats(observation: EvaluationObservation) -> dict | None:
        """从 Trace 的 optimize_dsl 步骤提取 Optimizer 统计。

        Optimizer 关闭时 Trace 不含该步骤，返回 None。
        """
        for step in observation.trace or []:
            if not isinstance(step, dict):
                continue
            if step.get("step") == "optimize_dsl":
                return {
                    "fixes_applied": step.get("fixes_applied", 0),
                    "warnings_issued": step.get("warnings", 0),
                    "rejections": step.get("rejections", 0),
                    "elapsed_ms": step.get("elapsed_ms", 0),
                    "status": step.get("status"),
                }
        return None

    def run_matrix(
        self,
        cases: list[V2TestCase],
        executor: EvaluationExecutor,
        resolver: CanonicalResolver,
        *,
        generator_mode: str,
        optimizer_enabled: bool,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        """对单个矩阵组合（generator × optimizer）批量运行真实评测。"""
        results: list[dict] = []
        total = len(cases)

        for i, case in enumerate(cases):
            try:
                observation = executor.execute(
                    case,
                    generator_mode=generator_mode,
                    optimizer_enabled=optimizer_enabled,
                )
            except Exception as exc:
                logger.error("[%s] 执行器异常：%s", case.id, exc)
                observation = EvaluationObservation(
                    case_id=case.id,
                    domain=getattr(case, "domain", "ecommerce"),
                    generator_mode=generator_mode,
                    optimizer_enabled=optimizer_enabled,
                    status="error",
                    error=str(exc),
                )

            result = self.score_observation(case, observation, resolver)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results
