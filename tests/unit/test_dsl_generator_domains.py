"""Registry-driven RuleBasedDSLGenerator tests (P0: bank / supply_chain).

The rule generator must select data_source / metric alias / dimension from the
domain's own registry so the generated DSL is valid and executable against that
domain's schema — never inventing ecommerce metrics/dimensions for a non-
ecommerce domain (the prior hardcoding made bank/supply_chain DSL fail
validation and triggered the validate<->correct_dsl infinite recursion).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nl2dsl.dsl.generator import RuleBasedDSLGenerator
from nl2dsl.dsl.validator import DSLValidator

SAMPLES = Path(__file__).resolve().parents[2] / "nl2dsl" / "evaluation" / "samples"
DATASET = Path(__file__).resolve().parents[2] / "tests" / "evaluation" / "dataset"


def _registry(metrics_file: str) -> dict:
    reg = yaml.safe_load((SAMPLES / metrics_file).read_text(encoding="utf-8"))
    return {
        "metrics": reg.get("metrics", {}),
        "dimensions": reg.get("dimensions", {}),
        "data_sources": reg.get("data_sources", {}),
    }


def _bank() -> dict:
    return _registry("bank_metrics.yaml")


def _supply_chain() -> dict:
    return _registry("supply_chain_metrics.yaml")


# ---------------------------------------------------------------------------
# bank: actual DSL fields come from the bank registry
# ---------------------------------------------------------------------------


class TestBankRegistryDriven:
    def test_customer_count_uses_bank_registry(self):
        reg = _bank()
        dsl = RuleBasedDSLGenerator(reg).generate("查询客户数量")
        assert dsl.data_source in reg["data_sources"]
        assert all(m.alias in reg["metrics"] for m in dsl.metrics)
        assert all(d in reg["dimensions"] for d in (dsl.dimensions or []))
        # customer_count lives in the customers data_source
        assert dsl.data_source == "customers"
        assert dsl.metrics[0].alias == "customer_count"
        # Pure aggregate -> no grouping dimension
        assert dsl.dimensions in (None, [])

    def test_avg_balance_by_account_type(self):
        reg = _bank()
        dsl = RuleBasedDSLGenerator(reg).generate("各账户类型的平均余额")
        assert dsl.data_source == "customer_accounts"
        assert dsl.metrics[0].alias == "avg_balance"
        assert dsl.metrics[0].func == "avg"
        assert dsl.dimensions == ["account_type"]

    def test_multi_metric_transaction_count_and_amount(self):
        reg = _bank()
        dsl = RuleBasedDSLGenerator(reg).generate("交易笔数和交易金额")
        aliases = {m.alias for m in dsl.metrics}
        assert "txn_count" in aliases
        assert "txn_amount" in aliases
        assert dsl.data_source == "transactions"

    def test_no_ecommerce_fields_invented(self):
        reg = _bank()
        dsl = RuleBasedDSLGenerator(reg).generate("查询客户数量")
        # ecommerce metric / dimension / data_source must NOT appear
        assert dsl.data_source != "orders"
        assert all(m.alias != "sales_amount" for m in dsl.metrics)
        assert "product_name" not in (dsl.dimensions or [])

    def test_all_bank_basic_cases_validate(self):
        """Every bank basic case must produce a registry-valid DSL (no
        validation failure -> no validate<->correct_dsl infinite loop)."""
        reg = _bank()
        gen = RuleBasedDSLGenerator(reg)
        validator = DSLValidator(reg)
        cases = yaml.safe_load(
            (DATASET / "bank" / "basic.yaml").read_text(encoding="utf-8")
        )["test_cases"]
        for case in cases:
            dsl = gen.generate(case["query"])
            validator.validate(dsl)  # must not raise


# ---------------------------------------------------------------------------
# supply_chain: actual DSL fields come from the supply-chain registry
# ---------------------------------------------------------------------------


class TestSupplyChainRegistryDriven:
    def test_total_inventory_uses_supply_chain_registry(self):
        reg = _supply_chain()
        dsl = RuleBasedDSLGenerator(reg).generate("总库存量")
        assert dsl.data_source in reg["data_sources"]
        assert all(m.alias in reg["metrics"] for m in dsl.metrics)
        assert all(d in reg["dimensions"] for d in (dsl.dimensions or []))
        assert dsl.data_source == "inventory"
        assert dsl.metrics[0].alias == "inventory_qty"

    def test_purchase_by_supplier(self):
        reg = _supply_chain()
        dsl = RuleBasedDSLGenerator(reg).generate("各供应商的采购金额")
        assert dsl.data_source == "purchase"
        assert dsl.metrics[0].alias == "purchase_amount"
        assert dsl.dimensions == ["supplier_name"]

    def test_no_ecommerce_fields_invented(self):
        reg = _supply_chain()
        dsl = RuleBasedDSLGenerator(reg).generate("总库存量")
        assert dsl.data_source != "orders"
        assert all(m.alias != "sales_amount" for m in dsl.metrics)

    def test_all_supply_chain_basic_cases_validate(self):
        reg = _supply_chain()
        gen = RuleBasedDSLGenerator(reg)
        validator = DSLValidator(reg)
        cases = yaml.safe_load(
            (DATASET / "supply_chain" / "basic.yaml").read_text(encoding="utf-8")
        )["test_cases"]
        for case in cases:
            dsl = gen.generate(case["query"])
            validator.validate(dsl)  # must not raise


# ---------------------------------------------------------------------------
# ecommerce path unchanged (regression guard)
# ---------------------------------------------------------------------------


class TestEcommercePathUnchanged:
    def _eco(self):
        return _registry("metrics.yaml")

    def test_sales_keyword_still_ecommerce(self):
        dsl = RuleBasedDSLGenerator(self._eco()).generate("查询销售额")
        assert dsl.data_source == "orders"
        assert dsl.metrics[0].alias == "sales_amount"
