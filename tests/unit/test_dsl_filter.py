import pytest
from pydantic import ValidationError
from nl2dsl.dsl.models import Filter


def test_filter_equality():
    f = Filter(field="region", operator="=", value="华东")
    assert f.field == "region"
    assert f.operator == "="
    assert f.value == "华东"


def test_filter_between():
    f = Filter(field="order_date", operator="between", value=["2024-01-01", "2024-03-31"])
    assert f.operator == "between"
    assert f.value == ["2024-01-01", "2024-03-31"]


def test_filter_in_operator():
    f = Filter(field="region", operator="in", value=["华东", "华南"])
    assert f.value == ["华东", "华南"]


def test_filter_invalid_operator():
    with pytest.raises(ValidationError):
        Filter(field="region", operator="invalid", value="华东")


def test_filter_no_value():
    f = Filter(field="region", operator="is_null")
    assert f.value is None
