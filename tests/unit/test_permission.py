import pytest
from nl2dsl.dsl.models import DSL, Filter
from nl2dsl.permission.row_level import RowLevelSecurity
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.exceptions import PermissionError


def test_row_level_inject():
    rls = RowLevelSecurity({
        "u123": {
            "row_filters": {
                "region": {"operator": "in", "value": ["华东", "华南"]}
            }
        }
    })

    dsl = DSL(data_source="orders", filters=[])
    result = rls.inject(dsl, "u123")

    assert len(result.filters) == 1
    assert result.filters[0].field == "region"
    assert result.filters[0].value == ["华东", "华南"]


def test_row_level_no_permissions():
    rls = RowLevelSecurity({})
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert result.filters is None or len(result.filters) == 0


def test_column_level_block():
    cls = ColumnLevelSecurity(
        sensitive_columns={"salary": {"level": "high"}}
    )

    dsl = DSL(data_source="orders", dimensions=["product_name", "salary"])
    with pytest.raises(PermissionError):
        cls.check(dsl, "u123")


def test_column_level_allow():
    cls = ColumnLevelSecurity(
        sensitive_columns={"salary": {"level": "high"}}
    )

    dsl = DSL(data_source="orders", dimensions=["product_name"])
    cls.check(dsl, "u123")  # should not raise


def test_data_masking():
    cls = ColumnLevelSecurity(
        sensitive_columns={},
        masking_rules={
            "phone": lambda x: f"{x[:3]}****{x[-4:]}"
        }
    )

    result = cls.mask({"phone": "13800138000"})
    assert result["phone"] == "138****8000"


def test_tenant_isolation():
    rls = RowLevelSecurity({
        "u123": {
            "tenant_id": "t001",
        }
    })
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert len(result.filters) == 1
    assert result.filters[0].field == "tenant_id"
    assert result.filters[0].value == "t001"
    assert result.filters[0].operator == "="


def test_tenant_with_row_filters():
    rls = RowLevelSecurity({
        "u123": {
            "tenant_id": "t001",
            "row_filters": {
                "region": {"operator": "=", "value": "华东"}
            }
        }
    })
    dsl = DSL(data_source="orders")
    result = rls.inject(dsl, "u123")
    assert len(result.filters) == 2
    fields = {f.field for f in result.filters}
    assert fields == {"region", "tenant_id"}
