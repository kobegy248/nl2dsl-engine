"""Tests for G001-G002 Governance rules."""

import pytest
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.rules.governance import G001_SensitiveFieldAccess, G002_MetricNotAuthorized


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def config():
    return SemanticConfig(
        metrics={
            "gmv": {"expr": "SUM(pay_amount)"},
            "profit": {"expr": "SUM(profit_amt)"},
        },
        dimensions={
            "region": {"column": "region", "type": "string"},
            "phone": {"column": "phone", "type": "string"},
        },
        data_sources={
            "orders": {"table": "order_fact", "metrics": ["gmv", "profit"], "dimensions": ["region", "phone"]},
        },
    )


class TestG001SensitiveFieldAccess:
    def test_triggers_when_sensitive_field_accessed_without_masking(self, config):
        ctx = RuleContext(
            semantic_config=config,
            user_role="analyst",
            permission_config={
                "sensitive_fields": {"phone": True, "salary": True},
                "masking_rules": {},
            },
        )
        rule = G001_SensitiveFieldAccess()
        dsl = {"data_source": "orders", "filters": [{"field": "phone", "operator": "=", "value": "138"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.is_fatal is True

    def test_allows_sensitive_field_with_masking(self, config):
        ctx = RuleContext(
            semantic_config=config,
            user_role="analyst",
            permission_config={
                "sensitive_fields": {"phone": True},
                "masking_rules": {"phone": "mask_phone"},
            },
        )
        rule = G001_SensitiveFieldAccess()
        dsl = {"data_source": "orders", "filters": [{"field": "phone", "operator": "=", "value": "138"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_does_not_trigger_when_no_permission_config(self, config):
        ctx = RuleContext(semantic_config=config)
        rule = G001_SensitiveFieldAccess()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""


class TestG002MetricNotAuthorized:
    def test_triggers_when_role_not_authorized(self, config):
        ctx = RuleContext(
            semantic_config=config,
            user_role="analyst",
            permission_config={
                "metric_permissions": {"gmv": ["manager", "admin"], "profit": ["admin"]},
            },
        )
        rule = G002_MetricNotAuthorized()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description != ""
        assert result.is_fatal is True

    def test_allows_authorized_role(self, config):
        ctx = RuleContext(
            semantic_config=config,
            user_role="manager",
            permission_config={
                "metric_permissions": {"gmv": ["manager", "admin"]},
            },
        )
        rule = G002_MetricNotAuthorized()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""

    def test_does_not_trigger_when_no_permission_config(self, config):
        ctx = RuleContext(semantic_config=config)
        rule = G002_MetricNotAuthorized()
        dsl = {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "gmv"}]}
        result = rule.check(dsl, ctx)
        assert result.description == ""
