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


def _ecommerce_config() -> SemanticConfig:
    """A synthetic semantic config mirroring the real ecommerce metrics.yaml.

    Uses the boolean ``True`` key for ``on`` to mimic PyYAML's parsing of an
    unquoted ``on:`` YAML key (YAML 1.1 boolean), which is how the live config
    is actually loaded.
    """
    return SemanticConfig(
        metrics={"sales_amount": {"expr": "SUM(order_amount)"}},
        dimensions={
            "customer_name": {"column": "customer_name", "type": "string"},
            "supplier_name": {"column": "supplier_name", "type": "string"},
        },
        data_sources={
            "orders": {
                "table": "order_fact",
                "metrics": ["sales_amount"],
                "dimensions": [],
                "joins": {
                    # `on` parsed as boolean True by PyYAML
                    "product_dim": {True: "product_id", "type": "inner", "alias": "p"},
                    "customer_dim": {True: "customer_id", "type": "left", "alias": "c"},
                    # multi-hop: supplier_dim joins through product_dim's alias `p`
                    "supplier_dim": {True: "p.supplier_id", "type": "left", "alias": "s"},
                },
            },
            "customers": {"table": "customer_dim", "metrics": [], "dimensions": ["customer_name"]},
            "suppliers": {"table": "supplier_dim", "metrics": [], "dimensions": ["supplier_name"]},
        },
    )


class TestP001MissingRequiredJoin:
    def _ctx(self):
        return RuleContext(semantic_config=_ecommerce_config(), original_question="按客户名称统计销售额")

    def test_single_hop_join_injected(self):
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["customer_name"],
        }
        result = rule.check(dsl, self._ctx())
        assert result.severity == "Fix"
        injected = result.after["joins"]
        assert len(injected) == 1
        assert injected[0]["table"] == "customer_dim"
        assert injected[0]["on_field"] == "customer_id"
        assert injected[0]["join_type"] == "left"
        assert injected[0]["alias"] == "c"

    def test_fix_applies_join_to_dsl(self):
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["customer_name"],
        }
        result = rule.check(dsl, self._ctx())
        fixed = rule.fix(dsl, result)
        assert fixed["joins"][0]["table"] == "customer_dim"

    def test_multi_hop_chain_injected_in_dependency_order(self):
        # supplier_dim joins on p.supplier_id => product_dim must come first
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["supplier_name"],
        }
        result = rule.check(dsl, self._ctx())
        assert result.severity == "Fix"
        injected = result.after["joins"]
        tables = [j["table"] for j in injected]
        assert tables == ["product_dim", "supplier_dim"]
        assert injected[-1]["on_field"] == "p.supplier_id"

    def test_no_issue_when_single_source(self):
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": [],  # no cross-table dimension
        }
        result = rule.check(dsl, self._ctx())
        assert result.description == ""

    def test_no_issue_when_join_already_present(self):
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["customer_name"],
            "joins": [{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}],
        }
        result = rule.check(dsl, self._ctx())
        assert result.description == ""

    def test_warn_when_no_join_path(self):
        # supplier_name resolves to supplier_dim, but if no join declared -> Warn
        cfg = _ecommerce_config()
        # remove supplier_dim and product_dim from joins to force a no-path case
        cfg.data_sources["orders"]["joins"] = {
            "customer_dim": {True: "customer_id", "type": "left", "alias": "c"},
        }
        ctx = RuleContext(semantic_config=cfg, original_question="按供应商统计销售额")
        rule = P001_MissingRequiredJoin()
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
            "dimensions": ["supplier_name"],
        }
        result = rule.check(dsl, ctx)
        assert result.severity == "Warn"
        assert "supplier_dim" in result.candidate_values
