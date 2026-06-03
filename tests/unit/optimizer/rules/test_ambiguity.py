"""Tests for A001-A002 Ambiguity rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.ambiguity import A001_AmbiguousMetric, A002_AmbiguousDimension


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def ambig_config():
    return SemanticConfig(
        metrics={
            "sales_amount": {"expr": "SUM(pay_amount)", "description": "Sales amount"},
            "sales_volume": {"expr": "SUM(quantity)", "description": "Sales volume"},
            "gmv": {"expr": "SUM(pay_amount)", "description": "GMV"},
        },
        dimensions={
            "region": {"column": "region", "type": "string"},
            "province": {"column": "province", "type": "string"},
        },
        data_sources={"orders": {"table": "t", "metrics": [], "dimensions": []}},
    )


class TestA001AmbiguousMetric:
    def test_triggers_when_multiple_candidates(self, ambig_config):
        ctx = RuleContext(semantic_config=ambig_config)
        rule = A001_AmbiguousMetric()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "sales"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.clarification_required is True
        assert len(result.candidate_values) >= 2

    def test_does_not_trigger_for_exact_match(self, ambig_config):
        ctx = RuleContext(semantic_config=ambig_config)
        rule = A001_AmbiguousMetric()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestA002AmbiguousDimension:
    def test_triggers_when_fuzzy_match_multiple(self, ambig_config):
        ctx = RuleContext(semantic_config=ambig_config)
        rule = A002_AmbiguousDimension()
        # "e" is a substring of both "region" and "province", triggering fuzzy match
        dsl = {"data_source": "orders", "dimensions": ["e"]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.clarification_required is True
        assert len(result.candidate_values) >= 2

    def test_does_not_trigger_for_exact_match(self, ambig_config):
        ctx = RuleContext(semantic_config=ambig_config)
        rule = A002_AmbiguousDimension()
        dsl = {"data_source": "orders", "dimensions": ["region"]}
        result = rule.check(dsl, ctx)
        assert result.description == ""
