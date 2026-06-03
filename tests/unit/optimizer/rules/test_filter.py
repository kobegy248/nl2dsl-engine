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


class TestF001InvalidEnumValue:
    @pytest.fixture
    def f001_config(self):
        return SemanticConfig(
            dimensions={
                "region": {"column": "region", "type": "string", "value_map": {"华东": "huadong", "华南": "huanan", "华北": "huabei"}},
                "status": {"column": "status", "type": "string", "values": ["pending", "completed", "cancelled"]},
                "name": {"column": "name", "type": "string"},
            },
            data_sources={
                "orders": {"table": "order_fact", "metrics": [], "dimensions": ["region", "status", "name"]},
            },
        )

    def test_exact_match_no_trigger(self, f001_config):
        from nl2dsl.optimizer.rules.filter import F001_InvalidEnumValue
        ctx = RuleContext(semantic_config=f001_config)
        rule = F001_InvalidEnumValue()
        dsl = {"data_source": "orders", "filters": [{"field": "region", "operator": "=", "value": "华东"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_fuzzy_match_triggers_fix(self, f001_config):
        from nl2dsl.optimizer.rules.filter import F001_InvalidEnumValue
        ctx = RuleContext(semantic_config=f001_config)
        rule = F001_InvalidEnumValue()
        dsl = {"data_source": "orders", "filters": [{"field": "region", "operator": "=", "value": "华东区"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.after["value"] == "华东"

    def test_no_match_when_field_has_no_enum(self, f001_config):
        from nl2dsl.optimizer.rules.filter import F001_InvalidEnumValue
        ctx = RuleContext(semantic_config=f001_config)
        rule = F001_InvalidEnumValue()
        dsl = {"data_source": "orders", "filters": [{"field": "name", "operator": "=", "value": "anything"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_values_list_fuzzy_match(self, f001_config):
        from nl2dsl.optimizer.rules.filter import F001_InvalidEnumValue
        ctx = RuleContext(semantic_config=f001_config)
        rule = F001_InvalidEnumValue()
        dsl = {"data_source": "orders", "filters": [{"field": "status", "operator": "=", "value": "pendding"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.after["value"] == "pending"


class TestF003MissingTimeRange:
    @pytest.fixture
    def ctx(self):
        return RuleContext(semantic_config=SemanticConfig())

    def test_triggers_with_time_keyword_no_range(self, ctx):
        from nl2dsl.optimizer.rules.filter import F003_MissingTimeRange
        ctx2 = RuleContext(semantic_config=SemanticConfig(), original_question="本月GMV是多少")
        rule = F003_MissingTimeRange()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "x", "alias": "gmv"}]}
        result = rule.check(dsl, ctx2)
        assert result.description != ""

    def test_does_not_trigger_without_time_keyword(self, ctx):
        from nl2dsl.optimizer.rules.filter import F003_MissingTimeRange
        ctx2 = RuleContext(semantic_config=SemanticConfig(), original_question="GMV是多少")
        rule = F003_MissingTimeRange()
        dsl = {"data_source": "orders"}
        result = rule.check(dsl, ctx2)
        assert result.description == ""

    def test_does_not_trigger_when_time_range_exists(self, ctx):
        from nl2dsl.optimizer.rules.filter import F003_MissingTimeRange
        ctx2 = RuleContext(semantic_config=SemanticConfig(), original_question="本月GMV")
        rule = F003_MissingTimeRange()
        dsl = {"data_source": "orders", "time_range": ("2024-01-01", "2024-01-31")}
        result = rule.check(dsl, ctx2)
        assert result.description == ""


class TestF004ContradictoryFilters:
    def test_triggers_on_contradictory_equals(self):
        from nl2dsl.optimizer.rules.filter import F004_ContradictoryFilters
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = F004_ContradictoryFilters()
        dsl = {"data_source": "orders", "filters": [
            {"field": "region", "operator": "=", "value": "华东"},
            {"field": "region", "operator": "=", "value": "华南"},
        ]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.severity == "Reject"

    def test_does_not_trigger_same_value(self):
        from nl2dsl.optimizer.rules.filter import F004_ContradictoryFilters
        ctx = RuleContext(semantic_config=SemanticConfig())
        rule = F004_ContradictoryFilters()
        dsl = {"data_source": "orders", "filters": [
            {"field": "region", "operator": "=", "value": "华东"},
            {"field": "region", "operator": "=", "value": "华东"},
        ]}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestF005ValueTypeMismatch:
    def test_triggers_string_in_integer_field(self):
        from nl2dsl.optimizer.rules.filter import F005_ValueTypeMismatch
        config = SemanticConfig(dimensions={"age": {"column": "age", "type": "integer"}}, data_sources={"t": {"table": "t", "metrics": [], "dimensions": ["age"]}})
        ctx = RuleContext(semantic_config=config)
        rule = F005_ValueTypeMismatch()
        dsl = {"data_source": "t", "filters": [{"field": "age", "operator": "=", "value": "一百"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
