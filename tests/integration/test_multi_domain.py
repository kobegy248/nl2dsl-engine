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

    # Verify they use different database engines (different SQLite files)
    ecommerce_url = str(ecommerce_ctx.sql_builder._engine.url)
    bank_url = str(bank_ctx.sql_builder._engine.url)
    assert ecommerce_url != bank_url
    assert "nl2dsl.db" in ecommerce_url
    assert "bank.db" in bank_url

    ecommerce_tables = set(inspect(ecommerce_ctx.sql_builder._engine).get_table_names())
    bank_tables = set(inspect(bank_ctx.sql_builder._engine).get_table_names())

    # They should not overlap (each domain has its own schema)
    assert "order_fact" not in bank_tables
    assert "t_cif_base" not in ecommerce_tables


def test_unknown_domain_fallback(engine):
    """Unknown domain falls back to ecommerce."""
    ctx = engine.get_domain("nonexistent")
    assert ctx.domain == "ecommerce"
