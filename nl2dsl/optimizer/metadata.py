"""RuleMetadata — registration metadata for each rule."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleMetadata:
    """Registration metadata for a rule.

    Declared as a ClassVar on each BaseRule subclass.
    """

    # Identity
    error_code: str
    """Unique error code, e.g. 'M001'."""

    category: str
    """Category: Metric | Dimension | Filter | Intent | Planning | Time | Ambiguity | Governance | Structural"""

    description: str
    """Human-readable one-line description."""

    # Scheduling
    priority: int
    """1-6: P1=Block, P2=Identity, P3=Consistency, P4=Auth, P5=Completeness, P6=Ambiguity"""

    enabled: bool = True
    """Whether this rule is active. Supports A/B testing."""

    # Behavior
    auto_fixable: bool = False
    """True if the rule provides a fix() method that can auto-correct."""

    severity: str = "Warn"
    """Fix | Warn | Reject"""

    confidence: str = "medium"
    """high | medium | low"""

    is_fatal: bool = False
    """True = Fatal Reject (stop pipeline immediately). False = Normal Reject (continue collecting)."""

    # Benchmark
    benchmark_weight: float = 0.0
    """Weight in Evaluation scoring (aligned with Eval dimension weights)."""
