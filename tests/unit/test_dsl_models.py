import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import DSL, Filter, Aggregation, OrderBy


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
