"""Intent rules: I001 (Unknown DataSource), I002 (DataSource-Only Metric)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class I001_UnknownDataSource(BaseRule):
    metadata = RuleMetadata(
        error_code="I001",
        category="Intent",
        description="data_source does not exist in semantic config",
        priority=1,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        if data_source and not context.semantic_config.has_data_source(data_source):
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Unknown data_source '{data_source}' — not found in semantic config",
                before={"data_source": data_source},
                location="data_source",
            )
        return RuleResult.no_issue("I001", "Intent")


@RuleRegistry.register
class I002_DataSourceOnlyMetric(BaseRule):
    """Check if any metric in the DSL has a uniquely correct data_source
    that differs from the current one. Auto-fix if unique match."""

    metadata = RuleMetadata(
        error_code="I002",
        category="Intent",
        description="Metrics only available in a different data_source — auto-correct if unique",
        priority=3,
        severity="Reject",
        confidence="medium",
        is_fatal=False,
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        metrics = dsl.get("metrics") or []
        if not metrics:
            return RuleResult.no_issue("I002", "Intent")

        # For each metric, find its data source
        source_votes: dict[str, int] = {}
        for m in metrics:
            alias = m.get("alias", "")
            if alias:
                src = context.semantic_config.find_data_source_for_metric(alias)
                if src:
                    source_votes[src] = source_votes.get(src, 0) + 1

        if not source_votes:
            return RuleResult.no_issue("I002", "Intent")

        # If all registered metrics point to the same data_source, and it differs
        unique_sources = list(source_votes.keys())
        if len(unique_sources) == 1 and unique_sources[0] != data_source:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"All metrics belong to '{unique_sources[0]}', but data_source is '{data_source}'",
                before={"data_source": data_source},
                after={"data_source": unique_sources[0]},
                location="data_source",
            )

        # If metrics point to multiple different sources → warn
        if len(unique_sources) > 1 and data_source not in unique_sources:
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Metrics span multiple data_sources: {unique_sources}. Current: '{data_source}'",
                before={"data_source": data_source},
                candidate_values=unique_sources,
            )

        return RuleResult.no_issue("I002", "Intent")
