"""Tests for Normalizer — structural DSL normalization."""

import pytest
from nl2dsl.optimizer.normalizer import Normalizer


@pytest.fixture
def normalizer():
    return Normalizer()


class TestNormalizerDefaults:
    def test_injects_missing_fields(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders"})
        assert dsl["limit"] == 100
        assert dsl["offset"] == 0
        assert dsl["metrics"] is None
        assert dsl["dimensions"] is None
        assert dsl["filters"] is None
        assert dsl["having"] is None
        assert dsl["order_by"] is None
        assert dsl["time_field"] is None
        assert dsl["time_range"] is None
        assert dsl["joins"] is None

    def test_does_not_overwrite_existing_fields(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": 50})
        assert dsl["limit"] == 50


class TestNormalizerTypeCoercion:
    def test_coerces_limit_string_to_int(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": "50"})
        assert dsl["limit"] == 50
        assert isinstance(dsl["limit"], int)

    def test_coerces_invalid_limit_to_default(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": "abc"})
        assert dsl["limit"] == 100

    def test_coerces_null_data_source_to_empty_string(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": None})
        assert dsl["data_source"] == ""


class TestNormalizerDedup:
    def test_dedup_dimensions(self, normalizer):
        dsl, log = normalizer.normalize(
            {"data_source": "orders", "dimensions": ["a", "b", "a", "c", "b"]}
        )
        assert dsl["dimensions"] == ["a", "b", "c"]

    def test_dedup_metrics_by_func_field(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [
                    {"func": "sum", "field": "amount"},
                    {"func": "sum", "field": "amount"},
                    {"func": "count", "field": "amount"},
                ],
            }
        )
        assert len(dsl["metrics"]) == 2

    def test_single_dimension_not_affected(self, normalizer):
        dsl, log = normalizer.normalize(
            {"data_source": "orders", "dimensions": ["product_name"]}
        )
        assert dsl["dimensions"] == ["product_name"]


class TestNormalizerAliases:
    def test_generates_alias_for_unaliased_metric(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [{"func": "sum", "field": "pay_amount"}],
            }
        )
        assert dsl["metrics"][0]["alias"] == "sum_pay_amount"

    def test_preserves_existing_alias(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [
                    {"func": "sum", "field": "pay_amount", "alias": "gmv"}
                ],
            }
        )
        assert dsl["metrics"][0]["alias"] == "gmv"


class TestNormalizerEmptyLists:
    def test_empty_metrics_becomes_none(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "metrics": []})
        assert dsl["metrics"] is None

    def test_empty_dimensions_becomes_none(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "dimensions": []})
        assert dsl["dimensions"] is None
