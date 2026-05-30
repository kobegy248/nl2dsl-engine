"""Unit tests for nl2dsl.agent.resolver."""

from __future__ import annotations

import pytest

from nl2dsl.agent.resolver import EntityResolver, ResolvedEntity
from nl2dsl.semantic.registry import SemanticRegistry


@pytest.fixture
def registry():
    """Return a SemanticRegistry populated with test data."""
    reg = SemanticRegistry()
    reg.metrics = {
        "sales_amount": {
            "expr": "SUM(order_amount)",
            "description": "销售额",
            "aliases": ["sale amount", "Sales"],
        },
        "order_count": {
            "expr": "COUNT(id)",
            "description": "订单数量",
        },
        "gmv": {
            "expr": "SUM(order_amount)",
            "description": "成交总额",
            "aliases": ["GMV", "gross merchandise value"],
        },
    }
    reg.dimensions = {
        "product_name": {
            "column": "product_name",
            "description": "产品名称",
        },
        "region": {
            "column": "region",
            "description": "地区",
            "value_map": {
                "华东": "HD",
                "华南": "HN",
                "华北": "HB",
            },
        },
        "channel": {
            "column": "channel",
            "description": "销售渠道",
            "aliases": ["销售通道"],
        },
    }
    reg.data_sources = {
        "orders": {
            "table": "order_fact",
            "metrics": ["sales_amount", "order_count", "gmv"],
            "dimensions": ["product_name", "region", "channel"],
        },
        "products": {
            "table": "product_dim",
            "metrics": [],
            "dimensions": ["product_name"],
        },
    }
    return reg


@pytest.fixture
def resolver(registry):
    """Return an EntityResolver backed by the test registry."""
    return EntityResolver(registry)


# ---------------------------------------------------------------------------
# resolve_metric
# ---------------------------------------------------------------------------


class TestResolveMetric:
    """Tests for EntityResolver.resolve_metric."""

    def test_description_match(self, resolver):
        """Match metric by Chinese description."""
        assert resolver.resolve_metric("销售额") == "sales_amount"

    def test_alias_match(self, resolver):
        """Match metric by alias."""
        assert resolver.resolve_metric("sale amount") == "sales_amount"

    def test_alias_case_insensitive(self, resolver):
        """Match metric by alias case-insensitively."""
        assert resolver.resolve_metric("sales") == "sales_amount"

    def test_no_match_returns_none(self, resolver):
        """No matching metric returns None."""
        assert resolver.resolve_metric("不存在的指标") is None

    def test_multi_word_alias(self, resolver):
        """Match metric by multi-word alias."""
        assert resolver.resolve_metric("gross merchandise value") == "gmv"


# ---------------------------------------------------------------------------
# resolve_dimension
# ---------------------------------------------------------------------------


class TestResolveDimension:
    """Tests for EntityResolver.resolve_dimension."""

    def test_description_match(self, resolver):
        """Match dimension by Chinese description."""
        assert resolver.resolve_dimension("产品名称") == "product_name"

    def test_alias_match(self, resolver):
        """Match dimension by alias."""
        assert resolver.resolve_dimension("销售通道") == "channel"

    def test_no_match_returns_none(self, resolver):
        """No matching dimension returns None."""
        assert resolver.resolve_dimension("不存在的维度") is None


# ---------------------------------------------------------------------------
# resolve_dimension_value
# ---------------------------------------------------------------------------


class TestResolveDimensionValue:
    """Tests for EntityResolver.resolve_dimension_value."""

    def test_value_map_match(self, resolver):
        """Match dimension value via value_map."""
        result = resolver.resolve_dimension_value("华东")
        assert result == ("region", "HD")

    def test_another_value_map_match(self, resolver):
        """Match another dimension value via value_map."""
        result = resolver.resolve_dimension_value("华南")
        assert result == ("region", "HN")

    def test_no_match_returns_none(self, resolver):
        """No matching dimension value returns None."""
        assert resolver.resolve_dimension_value("不存在的地区") is None


# ---------------------------------------------------------------------------
# resolve (full question)
# ---------------------------------------------------------------------------


class TestResolve:
    """Tests for EntityResolver.resolve."""

    def test_full_question_metrics_only(self, resolver):
        """Resolve metrics from a full question."""
        result = resolver.resolve("查询销售额和订单数量")
        assert result.metric_services == ["order_count", "sales_amount"]
        assert result.dimension_services == []
        assert result.data_source == "orders"

    def test_full_question_with_dimension_value(self, resolver):
        """Resolve dimension value from a full question."""
        result = resolver.resolve("华东的销售额是多少")
        assert result.metric_services == ["sales_amount"]
        assert ("region", "HD") in result.dimension_services
        assert result.data_source == "orders"

    def test_full_question_with_dimension(self, resolver):
        """Resolve dimension from a full question."""
        result = resolver.resolve("按产品名称查看销售额")
        assert result.metric_services == ["sales_amount"]
        assert ("product_name", None) in result.dimension_services
        assert result.data_source == "orders"

    def test_empty_question(self, resolver):
        """Empty question returns empty result."""
        result = resolver.resolve("")
        assert result == ResolvedEntity()

    def test_no_match_question(self, resolver):
        """Question with no known entities returns empty result."""
        result = resolver.resolve("今天天气怎么样")
        assert result.metric_services == []
        assert result.dimension_services == []
        # No metrics or dimensions, so no data source can be inferred
        assert result.data_source is None

    def test_data_source_inference_from_dimensions_only(self, resolver):
        """Data source inferred from dimensions when no metrics match."""
        result = resolver.resolve("产品名称有哪些")
        assert result.metric_services == []
        assert ("product_name", None) in result.dimension_services
        # Both orders and products have product_name; orders has higher score
        # because it has more dimensions, but with equal score the first one wins
        assert result.data_source is not None
