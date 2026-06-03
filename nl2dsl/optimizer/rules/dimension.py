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
