import os

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from tests.e2e.mock_data import create_mock_database


@pytest.fixture
def client(real_llm_client):
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
        llm_client=real_llm_client,
    )
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_dsl_endpoint(client):
    response = client.post("/api/v1/query/dsl", json={
        "question": "测试",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "dsl" in data
    assert data["dsl"]["data_source"] == "orders"


def test_query_dsl_with_sales_keyword(client):
    response = client.post("/api/v1/query/dsl", json={
        "question": "查询销售额最高的产品",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    dsl = data["dsl"]
    assert dsl["data_source"] == "orders"
    assert any(m.get("alias") == "sales_amount" for m in dsl.get("metrics", []))


def test_query_dsl_with_region_filter(client):
    response = client.post("/api/v1/query/dsl", json={
        "question": "查询华东地区的销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    dsl = data["dsl"]
    filters = dsl.get("filters", [])
    # Semantic resolver maps region -> region_code and 华东 -> HD
    assert any(f.get("field") == "region_code" and f.get("value") == "HD" for f in filters)


def test_query_endpoint(client):
    response = client.post("/api/v1/query", json={
        "question": "查询华东地区销售额最高的 10 个产品",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "dsl" in data
    assert "sql" in data
    assert data["sql"] is not None
    assert "SELECT" in data["sql"]


def test_query_execute_endpoint(client):
    dsl = {
        "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
        "dimensions": ["product_name"],
        "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        "order_by": [{"field": "sales_amount", "direction": "desc"}],
        "limit": 10,
        "data_source": "orders",
    }
    response = client.post("/api/v1/query/execute", json={
        "dsl": dsl,
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "sql" in data
    assert data["sql"] is not None
    assert "SELECT" in data["sql"]
    # Semantic resolver maps 华东 -> HD in the SQL
    assert "region_code" in data["sql"]


def test_get_schema(client):
    response = client.get("/api/v1/schema")
    assert response.status_code == 200
    data = response.json()
    assert "data_sources" in data
    assert "metrics" in data
    assert "dimensions" in data


def test_get_metrics(client):
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert isinstance(data["metrics"], list)


def test_post_feedback(client):
    # 反馈要求 query_id 对应审计记录存在：先发起一次真实查询
    q = client.post("/api/v1/query", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert q.status_code == 200
    query_id = q.json()["query_id"]

    response = client.post("/api/v1/feedback", json={
        "query_id": query_id,
        "user_id": "u001",
        "tenant_id": "t001",
        "corrected_dsl": {"data_source": "orders"},
        "comment": "The result looks good",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["query_id"] == query_id


def test_get_enums(client):
    response = client.get("/api/v1/admin/enums")
    assert response.status_code == 200
    data = response.json()
    assert "enums" in data
    assert isinstance(data["enums"], list)


def test_refresh_enums(client):
    response = client.post("/api/v1/admin/enums/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "refreshed"


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


def test_query_execute_invalid_dsl_returns_400(client):
    """Execute endpoint with invalid DSL fields should return 400."""
    response = client.post("/api/v1/query/execute", json={
        "dsl": {"data_source": "nonexistent"},  # no metrics, invalid data_source
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert "error_code" in data


def test_get_audit_query_not_found_returns_404(client):
    response = client.get("/api/v1/admin/audit/queries/nonexistent-query-id?tenant_id=t001")
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "NOT_FOUND"


def test_list_audit_queries_limit_out_of_range(client):
    response = client.get("/api/v1/admin/audit/queries?tenant_id=t001&limit=999")
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"


def test_list_audit_queries_limit_zero(client):
    response = client.get("/api/v1/admin/audit/queries?tenant_id=t001&limit=0")
    assert response.status_code == 400


def test_list_audit_queries_negative_offset(client):
    response = client.get("/api/v1/admin/audit/queries?tenant_id=t001&offset=-1")
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Stream endpoint
# ---------------------------------------------------------------------------


def test_stream_endpoint(client):
    """Stream endpoint should return SSE response."""
    response = client.post("/api/v1/query/stream", json={
        "question": "查询销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    # Read at least the done event
    body = response.read()
    assert b"event:" in body or b"done" in body


# ---------------------------------------------------------------------------
# Resume endpoint (no checkpointer → always 404 in test setup)
# ---------------------------------------------------------------------------


def test_resume_nonexistent_query_returns_404(client):
    response = client.post("/api/v1/query/resume", json={
        "query_id": "nonexistent-id",
        "action": "approve",
    })
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Audit list endpoint
# ---------------------------------------------------------------------------


def test_list_audit_queries_defaults(client):
    response = client.get("/api/v1/admin/audit/queries?tenant_id=t001")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "total" in data
    assert "items" in data
    assert data["limit"] == 20
    assert data["offset"] == 0


def test_list_audit_queries_with_filters(client):
    response = client.get("/api/v1/admin/audit/queries?tenant_id=t001&user_id=u001&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["limit"] == 5


def test_list_audit_queries_requires_tenant(client):
    """未限定 tenant 的管理查询必须被拒绝。"""
    response = client.get("/api/v1/admin/audit/queries")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Complex query scenarios
# ---------------------------------------------------------------------------


def test_query_with_join(client):
    """Query requiring JOIN should produce SQL with JOIN clause."""
    response = client.post("/api/v1/query", json={
        "question": "查询各品牌的销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "sql" in data
    sql = data["sql"]
    assert "JOIN" in sql.upper() or "join" in sql.lower()


def test_query_with_multiple_filters(client):
    """Query with multiple filter conditions."""
    response = client.post("/api/v1/query", json={
        "question": "查询华东地区线上渠道的销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    sql = data["sql"]
    assert "HD" in sql  # region_code mapped
    assert "online" in sql  # channel_code mapped


def test_query_with_top_n(client):
    """Query with top-N should set LIMIT correctly."""
    response = client.post("/api/v1/query", json={
        "question": "查询前5的销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    dsl = data["dsl"]
    assert dsl["limit"] == 5
