"""Integration tests for governed advanced-analysis post-processing."""

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine

from nl2dsl.dsl.models import Aggregation, DSL, OrderBy, PostProcess
from nl2dsl.query.post_processor import apply_post_process
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.executor import SQLExecutor


def _services():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    orders = Table(
        "order_fact",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("category", String),
        Column("product_name", String),
        Column("order_amount", Float),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            orders.insert(),
            [
                {"category": "手机", "product_name": "A", "order_amount": 100},
                {"category": "手机", "product_name": "A", "order_amount": 50},
                {"category": "手机", "product_name": "B", "order_amount": 80},
                {"category": "电脑", "product_name": "C", "order_amount": 200},
                {"category": "电脑", "product_name": "D", "order_amount": 120},
            ],
        )
    return (
        SQLBuilder(engine, {"orders": "order_fact"}),
        SQLExecutor(engine),
    )


def test_group_top_n_end_to_end():
    builder, executor = _services()
    dsl = DSL(
        data_source="orders",
        metrics=[
            Aggregation(func="sum", field="order_amount", alias="sales_amount")
        ],
        dimensions=["category", "product_name"],
        order_by=[OrderBy(field="sales_amount", direction="desc")],
        limit=1,
        post_process=PostProcess(
            type="group_top_n",
            metric="sales_amount",
            group_by=["category"],
            top_n=1,
        ),
    )

    sql = builder.build(dsl)
    assert "LIMIT" not in sql
    result = apply_post_process(executor.execute(sql), dsl.post_process)

    assert {(row["category"], row["product_name"]) for row in result} == {
        ("手机", "A"),
        ("电脑", "C"),
    }


def test_proportion_end_to_end():
    builder, executor = _services()
    dsl = DSL(
        data_source="orders",
        metrics=[
            Aggregation(func="sum", field="order_amount", alias="sales_amount")
        ],
        dimensions=["category"],
        post_process=PostProcess(
            type="proportion",
            metric="sales_amount",
            output_field="sales_share",
        ),
    )

    result = apply_post_process(executor.execute(builder.build(dsl)), dsl.post_process)
    shares = {row["category"]: row["sales_share"] for row in result}

    assert round(sum(shares.values()), 6) == 1.0
    assert shares["电脑"] > shares["手机"]
