import pytest
from nl2dsl.dsl.models import DSL, Filter, Aggregation, PostProcess
from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import ValidationError


@pytest.fixture
def validator():
    registry = {
        "metrics": {"sales_amount": None, "gmv": None},
        "dimensions": {"product_name": None, "region": None},
        "data_sources": {"orders": None},
    }
    return DSLValidator(registry)


def test_validate_valid_dsl(validator):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        data_source="orders",
    )
    validator.validate(dsl)


def test_validate_invalid_metric(validator):
    dsl = DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="unknown_metric")],
        data_source="orders",
    )
    with pytest.raises(ValidationError) as exc_info:
        validator.validate(dsl)
    assert "unknown_metric" in str(exc_info.value)


def test_validate_invalid_dimension(validator):
    dsl = DSL(
        dimensions=["unknown_dim"],
        data_source="orders",
    )
    with pytest.raises(ValidationError):
        validator.validate(dsl)


def test_validate_invalid_data_source(validator):
    dsl = DSL(data_source="unknown_source")
    with pytest.raises(ValidationError):
        validator.validate(dsl)


def test_validate_no_limit_no_metrics(validator):
    dsl = DSL(data_source="orders")
    with pytest.raises(ValidationError):
        validator.validate(dsl)


def test_validate_group_top_n():
    registry = {
        "metrics": {"sales_amount": {}},
        "dimensions": {"category": {}, "product_name": {}},
        "data_sources": {
            "orders": {
                "metrics": ["sales_amount"],
                "dimensions": ["category", "product_name"],
            }
        },
    }
    validator = DSLValidator(registry)
    dsl = DSL(
        data_source="orders",
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["category", "product_name"],
        post_process=PostProcess(
            type="group_top_n",
            metric="sales_amount",
            group_by=["category"],
            top_n=1,
        ),
    )
    validator.validate(dsl)


def test_validate_post_process_unknown_metric():
    registry = {
        "metrics": {"sales_amount": {}},
        "dimensions": {"category": {}},
        "data_sources": {
            "orders": {
                "metrics": ["sales_amount"],
                "dimensions": ["category"],
            }
        },
    }
    validator = DSLValidator(registry)
    dsl = DSL(
        data_source="orders",
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["category"],
        post_process=PostProcess(type="proportion", metric="unknown"),
    )
    with pytest.raises(ValidationError, match="后处理指标"):
        validator.validate(dsl)
