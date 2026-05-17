import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import Aggregation


def test_aggregation_sum():
    a = Aggregation(func="sum", field="order_amount", alias="sales_amount")
    assert a.func == "sum"
    assert a.field == "order_amount"
    assert a.alias == "sales_amount"


def test_aggregation_without_alias():
    a = Aggregation(func="count", field="id")
    assert a.alias is None


def test_aggregation_invalid_func():
    with pytest.raises(ValidationError):
        Aggregation(func="median", field="order_amount")
