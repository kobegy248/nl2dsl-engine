"""Unit tests for nl2dsl.agent.planner."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nl2dsl.agent.models import Plan, SubQuery
from nl2dsl.agent.planner import (
    _build_plan_prompt,
    _decompose_fallback,
    _make_plan_node,
    classify_intent,
)


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
