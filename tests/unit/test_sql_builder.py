import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime
from nl2dsl.dsl.models import DSL, Filter, Aggregation, OrderBy, PostProcess
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


@pytest.fixture
def builder_with_joins():
    """Builder with multi-table support for JOIN and condition tree tests."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_id", Integer),
        Column("product_name", String),
        Column("region", String),
        Column("channel", String),
        Column("pay_amount", Float),
        Column("order_amount", Float),
        Column("order_date", DateTime),
    )
    Table(
        "product_dim", metadata,
        Column("product_id", Integer, primary_key=True),
        Column("brand", String),
        Column("category", String),
    )
    metadata.create_all(engine)

    return SQLBuilder(
        engine,
        {"orders": "order_fact"},
        data_sources={
            "orders": {
                "joins": {
                    "product_dim": {
                        "on": "product_id",
                        "type": "inner",
                        "alias": "p",
                    }
                }
            }
        },
        dimension_mapping={},
    )


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


def test_post_process_query_does_not_apply_global_limit(builder):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["region", "product_name"],
        order_by=[OrderBy(field="sales_amount", direction="desc")],
        limit=1,
        data_source="orders",
        post_process=PostProcess(
            type="group_top_n",
            metric="sales_amount",
            group_by=["region"],
            top_n=1,
        ),
    )
    sql = builder.build(dsl)
    assert "LIMIT" not in sql


class TestConditionTree:
    def test_build_and_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "channel", "operator": "=", "value": "线上"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql
        assert "华东" in sql
        assert "线上" in sql
        assert "5000" in sql
        assert "AND" in sql.upper()

    def test_build_or_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "or",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "region", "operator": "=", "value": "华南"},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql
        assert "华南" in sql
        assert "OR" in sql.upper()

    def test_build_not_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [
                            {"field": "channel", "operator": "=", "value": "线下"},
                        ],
                    },
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql

    def test_build_nested_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "or",
                "children": [
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华东"},
                            {"field": "channel", "operator": "=", "value": "线上"},
                        ],
                    },
                    {
                        "op": "and",
                        "children": [
                            {"field": "region", "operator": "=", "value": "华南"},
                            {"field": "channel", "operator": "=", "value": "线下"},
                        ],
                    },
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "华东" in sql
        assert "华南" in sql
        assert "线上" in sql
        assert "线下" in sql


class TestOperators:
    def test_is_null(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="count", field="id", alias="order_count")],
            dimensions=["product_name"],
            filters=[{"field": "pay_amount", "operator": "is_null"}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "IS NULL" in sql.upper()

    def test_between_in_tree(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters={
                "op": "and",
                "children": [
                    {"field": "pay_amount", "operator": "between", "value": [5000, 20000]},
                ],
            },
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "BETWEEN" in sql.upper()
        assert "5000" in sql
        assert "20000" in sql


class TestHaving:
    def test_having_basic(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "HAVING" in sql.upper()
        assert "100000" in sql

    def test_having_with_filter(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[{"field": "region", "operator": "=", "value": "华东"}],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql.upper()
        assert "HAVING" in sql.upper()
        where_pos = sql.upper().find("WHERE")
        having_pos = sql.upper().find("HAVING")
        assert where_pos < having_pos


class TestTimeRange:
    def test_time_range_adds_where(self, builder_with_joins):
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            time_field="order_date",
            time_range=("2026-05-23", "2026-05-30"),
            data_source="orders",
        )
        sql = builder_with_joins.build(dsl)
        assert "WHERE" in sql.upper()
        assert "2026-05-23" in sql
        assert "2026-05-30" in sql
        assert "BETWEEN" in sql.upper() or "order_date" in sql.lower()


class TestMetricExprExpansion:
    """Builder must expand a registered metric from its registered expression,
    keyed by alias, ignoring the LLM's `field` guess. This keeps the builder
    correct even when SemanticResolver has not run (callers that go
    generate_dsl -> build directly). Regression for the order_amount/pay_amount
    hallucination where the LLM put a wrong physical column in `field`.
    """

    @pytest.fixture
    def builder_with_metrics(self):
        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        Table(
            "order_fact", metadata,
            Column("id", Integer, primary_key=True),
            Column("brand", String),
            Column("pay_amount", Float),
            Column("order_amount", Float),
        )
        metadata.create_all(engine)
        # sales_amount is registered as SUM(pay_amount) — NOT order_amount.
        return SQLBuilder(
            engine,
            {"orders": "order_fact"},
            data_sources={"orders": {"table": "order_fact"}},
            dimension_mapping={},
            metrics={
                "sales_amount": {"expr": "SUM(pay_amount)"},
                "gmv": {"expr": "SUM(order_amount)"},
            },
        )

    def test_registered_metric_alias_overrides_wrong_field(self, builder_with_metrics):
        """LLM hallucinated field=order_amount, but alias=sales_amount resolves
        to SUM(pay_amount). Builder must use pay_amount, not order_amount."""
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["brand"],
            data_source="orders",
        )
        sql = builder_with_metrics.build(dsl).lower()
        assert "pay_amount" in sql
        assert "order_amount" not in sql

    def test_registered_metric_works_without_resolver(self, builder_with_metrics):
        """field carries the metric name (Semantic First); builder expands it
        via the alias -> expr without needing SemanticResolver."""
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="sales_amount", alias="sales_amount")],
            dimensions=["brand"],
            data_source="orders",
        )
        sql = builder_with_metrics.build(dsl).lower()
        assert "pay_amount" in sql
        assert "order_amount" not in sql

    def test_unregistered_alias_falls_back_to_field(self, builder_with_metrics):
        """Custom alias not in registry: use the physical field as-is."""
        dsl = DSL(
            metrics=[Aggregation(func="avg", field="order_amount", alias="my_avg")],
            dimensions=["brand"],
            data_source="orders",
        )
        sql = builder_with_metrics.build(dsl).lower()
        assert "order_amount" in sql

    def test_no_metrics_registry_falls_back_to_field(self, builder_with_metrics):
        """metrics=None (legacy callers): pure field-based behavior preserved."""
        engine = create_engine("sqlite:///:memory:")
        md = MetaData()
        Table("order_fact", md, Column("id", Integer, primary_key=True), Column("order_amount", Float))
        md.create_all(engine)
        legacy = SQLBuilder(engine, {"orders": "order_fact"})
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            data_source="orders",
        )
        sql = legacy.build(dsl).lower()
        assert "order_amount" in sql


class TestValueMapTranslation:
    """SQLBuilder 必须按维度 value_map 把语义值翻译成物理编码。

    设计契约：SemanticResolver 保留语义值（如"华东"），由 SQLBuilder 负责在
    构建 WHERE 时翻译成内部编码（如"HD"），这样 region_code='HD' 才能命中
    存储编码的列。详见 resolver._map_single_value 注释。
    """

    @pytest.fixture
    def builder_with_value_map(self):
        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        Table(
            "order_fact", metadata,
            Column("id", Integer, primary_key=True),
            Column("product_name", String),
            Column("region_code", String),  # 存编码 HD/HN/HB
            Column("pay_amount", Float),
        )
        metadata.create_all(engine)
        return SQLBuilder(
            engine,
            {"orders": "order_fact"},
            dimension_mapping={"region": "region_code"},
            value_maps={
                "region": {"华东": "HD", "华南": "HN", "华北": "HB"},
            },
        )

    def test_translates_single_value_in_eq_filter(self, builder_with_value_map):
        """region='华东' -> WHERE region_code='HD'."""
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[Filter(field="region", operator="=", value="华东")],
            data_source="orders",
        )
        sql = builder_with_value_map.build(dsl)
        assert "'HD'" in sql
        assert "华东" not in sql

    def test_translates_list_values_in_in_filter(self, builder_with_value_map):
        """region in [华东,华南] -> region_code IN ('HD','HN')."""
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[Filter(field="region", operator="in", value=["华东", "华南"])],
            data_source="orders",
        )
        sql = builder_with_value_map.build(dsl)
        assert "'HD'" in sql and "'HN'" in sql
        assert "华东" not in sql and "华南" not in sql

    def test_value_not_in_map_kept_as_is(self, builder_with_value_map):
        """未在 value_map 中的值原样透传，不报错。"""
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            dimensions=["product_name"],
            filters=[Filter(field="region", operator="=", value="未知地区")],
            data_source="orders",
        )
        sql = builder_with_value_map.build(dsl)
        assert "未知地区" in sql

    def test_no_value_map_keeps_value_unchanged(self):
        """未配置 value_maps 的 builder 保持旧行为（原样使用值）。"""
        engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        Table("order_fact", metadata,
              Column("id", Integer, primary_key=True),
              Column("region", String),
              Column("pay_amount", Float))
        metadata.create_all(engine)
        legacy = SQLBuilder(engine, {"orders": "order_fact"})
        dsl = DSL(
            metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
            filters=[Filter(field="region", operator="=", value="华东")],
            data_source="orders",
        )
        sql = legacy.build(dsl)
        assert "华东" in sql
