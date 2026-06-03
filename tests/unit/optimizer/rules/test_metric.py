"""Tests for M001-M004 Metric rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.metric import M001_WrongAggFunc, M003_MissingAlias


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def config():
    return SemanticConfig(
        metrics={
            "sales_amount": {"expr": "SUM(pay_amount)", "description": "Sales"},
            "order_count": {"expr": "COUNT(order_id)", "description": "Orders"},
        },
        data_sources={
            "orders": {"table": "order_fact", "metrics": ["sales_amount", "order_count"], "dimensions": []},
        },
    )


@pytest.fixture
def context(config):
    return RuleContext(semantic_config=config)


class TestM001WrongAggFunc:
    def test_triggers_when_func_differs(self, context):
        rule = M001_WrongAggFunc()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "avg", "field": "pay_amount", "alias": "sales_amount"}],
        }
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.severity == "Fix"
        assert result.confidence == "high"
        assert "AVG" in result.description
        assert "SUM" in result.description

    def test_does_not_trigger_when_func_matches(self, context):
        rule = M001_WrongAggFunc()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_fix_replaces_func_correctly(self, context):
        rule = M001_WrongAggFunc()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "avg", "field": "pay_amount", "alias": "sales_amount"}],
        }
        result = rule.check(dsl, context)
        fixed = rule.fix(dsl, result)
        assert fixed["metrics"][0]["func"] == "sum"

    def test_unregistered_metric_skipped(self, context):
        """Metric with unregistered alias should not trigger M001."""
        rule = M001_WrongAggFunc()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "avg", "field": "revenue", "alias": "revenue"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_skips_metric_without_alias(self, context):
        """Metric without alias has no way to look up registered config."""
        rule = M001_WrongAggFunc()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "avg", "field": "pay_amount"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""


class TestM003MissingAlias:
    def test_triggers_when_alias_missing(self, context):
        rule = M003_MissingAlias()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount"}],
        }
        result = rule.check(dsl, context)
        assert result.description != ""
        assert result.severity == "Fix"
        assert result.after["alias"] == "sum_pay_amount"

    def test_does_not_trigger_when_alias_exists(self, context):
        rule = M003_MissingAlias()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}],
        }
        result = rule.check(dsl, context)
        assert result.description == ""

    def test_generates_correct_alias_format(self, context):
        rule = M003_MissingAlias()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "COUNT", "field": "order_id"}],
        }
        result = rule.check(dsl, context)
        assert result.after["alias"] == "count_order_id"

    def test_handles_empty_metrics(self, context):
        rule = M003_MissingAlias()
        result = rule.check({"data_source": "orders", "metrics": None}, context)
        assert result.description == ""

    def test_location_points_to_correct_metric_index(self, context):
        rule = M003_MissingAlias()
        dsl = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "gmv"},
                {"func": "count", "field": "order_id"},
            ],
        }
        result = rule.check(dsl, context)
        # Second metric (index 1) lacks alias
        assert "metrics[1]" in result.location

    def test_fix_adds_alias_to_dsl(self, context):
        """M003 is auto-fixable: fix() should add the generated alias."""
        rule = M003_MissingAlias()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount"}],
        }
        result = rule.check(dsl, context)
        fixed = rule.fix(dsl, result)
        assert fixed["metrics"][0]["alias"] == "sum_pay_amount"


class TestM004MetricDataSourceMismatch:
    @pytest.fixture
    def m004_config(self):
        return SemanticConfig(
            metrics={
                "sales_amount": {"expr": "SUM(pay_amount)"},
                "gmv": {"expr": "SUM(pay_amount)"},
                "user_count": {"expr": "COUNT(user_id)"},
            },
            data_sources={
                "orders": {"table": "order_fact", "metrics": ["sales_amount", "gmv"], "dimensions": []},
                "users": {"table": "user_dim", "metrics": ["user_count"], "dimensions": []},
            },
        )

    def test_triggers_when_metric_not_in_datasource(self, m004_config):
        from nl2dsl.optimizer.rules.metric import M004_MetricDataSourceMismatch
        ctx = RuleContext(semantic_config=m004_config)
        rule = M004_MetricDataSourceMismatch()
        dsl = {"data_source": "orders", "metrics": [{"func": "count", "field": "user_id", "alias": "user_count"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.severity == "Reject"

    def test_does_not_trigger_when_metric_in_datasource(self, m004_config):
        from nl2dsl.optimizer.rules.metric import M004_MetricDataSourceMismatch
        ctx = RuleContext(semantic_config=m004_config)
        rule = M004_MetricDataSourceMismatch()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_skips_unregistered_metric(self, m004_config):
        from nl2dsl.optimizer.rules.metric import M004_MetricDataSourceMismatch
        ctx = RuleContext(semantic_config=m004_config)
        rule = M004_MetricDataSourceMismatch()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "unknown", "alias": "unregistered"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""
