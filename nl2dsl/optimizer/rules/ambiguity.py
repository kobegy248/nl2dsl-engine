"""Ambiguity rules: A001 (Ambiguous Metric), A002 (Ambiguous Dimension)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


def _fuzzy_match_names(target: str, candidates: dict[str, dict], top_n: int = 5) -> list[str]:
    """Find candidate names that fuzzy-match the target.

    Strategy:
    1. Exact match => 1 candidate only (no ambiguity)
    2. Target is substring of name, or name is substring of target
    3. At least one common word between target and description

    Returns list of matching candidate names.
    """
    target_lower = target.lower().strip()
    matches = []

    for name, cfg in candidates.items():
        name_lower = name.lower()
        desc = cfg.get("description", "").lower() if isinstance(cfg, dict) else ""

        # Exact match
        if name_lower == target_lower:
            return [name]

        # Substring match
        if target_lower in name_lower or name_lower in target_lower:
            matches.append(name)
            continue

        # Description contains target or vice versa
        if target_lower in desc:
            matches.append(name)
            continue

        # At least 2 common consecutive characters (simple heuristic)
        common = 0
        for i in range(len(target_lower) - 1):
            if target_lower[i:i+2] in name_lower:
                common += 1
        if common >= 1 and len(target_lower) >= 3:
            matches.append(name)

    # Limit results
    return matches[:top_n]


@RuleRegistry.register
class A001_AmbiguousMetric(BaseRule):
    """Detect when a metric alias could match multiple registered metrics."""

    metadata = RuleMetadata(
        error_code="A001",
        category="Ambiguity",
        description="Metric name is ambiguous -- matches multiple registered metrics",
        priority=6,
        severity="Reject",
        confidence="medium",
        is_fatal=False,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics") or []
        if not metrics:
            return RuleResult.no_issue("A001", "Ambiguity")

        registered_metrics = context.semantic_config.metrics
        if not registered_metrics:
            return RuleResult.no_issue("A001", "Ambiguity")

        for i, m in enumerate(metrics):
            alias = m.get("alias", "")
            field = m.get("field", "")
            target = alias or field
            if not target:
                continue

            # Already registered => no ambiguity
            if context.semantic_config.has_metric(target):
                continue

            # Fuzzy match
            candidates = _fuzzy_match_names(target, registered_metrics)
            if len(candidates) >= 2:
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Ambiguous metric '{target}' -- could be: {candidates}",
                    location=f"metrics[{i}].alias" if alias else f"metrics[{i}].field",
                    clarification_required=True,
                    clarification_question=f"指标 '{target}' 有歧义，您指的是哪一个？",
                    candidate_values=candidates,
                )

        return RuleResult.no_issue("A001", "Ambiguity")


@RuleRegistry.register
class A002_AmbiguousDimension(BaseRule):
    """Detect when a dimension name could match multiple registered dimensions."""

    metadata = RuleMetadata(
        error_code="A002",
        category="Ambiguity",
        description="Dimension name is ambiguous -- matches multiple registered dimensions",
        priority=6,
        severity="Reject",
        confidence="medium",
        is_fatal=False,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        dims = dsl.get("dimensions") or []
        if not dims:
            return RuleResult.no_issue("A002", "Ambiguity")

        registered_dims = context.semantic_config.dimensions
        if not registered_dims:
            return RuleResult.no_issue("A002", "Ambiguity")

        for i, d in enumerate(dims):
            if not d:
                continue

            # Already registered => no ambiguity
            if context.semantic_config.has_dimension(d):
                continue

            # Fuzzy match
            candidates = _fuzzy_match_names(d, registered_dims)
            if len(candidates) >= 2:
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Ambiguous dimension '{d}' -- could be: {candidates}",
                    location=f"dimensions[{i}]",
                    clarification_required=True,
                    clarification_question=f"维度 '{d}' 有歧义，您指的是哪一个？",
                    candidate_values=candidates,
                )

        return RuleResult.no_issue("A002", "Ambiguity")
