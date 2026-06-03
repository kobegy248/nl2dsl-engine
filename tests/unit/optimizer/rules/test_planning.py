"""Tests for P001-P004 Planning rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.planning import (
    P001_MissingRequiredJoin,
    P002_UnnecessaryJoin,
    P003_LimitExceedsMax,
    P004_OrderByNotInOutput,
)


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


class TestP003LimitExceedsMax:
    def test_triggers_when_limit_too_high(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), max_limit=1000)
        rule = P003_LimitExceedsMax()
        dsl = {"data_source": "orders", "limit": 5000}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.after["limit"] == 1000

    def test_does_not_trigger_when_limit_ok(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), max_limit=10000)
        rule = P003_LimitExceedsMax()
        dsl = {"data_source": "orders", "limit": 50}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestP004OrderByNotInOutput:
    def test_triggers_when_field_not_present(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = P004_OrderByNotInOutput()
        dsl = {"data_source": "orders", "order_by": [{"field": "missing_field", "direction": "desc"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""

    def test_does_not_trigger_when_field_in_metrics(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = P004_OrderByNotInOutput()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "amount", "alias": "total"}],
               "order_by": [{"field": "total", "direction": "asc"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""
