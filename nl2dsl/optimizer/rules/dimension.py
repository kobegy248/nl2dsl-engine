"""Dimension rules: D001 (Unregistered), D002 (Not In DataSource), D003 (Redundant)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class D003_RedundantDimension(BaseRule):
    """Check for duplicate dimensions in the dimensions list."""

    metadata = RuleMetadata(
        error_code="D003",
        category="Dimension",
        description="Duplicate dimensions detected",
        priority=2,
        severity="Fix",
        confidence="high",
        auto_fixable=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        dims = dsl.get("dimensions") or []
        if not dims:
            return RuleResult.no_issue("D003", "Dimension")

        seen = set()
        duplicates = set()
        for d in dims:
            if d in seen:
                duplicates.add(d)
            seen.add(d)

        if duplicates:
            # Simpler approach: dedup preserving order
            deduped = list(dict.fromkeys(dims))
            return RuleResult.from_metadata(
                self.metadata,
                description=f"Removed duplicate dimensions: {sorted(duplicates)}",
                before={"dimensions": dims},
                after={"dimensions": deduped},
                location="dimensions",
            )
        return RuleResult.no_issue("D003", "Dimension")

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        if not result.after:
            return dsl
        import copy
        dsl = copy.deepcopy(dsl)
        dsl["dimensions"] = result.after.get("dimensions", dsl.get("dimensions"))
        return dsl


@RuleRegistry.register
class D002_DimensionNotInDataSource(BaseRule):
    """Check if each dimension belongs to the current data_source or is joinable."""

    metadata = RuleMetadata(
        error_code="D002",
        category="Dimension",
        description="Dimension does not belong to the current data_source",
        priority=3,
        severity="Reject",
        confidence="high",
        is_fatal=False,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        if not data_source:
            return RuleResult.no_issue("D002", "Dimension")

        dims = dsl.get("dimensions") or []
        source_dims = context.semantic_config.get_dimensions_for_source(data_source)

        for i, d in enumerate(dims):
            if d in context.semantic_config.dimensions and d not in source_dims:
                correct_source = context.semantic_config.find_data_source_for_dimension(d)
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Dimension '{d}' does not belong to data_source '{data_source}'"
                                + (f" (found in '{correct_source}')" if correct_source else ""),
                    before={"data_source": data_source, "dimension": d},
                    location=f"dimensions[{i}]",
                )
        return RuleResult.no_issue("D002", "Dimension")


@RuleRegistry.register
class D001_UnregisteredDimension(BaseRule):
    """Warn when a dimension is not found in the semantic config."""

    metadata = RuleMetadata(
        error_code="D001",
        category="Dimension",
        description="Dimension is not registered in the semantic layer",
        priority=5,
        severity="Warn",
        confidence="low",
    )

    def check(self, dsl: dict, context) -> RuleResult:
        dims = dsl.get("dimensions") or []
        for i, d in enumerate(dims):
            if d and not context.semantic_config.has_dimension(d):
                candidates = [
                    name for name in context.semantic_config.dimensions
                    if d.lower() in name.lower() or name.lower() in d.lower()
                ][:5]
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Dimension '{d}' is not registered in the semantic layer",
                    location=f"dimensions[{i}]",
                    candidate_values=candidates,
                )
        return RuleResult.no_issue("D001", "Dimension")
