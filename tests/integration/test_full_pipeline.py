import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float

from nl2dsl.dsl.builder import DSLBuilder
from nl2dsl.semantic.registry import SemanticRegistry
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.sql_engine.builder import SQLBuilder
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.sql_engine.executor import SQLExecutor
from nl2dsl.sql_engine.dialect import DialectConverter


@pytest.fixture
def pipeline():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_name", String),
        Column("region", String),
        Column("region_code", String),
        Column("order_amount", Float),
        Column("tenant_id", String),
    )
    metadata.create_all(engine)

    table = metadata.tables["order_fact"]
    with engine.connect() as conn:
        conn.execute(table.insert(), [
            {"product_name": "iPhone", "region": "华东", "region_code": "HD", "order_amount": 1000, "tenant_id": "t001"},
            {"product_name": "iPhone", "region": "华南", "region_code": "HN", "order_amount": 2000, "tenant_id": "t001"},
            {"product_name": "MacBook", "region": "华东", "region_code": "HD", "order_amount": 3000, "tenant_id": "t001"},
            {"product_name": "iPad", "region": "华北", "region_code": "HB", "order_amount": 1500, "tenant_id": "t002"},
        ])
        conn.commit()

    registry = {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)"},
        },
        "dimensions": {
            "product_name": {"column": "product_name"},
            "region": {
                "column": "region_code",
                "value_map": {"华东": "HD", "华南": "HN", "华北": "HB"},
            },
        },
        "data_sources": {
            "orders": {"table": "order_fact"},
        },
    }

    return {"engine": engine, "registry": registry}


def test_full_pipeline(pipeline):
    """DSL -> resolve -> build SQL -> scan -> execute."""
    engine = pipeline["engine"]
    registry = pipeline["registry"]

    dsl = (
        DSLBuilder("orders")
        .metric("sum", "order_amount", "sales_amount")
        .dimension("product_name")
        .build()
    )

    resolver = SemanticResolver(registry)
    resolved = resolver.resolve(dsl)
    assert resolved.metrics[0].field == "SUM(order_amount)"

    builder = SQLBuilder(engine, {"orders": "order_fact"})
    sql = builder.build(resolved)
    assert "SELECT" in sql
    assert "SUM(order_amount)" in sql

    scanner = SQLScanner()
    scanner.scan(sql)

    executor = SQLExecutor(engine)
    result = executor.execute(sql)
    assert len(result) == 3  # iPhone, MacBook, iPad (GROUP BY product_name)


def test_pipeline_with_value_map_filter(pipeline):
    """value_map: 华东 -> HD."""
    engine = pipeline["engine"]
    registry = pipeline["registry"]

    dsl = (
        DSLBuilder("orders")
        .metric("sum", "order_amount", "sales_amount")
        .dimension("product_name")
        .filter("region", "=", "华东")
        .build()
    )

    resolver = SemanticResolver(registry)
    resolved = resolver.resolve(dsl)
    assert resolved.filters[0].value == "HD"
    assert resolved.filters[0].field == "region_code"

    builder = SQLBuilder(engine, {"orders": "order_fact"})
    sql = builder.build(resolved)

    executor = SQLExecutor(engine)
    result = executor.execute(sql)
    assert len(result) == 2  # iPhone, MacBook in 华东


def test_pipeline_with_row_level_security(pipeline):
    """RLS injects region filter."""
    engine = pipeline["engine"]
    registry = pipeline["registry"]

    dsl = (
        DSLBuilder("orders")
        .metric("sum", "order_amount", "sales_amount")
        .dimension("product_name")
        .build()
    )

    rls = RowLevelSecurity({
        "u001": {"row_filters": {"region": {"operator": "=", "value": "华东"}}}
    })
    dsl_with_rls = rls.inject(dsl, "u001")
    assert len(dsl_with_rls.filters) == 1

    resolver = SemanticResolver(registry)
    resolved = resolver.resolve(dsl_with_rls)

    builder = SQLBuilder(engine, {"orders": "order_fact"})
    sql = builder.build(resolved)

    executor = SQLExecutor(engine)
    result = executor.execute(sql)
    assert len(result) == 2


def test_pipeline_with_tenant_isolation(pipeline):
    """Tenant filter isolates data."""
    engine = pipeline["engine"]
    registry = pipeline["registry"]

    dsl = (
        DSLBuilder("orders")
        .dimension("product_name")
        .build()
    )

    rls = RowLevelSecurity({
        "u001": {"tenant_id": "t001"}
    })
    dsl_with_tenant = rls.inject(dsl, "u001")
    assert any(f.field == "tenant_id" and f.value == "t001" for f in dsl_with_tenant.filters)

    builder = SQLBuilder(engine, {"orders": "order_fact"})
    sql = builder.build(dsl_with_tenant)

    executor = SQLExecutor(engine)
    result = executor.execute(sql)
    assert len(result) == 3  # only t001 data


def test_pipeline_with_dialect_conversion(pipeline):
    """Convert to MySQL dialect."""
    engine = pipeline["engine"]

    dsl = (
        DSLBuilder("orders")
        .dimension("product_name")
        .limit(10)
        .build()
    )

    builder = SQLBuilder(engine, {"orders": "order_fact"})
    sql = builder.build(dsl)

    converter = DialectConverter()
    mysql_sql = converter.transpile(sql, target="mysql")
    assert "LIMIT" in mysql_sql


def test_pipeline_sql_scanner_blocks_dangerous(pipeline):
    """Scanner blocks DELETE."""
    scanner = SQLScanner()
    with pytest.raises(Exception):
        scanner.scan("DELETE FROM order_fact")
