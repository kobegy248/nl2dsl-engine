import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import (
    DSL,
    Filter,
    FilterTreeNode,
    Having,
    Aggregation,
    OrderBy,
)


def test_filter_valid():
    f = Filter(field="region", operator="=", value="华东")
    assert f.field == "region"
    assert f.operator == "="
    assert f.value == "华东"


def test_aggregation_valid():
    a = Aggregation(func="sum", field="order_amount", alias="sales_amount")
    assert a.func == "sum"
    assert a.alias == "sales_amount"


def test_dsl_valid():
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        filters=[Filter(field="region", operator="=", value="华东")],
        order_by=[OrderBy(field="sales_amount", direction="desc")],
        limit=10,
        data_source="orders",
    )
    assert dsl.data_source == "orders"
    assert dsl.limit == 10
    assert dsl.offset == 0


def test_dsl_invalid_limit():
    with pytest.raises(ValidationError):
        DSL(data_source="orders", limit=99999)


def test_dsl_default_limit():
    dsl = DSL(data_source="orders")
    assert dsl.limit == 100


class TestFilterTreeNode:
    """Tests for the new filter tree structure."""

    def test_filter_leaf_as_dict(self):
        """Old flat list format still works."""
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "pay_amount", "operator": ">", "value": 5000},
            ],
        )
        assert isinstance(dsl.filters, list)
        assert dsl.filters[0].field == "region"
        assert dsl.filters[1].value == 5000

    def test_filter_tree_and(self):
        """New condition tree with 'and' operator."""
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {"field": "channel", "operator": "=", "value": "线上"},
                    {"field": "pay_amount", "operator": ">", "value": 5000},
                ],
            },
        )
        assert isinstance(dsl.filters, FilterTreeNode)
        assert dsl.filters.op == "and"
        assert len(dsl.filters.children) == 3
        assert dsl.filters.children[0].field == "region"

    def test_filter_tree_with_not(self):
        """Condition tree with 'not' operator."""
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [
                            {"field": "category", "operator": "=", "value": "手机"},
                        ],
                    },
                ],
            },
        )
        assert dsl.filters.op == "and"
        assert dsl.filters.children[1].op == "not"
        assert dsl.filters.children[1].children[0].field == "category"

    def test_filter_tree_nested_or(self):
        """Deeply nested or/and tree."""
        dsl = DSL(
            data_source="orders",
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
        )
        assert dsl.filters.op == "or"
        assert len(dsl.filters.children) == 2
        assert dsl.filters.children[0].op == "and"


class TestHaving:
    """Tests for the new having field."""

    def test_having_basic(self):
        dsl = DSL(
            data_source="orders",
            metrics=[{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        assert dsl.having is not None
        assert len(dsl.having) == 1
        assert dsl.having[0].field == "sales_amount"
        assert dsl.having[0].operator == ">"
        assert dsl.having[0].value == 100000


class TestTimeFields:
    """Tests for time_field and time_range."""

    def test_time_range_as_list(self):
        dsl = DSL(
            data_source="orders",
            time_field="order_date",
            time_range=["2026-05-23", "2026-05-30"],
        )
        assert dsl.time_field == "order_date"
        assert dsl.time_range == ("2026-05-23", "2026-05-30")

    def test_time_range_as_tuple(self):
        dsl = DSL(
            data_source="orders",
            time_field="order_date",
            time_range=("2026-01-01", "2026-12-31"),
        )
        assert dsl.time_range == ("2026-01-01", "2026-12-31")
