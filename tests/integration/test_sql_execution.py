import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float
from nl2dsl.sql_engine.executor import SQLExecutor


@pytest.fixture
def executor():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    orders = Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_name", String),
        Column("region", String),
        Column("order_amount", Float),
    )
    metadata.create_all(engine)

    # Insert test data
    with engine.connect() as conn:
        conn.execute(orders.insert(), [
            {"product_name": "iPhone", "region": "华东", "order_amount": 1000},
            {"product_name": "iPhone", "region": "华南", "order_amount": 2000},
            {"product_name": "MacBook", "region": "华东", "order_amount": 3000},
        ])
        conn.commit()

    return SQLExecutor(engine)


def test_execute_select(executor):
    sql = "SELECT product_name, SUM(order_amount) AS sales FROM order_fact GROUP BY product_name"
    result = executor.execute(sql)
    assert len(result) == 2
    assert result[0]["product_name"] in ("iPhone", "MacBook")


def test_execute_with_params(executor):
    sql = "SELECT * FROM order_fact WHERE region = '华东'"
    result = executor.execute(sql)
    assert len(result) == 2
