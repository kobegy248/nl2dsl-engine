"""Tests for F001-F005 Filter rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.filter import F002_OperatorTypeMismatch


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def config():
    return SemanticConfig(
        dimensions={
            "age": {"column": "age", "type": "integer"},
            "name": {"column": "name", "type": "string"},
            "is_active": {"column": "is_active", "type": "boolean"},
            "region": {"column": "region", "type": "string"},
        },
        data_sources={
            "orders": {"table": "orders", "metrics": [], "dimensions": ["age", "name", "is_active", "region"]},
        },
    )


@pytest.fixture
def context(config):
    return RuleContext(semantic_config=config)


class TestF002OperatorTypeMismatch:
    def test_triggers_like_on_integer(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "age", "operator": "like", "value": "%30%"}],
        }
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.severity == "Fix"
        assert "like" in result.description.lower()
        assert result.after["operator"] == "="

    def test_triggers_greater_than_on_boolean(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "is_active", "operator": ">", "value": 0}],
        }
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.after["operator"] == "="

    def test_triggers_greater_than_on_string(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "region", "operator": ">=", "value": "A"}],
        }
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.after["operator"] == "like"

    def test_does_not_trigger_equal_on_integer(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "age", "operator": "=", "value": 30}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_does_not_trigger_like_on_string(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "name", "operator": "like", "value": "%John%"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_does_not_trigger_when_field_type_unknown(self, context):
        """Unknown field types (default 'string') should not trigger F002."""
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "unknown_field", "operator": "like", "value": "x"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_handles_empty_filters(self, context):
        rule = F002_OperatorTypeMismatch()
        assert rule.check({"data_source": "orders", "filters": None}, context).description == ""
        assert rule.check({"data_source": "orders", "filters": []}, context).description == ""

    def test_location_points_to_correct_filter_index(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "age", "operator": "like", "value": "%30%"},
            ],
        }
        result = rule.check(dsl, context)
        assert "filters[1]" in result.location

    def test_fix_replaces_operator_in_dsl(self, context):
        rule = F002_OperatorTypeMismatch()
        dsl = {
            "data_source": "orders",
            "filters": [{"field": "age", "operator": "like", "value": "%30%"}],
        }
        result = rule.check(dsl, context)
        # F002 uses BaseRule's default _apply_location_fix
        fixed = rule.fix(dsl, result)
        assert fixed["filters"][0]["operator"] == "="
