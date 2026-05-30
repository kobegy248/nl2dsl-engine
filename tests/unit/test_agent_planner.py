"""Unit tests for nl2dsl.agent.planner."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nl2dsl.agent.models import Plan, SubQuery
from nl2dsl.agent.planner import (
    Planner,
    _build_plan_prompt,
    _decompose_by_intent,
    _decompose_fallback,
    _make_plan_node,
    classify_intent,
)
from nl2dsl.agent.strategies import IntentConfig, IntentRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_intent_registry():
    """Return a mock IntentRegistry for testing."""
    return IntentRegistry(
        intents={
            "compare": IntentConfig(
                keywords=["对比", "比较", "vs", "相比"],
                decomposition="split_by_objects",
                aggregation="diff",
                description="Compare two or more objects",
            ),
            "trend": IntentConfig(
                keywords=["趋势", "走势", "变化", "增长", "下降"],
                decomposition="single_with_time_grouping",
                aggregation="trend_direction",
                description="Analyze trends over time",
            ),
            "correlation": IntentConfig(
                keywords=["关联", "影响", "相关", "关系"],
                decomposition="split_by_objects",
                aggregation="pearson",
                description="Discover relationships",
            ),
            "proportion": IntentConfig(
                keywords=["占比", "构成", "贡献度"],
                decomposition="total_plus_groups",
                aggregation="proportion",
                description="Break down totals",
            ),
            "ranking": IntentConfig(
                keywords=["排名", "Top", "第几"],
                decomposition="single_with_ordering",
                aggregation="ranking",
                description="Order results",
            ),
            "single_query": IntentConfig(
                keywords=[],
                decomposition="passthrough",
                aggregation="passthrough",
                description="Fallback for simple queries",
            ),
        }
    )


# ---------------------------------------------------------------------------
# Tests for classify_intent (backward compatibility)
# ---------------------------------------------------------------------------


class TestClassifyIntent:
    """Tests for keyword-based intent classification."""

    def test_compare_keywords(self):
        """Questions with comparison keywords should classify as 'compare'."""
        assert classify_intent("对比华东和华南的销售额") == "compare"
        assert classify_intent("比较今年和去年的业绩") == "compare"
        assert classify_intent("同比分析") == "compare"
        assert classify_intent("环比增长率") == "compare"
        assert classify_intent("A和B相比") == "compare"
        assert classify_intent("产品A vs 产品B") == "compare"
        assert classify_intent("VS对比") == "compare"
        assert classify_intent("华东相比华南") == "compare"

    def test_trend_keywords(self):
        """Questions with trend keywords should classify as 'trend'."""
        assert classify_intent("销售额趋势") == "trend"
        assert classify_intent("业绩走势如何") == "trend"
        assert classify_intent("订单量变化") == "trend"
        assert classify_intent("增长情况") == "trend"
        assert classify_intent("下降趋势") == "trend"

    def test_correlation_keywords(self):
        """Questions with correlation keywords should classify as 'correlation'."""
        assert classify_intent("销售额和利润的关联") == "correlation"
        assert classify_intent("价格对销量的影响") == "correlation"
        assert classify_intent("相关性分析") == "correlation"
        assert classify_intent("两者关系") == "correlation"
        assert classify_intent("取决于什么因素") == "correlation"

    def test_single_query_default(self):
        """Questions without special keywords should classify as 'single_query'."""
        assert classify_intent("查询华东销售额") == "single_query"
        assert classify_intent("前10的产品") == "single_query"
        assert classify_intent("总订单量") == "single_query"
        assert classify_intent("") == "single_query"

    def test_priority_compare_over_trend(self):
        """Compare keywords take priority over trend."""
        # "对比" is compare, "趋势" is trend
        assert classify_intent("对比今年和去年的趋势") == "compare"


# ---------------------------------------------------------------------------
# Tests for _decompose_by_intent (config-driven)
# ---------------------------------------------------------------------------


class TestDecomposeByIntent:
    """Tests for config-driven task decomposition."""

    def test_compare_split_by_objects(self, mock_intent_registry):
        """compare intent with split_by_objects splits question."""
        plan = _decompose_by_intent(
            "对比华东和华南的销售额", "compare", mock_intent_registry
        )
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert plan.sub_queries[0].id == "sq-1"
        assert plan.sub_queries[1].id == "sq-2"
        assert "华东" in plan.sub_queries[0].description
        assert "华南" in plan.sub_queries[1].description
        assert "split_by_objects" in plan.reasoning

    def test_trend_single_with_time_grouping(self, mock_intent_registry):
        """trend intent with single_with_time_grouping."""
        plan = _decompose_by_intent(
            "销售额趋势", "trend", mock_intent_registry
        )
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description
        assert "single_with_time_grouping" in plan.reasoning

    def test_correlation_split_by_objects(self, mock_intent_registry):
        """correlation intent with split_by_objects."""
        plan = _decompose_by_intent(
            "销售额和利润的关联", "correlation", mock_intent_registry
        )
        assert plan.intent == "correlation"
        assert len(plan.sub_queries) == 2
        assert "销售额" in plan.sub_queries[0].description
        assert "利润" in plan.sub_queries[1].description

    def test_proportion_total_plus_groups(self, mock_intent_registry):
        """proportion intent with total_plus_groups."""
        plan = _decompose_by_intent(
            "各品类销售占比", "proportion", mock_intent_registry
        )
        assert plan.intent == "proportion"
        assert len(plan.sub_queries) == 2
        assert "总计" in plan.sub_queries[0].description
        assert "分组明细" in plan.sub_queries[1].description

    def test_ranking_single_with_ordering(self, mock_intent_registry):
        """ranking intent with single_with_ordering."""
        plan = _decompose_by_intent(
            "销售额排名前10的产品", "ranking", mock_intent_registry
        )
        assert plan.intent == "ranking"
        assert len(plan.sub_queries) == 1
        assert "按排序" in plan.sub_queries[0].description

    def test_single_query_passthrough(self, mock_intent_registry):
        """single_query intent with passthrough."""
        plan = _decompose_by_intent(
            "查询华东销售额", "single_query", mock_intent_registry
        )
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "查询华东销售额"

    def test_unknown_intent_passthrough(self, mock_intent_registry):
        """Unknown intent falls back to passthrough."""
        plan = _decompose_by_intent(
            "something", "unknown", mock_intent_registry
        )
        assert plan.intent == "unknown"
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "something"

    def test_compare_no_splitter(self, mock_intent_registry):
        """compare without splitters still produces 1 sub-query."""
        plan = _decompose_by_intent(
            "同比分析", "compare", mock_intent_registry
        )
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "同比分析"


# ---------------------------------------------------------------------------
# Tests for _decompose_fallback (backward compatibility)
# ---------------------------------------------------------------------------


class TestDecomposeFallback:
    """Tests for fallback task decomposition."""

    def test_compare_decomposition(self):
        """Compare intent splits by '和', '与', 'vs'."""
        plan = _decompose_fallback("对比华东和华南的销售额", "compare")
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert plan.sub_queries[0].id == "sq-1"
        assert plan.sub_queries[1].id == "sq-2"
        assert "华东" in plan.sub_queries[0].description
        assert "华南" in plan.sub_queries[1].description
        assert plan.sub_queries[1].depends_on == []

    def test_compare_with_vs(self):
        """Compare intent splits by 'vs'."""
        plan = _decompose_fallback("产品A vs 产品B的销量", "compare")
        assert len(plan.sub_queries) == 2
        assert "产品A" in plan.sub_queries[0].description
        assert "产品B" in plan.sub_queries[1].description

    def test_compare_with_yu(self):
        """Compare intent splits by '与'."""
        plan = _decompose_fallback("华东与华南销售额对比", "compare")
        assert len(plan.sub_queries) == 2
        assert "华东" in plan.sub_queries[0].description
        assert "华南" in plan.sub_queries[1].description

    def test_compare_no_splitter(self):
        """Compare without splitters still produces 1 sub-query."""
        plan = _decompose_fallback("同比分析", "compare")
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "同比分析"

    def test_trend_decomposition(self):
        """Trend intent produces single sub-query with time grouping note."""
        plan = _decompose_fallback("销售额趋势", "trend")
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description
        assert "趋势" in plan.sub_queries[0].description

    def test_correlation_decomposition(self):
        """Correlation intent splits by '和', '与'."""
        plan = _decompose_fallback("销售额和利润的关联", "correlation")
        assert plan.intent == "correlation"
        assert len(plan.sub_queries) == 2
        assert plan.sub_queries[0].id == "sq-1"
        assert plan.sub_queries[1].id == "sq-2"

    def test_single_query_decomposition(self):
        """Single_query intent passes through as 1 sub-query."""
        plan = _decompose_fallback("查询华东销售额", "single_query")
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "查询华东销售额"
        assert plan.sub_queries[0].depends_on == []

    def test_unknown_intent_fallback(self):
        """Unknown intent falls back to single_query."""
        plan = _decompose_fallback("something", "unknown")
        assert plan.intent == "unknown"
        assert len(plan.sub_queries) == 1


# ---------------------------------------------------------------------------
# Tests for Planner class
# ---------------------------------------------------------------------------


class TestPlannerInit:
    """Tests for Planner initialization."""

    def test_init_with_default_intents(self):
        """Planner loads intents from default path when none provided."""
        planner = Planner(llm_client=None)
        assert planner._llm is None
        assert planner._intents is not None
        assert "compare" in planner._intents.intents
        assert "trend" in planner._intents.intents

    def test_init_with_custom_intents(self, mock_intent_registry):
        """Planner uses provided IntentRegistry."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        assert planner._intents is mock_intent_registry

    def test_init_with_llm_client(self):
        """Planner stores LLM client."""
        llm = MagicMock()
        planner = Planner(llm_client=llm)
        assert planner._llm is llm


class TestPlannerClassifyByKeywords:
    """Tests for Planner._classify_by_keywords."""

    def test_classify_compare(self, mock_intent_registry):
        """Should classify compare keywords."""
        planner = Planner(intents=mock_intent_registry)
        assert planner._classify_by_keywords("对比华东和华南") == "compare"
        assert planner._classify_by_keywords("产品A vs 产品B") == "compare"

    def test_classify_trend(self, mock_intent_registry):
        """Should classify trend keywords."""
        planner = Planner(intents=mock_intent_registry)
        assert planner._classify_by_keywords("销售额趋势") == "trend"
        assert planner._classify_by_keywords("增长情况") == "trend"

    def test_classify_correlation(self, mock_intent_registry):
        """Should classify correlation keywords."""
        planner = Planner(intents=mock_intent_registry)
        assert planner._classify_by_keywords("销售额和利润的关联") == "correlation"

    def test_classify_single_query_fallback(self, mock_intent_registry):
        """Should fall back to single_query when no keywords match."""
        planner = Planner(intents=mock_intent_registry)
        assert planner._classify_by_keywords("查询华东销售额") == "single_query"


class TestPlannerRuleBasedPlan:
    """Tests for Planner._rule_based_plan."""

    def test_rule_based_plan_compare(self, mock_intent_registry):
        """Rule-based plan for compare intent."""
        planner = Planner(intents=mock_intent_registry)
        plan = planner._rule_based_plan("对比华东和华南的销售额")
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2

    def test_rule_based_plan_trend(self, mock_intent_registry):
        """Rule-based plan for trend intent."""
        planner = Planner(intents=mock_intent_registry)
        plan = planner._rule_based_plan("销售额趋势")
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description

    def test_rule_based_plan_single_query(self, mock_intent_registry):
        """Rule-based plan for single_query intent."""
        planner = Planner(intents=mock_intent_registry)
        plan = planner._rule_based_plan("查询华东销售额")
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1


@pytest.mark.asyncio
class TestPlannerPlanAsync:
    """Tests for Planner.plan async method."""

    async def test_plan_no_llm_uses_rules(self, mock_intent_registry):
        """When no LLM, plan() uses rule-based planning."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        plan = await planner.plan("对比华东和华南的销售额")
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2

    async def test_plan_with_llm_success(self, mock_intent_registry):
        """When LLM succeeds, plan() returns LLM plan."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(return_value=json.dumps({
            "intent": "compare",
            "sub_queries": [
                {"id": "sq-1", "description": "华东销售额", "depends_on": []},
                {"id": "sq-2", "description": "华南销售额", "depends_on": []},
            ],
            "reasoning": "对比两个地区",
            "requires_approval": False,
        }))

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("对比华东和华南的销售额")

        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert plan.sub_queries[0].description == "华东销售额"
        assert plan.reasoning == "对比两个地区"
        llm_client.agenerate.assert_called_once()

    async def test_plan_with_llm_sync_generate(self, mock_intent_registry):
        """When LLM only has sync generate, plan() still works."""
        llm_client = MagicMock()
        # No agenerate, only generate
        llm_client.agenerate = None
        llm_client.generate.return_value = json.dumps({
            "intent": "trend",
            "sub_queries": [
                {"id": "sq-1", "description": "销售趋势", "depends_on": []},
            ],
            "reasoning": "趋势分析",
        })

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("销售额趋势")

        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        llm_client.generate.assert_called_once()

    async def test_plan_with_llm_exception_falls_back(self, mock_intent_registry):
        """When LLM raises exception, plan() falls back to rules."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(side_effect=Exception("LLM timeout"))

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("对比华东和华南的销售额")

        # Should fall back to rule-based
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2

    async def test_plan_with_llm_invalid_json_falls_back(self, mock_intent_registry):
        """When LLM returns invalid JSON, plan() falls back to rules."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(return_value="not valid json")

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("销售额趋势")

        # Should fall back to rule-based
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1

    async def test_plan_with_registry_dict(self, mock_intent_registry):
        """plan() passes registry_dict to LLM prompt."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(return_value=json.dumps({
            "intent": "single_query",
            "sub_queries": [
                {"id": "sq-1", "description": "查询", "depends_on": []},
            ],
            "reasoning": "简单查询",
        }))

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        registry = {"metrics": {"sales": {"description": "销售额"}}}
        await planner.plan("查询销售额", registry_dict=registry)

        # Verify the prompt contained the metric
        call_args = llm_client.agenerate.call_args[0]
        prompt = call_args[0]
        assert "sales" in prompt
        assert "销售额" in prompt

    async def test_plan_llm_empty_response_falls_back(self, mock_intent_registry):
        """When LLM returns empty response, plan() falls back to rules."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(return_value="")

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("查询华东销售额")

        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1

    async def test_fallback_when_llm_fails(self, mock_intent_registry):
        """Explicit test: LLM failure falls back to rule-based plan."""
        llm_client = MagicMock()
        llm_client.agenerate = AsyncMock(side_effect=ConnectionError("LLM unreachable"))

        planner = Planner(llm_client=llm_client, intents=mock_intent_registry)
        plan = await planner.plan("对比今年和去年的销售额")

        # Fallback should still produce a valid plan
        assert isinstance(plan, Plan)
        assert plan.intent == "compare"
        assert len(plan.sub_queries) >= 1
        assert all(isinstance(sq, SubQuery) for sq in plan.sub_queries)


# ---------------------------------------------------------------------------
# Tests for rule-based plan via Planner.plan (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRuleBasedPlan:
    """Tests for rule-based planning through Planner.plan()."""

    async def test_rule_based_plan_compare(self, mock_intent_registry):
        """Rule-based plan for compare produces 2 sub-queries."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        plan = await planner.plan("对比华东和华南的销售额")

        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert "华东" in plan.sub_queries[0].description
        assert "华南" in plan.sub_queries[1].description

    async def test_rule_based_plan_trend(self, mock_intent_registry):
        """Rule-based plan for trend produces 1 sub-query with time grouping."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        plan = await planner.plan("销售额趋势")

        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description

    async def test_rule_based_plan_correlation(self, mock_intent_registry):
        """Rule-based plan for correlation produces 2 sub-queries."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        plan = await planner.plan("销售额和订单量的关系")

        assert plan.intent == "correlation"
        assert len(plan.sub_queries) == 2
        assert "销售额" in plan.sub_queries[0].description
        assert "订单量" in plan.sub_queries[1].description

    async def test_rule_based_plan_single_query(self, mock_intent_registry):
        """Rule-based plan for single_query produces 1 sub-query."""
        planner = Planner(llm_client=None, intents=mock_intent_registry)
        plan = await planner.plan("查询华东销售额")

        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "查询华东销售额"


# ---------------------------------------------------------------------------
# Tests for planner using intent config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPlannerUsesIntentConfig:
    """Tests that Planner uses IntentRegistry config for decomposition."""

    async def test_planner_uses_intent_config_decomposition(self):
        """Planner should use decomposition strategy from intent config."""
        custom_registry = IntentRegistry(
            intents={
                "custom_intent": IntentConfig(
                    keywords=["custom"],
                    decomposition="total_plus_groups",
                    aggregation="custom_agg",
                    description="Custom intent for testing",
                ),
                "single_query": IntentConfig(
                    keywords=[],
                    decomposition="passthrough",
                    aggregation="passthrough",
                    description="Fallback",
                ),
            }
        )

        planner = Planner(llm_client=None, intents=custom_registry)
        plan = await planner.plan("custom test question")

        # Should use total_plus_groups decomposition
        assert plan.intent == "custom_intent"
        assert len(plan.sub_queries) == 2
        assert "总计" in plan.sub_queries[0].description
        assert "分组明细" in plan.sub_queries[1].description

    async def test_planner_uses_config_keywords(self):
        """Planner should match keywords defined in intent config."""
        custom_registry = IntentRegistry(
            intents={
                "special": IntentConfig(
                    keywords=["special_keyword"],
                    decomposition="single_with_ordering",
                    aggregation="special",
                    description="Special intent",
                ),
                "single_query": IntentConfig(
                    keywords=[],
                    decomposition="passthrough",
                    aggregation="passthrough",
                    description="Fallback",
                ),
            }
        )

        planner = Planner(llm_client=None, intents=custom_registry)
        plan = await planner.plan("分析 special_keyword 数据")

        assert plan.intent == "special"
        assert len(plan.sub_queries) == 1
        assert "按排序" in plan.sub_queries[0].description

    async def test_planner_default_registry_loads_from_file(self):
        """Planner without explicit intents should load from default file."""
        planner = Planner(llm_client=None)
        plan = await planner.plan("对比华东和华南的销售额")

        # Should use the default intents.yaml config
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2


# ---------------------------------------------------------------------------
# Tests for _build_plan_prompt
# ---------------------------------------------------------------------------


class TestBuildPlanPrompt:
    """Tests for LLM plan prompt builder."""

    def test_prompt_contains_question(self):
        """Prompt should contain the user question."""
        registry = {"metrics": {}, "dimensions": {}}
        prompt = _build_plan_prompt("查询销售额", registry)
        assert "查询销售额" in prompt

    def test_prompt_contains_metrics(self):
        """Prompt should list available metrics."""
        registry = {
            "metrics": {
                "sales_amount": {"description": "销售额"},
                "order_count": {"description": "订单数"},
            },
        }
        prompt = _build_plan_prompt("test", registry)
        assert "sales_amount" in prompt
        assert "销售额" in prompt
        assert "order_count" in prompt

    def test_prompt_contains_dimensions(self):
        """Prompt should list available dimensions."""
        registry = {
            "dimensions": {
                "region": {"description": "地区"},
                "product_name": {"description": "产品"},
            },
        }
        prompt = _build_plan_prompt("test", registry)
        assert "region" in prompt
        assert "地区" in prompt

    def test_prompt_contains_output_format(self):
        """Prompt should specify JSON output format."""
        registry = {}
        prompt = _build_plan_prompt("test", registry)
        assert "JSON" in prompt
        assert "intent" in prompt
        assert "sub_queries" in prompt

    def test_empty_registry(self):
        """Prompt should handle empty registry gracefully."""
        prompt = _build_plan_prompt("test", {})
        assert "test" in prompt
        assert "可用指标" in prompt


# ---------------------------------------------------------------------------
# Tests for _make_plan_node (LangGraph backward compatibility)
# ---------------------------------------------------------------------------


class TestMakePlanNode:
    """Tests for the graph node factory."""

    def test_plan_node_no_llm_fallback(self):
        """When LLM is None, plan_node uses fallback classification."""
        plan_node = _make_plan_node(llm_client=None, registry_dict={})

        state = {
            "question": "对比华东和华南的销售额",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        assert "plan" in result
        assert "trace" in result
        plan = result["plan"]
        assert isinstance(plan, Plan)
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert result["trace"]["step"] == "plan"
        assert result["trace"]["status"] == "success"
        assert result["trace"]["source"] == "fallback"

    def test_plan_node_single_query(self):
        """Single query question produces single sub-query plan."""
        plan_node = _make_plan_node(llm_client=None, registry_dict={})

        state = {
            "question": "查询华东销售额",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        plan = result["plan"]
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].description == "查询华东销售额"

    def test_plan_node_with_llm(self):
        """When LLM is available, plan_node uses LLM output."""
        llm_client = MagicMock()
        llm_response = json.dumps({
            "intent": "compare",
            "sub_queries": [
                {"id": "sq-1", "description": "Get 2023 sales", "depends_on": []},
                {"id": "sq-2", "description": "Get 2024 sales", "depends_on": []},
            ],
            "reasoning": "User wants to compare two years",
            "requires_approval": False,
        })
        llm_client.generate.return_value = llm_response

        plan_node = _make_plan_node(llm_client=llm_client, registry_dict={})

        state = {
            "question": "对比今年和去年",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        plan = result["plan"]
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert plan.sub_queries[0].id == "sq-1"
        assert plan.sub_queries[1].id == "sq-2"
        assert plan.reasoning == "User wants to compare two years"
        assert result["trace"]["source"] == "llm"
        llm_client.generate.assert_called_once()

    def test_plan_node_llm_json_decode_error(self):
        """When LLM returns invalid JSON, falls back to keyword classification."""
        llm_client = MagicMock()
        llm_client.generate.return_value = "not valid json"

        plan_node = _make_plan_node(llm_client=llm_client, registry_dict={})

        state = {
            "question": "对比华东和华南",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        plan = result["plan"]
        assert plan.intent == "compare"
        assert result["trace"]["source"] == "fallback"

    def test_plan_node_llm_markdown_json(self):
        """When LLM returns JSON in markdown code block, parse it correctly."""
        llm_client = MagicMock()
        llm_response = "```json\n" + json.dumps({
            "intent": "trend",
            "sub_queries": [
                {"id": "sq-1", "description": "Sales trend", "depends_on": []},
            ],
            "reasoning": "User wants trend",
        }) + "\n```"
        llm_client.generate.return_value = llm_response

        plan_node = _make_plan_node(llm_client=llm_client, registry_dict={})

        state = {
            "question": "销售额趋势",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        plan = result["plan"]
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert result["trace"]["source"] == "llm"

    def test_plan_node_llm_exception(self):
        """When LLM raises exception, falls back to keyword classification."""
        llm_client = MagicMock()
        llm_client.generate.side_effect = Exception("LLM timeout")

        plan_node = _make_plan_node(llm_client=llm_client, registry_dict={})

        state = {
            "question": "趋势分析",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)

        plan = result["plan"]
        assert plan.intent == "trend"
        assert result["trace"]["source"] == "fallback"

    def test_plan_node_error_handler(self):
        """Error handler catches exceptions and returns error state."""
        # Create a plan_node with a broken LLM that raises during generate
        llm_client = MagicMock()
        llm_client.generate.side_effect = RuntimeError("unexpected")

        plan_node = _make_plan_node(llm_client=llm_client, registry_dict={})

        # Use a state that will trigger fallback (which should work)
        state = {
            "question": "查询销售额",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        # Should not raise — error handler wraps it
        result = plan_node(state)

        # Fallback should still produce a plan
        assert "plan" in result or "status" in result


# ---------------------------------------------------------------------------
# Integration-style tests for the plan node
# ---------------------------------------------------------------------------


class TestPlanNodeIntegration:
    """Integration-style tests for the plan node."""

    def test_end_to_end_compare(self):
        """Full flow: compare question -> plan with 2 sub-queries."""
        plan_node = _make_plan_node(llm_client=None, registry_dict={})

        state = {
            "question": "对比VIP客户和普通客户的销售额",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)
        plan = result["plan"]

        assert plan.intent == "compare"
        assert len(plan.sub_queries) >= 1
        assert all(isinstance(sq, SubQuery) for sq in plan.sub_queries)
        assert plan.reasoning != ""

    def test_end_to_end_trend(self):
        """Full flow: trend question -> plan with time grouping note."""
        plan_node = _make_plan_node(llm_client=None, registry_dict={})

        state = {
            "question": "最近三个月销售额走势",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)
        plan = result["plan"]

        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description

    def test_end_to_end_correlation(self):
        """Full flow: correlation question -> plan with multiple sub-queries."""
        plan_node = _make_plan_node(llm_client=None, registry_dict={})

        state = {
            "question": "销售额和订单量的关系",
            "domain": "ecommerce",
            "user_id": "u1",
            "tenant_id": "t1",
            "data_source": None,
            "original_question": None,
            "rewrite_reason": None,
            "verify_status": None,
            "verify_reason": None,
            "ambiguities": None,
            "dsl": None,
            "dsl_attempts": None,
            "sql": None,
            "sandbox_result": None,
            "complexity": None,
            "data": None,
            "status": "pending",
            "error": None,
            "error_code": None,
            "trace": None,
            "query_id": "q1",
            "started_at": 0.0,
            "llm_used": False,
            "plan": None,
        }

        result = plan_node(state)
        plan = result["plan"]

        assert plan.intent == "correlation"
        assert len(plan.sub_queries) >= 2
        assert "销售额" in plan.sub_queries[0].description
        assert "订单量" in plan.sub_queries[1].description
