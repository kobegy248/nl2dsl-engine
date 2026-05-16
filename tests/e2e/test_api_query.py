import pytest
from fastapi.testclient import TestClient
from nl2dsl.api import app


@pytest.fixture
def client():
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
    assert response.json()["status"] == "success"
