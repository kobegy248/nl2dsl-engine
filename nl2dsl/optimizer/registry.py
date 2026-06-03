"""RuleRegistry — decorator-based rule registration and discovery."""

from __future__ import annotations

from typing import Type

from nl2dsl.optimizer.base import BaseRule


class RuleRegistry:
    """Central registry for all optimization rules.

    Rules register via the @RuleRegistry.register decorator.
    The registry provides filtered queries by priority, category,
    and enabled status.
    """

    _rules: dict[str, Type[BaseRule]] = {}

    @classmethod
    def register(cls, rule_class: Type[BaseRule]) -> Type[BaseRule]:
        """Decorator: register a rule class by its metadata.error_code."""
        metadata = rule_class.metadata
        cls._rules[metadata.error_code] = rule_class
        return rule_class

    @classmethod
    def get(cls, error_code: str) -> Type[BaseRule] | None:
        """Get a rule class by error code."""
        return cls._rules.get(error_code)

    @classmethod
    def get_all(cls, enabled_only: bool = True) -> list[Type[BaseRule]]:
        """Get all registered rule classes."""
        rules = list(cls._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.metadata.enabled]
        return rules

    @classmethod
    def get_by_priority(
        cls, priority: int, enabled_only: bool = True
    ) -> list[Type[BaseRule]]:
        """Get rules at a specific priority level."""
        return [
            r
            for r in cls.get_all(enabled_only)
            if r.metadata.priority == priority
        ]

    @classmethod
    def get_by_category(
        cls, category: str, enabled_only: bool = True
    ) -> list[Type[BaseRule]]:
        """Get rules in a specific category."""
        return [
            r
            for r in cls.get_all(enabled_only)
            if r.metadata.category == category
        ]

    @classmethod
    def build_priority_queue(
        cls, enabled_only: bool = True
    ) -> dict[int, list[Type[BaseRule]]]:
        """Build a priority-grouped dict {priority: [rule_classes]}.

        Groups are sorted by priority (1-6). Rules within each group
        can execute in any order (no intra-priority dependencies).
        """
        queue: dict[int, list[Type[BaseRule]]] = {}
        for rule_cls in cls.get_all(enabled_only):
            p = rule_cls.metadata.priority
            queue.setdefault(p, []).append(rule_cls)
        return dict(sorted(queue.items()))

    @classmethod
    def clear(cls) -> None:
        """Clear all registered rules. Mainly for testing."""
        cls._rules.clear()

    @classmethod
    def count(cls, enabled_only: bool = True) -> int:
        """Return the number of registered rules."""
        return len(cls.get_all(enabled_only))
