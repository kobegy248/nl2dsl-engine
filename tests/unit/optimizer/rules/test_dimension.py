"""Tests for D001-D003 Dimension rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.dimension import D003_RedundantDimension


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def context():
    return RuleContext(semantic_config=SemanticConfig())


class TestD003RedundantDimension:
    def test_triggers_when_duplicates_exist(self, context):
        rule = D003_RedundantDimension()
        dsl = {"data_source": "orders", "dimensions": ["region", "product", "region"]}
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.severity == "Fix"
        assert "region" in result.description

    def test_does_not_trigger_when_all_unique(self, context):
        rule = D003_RedundantDimension()
        dsl = {"data_source": "orders", "dimensions": ["region", "product", "date"]}
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_does_not_trigger_when_empty_or_none(self, context):
        rule = D003_RedundantDimension()
        assert rule.check({"data_source": "orders", "dimensions": []}, context).description == ""
        assert rule.check({"data_source": "orders", "dimensions": None}, context).description == ""

    def test_fix_dedup_preserves_order(self, context):
        rule = D003_RedundantDimension()
        dsl = {"data_source": "orders", "dimensions": ["b", "a", "b", "c", "a"]}
        result = rule.check(dsl, context)
        fixed = rule.fix(dsl, result)
        assert fixed["dimensions"] == ["b", "a", "c"]

    def test_triggers_on_multiple_duplicates(self, context):
        rule = D003_RedundantDimension()
        dsl = {"data_source": "orders", "dimensions": ["x", "y", "x", "y", "x"]}
        result = rule.check(dsl, context)
        assert result.description != ""
        fixed = rule.fix(dsl, result)
        assert fixed["dimensions"] == ["x", "y"]
