import pytest
from nl2dsl.dsl.models import DSL, Filter, Aggregation
from nl2dsl.semantic.resolver import SemanticResolver
from nl2dsl.exceptions import SemanticError


@pytest.fixture
def resolver():
    registry = {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)"},
            "gmv": {"expr": "SUM(pay_amount)"},
        },
        "dimensions": {
            "product_name": {"column": "product_name"},
            "region": {
                "column": "region_code",
                "value_map": {"华东": "HD", "华南": "HN"},
            },
            "gender": {
                "column": "gender_code",
                "value_map": {"男性": 1, "女性": 2},
            },
        },
        "data_sources": {
            "orders": {"table": "order_fact"},
        },
    }
    return SemanticResolver(registry)


def test_resolve_metric_expr(resolver):
    """Metric expr is parsed into func + field; field holds the raw column name."""
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        data_source="orders",
    )
    resolved = resolver.resolve(dsl)
    assert resolved.metrics[0].func == "sum"
    assert resolved.metrics[0].field == "order_amount"


def test_resolve_value_map_keeps_semantic_value(resolver):
    """Semantic values are preserved in DSL; SQLBuilder maps to internal codes."""
    dsl = DSL(
        dimensions=["region"],
        filters=[Filter(field="region", operator="=", value="华东")],
        data_source="orders",
    )
    resolved = resolver.resolve(dsl)
    # Semantic value is kept (not mapped to internal code)
    assert resolved.filters[0].value == "华东"


def test_resolve_value_map_in_filter_list_keeps_semantic_values(resolver):
    """Semantic values in list filters are preserved."""
    dsl = DSL(
        dimensions=["region"],
        filters=[Filter(field="region", operator="in", value=["华东", "华南"])],
        data_source="orders",
    )
    resolved = resolver.resolve(dsl)
    assert resolved.filters[0].value == ["华东", "华南"]


def test_resolve_unknown_metric(resolver):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="x", alias="unknown")],
        data_source="orders",
    )
    with pytest.raises(SemanticError):
        resolver.resolve(dsl)


def test_get_table_name(resolver):
    assert resolver.get_table_name("orders") == "order_fact"
