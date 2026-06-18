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
    def test_dimension_dedup_is_not_normalizer_responsibility(self, normalizer):
        """D003 rule handles dimension dedup — Normalizer no longer does it."""
        dsl, log = normalizer.normalize(
            {"data_source": "orders", "dimensions": ["a", "b", "a", "c", "b"]}
        )
        # Normalizer no longer deduplicates dimensions (D003 handles it)
        assert dsl["dimensions"] == ["a", "b", "a", "c", "b"]

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
    def test_alias_generation_is_not_normalizer_responsibility(self, normalizer):
        """M003 rule handles alias generation — Normalizer no longer does it."""
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [{"func": "sum", "field": "pay_amount"}],
            }
        )
        # Normalizer no longer generates aliases (M003 handles it)
        assert "alias" not in dsl["metrics"][0] or dsl["metrics"][0]["alias"] is None

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


class TestNormalizerNegationTree:
    """Week 2 Task 4: 'not' single-leaf trees invert to != leaves, not dropped."""

    def test_not_equal_inverts_to_not_equal(self, normalizer):
        dsl, _ = normalizer.normalize({
            "data_source": "orders",
            "filters": {"op": "not", "children": [{"field": "category", "operator": "=", "value": "手机"}]},
        })
        assert dsl["filters"] == [{"field": "category", "operator": "!=", "value": "手机"}]

    def test_not_greater_than_inverts_to_le(self, normalizer):
        dsl, _ = normalizer.normalize({
            "data_source": "orders",
            "filters": {"op": "not", "children": [{"field": "price", "operator": ">", "value": 100}]},
        })
        assert dsl["filters"] == [{"field": "price", "operator": "<=", "value": 100}]

    def test_not_not_equal_inverts_to_equal(self, normalizer):
        dsl, _ = normalizer.normalize({
            "data_source": "orders",
            "filters": {"op": "not", "children": [{"field": "region", "operator": "!=", "value": "华东"}]},
        })
        assert dsl["filters"] == [{"field": "region", "operator": "=", "value": "华东"}]

    def test_and_tree_still_flattens(self, normalizer):
        dsl, _ = normalizer.normalize({
            "data_source": "orders",
            "filters": {"op": "and", "children": [
                {"field": "region", "operator": "=", "value": "华东"},
                {"field": "channel", "operator": "=", "value": "线上"},
            ]},
        })
        assert dsl["filters"] == [
            {"field": "region", "operator": "=", "value": "华东"},
            {"field": "channel", "operator": "=", "value": "线上"},
        ]

    def test_not_in_keeps_leaf_and_warns(self, normalizer):
        dsl, log = normalizer.normalize({
            "data_source": "orders",
            "filters": {"op": "not", "children": [{"field": "region", "operator": "in", "value": ["华东", "华南"]}]},
        })
        # Not silently dropped: the original leaf survives
        assert len(dsl["filters"]) == 1
        assert dsl["filters"][0]["operator"] == "in"
        assert any("not" in m.lower() for m in log.actions)

