import pytest
from nl2dsl.dsl.models import DSL, Filter
from nl2dsl.permission.row_level import RowLevelSecurity


def test_inject_single_filter():
    rls = RowLevelSecurity({
        "u123": {
            "row_filters": {
                "region": {"operator": "in", "value": ["华东", "华南"]}
            }
        }
    })
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert len(result.filters) == 1
    assert result.filters[0].field == "region"
    assert result.filters[0].value == ["华东", "华南"]


def test_inject_multiple_filters():
    rls = RowLevelSecurity({
        "u123": {
            "row_filters": {
                "region": {"operator": "in", "value": ["华东"]},
                "department": {"operator": "=", "value": "sales"},
            }
        }
    })
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert len(result.filters) == 2


def test_no_permissions():
    rls = RowLevelSecurity({})
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert result.filters is None or len(result.filters) == 0


def test_preserve_existing_filters():
    rls = RowLevelSecurity({
        "u123": {
            "row_filters": {
                "region": {"operator": "in", "value": ["华东"]}
            }
        }
    })
    dsl = DSL(data_source="orders", filters=[Filter(field="status", operator="=", value="active")])
    result = rls.inject(dsl, "u123")
    assert len(result.filters) == 2
    assert result.filters[0].field == "status"
