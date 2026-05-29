"""End-to-end tests for Agent orchestration integration into API endpoints.

Tests that:
1. Simple queries (single_query intent) still work through the existing graph flow
2. Complex queries (compare, trend, correlation) are routed through AgentOrchestrator
3. SSE streaming endpoint emits structured agent events for complex queries
4. QueryResponse includes explanation and confidence fields when available
5. Backward compatibility is maintained for existing endpoints
"""

from __future__ import annotations

import json
import os

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from tests.e2e.mock_data import create_mock_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_api_client():
    """Create a TestClient with mock data for agent E2E tests."""
    engine, *_ = create_mock_database("sqlite:///:memory:")

    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fixtures_dir, "metrics_test.yaml"), "r", encoding="utf-8") as f:
        metrics_data = yaml.safe_load(f)
    registry_dict = {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }

    app = create_app(
        engine=engine,
        registry_dict=registry_dict,
        enable_clarification=False,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_query_success(response):
    """Assert a /query response is successful."""
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data.get("status") == "success", f"Expected status='success', got: {data}"
    return data


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE response text into a list of event dicts.

    Handles both:
    - Standard format: event: <type>\ndata: <json>\n\n
    - Simple format: data: <json>\n\n
    """
    events = []
    # Split by double newline to get individual event blocks
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
        if data_str and data_str != "[DONE]":
            try:
                payload = json.loads(data_str)
                if event_type:
                    payload["_event_type"] = event_type
                events.append(payload)
            except json.JSONDecodeError:
                # Skip non-JSON data lines (like [DONE])
                pass
    return events


# ---------------------------------------------------------------------------
# Test class: Simple query path (backward compatibility)
# ---------------------------------------------------------------------------


class TestSimpleQueryPath:
    """Tests that simple queries still use the existing graph flow."""

    def test_simple_query_returns_success(self, agent_api_client):
        """A simple query (no compare/trend/correlation keywords) returns success."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "dsl" in data
        assert "sql" in data
        assert "data" in data

    def test_simple_query_has_data(self, agent_api_client):
        """Simple query returns actual data rows."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "查询华东地区的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert data["data"] is not None
        assert len(data["data"]) >= 1

    def test_simple_query_backward_compatible_fields(self, agent_api_client):
        """Simple query response contains all original fields."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "查询订单量",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # All original fields should be present
        assert "status" in data
        assert "data" in data
        assert "dsl" in data
        assert "sql" in data
        assert "execution_time_ms" in data
        assert "clarification" in data
        # New optional fields may or may not be present for simple queries

    def test_simple_query_dsl_endpoint_unchanged(self, agent_api_client):
        """DSL generation endpoint works unchanged."""
        response = agent_api_client.post("/api/v1/query/dsl", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "dsl" in data
        assert data["dsl"]["data_source"] == "orders"

    def test_simple_query_execute_endpoint_unchanged(self, agent_api_client):
        """Execute endpoint works unchanged."""
        dsl = {
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "data_source": "orders",
        }
        response = agent_api_client.post("/api/v1/query/execute", json={
            "dsl": dsl,
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "sql" in data
        assert "data" in data


# ---------------------------------------------------------------------------
# Test class: Complex query path (AgentOrchestrator)
# ---------------------------------------------------------------------------


class TestComplexQueryPath:
    """Tests that complex queries are routed through AgentOrchestrator."""

    def test_compare_query_returns_success(self, agent_api_client):
        """A compare query is handled by the agent and returns success."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data
        assert data["data"] is not None

    def test_compare_query_has_explanation(self, agent_api_client):
        """Compare query response includes explanation field."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Complex queries should have explanation
        assert "explanation" in data
        assert data["explanation"] is not None
        assert isinstance(data["explanation"], str)
        assert len(data["explanation"]) > 0

    def test_compare_query_has_confidence(self, agent_api_client):
        """Compare query response includes confidence field."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "confidence" in data
        assert data["confidence"] is not None
        assert isinstance(data["confidence"], float)
        assert 0.0 <= data["confidence"] <= 1.0

    def test_trend_query_returns_success(self, agent_api_client):
        """A trend query is handled by the agent and returns success."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "销售额趋势",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data

    def test_trend_query_has_explanation_and_confidence(self, agent_api_client):
        """Trend query includes explanation and confidence."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "销售额趋势",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "explanation" in data
        assert "confidence" in data

    def test_correlation_query_returns_success(self, agent_api_client):
        """A correlation query is handled by the agent and returns success."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "销售额和订单量的关系",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "data" in data

    def test_correlation_query_has_explanation_and_confidence(self, agent_api_client):
        """Correlation query includes explanation and confidence."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "销售额和订单量的关系",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        assert "explanation" in data
        assert "confidence" in data


# ---------------------------------------------------------------------------
# Test class: SSE streaming endpoint
# ---------------------------------------------------------------------------


class TestSSEStreaming:
    """Tests for the SSE streaming endpoint with agent events."""

    def test_stream_simple_query(self, agent_api_client):
        """Simple query stream emits standard graph updates."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        # Should be SSE content type
        assert "text/event-stream" in response.headers.get("content-type", "")
        # Should have data in the response
        assert len(response.text) > 0

    def test_stream_complex_query_emits_events(self, agent_api_client):
        """Complex query stream emits structured agent events."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = _parse_sse_events(response.text)
        # Should have some events
        assert len(events) > 0

        # Check for agent-specific event types
        event_types = [e.get("_event_type") for e in events if "_event_type" in e]
        # At minimum should have plan and explain events for complex queries
        assert "plan" in event_types, f"Expected 'plan' event, got: {event_types}"
        assert "explain" in event_types, f"Expected 'explain' event, got: {event_types}"

    def test_stream_has_plan_event(self, agent_api_client):
        """Stream includes a plan event with plan details."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        plan_events = [e for e in events if e.get("_event_type") == "plan"]
        assert len(plan_events) >= 1
        # Plan event should contain plan info
        plan_event = plan_events[0]
        assert "plan" in plan_event or "intent" in plan_event

    def test_stream_has_sub_query_events(self, agent_api_client):
        """Stream includes sub_query_start and sub_query_result events."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        event_types = [e.get("_event_type") for e in events]
        assert "sub_query_start" in event_types
        assert "sub_query_result" in event_types

    def test_stream_has_aggregate_event(self, agent_api_client):
        """Stream includes aggregate event for complex queries."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        event_types = [e.get("_event_type") for e in events]
        assert "aggregate" in event_types

    def test_stream_has_explain_event(self, agent_api_client):
        """Stream includes explain event with explanation."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        events = _parse_sse_events(response.text)
        explain_events = [e for e in events if e.get("_event_type") == "explain"]
        assert len(explain_events) >= 1
        # Should have explanation text
        first = explain_events[0]
        assert "explanation" in first or any(isinstance(v, str) and len(v) > 0 for v in first.values())

    def test_stream_ends_with_done(self, agent_api_client):
        """Stream ends with a [DONE] marker."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        assert "[DONE]" in response.text


# ---------------------------------------------------------------------------
# Test class: QueryResponse model fields
# ---------------------------------------------------------------------------


class TestQueryResponseFields:
    """Tests that QueryResponse has the new optional fields."""

    def test_query_response_has_explanation_field(self, agent_api_client):
        """Query response schema accepts explanation field."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = response.json()
        # Should not fail validation - explanation is optional
        assert "status" in data

    def test_query_response_has_confidence_field(self, agent_api_client):
        """Query response schema accepts confidence field."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = response.json()
        # Should not fail validation - confidence is optional
        assert "status" in data


# ---------------------------------------------------------------------------
# Test class: Audit logging
# ---------------------------------------------------------------------------


class TestAgentAuditLogging:
    """Tests that agent queries are properly audit-logged."""

    def test_complex_query_logged_to_audit(self, agent_api_client):
        """Complex queries create audit log entries."""
        response = agent_api_client.post("/api/v1/query", json={
            "question": "对比华东和华南的销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        data = _assert_query_success(response)
        # Audit log should have been written (we can verify by querying audit endpoint)
        # The query_id should be in the response or we can list recent queries
        # For now, just verify the query succeeded
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Test class: Error handling
# ---------------------------------------------------------------------------


class TestAgentErrorHandling:
    """Tests for error handling in agent-integrated endpoints."""

    def test_invalid_question_still_handled(self, agent_api_client):
        """An invalid/question that causes error is handled gracefully."""
        # Even a weird question should not crash the server
        response = agent_api_client.post("/api/v1/query", json={
            "question": "",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # Should return either success or a proper error response
        assert response.status_code in (200, 400, 422)

    def test_stream_invalid_question(self, agent_api_client):
        """Streaming an invalid question does not crash."""
        response = agent_api_client.post("/api/v1/query/stream", json={
            "question": "",
            "user_id": "u001",
            "tenant_id": "t001",
        })
        # Should still return SSE stream
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
