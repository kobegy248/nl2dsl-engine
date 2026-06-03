"""Tests for I001 Intent rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.intent import I001_UnknownDataSource


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def config():
    return SemanticConfig(
        data_sources={
            "orders": {"table": "order_fact", "metrics": [], "dimensions": []},
        }
    )


@pytest.fixture
def context(config):
    return RuleContext(semantic_config=config)


class TestI001UnknownDataSource:
    def test_triggers_when_data_source_unknown(self, context):
        rule = I001_UnknownDataSource()
        result = rule.check({"data_source": "nonexistent"}, context)
        assert result.description != ""
        assert result.severity == "Reject"
        assert result.is_fatal is True
        assert "nonexistent" in result.description

    def test_does_not_trigger_when_data_source_exists(self, context):
        rule = I001_UnknownDataSource()
        result = rule.check({"data_source": "orders"}, context)
        assert result.description == ""

    def test_does_not_trigger_when_data_source_empty(self, context):
        """Empty data_source is handled by S002, not I001."""
        rule = I001_UnknownDataSource()
        result = rule.check({"data_source": ""}, context)
        assert result.description == ""

    def test_triggers_with_correct_location(self, context):
        rule = I001_UnknownDataSource()
        result = rule.check({"data_source": "fake_db"}, context)
        assert result.location == "data_source"


class TestI002DataSourceOnlyMetric:
    @pytest.fixture
    def i002_config(self):
        return SemanticConfig(
            metrics={
                "sales_amount": {"expr": "SUM(pay_amount)"},
                "gmv": {"expr": "SUM(pay_amount)"},
            },
            data_sources={
                "orders": {"table": "order_fact", "metrics": ["sales_amount", "gmv"], "dimensions": []},
                "products": {"table": "product_dim", "metrics": [], "dimensions": []},
            },
        )

    def test_triggers_when_all_metrics_in_different_source(self, i002_config):
        from nl2dsl.optimizer.rules.intent import I002_DataSourceOnlyMetric
        ctx = RuleContext(semantic_config=i002_config)
        rule = I002_DataSourceOnlyMetric()
        dsl = {"data_source": "products", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.after["data_source"] == "orders"

    def test_does_not_trigger_when_source_matches(self, i002_config):
        from nl2dsl.optimizer.rules.intent import I002_DataSourceOnlyMetric
        ctx = RuleContext(semantic_config=i002_config)
        rule = I002_DataSourceOnlyMetric()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_does_not_trigger_with_empty_metrics(self, i002_config):
        from nl2dsl.optimizer.rules.intent import I002_DataSourceOnlyMetric
        ctx = RuleContext(semantic_config=i002_config)
        rule = I002_DataSourceOnlyMetric()
        result = rule.check({"data_source": "products", "metrics": None}, ctx)
        assert result.description == ""
