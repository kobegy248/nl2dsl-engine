"""BaseRule abstract class and RuleResult data class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from nl2dsl.optimizer.metadata import RuleMetadata


@dataclass
class RuleResult:
    """The result of running a single rule's check() method."""

    # Identity
    error_code: str
    category: str
    severity: str  # Fix | Warn | Reject
    confidence: str  # high | medium | low
    is_fatal: bool = False

    # Content
    description: str = ""
    before: Any | None = None
    after: Any | None = None
    location: str | None = None  # e.g. "metrics[0].func"

    # Clarification (for A001/A002/T002)
    clarification_required: bool = False
    clarification_question: str | None = None
    candidate_values: list[str] = field(default_factory=list)

    # Metadata
    applied: bool = False
    """Whether a Fix was actually applied to the DSL."""

    @classmethod
    def no_issue(cls, error_code: str, category: str) -> RuleResult:
        """Convenience factory for a 'no issue found' result."""
        return cls(
            error_code=error_code,
            category=category,
            severity="Fix",
            confidence="high",
            description="",
        )

    @classmethod
    def from_metadata(
        cls,
        metadata: RuleMetadata,
        *,
        description: str = "",
        before: Any | None = None,
        after: Any | None = None,
        location: str | None = None,
        clarification_required: bool = False,
        clarification_question: str | None = None,
        candidate_values: list[str] | None = None,
        applied: bool = False,
        confidence: str | None = None,
    ) -> RuleResult:
        """Build a RuleResult from a rule's metadata.

        Args:
            metadata: The rule's metadata descriptor.
            confidence: Optional override for the metadata's confidence level.
        """
        return cls(
            error_code=metadata.error_code,
            category=metadata.category,
            severity=metadata.severity,
            confidence=confidence if confidence is not None else metadata.confidence,
            is_fatal=metadata.is_fatal,
            description=description,
            before=before,
            after=after,
            location=location,
            clarification_required=clarification_required,
            clarification_question=clarification_question,
            candidate_values=candidate_values or [],
            applied=applied,
        )


class BaseRule(ABC):
    """Abstract base class for all optimization rules.

    Subclasses must:
      - Define `metadata` as a ClassVar[RuleMetadata]
      - Implement `check(dsl, context) -> RuleResult`
      - Optionally override `fix(dsl, result) -> dict` for auto-fixable rules
    """

    metadata: ClassVar[RuleMetadata]

    @abstractmethod
    def check(self, dsl: dict, context: Any) -> RuleResult:
        """Detect a semantic issue in the DSL.

        Args:
            dsl: The current DSL dict (normalized).
            context: RuleContext with semantic config, user info, etc.

        Returns:
            RuleResult describing the issue found, or RuleResult.no_issue().
        """
        ...

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        """Apply a correction to the DSL.

        Default implementation: if result.after is set and the rule
        targets a specific location, apply the fix.

        Override for complex fix logic.

        Args:
            dsl: The current DSL dict.
            result: The RuleResult from check() with before/after populated.

        Returns:
            Modified DSL dict.
        """
        if not self.metadata.auto_fixable:
            return dsl
        if result.after is None:
            return dsl
        return self._apply_location_fix(dsl, result)

    def _apply_location_fix(self, dsl: dict, result: RuleResult) -> dict:
        """Apply a fix at a specific location path like 'metrics[0].func'."""
        if not result.location:
            return dsl
        import copy

        dsl = copy.deepcopy(dsl)

        parts = result.location.replace("[", ".").replace("]", "").split(".")
        target = dsl
        for part in parts[:-1]:
            if part.isdigit():
                target = target[int(part)]
            else:
                target = target[part]
        final_key = parts[-1]
        if final_key.isdigit():
            target[int(final_key)] = result.after
        else:
            # If after is a dict and the final key is in it, extract just that value
            # (the location pinpoints the exact field, after describes the change)
            if isinstance(result.after, dict) and final_key in result.after:
                target[final_key] = result.after[final_key]
            else:
                target[final_key] = result.after
        return dsl
