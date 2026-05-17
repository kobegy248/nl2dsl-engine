import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import OrderBy


def test_order_by_default_direction():
    o = OrderBy(field="sales_amount")
    assert o.field == "sales_amount"
    assert o.direction == "asc"


def test_order_by_desc():
    o = OrderBy(field="sales_amount", direction="desc")
    assert o.direction == "desc"


def test_order_by_invalid_direction():
    with pytest.raises(ValidationError):
        OrderBy(field="sales_amount", direction="invalid")
