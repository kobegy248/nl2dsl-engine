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
