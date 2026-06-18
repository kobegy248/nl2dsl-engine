"""Semantic Query Optimizer — rule-engine-based DSL optimization.

Usage:
    from nl2dsl.optimizer import optimize

    optimized_dsl, report = optimize(
        dsl,
        semantic_config=semantic_config,
        user_role="analyst",
        original_question="华东区GMV",
    )
"""

from __future__ import annotations

from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.engine import RuleEngine
from nl2dsl.optimizer.normalizer import Normalizer
from nl2dsl.optimizer.report import OptimizationReport

# Import rule modules so @RuleRegistry.register executes
from nl2dsl.optimizer.rules import structural  # noqa: F401
from nl2dsl.optimizer.rules import intent  # noqa: F401
from nl2dsl.optimizer.rules import metric  # noqa: F401
from nl2dsl.optimizer.rules import dimension  # noqa: F401
from nl2dsl.optimizer.rules import filter as filter_rules  # noqa: F401
from nl2dsl.optimizer.rules import governance  # noqa: F401
from nl2dsl.optimizer.rules import planning  # noqa: F401
from nl2dsl.optimizer.rules import time  # noqa: F401
from nl2dsl.optimizer.rules import ambiguity  # noqa: F401


def optimize(
    dsl: dict,
    *,
    semantic_config: SemanticConfig,
    user_id: str | None = None,
    user_role: str | None = None,
    permission_config: dict | None = None,
    original_question: str | None = None,
    enabled_rules: list[str] | None = None,
    disabled_rules: list[str] | None = None,
    max_limit: int = 10000,
    reference_date=None,
) -> tuple[dict, OptimizationReport]:
    """Run semantic optimization on a DSL dict.

    Pipeline: Normalize → Rule Engine → (future: Canonical Resolver)

    Args:
        dsl: Raw DSL dict (LLM output).
        semantic_config: Loaded semantic layer configuration.
        user_id: Optional user identifier.
        user_role: Optional user role for permission checks.
        permission_config: Optional permission configuration dict.
        original_question: Original NL question for ambiguity/time checks.
        enabled_rules: Whitelist of error codes to run.
        disabled_rules: Blacklist of error codes to skip.
        max_limit: Maximum query limit (default 10000).

    Returns:
        (optimized_dsl_dict, OptimizationReport)
    """
    # Phase 1: Normalize
    normalizer = Normalizer()
    normalized_dsl, _normalizer_log = normalizer.normalize(dsl)

    # Phase 2: Rule Engine
    context = RuleContext(
        semantic_config=semantic_config,
        user_id=user_id,
        user_role=user_role,
        permission_config=permission_config,
        original_question=original_question,
        max_limit=max_limit,
        reference_date=reference_date,
    )

    engine = RuleEngine(context)
    optimized_dsl, report = engine.run(
        normalized_dsl,
        enabled_rules=enabled_rules,
        disabled_rules=disabled_rules,
    )

    return optimized_dsl, report
