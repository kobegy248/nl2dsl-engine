import pytest

from nl2dsl.dsl.models import DSL, FilterTreeNode, Having, Aggregation
from nl2dsl.dsl.semantic_validator import SemanticValidator, SemanticWarning


@pytest.fixture
def validator():
    registry = {
        "metrics": {
            "sales_amount": {"expr": "SUM(pay_amount)", "description": "销售额"},
            "order_count": {"expr": "COUNT(id)", "description": "订单量"},
        },
        "dimensions": {
            "product_name": {"column": "product_name", "description": "产品"},
            "brand": {"column": "brand", "description": "品牌"},
            "region": {"column": "region", "description": "地区"},
            "category": {"column": "category", "description": "品类"},
        },
        "data_sources": {
            "orders": {"table": "order_fact"},
        },
        "fields": {
            "region": {
                "type": "string",
                "allowed_values": ["华东", "华南", "华北", "西南"],
            },
            "pay_amount": {"type": "number"},
            "order_date": {"type": "date"},
        },
    }
    return SemanticValidator(registry)


class TestFieldExistence:
    def test_metric_alias_exists(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[
                Aggregation(func="sum", field="pay_amount", alias="sales_amount")
            ],
            dimensions=["brand"],
        )
        errors, warnings = validator.validate(dsl)
        assert not errors

    def test_metric_alias_missing(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[
                Aggregation(func="sum", field="pay_amount", alias="unknown_metric")
            ],
            dimensions=["brand"],
        )
        errors, _ = validator.validate(dsl)
        assert any("unknown_metric" in e for e in errors)

    def test_dimension_exists(self, validator):
        dsl = DSL(data_source="orders", dimensions=["brand"])
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_dimension_missing(self, validator):
        dsl = DSL(data_source="orders", dimensions=["unknown_dim"])
        errors, _ = validator.validate(dsl)
        assert any("unknown_dim" in e for e in errors)

    def test_data_source_exists(self, validator):
        dsl = DSL(data_source="orders")
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_data_source_missing(self, validator):
        dsl = DSL(data_source="nonexistent")
        errors, _ = validator.validate(dsl)
        assert any("nonexistent" in e for e in errors)


class TestFilterValidation:
    def test_filter_field_exists(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "region", "operator": "=", "value": "华东"}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_filter_numeric_operator_with_number(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": ">", "value": 5000}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_filter_numeric_operator_with_string_error(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": ">", "value": "5000"}],
        )
        errors, _ = validator.validate(dsl)
        assert any(
            "> requires a number" in e or "numeric" in e.lower() for e in errors
        )

    def test_between_requires_list(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "pay_amount", "operator": "between", "value": 100}],
        )
        errors, _ = validator.validate(dsl)
        assert any(
            "between requires" in e.lower() or "[min, max]" in e for e in errors
        )

    def test_in_requires_list(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[{"field": "region", "operator": "in", "value": "华东"}],
        )
        errors, _ = validator.validate(dsl)
        assert any(
            "in requires" in e.lower() or "list" in e.lower() for e in errors
        )


class TestFilterTreeValidation:
    def test_nested_tree_valid(self, validator):
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "region", "operator": "=", "value": "华东"},
                    {
                        "op": "not",
                        "children": [
                            {"field": "category", "operator": "=", "value": "手机"}
                        ],
                    },
                ],
            },
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_tree_with_unknown_field_warns(self, validator):
        dsl = DSL(
            data_source="orders",
            filters={
                "op": "and",
                "children": [
                    {"field": "unknown_field", "operator": "=", "value": "x"},
                ],
            },
        )
        errors, warnings = validator.validate(dsl)
        # unknown_field not in registry fields -> warning (not error)
        assert any("unknown_field" in w.message for w in warnings)


class TestConditionConflict:
    def test_same_field_equal_different_values(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "region", "operator": "=", "value": "华南"},
            ],
        )
        errors, _ = validator.validate(dsl)
        assert any("conflict" in e.lower() for e in errors)

    def test_no_conflict_different_fields(self, validator):
        dsl = DSL(
            data_source="orders",
            filters=[
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "channel", "operator": "=", "value": "线上"},
            ],
        )
        errors, _ = validator.validate(dsl)
        assert not errors


class TestHavingValidation:
    def test_having_with_metric_ok(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[
                Aggregation(func="sum", field="pay_amount", alias="sales_amount")
            ],
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        errors, _ = validator.validate(dsl)
        assert not errors

    def test_having_without_metric_error(self, validator):
        dsl = DSL(
            data_source="orders",
            dimensions=["brand"],
            having=[{"field": "sales_amount", "operator": ">", "value": 100000}],
        )
        errors, _ = validator.validate(dsl)
        assert any(
            "having" in e.lower() and "metric" in e.lower() for e in errors
        )

    def test_having_field_not_in_metrics(self, validator):
        dsl = DSL(
            data_source="orders",
            metrics=[
                Aggregation(func="sum", field="pay_amount", alias="sales_amount")
            ],
            dimensions=["brand"],
            having=[{"field": "unknown_alias", "operator": ">", "value": 100}],
        )
        errors, _ = validator.validate(dsl)
        assert any("unknown_alias" in e for e in errors)
