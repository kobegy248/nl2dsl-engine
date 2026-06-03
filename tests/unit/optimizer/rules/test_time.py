"""Tests for T001-T002 Time rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.time import T001_InvalidTimeGrain, T002_MissingTimeContext


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


class TestT001InvalidTimeGrain:
    def test_triggers_when_grain_conflicts(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = T001_InvalidTimeGrain()
        # "daily" maps to "day", "年" maps to "year" → conflict
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "daily_sales"}], "dimensions": ["年"]}
        result = rule.check(dsl, ctx)
        assert result.description != ""

    def test_does_not_trigger_without_grain_keywords(self):
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = T001_InvalidTimeGrain()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestT002MissingTimeContext:
    def test_triggers_with_comparison_keyword(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), original_question="GMV同比增长多少")
        rule = T002_MissingTimeContext()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.clarification_required is True

    def test_does_not_trigger_without_keyword(self):
        ctx = RuleContext(semantic_config=SemanticConfig(), original_question="GMV是多少")
        rule = T002_MissingTimeContext()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx)
        assert result.description == ""
