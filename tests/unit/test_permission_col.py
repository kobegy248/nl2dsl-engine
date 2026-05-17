import pytest
from nl2dsl.dsl.models import DSL
from nl2dsl.permission.column_level import ColumnLevelSecurity
from nl2dsl.exceptions import PermissionError


def test_block_sensitive_column():
    cls = ColumnLevelSecurity(
        sensitive_columns={"salary": {"level": "high"}, "phone": {"level": "high"}}
    )
    dsl = DSL(data_source="orders", dimensions=["product_name", "salary"])
    with pytest.raises(PermissionError) as exc:
        cls.check(dsl, "u123")
    assert "salary" in str(exc.value)


def test_allow_non_sensitive():
    cls = ColumnLevelSecurity(
        sensitive_columns={"salary": {"level": "high"}}
    )
    dsl = DSL(data_source="orders", dimensions=["product_name"])
    cls.check(dsl, "u123")  # should not raise


def test_allow_metrics():
    from nl2dsl.dsl.models import Aggregation
    cls = ColumnLevelSecurity(
        sensitive_columns={"salary": {"level": "high"}}
    )
    dsl = DSL(
        data_source="orders",
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
    )
    cls.check(dsl, "u123")  # should not raise


def test_mask_phone():
    cls = ColumnLevelSecurity(
        sensitive_columns={},
        masking_rules={
            "phone": lambda x: f"{x[:3]}****{x[-4:]}" if len(x) >= 7 else x,
        }
    )
    result = cls.mask({"phone": "13800138000", "name": "张三"})
    assert result["phone"] == "138****8000"
    assert result["name"] == "张三"


def test_mask_email():
    cls = ColumnLevelSecurity(
        masking_rules={
            "email": lambda x: f"{x[:2]}***@{x.split('@')[1]}" if "@" in x else x,
        }
    )
    result = cls.mask({"email": "zhangsan@example.com"})
    assert result["email"] == "zh***@example.com"


def test_mask_id_card():
    cls = ColumnLevelSecurity(
        masking_rules={
            "id_card": lambda x: f"{x[:4]}**********{x[-4:]}" if len(x) >= 14 else x,
        }
    )
    result = cls.mask({"id_card": "110101199001011234"})
    assert result["id_card"] == "1101**********1234"
