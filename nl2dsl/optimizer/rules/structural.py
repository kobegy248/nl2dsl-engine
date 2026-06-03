"""Structural rules: S001 (Empty Query), S002 (Missing DataSource)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class S001_EmptyQuery(BaseRule):
    metadata = RuleMetadata(
        error_code="S001",
        category="Structural",
        description="DSL has no metrics and no dimensions — equivalent to SELECT *",
        priority=1,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics")
        dimensions = dsl.get("dimensions")
        if not metrics and not dimensions:
            return RuleResult.from_metadata(
                self.metadata,
                description="Both metrics and dimensions are empty — query would be SELECT *",
                before={"metrics": metrics, "dimensions": dimensions},
            )
        return RuleResult.no_issue("S001", "Structural")


@RuleRegistry.register
class S002_MissingDataSource(BaseRule):
    metadata = RuleMetadata(
        error_code="S002",
        category="Structural",
        description="DSL is missing a data_source",
        priority=1,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        if not data_source:
            return RuleResult.from_metadata(
                self.metadata,
                description="data_source is empty or missing — cannot determine query target",
                before={"data_source": data_source},
            )
        return RuleResult.no_issue("S002", "Structural")
