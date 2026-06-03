"""Tests for RuleRegistry."""

import pytest
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure registry is clean before and after each test."""
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


def _make_rule(error_code: str, priority: int, category: str, enabled: bool = True):
    """Factory to create a minimal rule class for testing."""

    @RuleRegistry.register
    class _TestRule(BaseRule):
        metadata = RuleMetadata(
            error_code=error_code,
            category=category,
            description=f"Test rule {error_code}",
            priority=priority,
            enabled=enabled,
        )

        def check(self, dsl, context):
            return RuleResult.no_issue(error_code, category)

    return _TestRule


class TestRuleRegistryRegistration:
    def test_register_and_get(self):
        rule_cls = _make_rule("T001", priority=5, category="Time")
        assert RuleRegistry.count() == 1
        assert RuleRegistry.get("T001") is rule_cls

    def test_get_nonexistent_returns_none(self):
        assert RuleRegistry.get("NOPE") is None

    def test_multiple_registrations(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        assert RuleRegistry.count() == 3


class TestRuleRegistryFiltering:
    def test_get_by_priority(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")

        p1 = RuleRegistry.get_by_priority(1)
        assert len(p1) == 2
        assert all(r.metadata.priority == 1 for r in p1)

    def test_get_by_category(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        _make_rule("M002", priority=5, category="Metric")

        metric_rules = RuleRegistry.get_by_category("Metric")
        assert len(metric_rules) == 2

    def test_disabled_rules_excluded(self):
        _make_rule("S001", priority=1, category="Structural", enabled=True)
        _make_rule("S002", priority=1, category="Structural", enabled=False)

        assert RuleRegistry.count(enabled_only=True) == 1
        assert RuleRegistry.count(enabled_only=False) == 2


class TestRuleRegistryPriorityQueue:
    def test_build_priority_queue(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        _make_rule("A001", priority=6, category="Ambiguity")

        queue = RuleRegistry.build_priority_queue()
        assert list(queue.keys()) == [1, 2, 6]
        assert len(queue[1]) == 1
        assert len(queue[2]) == 1
        assert len(queue[6]) == 1

    def test_same_priority_grouped(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("I001", priority=1, category="Intent")

        queue = RuleRegistry.build_priority_queue()
        assert list(queue.keys()) == [1]
        assert len(queue[1]) == 3
