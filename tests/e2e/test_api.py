import os

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from tests.e2e.mock_data import create_mock_database


@pytest.fixture
def client():
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
    response = client.post("/api/v1/feedback", json={
        "query_id": "q-12345",
        "user_id": "u001",
        "corrected_dsl": {"data_source": "orders"},
        "comment": "The result looks good",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["query_id"] == "q-12345"


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
