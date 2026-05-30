"""Unit tests for the intent configuration system."""

from __future__ import annotations

import pathlib

import pytest

from nl2dsl.agent.strategies import IntentConfig, IntentRegistry


class TestIntentConfig:
    """Tests for IntentConfig model."""

    def test_creation(self):
        config = IntentConfig(
            keywords=["对比", "比较"],
            decomposition="split_by_objects",
            aggregation="diff",
            description="Compare objects",
        )
        assert config.keywords == ["对比", "比较"]
        assert config.decomposition == "split_by_objects"
        assert config.aggregation == "diff"
        assert config.description == "Compare objects"

    def test_empty_keywords(self):
        config = IntentConfig(
            keywords=[],
            decomposition="passthrough",
            aggregation="passthrough",
            description="Fallback intent",
        )
        assert config.keywords == []


class TestIntentRegistryLoad:
    """Tests for loading IntentRegistry from YAML."""

    def test_load_from_default_path(self):
        registry = IntentRegistry.load()
        assert "compare" in registry.intents
        assert "trend" in registry.intents
        assert "correlation" in registry.intents
        assert "proportion" in registry.intents
        assert "ranking" in registry.intents
        assert "single_query" in registry.intents

    def test_load_compare_intent(self):
        registry = IntentRegistry.load()
        compare = registry.intents["compare"]
        assert compare.keywords == ["对比", "比较", "vs", "相比", "同比", "环比"]
        assert compare.decomposition == "split_by_objects"
        assert compare.aggregation == "diff"

    def test_load_trend_intent(self):
        registry = IntentRegistry.load()
        trend = registry.intents["trend"]
        assert trend.keywords == ["趋势", "走势", "变化", "增长", "下降"]
        assert trend.decomposition == "single_with_time_grouping"
        assert trend.aggregation == "trend_direction"

    def test_load_correlation_intent(self):
        registry = IntentRegistry.load()
        corr = registry.intents["correlation"]
        assert corr.keywords == ["关联", "影响", "相关", "关系"]
        assert corr.decomposition == "split_by_objects"
        assert corr.aggregation == "pearson"

    def test_load_proportion_intent(self):
        registry = IntentRegistry.load()
        prop = registry.intents["proportion"]
        assert prop.keywords == ["占比", "构成", "贡献度"]
        assert prop.decomposition == "total_plus_groups"
        assert prop.aggregation == "proportion"

    def test_load_ranking_intent(self):
        registry = IntentRegistry.load()
        rank = registry.intents["ranking"]
        assert rank.keywords == ["排名", "Top", "第几"]
        assert rank.decomposition == "single_with_ordering"
        assert rank.aggregation == "ranking"

    def test_load_single_query_intent(self):
        registry = IntentRegistry.load()
        sq = registry.intents["single_query"]
        assert sq.keywords == []
        assert sq.decomposition == "passthrough"
        assert sq.aggregation == "passthrough"

    def test_load_from_explicit_path(self, tmp_path: pathlib.Path):
        yaml_path = tmp_path / "intents.yaml"
        yaml_path.write_text(
            "intents:\n"
            "  test_intent:\n"
            "    keywords: [\"foo\", \"bar\"]\n"
            "    decomposition: test_decomp\n"
            "    aggregation: test_agg\n"
            "    description: Test description\n",
            encoding="utf-8",
        )
        registry = IntentRegistry.load(yaml_path)
        assert "test_intent" in registry.intents
        assert registry.intents["test_intent"].keywords == ["foo", "bar"]


class TestIntentRegistryKeywordMatching:
    """Tests for get_intent_by_keywords."""

    @pytest.fixture
    def registry(self) -> IntentRegistry:
        return IntentRegistry.load()

    def test_match_compare_chinese(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("对比华东和华南") == "compare"

    def test_match_compare_vs(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("A vs B") == "compare"

    def test_match_trend(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("销售额的趋势是什么") == "trend"

    def test_match_correlation(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("价格和销量的关联") == "correlation"

    def test_match_proportion(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("各渠道占比") == "proportion"

    def test_match_ranking(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("Top 10 排名") == "ranking"

    def test_no_match_returns_none(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("简单的查询") is None

    def test_fallback_to_single_query_by_caller(self, registry: IntentRegistry):
        """When no keyword matches, caller should fall back to single_query."""
        matched = registry.get_intent_by_keywords("查询总销售额")
        assert matched is None
        # Caller responsibility: use single_query as fallback
        intent = matched if matched is not None else "single_query"
        assert intent == "single_query"

    def test_case_insensitive_matching(self, registry: IntentRegistry):
        assert registry.get_intent_by_keywords("VS comparison") == "compare"
        assert registry.get_intent_by_keywords("TOP 10") == "ranking"
