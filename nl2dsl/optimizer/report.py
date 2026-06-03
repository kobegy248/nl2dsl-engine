"""OptimizationReport — the output of one optimization run."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from nl2dsl.optimizer.base import RuleResult


@dataclass
class OptimizationReport:
    """Complete report from one optimization run."""

    # Identity
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    query_id: str | None = None

    # Statistics
    total_rules_checked: int = 0
    total_rules_triggered: int = 0

    fixes_applied: list[dict] = field(default_factory=list)
    fixes_bypassed: list[dict] = field(default_factory=list)
    warnings_issued: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    fatal_rejection: dict | None = None

    # Metrics
    fix_rate: float = 0.0
    warning_rate: float = 0.0
    rejection_rate: float = 0.0
    fatal: bool = False

    # Performance
    elapsed_ms: int = 0
    phases: dict[str, int] = field(default_factory=dict)

    # DSL comparison
    dsl_before: dict | None = None
    dsl_after: dict | None = None
    diff: list[str] = field(default_factory=list)

    def add_result(self, result: RuleResult) -> None:
        """Classify and record a RuleResult."""
        result_dict = {
            "error_code": result.error_code,
            "category": result.category,
            "severity": result.severity,
            "confidence": result.confidence,
            "description": result.description,
            "before": result.before,
            "after": result.after,
            "location": result.location,
            "clarification_required": result.clarification_required,
            "clarification_question": result.clarification_question,
            "candidate_values": result.candidate_values,
            "applied": result.applied,
        }

        if result.severity == "Fix" and result.applied:
            self.fixes_applied.append(result_dict)
        elif result.severity == "Fix" and not result.applied:
            self.fixes_bypassed.append(result_dict)
        elif result.severity == "Warn":
            self.warnings_issued.append(result_dict)
        elif result.severity == "Reject":
            if result.is_fatal:
                self.fatal_rejection = result_dict
                self.fatal = True
            else:
                self.rejections.append(result_dict)

    def finalize(self, elapsed_ms: int, phases: dict[str, int] | None = None) -> None:
        """Compute summary metrics after all rules have run."""
        self.elapsed_ms = elapsed_ms
        if phases:
            self.phases = phases

        total = max(self.total_rules_triggered, 1)
        self.fix_rate = len(self.fixes_applied) / total
        self.warning_rate = len(self.warnings_issued) / total
        self.rejection_rate = (
            len(self.rejections) + (1 if self.fatal_rejection else 0)
        ) / total

    def compute_diff(self) -> None:
        """Generate a human-readable diff between dsl_before and dsl_after."""
        if not self.dsl_before or not self.dsl_after:
            return
        diffs = []
        for key in self.dsl_before:
            before_val = self.dsl_before.get(key)
            after_val = self.dsl_after.get(key)
            if before_val != after_val:
                diffs.append(f"{key}: {before_val!r} -> {after_val!r}")
        self.diff = diffs

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "report_id": self.report_id,
            "query_id": self.query_id,
            "total_rules_checked": self.total_rules_checked,
            "total_rules_triggered": self.total_rules_triggered,
            "fixes_applied": self.fixes_applied,
            "fixes_bypassed": self.fixes_bypassed,
            "warnings_issued": self.warnings_issued,
            "rejections": self.rejections,
            "fatal_rejection": self.fatal_rejection,
            "fix_rate": self.fix_rate,
            "warning_rate": self.warning_rate,
            "rejection_rate": self.rejection_rate,
            "fatal": self.fatal,
            "elapsed_ms": self.elapsed_ms,
            "phases": self.phases,
            "diff": self.diff,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
