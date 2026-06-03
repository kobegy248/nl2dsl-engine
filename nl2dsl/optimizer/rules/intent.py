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
