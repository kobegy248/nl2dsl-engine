"""Integration tests for multi-domain database isolation."""

import pytest
from sqlalchemy import inspect

from nl2dsl.engine import Engine


@pytest.fixture(scope="module")
def engine():
    return Engine()


def test_both_domains_loaded(engine):
    """Both ecommerce and bank domains are discovered."""
    assert "ecommerce" in engine.domains
    assert "bank" in engine.domains


def test_ecommerce_has_order_metrics(engine):
    ctx = engine.get_domain("ecommerce")
    assert "sales_amount" in ctx.registry_dict["metrics"]
    assert "order_count" in ctx.registry_dict["metrics"]


def test_bank_has_balance_metrics(engine):
    ctx = engine.get_domain("bank")
    assert "total_balance" in ctx.registry_dict["metrics"]
    assert "available_balance" in ctx.registry_dict["metrics"]


def test_ecommerce_and_bank_use_different_databases(engine):
    """Each domain has its own database with distinct tables."""
    ecommerce_ctx = engine.get_domain("ecommerce")
    bank_ctx = engine.get_domain("bank")

    ecommerce_tables = set(inspect(ecommerce_ctx.sql_builder._engine).get_table_names())
    bank_tables = set(inspect(bank_ctx.sql_builder._engine).get_table_names())

    # Ecommerce should have order/product/customer tables
    assert "order_fact" in ecommerce_tables
    assert "product_dim" in ecommerce_tables
    assert "customer_dim" in ecommerce_tables

    # Bank should have banking tables
    assert "t_cif_base" in bank_tables
    assert "t_acct_main" in bank_tables
    assert "t_txn_dtl" in bank_tables

    # They should not overlap
    assert "order_fact" not in bank_tables
    assert "t_cif_base" not in ecommerce_tables


def test_unknown_domain_fallback(engine):
    """Unknown domain falls back to ecommerce."""
    ctx = engine.get_domain("nonexistent")
    assert ctx.domain == "ecommerce"
