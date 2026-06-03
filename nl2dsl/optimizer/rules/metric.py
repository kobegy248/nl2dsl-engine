"""Metric rules: M001 (Wrong AggFunc), M002 (Unregistered), M003 (Missing Alias), M004 (Mismatch)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class M001_WrongAggFunc(BaseRule):
    """Check if LLM used the wrong aggregation function for a registered metric."""

    metadata = RuleMetadata(
        error_code="M001",
        category="Metric",
        description="Wrong aggregation function for registered metric",
        priority=2,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics") or []
        for i, m in enumerate(metrics):
            alias = m.get("alias", "")
            if not alias:
                continue
            expected_func = context.semantic_config.get_metric_func(alias)
            if expected_func and m.get("func", "").lower() != expected_func:
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Aggregation function corrected: {m['func'].upper()} → {expected_func.upper()} for metric '{alias}'",
                    before={"func": m["func"]},
                    after={"func": expected_func},
                    location=f"metrics[{i}].func",
                )
        return RuleResult.no_issue("M001", "Metric")

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        if not result.location or not result.after:
            return dsl
        import copy
        dsl = copy.deepcopy(dsl)
        # Parse location: "metrics[0].func"
        parts = result.location.replace("[", ".").replace("]", "").split(".")
        target = dsl
        for part in parts[:-1]:
            target = target[int(part)] if part.isdigit() else target[part]
        final_key = parts[-1]
        target[final_key] = result.after.get(final_key, result.after)
        return dsl


@RuleRegistry.register
class M003_MissingAlias(BaseRule):
    """Check if any metric expression is missing an alias."""

    metadata = RuleMetadata(
        error_code="M003",
        category="Metric",
        description="Metric is missing an alias — HAVING/ORDER BY cannot reference it",
        priority=2,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics") or []
        for i, m in enumerate(metrics):
            if not m.get("alias"):
                func = m.get("func", "")
                field = m.get("field", "unknown")
                alias = f"{func.lower()}_{field}" if func else field
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Generated alias '{alias}' for metrics[{i}] ({func.upper()}({field}))",
                    before={"alias": None},
                    after={"alias": alias},
                    location=f"metrics[{i}].alias",
                )
        return RuleResult.no_issue("M003", "Metric")
