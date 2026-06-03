"""Time rules: T001 (Invalid Time Grain), T002 (Missing Time Context)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


# Time grain keywords
_GRAIN_KEYWORDS = {
    "daily": "day", "日": "day", "每天": "day", "每日": "day",
    "monthly": "month", "月": "month", "每月": "month",
    "yearly": "year", "年": "year", "每年": "year",
    "weekly": "week", "周": "week", "每周": "week",
    "hourly": "hour", "小时": "hour", "每小时": "hour",
}

# Comparison keywords for T002
_COMPARISON_KEYWORDS = [
    "同比", "环比", "去年同期", "上期", "对比", "比较",
    "增长率", "增长", "下降", "变化",
    "YoY", "MoM", "year over year", "month over month",
    "compared to", "versus", "vs",
]


@RuleRegistry.register
class T001_InvalidTimeGrain(BaseRule):
    """Warn when metric naming suggests a time grain that conflicts with dimensions."""

    metadata = RuleMetadata(
        error_code="T001",
        category="Time",
        description="Metric time grain conflicts with dimension time granularity",
        priority=5,
        severity="Warn",
        confidence="medium",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics") or []
        dims = dsl.get("dimensions") or []

        # Detect grain from metric names
        metric_grains = set()
        for m in metrics:
            alias = m.get("alias", "").lower()
            field = m.get("field", "").lower()
            combined = f"{alias} {field}"
            for keyword, grain in _GRAIN_KEYWORDS.items():
                if keyword in combined:
                    metric_grains.add(grain)

        if not metric_grains:
            return RuleResult.no_issue("T001", "Time")

        # Detect grain from dimension names
        dim_grains = set()
        for d in dims:
            d_lower = d.lower()
            for keyword, grain in _GRAIN_KEYWORDS.items():
                if keyword in d_lower:
                    dim_grains.add(grain)

        if not dim_grains:
            return RuleResult.no_issue("T001", "Time")

        # Conflict: metric grain != dimension grain
        conflicts = metric_grains - dim_grains
        if conflicts:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Metric suggests grain {metric_grains} but dimensions group by {dim_grains}",
                before={"metric_grains": list(metric_grains), "dim_grains": list(dim_grains)},
            )

        return RuleResult.no_issue("T001", "Time")


@RuleRegistry.register
class T002_MissingTimeContext(BaseRule):
    """Reject + Clarify when the question has comparison keywords but DSL lacks context."""

    metadata = RuleMetadata(
        error_code="T002",
        category="Time",
        description="Query contains comparison/time-contrast keywords but DSL lacks comparison context",
        priority=5,
        severity="Reject",
        confidence="high",
        is_fatal=False,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        question = context.original_question or ""
        if not question:
            return RuleResult.no_issue("T002", "Time")

        # Check for comparison keywords
        found_keywords = [kw for kw in _COMPARISON_KEYWORDS if kw in question]
        if not found_keywords:
            return RuleResult.no_issue("T002", "Time")

        # Check if DSL already has time_range or time_field
        has_time_context = (
            dsl.get("time_range") is not None
            or dsl.get("time_field") is not None
        )

        if not has_time_context:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Query has comparison keywords {found_keywords} but DSL lacks time context",
                clarification_required=True,
                clarification_question="请明确对比的时间基准和时间窗口。例如：与去年同期对比？环比上个月？",
                candidate_values=found_keywords,
            )

        return RuleResult.no_issue("T002", "Time")
