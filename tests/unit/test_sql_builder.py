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


def test_like_prefix_match_for_indexed_high_selectivity():
    """indexed + high selectivity 列:like 编译为前缀匹配 'val%'(走索引)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from nl2dsl.optimizer.context import SemanticConfig
    from sqlalchemy import create_engine, MetaData, Table, Column, String, Date

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("order_date", Date), Column("product_name", String))
    meta.create_all(engine)

    config = SemanticConfig(
        dimensions={
            "order_date": {"column": "order_date", "type": "date", "selectivity": "high", "indexed": True},
        }
    )
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"order_date": "order_date"}, {}, {}, semantic_config=config,
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="order_date", operator="like", value="2026-07")])
    sql = builder.build(dsl)
    assert "order_date LIKE '2026-07%'" in sql
    assert "%2026-07%" not in sql


def test_like_full_match_for_unindexed_text():
    """无索引文本列:like 保持全模糊 '%val%'。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from nl2dsl.optimizer.context import SemanticConfig
    from sqlalchemy import create_engine, MetaData, Table, Column, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    config = SemanticConfig(
        dimensions={
            "product_name": {"column": "product_name", "type": "string", "selectivity": "high", "indexed": False},
        }
    )
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {}, semantic_config=config,
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="like", value="手机")])
    sql = builder.build(dsl)
    assert "product_name LIKE '%手机%'" in sql


def test_like_default_full_match_without_stats():
    """无统计信息时:like 退回当前行为 '%val%'(向后兼容)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {},
        # 不传 semantic_config
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="like", value="手机")])
    sql = builder.build(dsl)
    assert "product_name LIKE '%手机%'" in sql


def test_filter_value_type_aligned_numeric_string_to_int():
    """Integer 列收到数字字符串 '100' → 无损转 int,命中索引。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("amount", Integer))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"amount": "amount"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="amount", operator="=", value="100")])
    sql = builder.build(dsl)
    # literal_binds 内联:int 100 不带引号
    assert "amount = 100" in sql
    assert "amount = '100'" not in sql


def test_filter_value_type_aligned_number_to_str_warns():
    """String 列收到数字 123 → 显式转 str '123'(有损但显式)。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, String
    import logging

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_name", String))
    meta.create_all(engine)

    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, {"orders": {"table": "order_fact"}},
        {"product_name": "product_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Filter
    dsl = DSL(data_source="orders", filters=[Filter(field="product_name", operator="=", value=123)])
    sql = builder.build(dsl)
    assert "product_name = '123'" in sql


def test_join_reordered_small_drives_large():
    """无跨依赖时:small 表排在前(驱动),large 排在后。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_id", Integer), Column("customer_id", Integer))
    Table("product_dim", meta, Column("product_id", Integer), Column("product_name", String))
    Table("customer_dim", meta, Column("customer_id", Integer), Column("customer_name", String))
    meta.create_all(engine)

    # 两个独立 join(无跨依赖:on_field 不含 ".")
    data_sources = {
        "orders": {
            "table": "order_fact", "size": "large",
            "joins": {
                "product_dim": {"on": "product_id", "type": "left", "alias": "p"},
                "customer_dim": {"on": "customer_id", "type": "left", "alias": "c"},
            },
        },
        "product_dim": {"table": "product_dim", "size": "medium"},
        "customer_dim": {"table": "customer_dim", "size": "small"},
    }
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, data_sources,
        {"product_name": "product_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Aggregation
    # 引用两个 join 表的列(product_name + customer_name),触发两个 join
    dsl = DSL(
        data_source="orders",
        metrics=[Aggregation(func="sum", field="product_id", alias="m")],
        dimensions=["product_name", "customer_name"],
    )
    sql = builder.build(dsl)
    # customer_dim(small) 应在 product_dim(medium) 之前
    c_pos = sql.lower().find("customer_dim")
    p_pos = sql.lower().find("product_dim")
    assert c_pos != -1 and p_pos != -1
    assert c_pos < p_pos, f"small 应驱动,但 SQL 顺序: {sql}"


def test_join_not_reordered_with_cross_dependency():
    """有跨依赖(supplier_dim on p.supplier_id)时:保持依赖顺序,不重排。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("order_fact", meta, Column("product_id", Integer))
    Table("product_dim", meta, Column("product_id", Integer), Column("supplier_id", Integer))
    Table("supplier_dim", meta, Column("supplier_id", Integer), Column("supplier_name", String))
    meta.create_all(engine)

    data_sources = {
        "orders": {
            "table": "order_fact", "size": "large",
            "joins": {
                "product_dim": {"on": "product_id", "type": "left", "alias": "p"},
                "supplier_dim": {"on": "p.supplier_id", "type": "left", "alias": "s"},
            },
        },
        "product_dim": {"table": "product_dim", "size": "medium"},
        "supplier_dim": {"table": "supplier_dim", "size": "small"},
    }
    builder = SQLBuilder(
        engine, {"orders": "order_fact"}, data_sources,
        {"supplier_name": "supplier_name"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL
    dsl = DSL(data_source="orders", dimensions=["supplier_name"])
    sql = builder.build(dsl)
    # 依赖链:product_dim 必须在 supplier_dim 之前(on p.supplier_id)
    p_pos = sql.lower().find("product_dim")
    s_pos = sql.lower().find("supplier_dim")
    assert p_pos < s_pos, f"依赖链被破坏: {sql}"


def test_bank_join_reordered_small_drives_large():
    """银行域 customer_accounts: t_org_hier(small) 应排到 t_cif_base(medium) 之前。

    镜像 bank_metrics.yaml 的真实结构:t_acct_main 为主表,join t_cif_base(经
    customers data_source 注册,medium)与 t_org_hier(经 org_hierarchy data_source
    注册,small),on_field 均无 "."(无跨依赖),故按 size 重排。
    """
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("t_acct_main", meta, Column("cif_no", String), Column("mgr_emp_no", String))
    Table("t_cif_base", meta, Column("cif_no", String), Column("cust_nm", String))
    Table("t_org_hier", meta, Column("mgr_emp_no", String), Column("org_nm", String))
    meta.create_all(engine)

    data_sources = {
        "customer_accounts": {
            "table": "t_acct_main", "size": "large",
            "joins": {
                "t_cif_base": {"on": "cif_no", "type": "left", "alias": "c"},
                "t_org_hier": {"on": "mgr_emp_no", "type": "left", "alias": "o"},
            },
        },
        # t_cif_base 经 customers data_source 注册(与 bank_metrics.yaml 一致)
        "customers": {"table": "t_cif_base", "size": "medium"},
        # t_org_hier 经 org_hierarchy data_source 注册(本次新增)
        "org_hierarchy": {"table": "t_org_hier", "size": "small"},
    }
    builder = SQLBuilder(
        engine, {"customer_accounts": "t_acct_main"}, data_sources,
        {"customer_name": "cust_nm", "org_name": "org_nm"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Aggregation
    # 引用两个 join 表的列(cust_nm + org_nm),触发两个 join
    dsl = DSL(
        data_source="customer_accounts",
        metrics=[Aggregation(func="count", field="cif_no", alias="m")],
        dimensions=["customer_name", "org_name"],
    )
    sql = builder.build(dsl)
    # t_org_hier(small) 应在 t_cif_base(medium) 之前
    o_pos = sql.lower().find("t_org_hier")
    c_pos = sql.lower().find("t_cif_base")
    assert o_pos != -1 and c_pos != -1, f"join 表未出现在 SQL 中: {sql}"
    assert o_pos < c_pos, f"small 应驱动,但 SQL 顺序: {sql}"


def test_bank_join_not_reordered_without_standalone_data_source():
    """银行域:join 表未注册为独立 data_source 时,size 回退权重 3,稳定排序保持原顺序。"""
    from nl2dsl.sql_engine.builder import SQLBuilder
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String

    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    Table("t_acct_main", meta, Column("cif_no", String), Column("mgr_emp_no", String))
    Table("t_cif_base", meta, Column("cif_no", String), Column("cust_nm", String))
    Table("t_org_hier", meta, Column("mgr_emp_no", String), Column("org_nm", String))
    meta.create_all(engine)

    data_sources = {
        "customer_accounts": {
            "table": "t_acct_main", "size": "large",
            "joins": {
                "t_cif_base": {"on": "cif_no", "type": "left", "alias": "c"},
                "t_org_hier": {"on": "mgr_emp_no", "type": "left", "alias": "o"},
            },
        },
        # 仅注册 t_cif_base,t_org_hier 未注册 → size=None → 回退权重 3
        "customers": {"table": "t_cif_base", "size": "medium"},
    }
    builder = SQLBuilder(
        engine, {"customer_accounts": "t_acct_main"}, data_sources,
        {"customer_name": "cust_nm", "org_name": "org_nm"}, {}, {},
    )
    from nl2dsl.dsl.models import DSL, Aggregation
    dsl = DSL(
        data_source="customer_accounts",
        metrics=[Aggregation(func="count", field="cif_no", alias="m")],
        dimensions=["customer_name", "org_name"],
    )
    sql = builder.build(dsl)
    # t_cif_base(medium, 权重1) 应在 t_org_hier(None, 回退权重3) 之前
    c_pos = sql.lower().find("t_cif_base")
    o_pos = sql.lower().find("t_org_hier")
    assert c_pos != -1 and o_pos != -1, f"join 表未出现在 SQL 中: {sql}"
    assert c_pos < o_pos, f"未注册表应回退到权重3排后,但 SQL 顺序: {sql}"
