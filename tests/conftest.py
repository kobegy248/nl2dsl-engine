"""Pytest fixtures for NL2DSL."""

import os

import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime


@pytest.fixture(scope="session")
def real_llm_client():
    """Create a real LLM client from environment variables.

    Tests using this fixture are skipped if NL2DSL_LLM_API_KEY is not set.
    """
    api_key = os.environ.get("NL2DSL_LLM_API_KEY", "")
    if not api_key:
        pytest.skip("NL2DSL_LLM_API_KEY not set, skipping test that requires real LLM")

    from nl2dsl.llm.client import LLMClient
    from nl2dsl.config import settings

    return LLMClient(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


@pytest.fixture
def sqlite_engine():
    """Create an in-memory SQLite engine with test data."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_name", String),
        Column("region", String),
        Column("region_code", String),
        Column("order_amount", Float),
        Column("order_date", DateTime),
    )
    metadata.create_all(engine)
    return engine


@pytest.fixture
def semantic_registry():
    """Return a test semantic registry config."""
    return {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)", "description": "销售额"},
            "gmv": {"expr": "SUM(pay_amount)", "description": "GMV"},
        },
        "dimensions": {
            "product_name": {"column": "product_name", "description": "产品名称"},
            "region": {
                "column": "region_code",
                "description": "地区",
                "value_map": {"华东": "HD", "华南": "HN", "华北": "HB"},
            },
        },
        "data_sources": {
            "orders": {"table": "order_fact", "metrics": ["sales_amount", "gmv"], "dimensions": ["product_name", "region"]},
        },
    }
