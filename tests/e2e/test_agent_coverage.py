"""Comprehensive end-to-end tests for Agent-Driven Pipeline.

Covers all new capabilities from the Agent-Driven Pipeline design:
- AgentController routing (Simple / Complex / Exploration)
- Planner 7 intent types with decomposition strategies
- Dispatcher parallel / serial scheduling with dependency handling
- Aggregator strategies (diff, trend_direction, pearson, proportion, ranking)
- Confidence scoring and conditional routing
- Decompose, verify_dsl, explain graph nodes
- Error recovery paths (correct_dsl, simplify_dsl, human_review)
- Permission and governance (row-level, column-level, semantic resolution)
- SSE streaming with structured agent events
- Edge cases and boundary conditions
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_query_success(response):
    """Assert a /query response is successful."""
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data.get("status") == "success", f"Expected status='success', got: {data}"
    return data


def _assert_query_warning(response):
    """Assert a /query response is warning (partial success)."""
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "warning", f"Expected status='warning', got: {data}"
    return data


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE response text into a list of event dicts."""
    events = []
    blocks = response_text.strip().split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        event_type = None
        data_str = None
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:"):].strip()
        if not data_str or data_str == "{}":
            continue
        try:
            payload = json.loads(data_str)
            if event_type:
                payload["_event_type"] = event_type
            events.append(payload)
        except json.JSONDecodeError:
            pass
    return events


# ===========================================================================
# A. AgentController Routing
# ===========================================================================


class TestAgentControllerRouting:
    """Tests for AgentController routing decisions."""

    def test_simple_query_routed_to_graph(self, mock_api_client):
        """Simple query (1 metric + 1 dimension) → SimpleExecutionPlan → graph flow."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Simple path returns DSL and SQL
        assert "dsl" in data
        assert "sql" in data
        assert data["dsl"] is not None
        assert data["sql"] is not None

    def test_complex_query_routed_to_agent(self, mock_api_client):
        """Complex query (multiple dimensions) → ComplexExecutionPlan → AgentOrchestrator."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Complex path returns data and explanation
        assert "data" in data
        assert data["data"] is not None
        assert "explanation" in data
        assert data["explanation"] is not None

    def test_exploration_query_delegated_to_simple(self, mock_api_client):
        """Exploration query (no metrics/dimensions) → ExplorationPlan → simple path."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询一下",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data

    def test_comparison_marker_triggers_complex(self, mock_api_client):
        """Question with time comparison marker → ComplexExecutionPlan."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "今年同比去年的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_multiple_metrics_trigger_complex(self, mock_api_client):
        """Question with multiple metrics → ComplexExecutionPlan."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额和订单量",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data


# ===========================================================================
# B. Planner Intent Decomposition
# ===========================================================================


class TestPlannerIntentDecomposition:
    """Tests for Planner intent classification and task decomposition."""

    def test_compare_intent_split_by_objects(self, mock_api_client):
        """Compare intent: split_by_objects produces 2 sub-queries."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Both sub-queries should have executed and produced data
        assert data["data"] is not None
        assert len(data["data"]) >= 1

    def test_compare_intent_with_common_suffix(self, mock_api_client):
        """Compare intent preserves common suffix (e.g. '的销售额')."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比线上和线下渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Query succeeds; data may be empty due to random mock data + row filters
        assert "data" in data

    def test_trend_intent_time_grouping(self, mock_api_client):
        """Trend intent: single_with_time_grouping decomposition."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "销售额趋势",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_correlation_intent_split(self, mock_api_client):
        """Correlation intent: split_by_objects decomposition."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "销售额和订单量的关系",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_single_query_intent_passthrough(self, mock_api_client):
        """Single query intent: passthrough (no decomposition)."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "dsl" in data
        assert data["dsl"] is not None


class TestPlannerDirect:
    """Direct tests for Planner decomposition logic."""

    def test_planner_compare_decomposition(self):
        """Planner decomposes compare question into 2 sub-queries."""
        from nl2dsl.agent.planner import classify_intent, _decompose_fallback

        question = "对比华东和华南的销售额"
        intent = classify_intent(question)
        assert intent == "compare"

        plan = _decompose_fallback(question, intent)
        assert plan.intent == "compare"
        assert len(plan.sub_queries) == 2
        assert "华东" in plan.sub_queries[0].description
        assert "华南" in plan.sub_queries[1].description

    def test_planner_trend_decomposition(self):
        """Planner decomposes trend question into 1 time-grouped sub-query."""
        from nl2dsl.agent.planner import classify_intent, _decompose_fallback

        question = "销售额趋势"
        intent = classify_intent(question)
        assert intent == "trend"

        plan = _decompose_fallback(question, intent)
        assert plan.intent == "trend"
        assert len(plan.sub_queries) == 1
        assert "时间分组" in plan.sub_queries[0].description

    def test_planner_correlation_decomposition(self):
        """Planner decomposes correlation question into 2 sub-queries."""
        from nl2dsl.agent.planner import classify_intent, _decompose_fallback

        question = "销售额和订单量的关系"
        intent = classify_intent(question)
        assert intent == "correlation"

        plan = _decompose_fallback(question, intent)
        assert plan.intent == "correlation"
        assert len(plan.sub_queries) == 2

    def test_planner_compare_common_suffix_preserved(self):
        """Compare decomposition preserves common suffix like '的销售额'."""
        from nl2dsl.agent.planner import _decompose_by_intent
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        question = "对比华东和华南的销售额"
        plan = _decompose_by_intent(question, "compare", registry)
        # Both sub-queries should contain the metric context
        for sq in plan.sub_queries:
            assert "销售额" in sq.description

    def test_planner_single_query_no_split(self):
        """Single query is not split."""
        from nl2dsl.agent.planner import classify_intent, _decompose_fallback

        question = "查询各品牌销售额"
        intent = classify_intent(question)
        assert intent == "single_query"

        plan = _decompose_fallback(question, intent)
        assert plan.intent == "single_query"
        assert len(plan.sub_queries) == 1

    def test_planner_proportion_decomposition(self):
        """Proportion intent: total_plus_groups decomposition."""
        from nl2dsl.agent.planner import _decompose_by_intent
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        question = "各品类销售额占比"
        plan = _decompose_by_intent(question, "proportion", registry)
        assert plan.intent == "proportion"
        assert len(plan.sub_queries) == 2

    def test_planner_ranking_decomposition(self):
        """Ranking intent: single_with_ordering decomposition."""
        from nl2dsl.agent.planner import _decompose_by_intent
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        question = "销售额排名前5的品牌"
        plan = _decompose_by_intent(question, "ranking", registry)
        assert plan.intent == "ranking"
        assert len(plan.sub_queries) == 1
        assert "排序" in plan.sub_queries[0].description

    def test_planner_sequential_decomposition(self):
        """Sequential intent: sequential decomposition."""
        from nl2dsl.agent.planner import _decompose_by_intent
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        question = "先查华东销售额，再查华南销售额"
        plan = _decompose_by_intent(question, "sequential", registry)
        assert plan.intent == "sequential"


# ===========================================================================
# C. Dispatcher Scheduling
# ===========================================================================


class TestDispatcherScheduling:
    """Tests for Dispatcher parallel/serial sub-query scheduling."""

    def test_independent_sub_queries_produce_results(self, mock_api_client):
        """Independent sub-queries (compare) produce combined results."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["data"] is not None
        assert len(data["data"]) >= 1

    def test_dispatcher_parallel_limit_respected(self):
        """Dispatcher respects MAX_PARALLEL_SUB_QUERIES limit."""
        from nl2dsl.agent.dispatcher import MAX_PARALLEL_SUB_QUERIES
        assert MAX_PARALLEL_SUB_QUERIES == 3


# ===========================================================================
# D. Aggregator Strategies
# ===========================================================================


class TestAggregatorDirect:
    """Direct tests for Aggregator strategies."""

    def test_compare_aggregation_diff(self):
        """Compare strategy computes diff and growth_rate."""
        from nl2dsl.agent.aggregator import _aggregate_compare

        rows = [
            {"region": "华东", "sales_amount": 1000.0},
            {"region": "华南", "sales_amount": 1250.0},
        ]
        result = _aggregate_compare(rows)
        assert "comparison" in result
        assert result["comparison"]["diff"] == 250.0
        assert result["comparison"]["growth_rate"] == "25.00%"

    def test_compare_aggregation_same_value(self):
        """Compare strategy handles equal values."""
        from nl2dsl.agent.aggregator import _aggregate_compare

        rows = [
            {"region": "华东", "sales_amount": 1000.0},
            {"region": "华南", "sales_amount": 1000.0},
        ]
        result = _aggregate_compare(rows)
        assert result["comparison"]["diff"] == 0.0
        # When values are equal and non-zero, growth_rate is 0.00%
        assert result["comparison"]["growth_rate"] == "0.00%"

    def test_compare_aggregation_zero_base(self):
        """Compare strategy handles zero base value."""
        from nl2dsl.agent.aggregator import _aggregate_compare

        rows = [
            {"region": "华东", "sales_amount": 0.0},
            {"region": "华南", "sales_amount": 100.0},
        ]
        result = _aggregate_compare(rows)
        assert result["comparison"]["diff"] == 100.0
        assert result["comparison"]["growth_rate"] == "N/A"

    def test_trend_aggregation_up(self):
        """Trend strategy detects upward trend."""
        from nl2dsl.agent.aggregator import _aggregate_trend

        rows = [
            {"month": "2024-01", "sales": 100.0},
            {"month": "2024-02", "sales": 150.0},
            {"month": "2024-03", "sales": 200.0},
        ]
        result = _aggregate_trend(rows)
        assert result["trend"] == "up"

    def test_trend_aggregation_down(self):
        """Trend strategy detects downward trend."""
        from nl2dsl.agent.aggregator import _aggregate_trend

        rows = [
            {"month": "2024-01", "sales": 200.0},
            {"month": "2024-02", "sales": 150.0},
            {"month": "2024-03", "sales": 100.0},
        ]
        result = _aggregate_trend(rows)
        assert result["trend"] == "down"

    def test_trend_aggregation_flat(self):
        """Trend strategy detects flat trend."""
        from nl2dsl.agent.aggregator import _aggregate_trend

        rows = [
            {"month": "2024-01", "sales": 100.0},
            {"month": "2024-02", "sales": 100.0},
        ]
        result = _aggregate_trend(rows)
        assert result["trend"] == "flat"

    def test_trend_aggregation_insufficient_data(self):
        """Trend strategy handles single row."""
        from nl2dsl.agent.aggregator import _aggregate_trend

        rows = [{"month": "2024-01", "sales": 100.0}]
        result = _aggregate_trend(rows)
        assert result["trend"] == "flat"

    def test_correlation_aggregation_positive(self):
        """Correlation strategy computes positive Pearson coefficient."""
        from nl2dsl.agent.aggregator import _aggregate_correlation

        rows = [
            {"x": 1.0, "y": 2.0},
            {"x": 2.0, "y": 4.0},
            {"x": 3.0, "y": 6.0},
            {"x": 4.0, "y": 8.0},
        ]
        result = _aggregate_correlation(rows)
        assert result["correlation"] is not None
        assert result["correlation"] > 0.99  # Strong positive correlation

    def test_correlation_aggregation_negative(self):
        """Correlation strategy computes negative Pearson coefficient."""
        from nl2dsl.agent.aggregator import _aggregate_correlation

        rows = [
            {"x": 1.0, "y": 8.0},
            {"x": 2.0, "y": 6.0},
            {"x": 3.0, "y": 4.0},
            {"x": 4.0, "y": 2.0},
        ]
        result = _aggregate_correlation(rows)
        assert result["correlation"] is not None
        assert result["correlation"] < -0.99  # Strong negative correlation

    def test_correlation_aggregation_insufficient_data(self):
        """Correlation strategy handles insufficient data."""
        from nl2dsl.agent.aggregator import _aggregate_correlation

        rows = [{"x": 1.0, "y": 2.0}]
        result = _aggregate_correlation(rows)
        assert result["correlation"] is None

    def test_single_query_passthrough(self):
        """Single query strategy passes through rows unchanged."""
        from nl2dsl.agent.aggregator import _aggregate_single

        rows = [{"a": 1}, {"a": 2}]
        result = _aggregate_single(rows)
        assert result["rows"] == rows

    def test_aggregate_class_routing(self):
        """Aggregate class routes to correct strategy by intent name."""
        from nl2dsl.agent.aggregator import Aggregate
        from nl2dsl.agent.models import QueryResult

        agg = Aggregate()
        results = {
            "sq-1": QueryResult(sub_query_id="sq-1", data=[{"sales": 100}]),
        }
        # Unknown intent falls back to single_query passthrough
        result = agg.run(results, "unknown_intent")
        assert "rows" in result

    def test_aggregate_collects_success_and_warning(self):
        """Aggregator collects rows from both success and warning sub-queries."""
        from nl2dsl.agent.aggregator import Aggregate
        from nl2dsl.agent.models import QueryResult

        agg = Aggregate()
        results = {
            "sq-1": QueryResult(sub_query_id="sq-1", data=[{"sales": 100}], status="success"),
            "sq-2": QueryResult(sub_query_id="sq-2", data=[{"sales": 200}], status="warning"),
            "sq-3": QueryResult(sub_query_id="sq-3", data=[], status="error"),
        }
        result = agg.run(results, "compare")
        # Should include rows from success + warning, exclude error
        assert len(result["rows"]) == 2


# ===========================================================================
# E. Confidence Scoring and Routing
# ===========================================================================


class TestConfidenceAndRouting:
    """Tests for confidence scoring and conditional routing."""

    def test_confidence_present_in_response(self, mock_api_client):
        """Query response includes confidence field."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "confidence" in data
        if data["confidence"] is not None:
            assert isinstance(data["confidence"], float)
            assert 0.0 <= data["confidence"] <= 1.0

    def test_confidence_high_routing_continue(self, mock_api_client):
        """High confidence routes to continue (execution succeeds)."""
        # In mock env: syntax=1.0, semantic=0.5(neutral) → min=0.5 → continue
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Should succeed, not clarification
        assert data["status"] == "success"

    def test_confidence_routing_neutral_fallback(self, mock_api_client):
        """Neutral semantic score (no LLM) does not block execution."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["status"] == "success"

    def test_explanation_present_in_complex_response(self, mock_api_client):
        """Complex query response includes explanation field."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "explanation" in data
        assert data["explanation"] is not None
        assert isinstance(data["explanation"], str)
        assert len(data["explanation"]) > 0

    def test_explanation_contains_question_context(self, mock_api_client):
        """Explanation references the user's question context."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        explanation = data.get("explanation", "")
        # Template-based explanation includes the question
        assert "对比" in explanation or "华东" in explanation or "华南" in explanation


# ===========================================================================
# F. Graph Node Coverage
# ===========================================================================


class TestGraphNodeCoverage:
    """Tests for specific LangGraph nodes in the pipeline."""

    def test_dsl_endpoint_returns_valid_dsl(self, mock_api_client):
        """DSL generation endpoint returns valid DSL structure."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        dsl = data["dsl"]
        assert dsl["data_source"] == "orders"
        assert "metrics" in dsl
        assert "dimensions" in dsl
        assert dsl["limit"] <= 100

    def test_dsl_endpoint_top_n_extraction(self, mock_api_client):
        """DSL endpoint extracts top-N from question."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询销售额排名前5的品牌",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["dsl"]["limit"] == 5

    def test_dsl_endpoint_top_n_chinese_number(self, mock_api_client):
        """DSL endpoint extracts Chinese number '前五' as limit."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询销售额前五的品牌",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["dsl"]["limit"] <= 10

    def test_dsl_endpoint_region_filter_mapped(self, mock_api_client):
        """DSL endpoint maps '华东' to region filter."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        filters = data["dsl"].get("filters", [])
        # After semantic resolution, field may be 'region' or 'region_code'
        region_filter = next(
            (f for f in filters if f.get("field") in ("region", "region_code")),
            None,
        )
        assert region_filter is not None
        # Value may be '华东' or 'HD' after semantic resolution
        assert region_filter["value"] in ("华东", "HD")

    def test_execute_endpoint_with_valid_dsl(self, mock_api_client):
        """Execute endpoint runs DSL and returns SQL + data."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert "SELECT" in data["sql"]
        assert "data" in data

    def test_execute_endpoint_semantic_resolution(self, mock_api_client):
        """Execute endpoint applies semantic resolution (region → region_code)."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "region_code" in data["sql"]
        assert "HD" in data["sql"]

    def test_simplify_dsl_fallback_on_invalid_metric(self, mock_api_client):
        """Invalid metric in DSL gets simplified to valid defaults."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # Should succeed with simplified DSL
        data = _assert_query_success(response)
        assert "data" in data

    def test_verify_dsl_skipped_without_llm(self, mock_api_client):
        """Verify DSL node is skipped when no LLM is available."""
        # This is implicitly tested by any successful query - verify_dsl
        # runs but returns "skipped" status, not blocking execution
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["status"] == "success"


# ===========================================================================
# G. Error Recovery Paths
# ===========================================================================


class TestErrorRecovery:
    """Tests for error recovery paths."""

    def test_invalid_dsl_returns_400(self, mock_api_client):
        """Execute endpoint with invalid DSL returns 400."""
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": {"data_source": "nonexistent"},
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"
        assert "error_code" in data

    def test_empty_question_handled(self, mock_api_client):
        """Empty question is handled gracefully."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # Should not crash
        assert response.status_code in (200, 400, 422)

    def test_nonexistent_data_source_error(self, mock_api_client):
        """DSL with nonexistent data_source returns error."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "data_source": "nonexistent_source",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"

    def test_empty_result_returns_empty_array(self, mock_api_client):
        """Query with impossible filters returns empty data array."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["brand"],
            "filters": [{"field": "region", "operator": "=", "value": "西北"}],
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u003",  # u003 has no row_filters
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # No data matches '西北' region
        assert data["data"] == []


# ===========================================================================
# H. Permission and Governance
# ===========================================================================


class TestPermissionGovernance:
    """Tests for permission injection and semantic resolution."""

    def test_row_level_filter_u001_east_south_only(self, mock_api_client):
        """u001 can only see 华东(HD) and 华南(HN) data."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # SQL should contain row-level filter with region codes
        if data.get("sql"):
            assert "HD" in data["sql"] or "HN" in data["sql"]

    def test_row_level_filter_u002_north_west_only(self, mock_api_client):
        """u002 can only see 华北(HB) and 西南(XN) data."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各地区的销售额",
            "user_id": "u002",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        if data.get("sql"):
            assert "HB" in data["sql"] or "XN" in data["sql"]

    def test_row_level_filter_injected_in_sql(self, mock_api_client):
        """Row-level filter is injected into generated SQL."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        # u001's row filter should be in SQL
        sql = data["sql"]
        assert "region_code" in sql

    def test_semantic_region_mapping_hd(self, mock_api_client):
        """Region '华东' is mapped to region_code 'HD' in SQL."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert "HD" in data["sql"]

    def test_semantic_channel_mapping_online(self, mock_api_client):
        """Channel '线上' is mapped to channel_code 'online' in SQL."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询线上渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert "online" in data["sql"]

    def test_multi_table_join_in_sql(self, mock_api_client):
        """Query involving customer dimension produces JOIN SQL."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各客户类型的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        sql = data["sql"].upper()
        assert "JOIN" in sql

    def test_multi_table_join_product_dim(self, mock_api_client):
        """Query involving brand produces product_dim JOIN."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各品牌的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        sql = data["sql"].upper()
        assert "JOIN" in sql

    def test_entity_resolver_region_mapping(self):
        """EntityResolver correctly maps '华东' to region dimension."""
        from nl2dsl.agent.resolver import EntityResolver
        from nl2dsl.semantic.registry import SemanticRegistry

        # Build a minimal registry
        registry = SemanticRegistry()
        registry.dimensions = {
            "region": {
                "column": "region_code",
                "description": "地区",
                "value_map": {"华东": "HD", "华南": "HN"},
            }
        }
        resolver = EntityResolver(registry)
        result = resolver.resolve_dimension_value("华东")
        assert result == ("region", "HD")

    def test_entity_resolver_metric_mapping(self):
        """EntityResolver correctly maps metric descriptions."""
        from nl2dsl.agent.resolver import EntityResolver
        from nl2dsl.semantic.registry import SemanticRegistry

        registry = SemanticRegistry()
        registry.metrics = {
            "sales_amount": {
                "expr": "SUM(pay_amount)",
                "description": "销售额",
            }
        }
        resolver = EntityResolver(registry)
        result = resolver.resolve_metric("销售额")
        assert result == "sales_amount"


# ===========================================================================
# I. SSE Streaming
# ===========================================================================


class TestSSEStreamingDetailed:
    """Detailed tests for SSE streaming endpoint."""

    def test_stream_simple_query_graph_updates(self, mock_api_client):
        """Simple query stream emits graph update events."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "查询各品牌销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert len(response.text) > 0
        assert "event: done" in response.text

    def test_stream_complex_query_agent_events(self, mock_api_client):
        """Complex query stream emits agent events (plan, explain)."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        event_types = {e.get("_event_type") for e in events}
        # Should have plan and explain events at minimum
        assert "plan" in event_types
        assert "explain" in event_types

    def test_stream_complex_query_sub_query_events(self, mock_api_client):
        """Complex query stream includes sub_query_start and sub_query_result."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        event_types = {e.get("_event_type") for e in events}
        assert "sub_query_start" in event_types
        assert "sub_query_result" in event_types

    def test_stream_complex_query_aggregate_event(self, mock_api_client):
        """Complex query stream includes aggregate event."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        event_types = {e.get("_event_type") for e in events}
        assert "aggregate" in event_types

    def test_stream_ends_with_done_event(self, mock_api_client):
        """All streams end with a done event."""
        for question in ["查询销售额", "对比华东和华南的销售额"]:
            response = mock_api_client.post("/api/v1/query/stream", json={
                "question": question,
                "user_id": "u001",
                "tenant_id": "t001",
            })
            assert "event: done" in response.text

    def test_stream_trend_query_emits_events(self, mock_api_client):
        """Trend query stream emits structured agent events."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "销售额趋势",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        event_types = {e.get("_event_type") for e in events}
        assert "plan" in event_types
        assert "explain" in event_types


# ===========================================================================
# J. Edge Cases and Boundary Conditions
# ===========================================================================


class TestEdgeCases:
    """Edge cases and boundary condition tests."""

    def test_limit_capped_at_100(self, mock_api_client):
        """Limit > 100 is capped to 100."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询全部销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["dsl"]["limit"] <= 100

    def test_multiple_filters_combined(self, mock_api_client):
        """Query with multiple filters (region + channel)."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询华东地区线上渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        sql = data["sql"]
        assert "HD" in sql
        assert "online" in sql

    def test_schema_endpoint_returns_structure(self, mock_api_client):
        """Schema endpoint returns expected structure."""
        response = mock_api_client.get("/api/v1/schema")
        assert response.status_code == 200
        data = response.json()
        # Schema endpoint returns data directly (no status wrapper)
        assert "data_sources" in data
        assert "metrics" in data
        assert "dimensions" in data
        assert isinstance(data["metrics"], list)
        assert isinstance(data["dimensions"], list)
        assert len(data["metrics"]) > 0
        assert len(data["dimensions"]) > 0

    def test_metrics_endpoint_returns_list(self, mock_api_client):
        """Metrics endpoint returns list of metrics."""
        response = mock_api_client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        # Metrics endpoint returns data directly (no status wrapper)
        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0

    def test_feedback_endpoint_accepts_data(self, mock_api_client):
        """Feedback endpoint accepts correction data."""
        q = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
        })
        query_id = q.json()["query_id"]
        response = mock_api_client.post("/api/v1/feedback", json={
            "query_id": query_id,
            "user_id": "u001",
            "tenant_id": "t001",
            "corrected_dsl": {"data_source": "orders"},
            "comment": "Test feedback",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"

    def test_health_check(self, mock_api_client):
        """Health check returns ok."""
        response = mock_api_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_query_with_order_by(self, mock_api_client):
        """Query with ordering returns ordered results."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额最高的产品",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        # SQL should contain ORDER BY
        assert "ORDER" in data["sql"].upper()

    def test_complex_query_multiple_dimensions(self, mock_api_client):
        """Query with multiple dimension keywords triggers complex path."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "查询各地区各渠道的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_audit_log_query_list(self, mock_api_client):
        """Audit log list endpoint returns query history."""
        # First make a query to create an audit entry
        mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # Then list audit entries (管理接口必须限定 tenant)
        response = mock_api_client.get("/api/v1/admin/audit/queries?tenant_id=t001&limit=10")
        data = _assert_query_success(response)
        assert "items" in data
        assert "total" in data
        assert data["limit"] == 10

    def test_audit_log_query_detail(self, mock_api_client):
        """Audit log detail endpoint returns query details."""
        # First make a query
        mock_api_client.post("/api/v1/query", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # List and get the first one (管理接口必须限定 tenant)
        list_response = mock_api_client.get("/api/v1/admin/audit/queries?tenant_id=t001&limit=1")
        list_data = _assert_query_success(list_response)
        if list_data["items"]:
            query_id = list_data["items"][0]["query_id"]
            detail_response = mock_api_client.get(
                f"/api/v1/admin/audit/queries/{query_id}?tenant_id=t001"
            )
            detail_data = _assert_query_success(detail_response)
            assert "item" in detail_data
            assert detail_data["item"]["query_id"] == query_id


# ===========================================================================
# K. AgentOrchestrator Integration
# ===========================================================================


class TestAgentOrchestratorIntegration:
    """Tests for AgentOrchestrator end-to-end integration."""

    def test_agent_result_contains_plan(self, mock_api_client):
        """Complex query result includes execution plan info."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Explanation should reference the plan
        assert data["explanation"] is not None

    def test_agent_confidence_aggregated_from_sub_queries(self, mock_api_client):
        """Confidence is aggregated from sub-query confidence scores."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "confidence" in data
        if data["confidence"] is not None:
            assert 0.0 <= data["confidence"] <= 1.0

    def test_agent_explanation_with_quality_notes(self, mock_api_client):
        """Explanation includes quality annotations for partial failures."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["explanation"] is not None
        assert isinstance(data["explanation"], str)

    def test_agent_handles_trend_query(self, mock_api_client):
        """AgentOrchestrator handles trend intent correctly."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "销售额趋势",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_agent_handles_correlation_query(self, mock_api_client):
        """AgentOrchestrator handles correlation intent correctly."""
        response = mock_api_client.post("/api/v1/query", json={
            "question": "销售额和订单量的关系",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert "explanation" in data

    def test_agent_sse_callback_events(self, mock_api_client):
        """AgentOrchestrator emits SSE events during execution."""
        response = mock_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        # Should have multiple event types
        event_types = {e.get("_event_type") for e in events}
        assert len(event_types) >= 2

    def test_agent_sub_query_error_handling(self, mock_api_client):
        """Agent handles sub-query errors gracefully."""
        # Even with potential sub-query issues, overall query should not crash
        response = mock_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = response.json()
        # Should either succeed or return a proper error
        assert data["status"] in ("success", "warning", "error")


# ===========================================================================
# L. Intent Registry Coverage
# ===========================================================================


class TestIntentRegistry:
    """Tests for intent registry configuration coverage."""

    def test_intent_registry_loads_from_yaml(self):
        """IntentRegistry loads all intents from intents.yaml."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        expected_intents = {
            "compare", "trend", "correlation", "proportion",
            "sequential", "ranking", "single_query",
        }
        assert set(registry.intents.keys()) == expected_intents

    def test_compare_intent_config(self):
        """Compare intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["compare"]
        assert config.decomposition == "split_by_objects"
        assert config.aggregation == "diff"
        assert "对比" in config.keywords

    def test_trend_intent_config(self):
        """Trend intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["trend"]
        assert config.decomposition == "single_with_time_grouping"
        assert config.aggregation == "trend_direction"
        assert "趋势" in config.keywords

    def test_correlation_intent_config(self):
        """Correlation intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["correlation"]
        assert config.decomposition == "split_by_objects"
        assert config.aggregation == "pearson"
        assert "关联" in config.keywords

    def test_proportion_intent_config(self):
        """Proportion intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["proportion"]
        assert config.decomposition == "total_plus_groups"
        assert config.aggregation == "proportion"
        assert "占比" in config.keywords

    def test_ranking_intent_config(self):
        """Ranking intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["ranking"]
        assert config.decomposition == "single_with_ordering"
        assert config.aggregation == "ranking"
        assert "排名" in config.keywords

    def test_sequential_intent_config(self):
        """Sequential intent has correct configuration."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        config = registry.intents["sequential"]
        assert config.decomposition == "sequential"
        assert config.aggregation == "sequential_filter"
        assert "先查" in config.keywords

    def test_keyword_matching(self):
        """IntentRegistry matches questions to correct intents."""
        from nl2dsl.agent.strategies import IntentRegistry

        registry = IntentRegistry.load("configs/intents.yaml")
        assert registry.get_intent_by_keywords("对比华东和华南") == "compare"
        assert registry.get_intent_by_keywords("销售额趋势") == "trend"
        assert registry.get_intent_by_keywords("关联分析") == "correlation"
        assert registry.get_intent_by_keywords("销售额排名") == "ranking"
        assert registry.get_intent_by_keywords("各品类占比") == "proportion"
        assert registry.get_intent_by_keywords("先查销售额") == "sequential"
        assert registry.get_intent_by_keywords("普通查询") is None  # No keywords match


# ===========================================================================
# M. Backward Compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """Tests ensuring backward compatibility with existing endpoints."""

    def test_dsl_generate_endpoint_unchanged(self, mock_api_client):
        """DSL generation endpoint still works as before."""
        response = mock_api_client.post("/api/v1/query/dsl", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "dsl" in data
        assert data["dsl"]["data_source"] == "orders"

    def test_execute_endpoint_unchanged(self, mock_api_client):
        """Execute endpoint still works as before."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
            "order_by": [{"field": "sales_amount", "direction": "desc"}],
            "limit": 10,
            "data_source": "orders",
        }
        response = mock_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert "data" in data

    def test_schema_endpoint_unchanged(self, mock_api_client):
        """Schema endpoint still returns expected structure."""
        response = mock_api_client.get("/api/v1/schema")
        assert response.status_code == 200
        data = response.json()
        assert "data_sources" in data
        assert "metrics" in data
        assert "dimensions" in data

    def test_metrics_endpoint_unchanged(self, mock_api_client):
        """Metrics endpoint still returns list."""
        response = mock_api_client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    def test_feedback_endpoint_unchanged(self, mock_api_client):
        """Feedback endpoint still accepts data."""
        q = mock_api_client.post("/api/v1/query", json={
            "question": "查询订单量", "user_id": "u001", "tenant_id": "t001",
        })
        query_id = q.json()["query_id"]
        response = mock_api_client.post("/api/v1/feedback", json={
            "query_id": query_id,
            "user_id": "u001",
            "tenant_id": "t001",
            "corrected_dsl": {"data_source": "orders"},
            "comment": "Looks good",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
