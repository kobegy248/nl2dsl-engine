import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime
from nl2dsl.dsl.models import DSL, Filter, Aggregation, OrderBy
from nl2dsl.sql_engine.builder import SQLBuilder


@pytest.fixture
def builder():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_name", String),
        Column("region", String),
        Column("order_amount", Float),
        Column("order_date", DateTime),
    )
    metadata.create_all(engine)

    return SQLBuilder(engine, {"orders": "order_fact"})


def test_build_simple_select(builder):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        data_source="orders",
    )
    sql = builder.build(dsl)
    assert "SELECT" in sql
    assert "product_name" in sql
    assert "sum(" in sql.lower()
    assert "GROUP BY" in sql


def test_build_with_filter(builder):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        filters=[Filter(field="region", operator="=", value="华东")],
        data_source="orders",
    )
    sql = builder.build(dsl)
    assert "WHERE" in sql
    assert "华东" in sql


def test_build_with_order_and_limit(builder):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        order_by=[OrderBy(field="sales_amount", direction="desc")],
        limit=10,
        data_source="orders",
    )
    sql = builder.build(dsl)
    assert "ORDER BY" in sql
    assert "DESC" in sql
    assert "LIMIT" in sql
