"""Unit tests for nl2dsl.agent.explainer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nl2dsl.agent.explainer import (
    _build_explanation_prompt,
    _format_data_summary,
    _generate_template_explanation,
    _make_explain_node,
)
from nl2dsl.agent.models import Plan, SubQuery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_base_state(
    plan: Plan | None = None,
    question: str = "查询华东销售额",
    data: list[dict] | None = None,
) -> dict:
    """Create a base state dict for explainer node tests."""
    return {
        "question": question,
        "domain": "ecommerce",
        "user_id": "u1",
        "tenant_id": "t1",
        "data_source": None,
        "original_question": None,
        "rewrite_reason": None,
        "verify_status": None,
        "verify_reason": None,
        "ambiguities": None,
        "plan": plan,
        "dsl": None,
        "dsl_attempts": None,
        "sql": None,
        "sandbox_result": None,
        "complexity": None,
        "data": data if data is not None else [],
        "status": "pending",
        "error": None,
        "error_code": None,
        "trace": None,
        "query_id": "q1",
        "started_at": 0.0,
        "llm_used": False,
        "confidence": None,
        "explanation": None,
    }


def _make_plan(intent: str = "single_query", reasoning: str = "") -> Plan:
    """Create a Plan for testing."""
    return Plan(
        intent=intent,
        sub_queries=[SubQuery(id="sq-1", description="test query", depends_on=[])],
        reasoning=reasoning or "测试推理",
    )


# ---------------------------------------------------------------------------
# _format_data_summary
# ---------------------------------------------------------------------------


class TestFormatDataSummary:
    """Tests for _format_data_summary helper."""

    def test_empty_data(self):
        """Empty data returns empty string."""
        assert _format_data_summary([]) == ""

    def test_single_row(self):
        """Single row formats correctly."""
        data = [{"region": "华东", "sales": 100}]
        result = _format_data_summary(data)
        assert "region=华东" in result
        assert "sales=100" in result

    def test_multiple_rows_truncated(self):
        """Only first max_rows rows are shown."""
        data = [
            {"a": 1},
            {"a": 2},
            {"a": 3},
            {"a": 4},
        ]
        result = _format_data_summary(data, max_rows=3)
        assert result.count("a=") == 3
        assert "..." in result

    def test_custom_max_rows(self):
        """max_rows parameter controls truncation."""
        data = [{"x": i} for i in range(10)]
        result = _format_data_summary(data, max_rows=5)
        assert result.count("x=") == 5
        assert "共10条" in result

    def test_row_separator(self):
        """Rows are separated by semicolons."""
        data = [{"a": 1}, {"a": 2}]
        result = _format_data_summary(data)
        assert "; " in result


# ---------------------------------------------------------------------------
# _build_explanation_prompt
# ---------------------------------------------------------------------------


class TestBuildExplanationPrompt:
    """Tests for _build_explanation_prompt helper."""

    def test_prompt_contains_question(self):
        """Prompt should contain the user question."""
        plan = _make_plan("single_query", "查询华东销售额")
        data = [{"sales": 100}]
        prompt = _build_explanation_prompt("查询华东销售额", plan, data)
        assert "查询华东销售额" in prompt

    def test_prompt_contains_intent(self):
        """Prompt should contain the plan intent."""
        plan = _make_plan("compare", "对比分析")
        prompt = _build_explanation_prompt("test", plan, [])
        assert "compare" in prompt

    def test_prompt_contains_reasoning(self):
        """Prompt should contain the plan reasoning."""
        plan = _make_plan("single_query", "这是推理过程")
        prompt = _build_explanation_prompt("test", plan, [])
        assert "这是推理过程" in prompt

    def test_prompt_contains_data_summary(self):
        """Prompt should contain formatted data summary."""
        plan = _make_plan("single_query")
        data = [{"region": "华东", "sales": 100}]
        prompt = _build_explanation_prompt("test", plan, data)
        assert "region=华东" in prompt

    def test_prompt_asks_for_first_person(self):
        """Prompt should ask for first person '我'."""
        plan = _make_plan("single_query")
        prompt = _build_explanation_prompt("test", plan, [])
        assert "我" in prompt

    def test_prompt_asks_for_concise(self):
        """Prompt should ask for concise explanation under 200 chars."""
        plan = _make_plan("single_query")
        prompt = _build_explanation_prompt("test", plan, [])
        assert "200" in prompt


# ---------------------------------------------------------------------------
# _generate_template_explanation
# ---------------------------------------------------------------------------


class TestGenerateTemplateExplanation:
    """Tests for template-based explanation generation."""

    def test_single_query(self):
        """single_query intent uses correct template."""
        plan = _make_plan("single_query", "查询华东地区销售数据")
        data = [{"region": "华东", "sales": 100}]
        result = _generate_template_explanation("查询华东销售额", plan, data)
        assert "您的问题是" in result
        assert "查询华东销售额" in result
        assert "查询结果为" in result
        assert "region=华东" in result

    def test_compare(self):
        """compare intent uses correct template."""
        plan = Plan(
            intent="compare",
            sub_queries=[
                SubQuery(id="sq-1", description="华东销售额", depends_on=[]),
                SubQuery(id="sq-2", description="华南销售额", depends_on=[]),
            ],
            reasoning="对比两个地区",
        )
        data = [{"region": "华东", "sales": 100}, {"region": "华南", "sales": 200}]
        result = _generate_template_explanation("对比华东和华南销售额", plan, data)
        assert "您的问题是" in result
        assert "对比两个地区" in result
        assert "其中" in result

    def test_trend(self):
        """trend intent uses correct template."""
        plan = _make_plan("trend", "分析销售趋势")
        data = [
            {"month": "2024-01", "sales": 100},
            {"month": "2024-02", "sales": 200},
        ]
        result = _generate_template_explanation("销售额趋势", plan, data)
        assert "您的问题是" in result
        assert "分析销售趋势" in result
        assert "呈上升趋势" in result

    def test_trend_down(self):
        """trend with decreasing data shows down trend."""
        plan = _make_plan("trend", "分析销售趋势")
        data = [
            {"month": "2024-01", "sales": 300},
            {"month": "2024-02", "sales": 200},
            {"month": "2024-03", "sales": 100},
        ]
        result = _generate_template_explanation("销售额趋势", plan, data)
        assert "呈下降趋势" in result

    def test_trend_flat(self):
        """trend with flat data shows flat trend."""
        plan = _make_plan("trend", "分析销售趋势")
        data = [
            {"month": "2024-01", "sales": 100},
            {"month": "2024-02", "sales": 100},
        ]
        result = _generate_template_explanation("销售额趋势", plan, data)
        assert "基本持平" in result

    def test_trend_insufficient_data(self):
        """trend with less than 2 data points shows flat."""
        plan = _make_plan("trend", "分析销售趋势")
        data = [{"month": "2024-01", "sales": 100}]
        result = _generate_template_explanation("销售额趋势", plan, data)
        assert "数据点不足" in result

    def test_correlation(self):
        """correlation intent uses correct template."""
        plan = _make_plan("correlation", "分析关联性")
        data = [
            {"x": 1, "y": 2},
            {"x": 2, "y": 4},
            {"x": 3, "y": 6},
        ]
        result = _generate_template_explanation("销售额和订单量关系", plan, data)
        assert "您的问题是" in result
        assert "分析关联性" in result
        assert "正相关" in result

    def test_correlation_negative(self):
        """correlation with negative trend."""
        plan = _make_plan("correlation", "分析关联性")
        data = [
            {"x": 1, "y": 10},
            {"x": 2, "y": 5},
            {"x": 3, "y": 1},
        ]
        result = _generate_template_explanation("销售额和订单量关系", plan, data)
        assert "负相关" in result

    def test_correlation_insufficient_data(self):
        """correlation with less than 2 points shows no correlation."""
        plan = _make_plan("correlation", "分析关联性")
        data = [{"x": 1, "y": 2}]
        result = _generate_template_explanation("销售额和订单量关系", plan, data)
        assert "数据点不足" in result

    def test_empty_data(self):
        """Empty data still produces explanation."""
        plan = _make_plan("single_query", "查询数据")
        result = _generate_template_explanation("查询销售额", plan, [])
        assert "您的问题是" in result
        assert "未查询到相关数据" in result


# ---------------------------------------------------------------------------
# _make_explain_node
# ---------------------------------------------------------------------------


class TestMakeExplainNode:
    """Tests for the graph node factory."""

    def test_explain_node_no_llm_fallback(self):
        """When LLM is None, uses template-based explanation."""
        explain_node = _make_explain_node(llm_client=None)

        plan = _make_plan("single_query", "查询华东销售数据")
        state = _make_base_state(plan=plan, data=[{"region": "华东", "sales": 100}])

        result = explain_node(state)

        assert "explanation" in result
        assert "trace" in result
        assert "您的问题是" in result["explanation"]
        assert result["trace"]["step"] == "explain"
        assert result["trace"]["status"] == "success"
        assert result["trace"]["source"] == "template"

    def test_explain_node_with_llm(self):
        """When LLM is available, uses LLM-generated explanation."""
        llm_client = MagicMock()
        llm_client.generate.return_value = "我查询了华东地区的销售额，结果为100元。"

        explain_node = _make_explain_node(llm_client=llm_client)

        plan = _make_plan("single_query", "查询华东销售数据")
        state = _make_base_state(plan=plan, data=[{"region": "华东", "sales": 100}])

        result = explain_node(state)

        assert "explanation" in result
        assert result["explanation"] == "我查询了华东地区的销售额，结果为100元。"
        assert result["trace"]["source"] == "llm"
        llm_client.generate.assert_called_once()

    def test_explain_node_no_plan_creates_default(self):
        """When no plan in state, creates default single-query plan."""
        explain_node = _make_explain_node(llm_client=None)

        state = _make_base_state(plan=None, question="查询华东销售额", data=[{"sales": 100}])

        result = explain_node(state)

        assert "explanation" in result
        assert "您的问题是" in result["explanation"]
        assert "查询华东销售额" in result["explanation"]

    def test_explain_node_llm_empty_response_fallback(self):
        """When LLM returns empty, falls back to template."""
        llm_client = MagicMock()
        llm_client.generate.return_value = ""

        explain_node = _make_explain_node(llm_client=llm_client)

        plan = _make_plan("single_query", "查询数据")
        state = _make_base_state(plan=plan, data=[{"sales": 100}])

        result = explain_node(state)

        assert "explanation" in result
        assert result["trace"]["source"] == "template"

    def test_explain_node_llm_exception_fallback(self):
        """When LLM raises exception, falls back to template."""
        llm_client = MagicMock()
        llm_client.generate.side_effect = Exception("LLM timeout")

        explain_node = _make_explain_node(llm_client=llm_client)

        plan = _make_plan("single_query", "查询数据")
        state = _make_base_state(plan=plan, data=[{"sales": 100}])

        result = explain_node(state)

        assert "explanation" in result
        assert result["trace"]["source"] == "template"

    def test_explain_node_compare_intent(self):
        """Compare intent produces appropriate explanation."""
        explain_node = _make_explain_node(llm_client=None)

        plan = Plan(
            intent="compare",
            sub_queries=[
                SubQuery(id="sq-1", description="华东销售额", depends_on=[]),
                SubQuery(id="sq-2", description="华南销售额", depends_on=[]),
            ],
            reasoning="对比两个地区销售",
        )
        state = _make_base_state(
            plan=plan,
            question="对比华东和华南销售额",
            data=[{"region": "华东", "sales": 100}, {"region": "华南", "sales": 200}],
        )

        result = explain_node(state)

        assert "explanation" in result
        assert "对比两个地区销售" in result["explanation"]

    def test_explain_node_trend_intent(self):
        """Trend intent produces appropriate explanation."""
        explain_node = _make_explain_node(llm_client=None)

        plan = _make_plan("trend", "分析销售趋势")
        state = _make_base_state(
            plan=plan,
            question="销售额趋势",
            data=[
                {"month": "2024-01", "sales": 100},
                {"month": "2024-02", "sales": 200},
            ],
        )

        result = explain_node(state)

        assert "explanation" in result
        assert "呈上升趋势" in result["explanation"]

    def test_explain_node_correlation_intent(self):
        """Correlation intent produces appropriate explanation."""
        explain_node = _make_explain_node(llm_client=None)

        plan = _make_plan("correlation", "分析关联性")
        state = _make_base_state(
            plan=plan,
            question="销售额和订单量关系",
            data=[
                {"x": 1, "y": 2},
                {"x": 2, "y": 4},
                {"x": 3, "y": 6},
            ],
        )

        result = explain_node(state)

        assert "explanation" in result
        assert "正相关" in result["explanation"]

    def test_explain_node_trace_structure(self):
        """Trace should have correct structure."""
        explain_node = _make_explain_node(llm_client=None)

        plan = _make_plan("single_query")
        state = _make_base_state(plan=plan, data=[{"sales": 100}])

        result = explain_node(state)

        trace = result["trace"]
        assert trace["step"] == "explain"
        assert trace["status"] == "success"
        assert "source" in trace

    def test_explain_node_error_handler(self):
        """Error handler catches exceptions and returns error state."""
        llm_client = MagicMock()
        llm_client.generate.side_effect = RuntimeError("unexpected")

        explain_node = _make_explain_node(llm_client=llm_client)

        # Even with exception in LLM, fallback should work
        plan = _make_plan("single_query")
        state = _make_base_state(plan=plan, data=[{"sales": 100}])

        # Should not raise — error handler wraps it, and fallback handles LLM failure
        result = explain_node(state)

        assert "explanation" in result or "status" in result
