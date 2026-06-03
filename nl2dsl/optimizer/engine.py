"""RuleEngine — dispatcher, priority queue, and pipeline execution."""

from __future__ import annotations

import time
from typing import Type

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.context import RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.report import OptimizationReport


class RuleEngine:
    """Executes rules in priority order against a normalized DSL.

    Pipeline:
      1. Build priority queue from RuleRegistry
      2. For each priority level (P1→P6):
         a. Execute all rules' check() methods
         b. Collect RuleResults
         c. Apply Fixes (call fix())
         d. Check for Fatal Reject → stop if found
         e. Update DSL for next priority level
      3. Compose OptimizationReport

    Normal Reject errors (is_fatal=False) do NOT stop the pipeline
    — they are recorded and execution continues to collect more issues.
    """

    def __init__(self, context: RuleContext):
        self._context = context

    def run(
        self,
        dsl: dict,
        *,
        enabled_rules: list[str] | None = None,
        disabled_rules: list[str] | None = None,
    ) -> tuple[dict, OptimizationReport]:
        """Run the full optimization pipeline.

        Args:
            dsl: Normalized DSL dict.
            enabled_rules: If set, ONLY run these error codes (whitelist).
            disabled_rules: If set, skip these error codes (blacklist).

        Returns:
            (optimized_dsl_dict, OptimizationReport)
        """
        start_time = time.time()
        report = OptimizationReport()
        report.dsl_before = dict(dsl)  # shallow copy for diff

        current_dsl = dict(dsl)
        phases: dict[str, int] = {}

        # Build priority queue
        queue = RuleRegistry.build_priority_queue(enabled_only=True)
        report.total_rules_checked = sum(len(rules) for rules in queue.values())

        # Execute each priority level
        for priority in sorted(queue.keys()):
            phase_start = time.time()
            rules = queue[priority]

            # Filter by whitelist/blacklist
            rules = self._filter_rules(rules, enabled_rules, disabled_rules)
            if not rules:
                continue

            # Execute all rules at this priority level
            for rule_cls in rules:
                result = self._execute_rule(rule_cls, current_dsl)
                if result is None:
                    continue

                report.total_rules_triggered += 1

                # Apply fix if applicable
                if result.severity == "Fix" and rule_cls.metadata.auto_fixable:
                    try:
                        rule_instance = rule_cls()
                        current_dsl = rule_instance.fix(current_dsl, result)
                        result.applied = True
                    except Exception:
                        result.applied = False

                report.add_result(result)

                # Fatal Reject → stop immediately
                if result.is_fatal and result.severity == "Reject":
                    elapsed = int((time.time() - start_time) * 1000)
                    report.dsl_after = current_dsl
                    report.compute_diff()
                    report.finalize(elapsed, phases)
                    return current_dsl, report

            phases[f"P{priority}"] = int((time.time() - phase_start) * 1000)

        elapsed = int((time.time() - start_time) * 1000)
        report.dsl_after = current_dsl
        report.compute_diff()
        report.finalize(elapsed, phases)
        return current_dsl, report

    def _execute_rule(
        self, rule_cls: Type[BaseRule], dsl: dict
    ) -> RuleResult | None:
        """Instantiate and execute a single rule's check().

        Returns None if the rule finds no issue (empty description).
        """
        try:
            rule = rule_cls()
            result = rule.check(dsl, self._context)
            if not result.description:
                return None  # No issue found
            return result
        except Exception as exc:
            # Rule crashed → emit a warning-level result
            return RuleResult(
                error_code=rule_cls.metadata.error_code,
                category=rule_cls.metadata.category,
                severity="Warn",
                confidence="low",
                description=f"Rule execution error: {exc}",
                is_fatal=False,
            )

    @staticmethod
    def _filter_rules(
        rules: list[Type[BaseRule]],
        enabled: list[str] | None,
        disabled: list[str] | None,
    ) -> list[Type[BaseRule]]:
        """Apply whitelist/blacklist filtering."""
        if enabled is not None:
            enabled_set = set(enabled)
            return [r for r in rules if r.metadata.error_code in enabled_set]
        if disabled is not None:
            disabled_set = set(disabled)
            return [r for r in rules if r.metadata.error_code not in disabled_set]
        return rules
