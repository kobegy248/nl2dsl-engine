"""Pytest fixtures for NL2DSL."""

import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime


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
