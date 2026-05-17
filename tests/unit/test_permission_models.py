from nl2dsl.permission.models import UserPermission, RowFilter


def test_row_filter():
    rf = RowFilter(field="region", operator="in", value=["华东", "华南"])
    assert rf.field == "region"
    assert rf.operator == "in"
    assert rf.value == ["华东", "华南"]


def test_user_permission():
    perm = UserPermission(
        user_id="u123",
        row_filters={
            "region": RowFilter(field="region", operator="in", value=["华东"]),
        },
        allowed_dimensions=["product_name", "region"],
    )
    assert perm.user_id == "u123"
    assert "region" in perm.row_filters
