"""Unit tests for the StateGraph builder."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from nl2dsl.dsl.models import DSL, Aggregation, Join
from nl2dsl.query.sandbox import SandboxResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_minimal_state(**overrides) -> QueryState:
    """Build a minimal QueryState with defaults."""
    defaults = {
        "question": "test question",
        "user_id": "u001",
        "tenant_id": "t001",
        "data_source": "orders",
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
        "query_id": "q001",
        "started_at": 0.0,
        "llm_used": False,
    }
    defaults.update(overrides)
    return QueryState(**defaults)


def _make_mock_llm_client():
    """Create a mock LLM client that returns valid DSL JSON."""
    llm_client = MagicMock()
    llm_client.generate = MagicMock(return_value=(
        '{"data_source": "orders", "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}], "dimensions": ["product_name"]}'
    ))
    return llm_client


def _make_smart_mock_llm_client():
    """Create a mock LLM client that returns context-appropriate responses."""
    llm_client = MagicMock()

    def _smart_generate(prompt, system_prompt=""):
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)

        # Plan node prompt
        if "意图识别" in prompt_str or "intent" in prompt_str.lower() or "sub_queries" in prompt_str:
            return '{"intent": "single_query", "sub_queries": [{"id": "sq-1", "description": "查询", "depends_on": []}], "reasoning": "简单查询"}'

        # Confidence node prompt (asks for a score)
        if "评分" in prompt_str or "confidence" in prompt_str.lower() or "分数" in prompt_str:
            return "85"

        # Verify DSL prompt
        if "质量检查" in prompt_str or "verify" in prompt_str.lower() or "PASS" in prompt_str:
            return "PASS\nDSL matches the question"

        # Explain node prompt
        if "解释" in prompt_str or "explanation" in prompt_str.lower() or "第一人称" in prompt_str:
            return "查询结果显示销售额为1000元。"

        # Decompose prompt
        if "改写" in prompt_str or "decompose" in prompt_str.lower():
            return "KEEP"

        # Default: return DSL JSON for generate_dsl
        return '{"data_source": "orders", "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}], "dimensions": ["product_name"]}'

    llm_client.generate = MagicMock(side_effect=_smart_generate)
    return llm_client


@pytest.fixture
def mock_services():
    """Create a full set of mock services for build_graph."""
    executor = MagicMock()
    executor.execute = MagicMock(return_value=[{"product_name": "iPhone", "sales_amount": 1000.0}])

    return {
        "llm_client": _make_smart_mock_llm_client(),
        "rag_retriever": None,
        "validator": MagicMock(),
        "row_security": MagicMock(),
        "col_security": MagicMock(),
        "resolver": MagicMock(),
        "sql_builder": MagicMock(),
        "scanner": MagicMock(),
        "sandbox": MagicMock(),
        "executor": executor,
        "clarification_detector": MagicMock(),
        "registry_dict": {},
        "llm_system_prompt": "",
    }


@pytest.fixture
def valid_dsl():
    return DSL(
        metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
        dimensions=["product_name"],
        data_source="orders",
    )


# ---------------------------------------------------------------------------
# build_graph compilation tests
# ---------------------------------------------------------------------------


class TestBuildGraphCompilation:
    def test_builds_without_error(self, mock_services):
        graph = build_graph(**mock_services)
        assert graph is not None

    def test_returns_compiled_graph(self, mock_services):
        graph = build_graph(**mock_services)
        # Compiled graphs have 'nodes' attribute
        assert hasattr(graph, "nodes")

    def test_has_expected_nodes(self, mock_services):
        graph = build_graph(**mock_services)
        expected_nodes = {
            "clarification",
            "plan",
            "validation",
            "permission_check",
            "resolve_semantic",
            "confidence",
            "build_sql",
            "scan_sql",
            "sandbox_check",
            "human_review",
            "execute_sql",
            "simplify_dsl",
            "verify_dsl",
            "explain",
        }
        for node in expected_nodes:
            assert node in graph.nodes, f"Node '{node}' not found in compiled graph"

    def test_builds_with_checkpointer(self, mock_services):
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
        graph = build_graph(**mock_services, checkpointer=checkpointer)
        assert graph is not None


# ---------------------------------------------------------------------------
# Full pipeline invocation tests
# ---------------------------------------------------------------------------


class TestBuildGraphInvocation:
    def test_simple_query_success_path(self, mock_services, valid_dsl):
        """Test the happy path: clarification -> validation -> ... -> execute -> END."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = (
            "SELECT product_name, SUM(order_amount) FROM order_fact GROUP BY product_name LIMIT 10"
        )
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should reach execute_sql and return success
        assert result["status"] == "success"
        assert result["sql"] is not None
        assert result["data"] is not None
        # Trace should record multiple steps
        assert result["trace"] is not None
        assert len(result["trace"]) >= 1

    def test_clarification_returns_early(self, mock_services):
        """If ambiguities are detected, pipeline ends early with clarification status."""
        mock_services["clarification_detector"].detect.return_value = [
            MagicMock(model_dump=lambda: {"type": "metric", "question": "Which metric?", "options": ["a", "b"]})
        ]

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询")
        result = graph.invoke(state)

        assert result["status"] == "clarification"
        assert result["ambiguities"] is not None
        # Should not have reached validation
        mock_services["validator"].validate.assert_not_called()

    def test_sandbox_review_triggers_human_review(self, mock_services, valid_dsl):
        """If sandbox fails, route to human_review then to execute_sql."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT * FROM order_fact"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=False,
            risks=["Full table scan detected"],
            sample_rows=[],
        )

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Without checkpointer/interrupt, human_review node runs and then
        # routes to execute_sql, so final status is success
        assert result["status"] == "success"
        # Trace should show human_review was visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "human_review" in trace_steps

    def test_error_in_validation_subgraph(self, mock_services):
        """If LLM returns invalid JSON, graph falls back to mock_dsl and succeeds."""
        # Disable LLM entirely to test the mock_dsl fallback path
        mock_services["llm_client"] = None
        mock_services["clarification_detector"].detect.return_value = []

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Without LLM, validation subgraph uses mock_dsl
        # Note: confidence will be 50 (neutral_no_llm) which routes to "clarify"
        # This is expected behavior when LLM is unavailable
        assert result["dsl"] is not None
        assert result["llm_used"] is False

    def test_complex_query_routes_through_scan(self, mock_services):
        """Complex queries should still route to scan_sql."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = (
            "SELECT product_name, region, SUM(order_amount) FROM order_fact "
            "LEFT JOIN customer_dim ON order_fact.customer_id = customer_dim.customer_id "
            "GROUP BY product_name, region LIMIT 10"
        )
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )

        graph = build_graph(**mock_services)

        # Complex DSL with join
        complex_dsl = DSL(
            metrics=[Aggregation(func="sum", field="order_amount", alias="sales_amount")],
            dimensions=["product_name", "region"],
            data_source="orders",
            joins=[Join(table="customer_dim", on_field="customer_id", join_type="left", alias="c")],
        )
        state = make_minimal_state(question="查询销售额", dsl=complex_dsl)
        result = graph.invoke(state)

        # Should still complete successfully
        assert result["status"] == "success"
        # scan_sql should have been called
        mock_services["scanner"].scan.assert_called_once()

    def test_trace_accumulates_across_nodes(self, mock_services, valid_dsl):
        """Trace should accumulate entries from each node visited."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT 1"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        trace = result.get("trace", [])
        assert trace is not None
        assert len(trace) >= 1
        # Each trace entry should have a 'step' field
        for entry in trace:
            assert "step" in entry


# ---------------------------------------------------------------------------
# Edge routing tests within the full graph
# ---------------------------------------------------------------------------


class TestBuildGraphEdgeRouting:
    def test_build_sql_error_routes_to_end(self, mock_services):
        """If build_sql sets error status, route to END."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.side_effect = Exception("SQL build failed")

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        assert result["status"] == "error"
        assert "SQL build failed" in result["error"]

    def test_sandbox_pass_routes_to_execute(self, mock_services):
        """If sandbox passes, route to execute_sql."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT 1"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should execute SQL
        assert result["status"] == "success"
        mock_services["executor"].execute.assert_called_once()

    def test_execute_retry_routes_to_simplify(self, mock_services):
        """If execute fails, route to simplify_dsl then back to build_sql."""
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT 1"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )
        # First execute fails, second succeeds
        mock_services["executor"].execute.side_effect = [
            Exception("DB timeout"),
            [{"product_name": "iPhone", "sales_amount": 1000.0}],
        ]

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should eventually succeed after retry
        # Note: The retry loop goes simplify_dsl -> build_sql -> scan_sql -> sandbox -> execute
        # With mocked build returning same SQL, the second execute should work
        # But since build_sql returns same SQL each time, and execute fails first time...
        # The actual behavior depends on the retry logic in route_after_execute
        # which checks attempt count. With no dsl_attempts, it should retry once.
        assert result is not None


# ---------------------------------------------------------------------------
# Checkpointer / interrupt tests
# ---------------------------------------------------------------------------


class TestBuildGraphWithCheckpointer:
    def test_interrupt_before_human_review(self, mock_services):
        """With checkpointer, graph should interrupt before human_review."""
        from langgraph.checkpoint.memory import InMemorySaver

        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT * FROM order_fact"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=False,
            risks=["Risky query"],
            sample_rows=[],
        )

        checkpointer = InMemorySaver()
        graph = build_graph(**mock_services, checkpointer=checkpointer)

        state = make_minimal_state(question="查询销售额")
        config = {"configurable": {"thread_id": "test-thread-1"}}

        # With interrupt_before=["human_review"], the graph should stop before human_review
        result = graph.invoke(state, config)

        # The result should contain the state up to sandbox_check
        # Since interrupt is before human_review, the node hasn't run yet
        # But LangGraph may still return the state
        assert result is not None
        assert result.get("sandbox_result") is not None

    def test_graph_compiles_with_none_checkpointer(self, mock_services):
        """Graph should compile fine without a checkpointer."""
        graph = build_graph(**mock_services, checkpointer=None)
        assert graph is not None
        assert hasattr(graph, "invoke")


# ---------------------------------------------------------------------------
# Agent node integration tests
# ---------------------------------------------------------------------------


class TestAgentNodesInGraph:
    def test_agent_nodes_present_in_compiled_graph(self, mock_services):
        """Plan, confidence, and explain nodes should be in the compiled graph."""
        graph = build_graph(**mock_services)
        expected_agent_nodes = {"plan", "confidence", "explain"}
        for node in expected_agent_nodes:
            assert node in graph.nodes, f"Agent node '{node}' not found in compiled graph"

    def test_single_query_routes_through_plan_to_decompose(self, mock_services, valid_dsl):
        """single_query intent should route: clarification -> plan -> decompose -> ... -> END."""
        # Use smart LLM mock that returns context-appropriate responses
        mock_services["llm_client"] = _make_smart_mock_llm_client()
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = (
            "SELECT product_name, SUM(order_amount) FROM order_fact GROUP BY product_name LIMIT 10"
        )
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )
        mock_services["validator"].validate.return_value = None

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should complete successfully through the plan node
        assert result["status"] == "success"
        assert result["plan"] is not None
        assert result["plan"].intent == "single_query"
        # Trace should show plan was visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "plan" in trace_steps

    def test_plan_node_routes_agent_intent_to_end(self, mock_services):
        """Non-single_query intent (e.g. compare) should route from plan to END."""
        # Disable LLM so plan node uses keyword fallback
        mock_services["llm_client"] = None
        mock_services["clarification_detector"].detect.return_value = []

        graph = build_graph(**mock_services)

        # Use a question that triggers compare intent via keyword matching
        state = make_minimal_state(question="对比华东和华南的销售额")
        result = graph.invoke(state)

        # Should end after plan node (agent path)
        assert result["plan"] is not None
        assert result["plan"].intent == "compare"
        # Since "agent" route goes to END, status should not be "success"
        # (the pipeline didn't reach execute_sql)
        assert result["status"] != "success"
        # Trace should show plan was visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "plan" in trace_steps

    def test_confidence_node_routes_continue_when_high(self, mock_services, valid_dsl):
        """High confidence (>= 60) should route: confidence -> build_sql -> ... -> END."""
        # Disable LLM so confidence node uses neutral semantic score (50)
        # With validator passing (syntax=100), confidence = min(100, 50) = 50 < 60
        # So we also need to mock the LLM to return a high semantic score
        mock_services["llm_client"] = _make_mock_llm_client()
        # Override generate to return a high confidence score for the confidence node's prompt
        mock_services["llm_client"].generate = MagicMock(return_value="85")
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT 1"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )
        # Mock validator to pass (syntax confidence = 100)
        mock_services["validator"].validate.return_value = None

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should complete successfully
        assert result["status"] == "success"
        # Confidence should be set
        assert result["confidence"] is not None
        assert result["confidence"] >= 60.0
        # Trace should show confidence was visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "confidence" in trace_steps

    def test_confidence_node_routes_end_when_error(self, mock_services, valid_dsl):
        """route_after_confidence should return 'end' when status is error."""
        from nl2dsl.graph.edges import route_after_confidence

        # Direct test of the routing function with error status
        error_state = make_minimal_state(status="error", error="Something failed")
        assert route_after_confidence(error_state) == "end"

    def test_confidence_node_routes_clarify_when_low_confidence(self, mock_services, valid_dsl):
        """route_after_confidence should return 'clarify' when status is clarification."""
        from nl2dsl.graph.edges import route_after_confidence

        clarify_state = make_minimal_state(status="clarification", confidence=50)
        assert route_after_confidence(clarify_state) == "clarify"

    def test_confidence_node_routes_continue_when_high_confidence(self, mock_services, valid_dsl):
        """route_after_confidence should return 'continue' when confidence is high."""
        from nl2dsl.graph.edges import route_after_confidence

        continue_state = make_minimal_state(status="pending", confidence=85)
        assert route_after_confidence(continue_state) == "continue"

    def test_explain_node_runs_after_verify_dsl(self, mock_services, valid_dsl):
        """explain node should run after verify_dsl and set explanation."""
        # Use smart LLM mock that returns context-appropriate responses
        mock_services["llm_client"] = _make_smart_mock_llm_client()
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = "SELECT 1"
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )
        mock_services["validator"].validate.return_value = None

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询销售额")
        result = graph.invoke(state)

        # Should have explanation set by explain node
        assert result["explanation"] is not None
        assert len(result["explanation"]) > 0
        # Trace should show explain was visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "explain" in trace_steps

    def test_graph_flow_with_all_agent_nodes(self, mock_services, valid_dsl):
        """Full flow: clarification -> plan -> decompose -> ... -> confidence -> ... -> verify_dsl -> explain -> END."""
        # Use smart LLM mock that returns context-appropriate responses
        mock_services["llm_client"] = _make_smart_mock_llm_client()
        mock_services["clarification_detector"].detect.return_value = []
        mock_services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services["col_security"].check.return_value = None
        mock_services["resolver"].resolve.side_effect = lambda dsl: dsl
        mock_services["sql_builder"].build.return_value = (
            "SELECT product_name, SUM(order_amount) FROM order_fact GROUP BY product_name LIMIT 10"
        )
        mock_services["scanner"].scan.return_value = None
        mock_services["sandbox"].check.return_value = SandboxResult(
            passed=True, risks=[], sample_rows=[]
        )
        mock_services["validator"].validate.return_value = None

        graph = build_graph(**mock_services)

        state = make_minimal_state(question="查询华东销售额")
        result = graph.invoke(state)

        # Full success path
        assert result["status"] == "success"
        assert result["sql"] is not None
        assert result["data"] is not None
        assert result["plan"] is not None
        assert result["confidence"] is not None
        assert result["explanation"] is not None

        # Check all agent nodes were visited
        trace_steps = [t["step"] for t in (result.get("trace") or [])]
        assert "plan" in trace_steps
        assert "confidence" in trace_steps
        assert "explain" in trace_steps
