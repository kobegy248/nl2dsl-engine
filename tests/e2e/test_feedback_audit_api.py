"""Phase 3/4 E2E：query_id 返回 + 反馈审计关联 + 去重（rule 模式，无需 LLM）。"""

from __future__ import annotations

import os

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from tests.e2e.mock_data import create_mock_database

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """解析 SSE 响应体为 [(event, data_dict), ...]。"""
    import json as _json

    events = []
    for block in body.split("\n\n"):
        event_name = None
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if event_name is None:
            continue
        data = _json.loads("".join(data_lines)) if data_lines else {}
        events.append((event_name, data))
    return events


@pytest.fixture(scope="module")
def client():
    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load(open(os.path.join(FIXTURES, "metrics_test.yaml"), encoding="utf-8"))
    perm = yaml.safe_load(open(os.path.join(FIXTURES, "permissions_test.yaml"), encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
        "permissions": perm.get("users", {}),
    }
    app = create_app(
        engine=engine,
        registry_dict=registry,
        permissions=perm.get("users", {}),
        sensitive_columns=perm.get("sensitive_columns", {}),
        masking_rules=perm.get("masking_rules", {}),
        enable_clarification=False,
        llm_client=None,
        generator_mode="rule",
        enable_optimizer=True,
    )
    return TestClient(app)


def _query(client, question="查询销售额", user="u001", tenant="t001"):
    resp = client.post("/api/v1/query", json={"question": question, "user_id": user, "tenant_id": tenant})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Phase 3: query_id ---

def test_query_endpoint_returns_query_id(client):
    data = _query(client)
    assert data["status"] == "success"
    assert "query_id" in data and data["query_id"]


def test_query_dsl_endpoint_returns_query_id(client):
    resp = client.post("/api/v1/query/dsl", json={"question": "查询销售额", "user_id": "u001", "tenant_id": "t001"})
    assert resp.status_code == 200
    assert resp.json()["query_id"]


def test_query_execute_endpoint_returns_query_id(client):
    dsl = {
        "data_source": "orders",
        "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
        "dimensions": ["product_name"],
        "limit": 10,
    }
    resp = client.post("/api/v1/query/execute", json={"dsl": dsl, "user_id": "u001", "tenant_id": "t001"})
    assert resp.status_code == 200
    assert resp.json()["query_id"]


def test_query_id_links_to_audit(client):
    data = _query(client)
    qid = data["query_id"]
    resp = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["query_id"] == qid
    assert isinstance(item["trace"], list) and item["trace"]


# --- Phase 4: feedback validation ---

def test_feedback_rejects_missing_audit(client):
    resp = client.post("/api/v1/feedback", json={
        "query_id": "does-not-exist", "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "comment": "x",
    })
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_feedback_rejects_wrong_user(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u-hacker", "tenant_id": "t001",
        "is_correct": False, "comment": "x",
    })
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_feedback_rejects_wrong_tenant(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t-hacker",
        "is_correct": False, "comment": "x",
    })
    assert resp.status_code == 400


def test_feedback_dedup_returns_original_id(client):
    data = _query(client)
    payload = {
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "issue_type": "metric",
        "corrected_dsl": {"data_source": "orders"}, "comment": "口径不对",
    }
    r1 = client.post("/api/v1/feedback", json=payload).json()
    r2 = client.post("/api/v1/feedback", json=payload).json()
    assert r1["feedback_id"] == r2["feedback_id"]
    assert r1["deduplicated"] is False
    assert r2["deduplicated"] is True


def test_feedback_rejects_invalid_corrected_dsl(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t001",
        "is_correct": False,
        "corrected_dsl": {"filters": "not-a-list"}, "comment": "x",
    })
    assert resp.status_code == 400


def test_feedback_detail_links_audit(client):
    data = _query(client)
    fb = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "issue_type": "metric", "comment": "不对",
    }).json()
    resp = client.get(f"/api/v1/admin/feedback/{fb['feedback_id']}", params={"tenant_id": "t001"})
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["audit_summary"]["question"] == "查询销售额"
    # 不在反馈项里复制 SQL/Trace
    assert "sql" not in item
    assert "trace" not in item


def test_feedback_list(client):
    data = _query(client, question="查询订单量")
    client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "comment": "x",
    })
    # 管理 API 必须限定租户范围。
    resp = client.get("/api/v1/admin/feedback", params={"tenant_id": "t001", "user_id": "u001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert "sql" not in body["items"][0]


def test_feedback_list_requires_tenant(client):
    """未限定 tenant 的管理查询必须被拒绝，禁止跨租户全量返回。"""
    resp = client.get("/api/v1/admin/feedback", params={"user_id": "u001"})
    assert resp.status_code == 400


# --- P0-1: tenant_id 强校验 ---

def test_feedback_rejects_missing_tenant(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001",
        "is_correct": False, "comment": "x",
    })
    assert resp.status_code == 422


def test_feedback_rejects_blank_tenant(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "   ",
        "is_correct": False, "comment": "x",
    })
    assert resp.status_code == 422


def test_feedback_correct_tenant_succeeds(client):
    data = _query(client)
    resp = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "issue_type": "metric", "comment": "口径不对",
    })
    assert resp.status_code == 200
    assert resp.json()["feedback_id"]


# --- P1-3: /query/execute 写审计 + query_id 关联 ---

def _execute(client, dsl=None, user="u001", tenant="t001"):
    if dsl is None:
        dsl = {
            "data_source": "orders",
            "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
            "dimensions": ["product_name"],
            "limit": 10,
        }
    return client.post("/api/v1/query/execute", json={"dsl": dsl, "user_id": user, "tenant_id": tenant})


def test_execute_success_audit_linkable(client):
    resp = _execute(client)
    assert resp.status_code == 200
    qid = resp.json()["query_id"]
    detail = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    item = detail.json()["item"]
    assert item["query_id"] == qid
    assert item["tenant_id"] == "t001"


def test_execute_query_id_usable_for_feedback(client):
    qid = _execute(client).json()["query_id"]
    resp = client.post("/api/v1/feedback", json={
        "query_id": qid, "user_id": "u001", "tenant_id": "t001",
        "is_correct": False, "issue_type": "result", "comment": "结果不对",
    })
    assert resp.status_code == 200
    assert resp.json()["feedback_id"]


def test_execute_failure_has_audit(client):
    # 无 metrics 的非法 DSL → 400，但仍应写入 error 审计记录。
    resp = _execute(client, dsl={"data_source": "orders"})
    assert resp.status_code == 400
    listed = client.get("/api/v1/admin/audit/queries", params={"tenant_id": "t001", "status": "error", "limit": 100})
    assert listed.status_code == 200
    items = listed.json()["items"]
    # 失败的 execute 审计 question 固定为 "(execute)"
    assert any(it.get("question") == "(execute)" for it in items)


# --- 第二轮审阅 P1：query/execute 所有失败都必须审计 ---

def test_execute_dsl_schema_error_has_audit(client):
    """DSL Schema 解析失败（pydantic ValidationError）后存在 error Audit，响应携带 query_id。"""
    resp = _execute(client, dsl={"data_source": "orders", "limit": "not-a-number"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["query_id"], "错误响应必须携带 query_id"
    # 该 query_id 对应的审计记录存在且为 error
    detail = client.get(
        f"/api/v1/admin/audit/queries/{body['query_id']}", params={"tenant_id": "t001"}
    )
    assert detail.status_code == 200
    item = detail.json()["item"]
    assert item["status"] == "error"
    assert item["error_code"] == "DSL_SCHEMA_ERROR"


def test_execute_unknown_domain_has_audit(client):
    """_get_domain_graph 抛 NotFoundError（未知领域）后存在 error Audit，404 携带 query_id。"""
    resp = client.post(
        "/api/v1/query/execute",
        json={
            "dsl": {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}], "limit": 10},
            "user_id": "u001", "tenant_id": "t001", "domain": "bank",
        },
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["query_id"]
    detail = client.get(
        f"/api/v1/admin/audit/queries/{body['query_id']}", params={"tenant_id": "t001"}
    )
    assert detail.status_code == 200
    assert detail.json()["item"]["status"] == "error"
    assert detail.json()["item"]["error_code"] == "NOT_FOUND"


def test_execute_sql_failure_has_audit(client):
    """SQL 构建/执行失败（引用不存在的列）后存在 error Audit。"""
    resp = _execute(client, dsl={
        "data_source": "orders",
        "metrics": [{"func": "sum", "field": "nonexistent_col_xyz", "alias": "x"}],
        "dimensions": ["product_name"],
        "limit": 10,
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["query_id"]
    detail = client.get(
        f"/api/v1/admin/audit/queries/{body['query_id']}", params={"tenant_id": "t001"}
    )
    assert detail.status_code == 200
    assert detail.json()["item"]["status"] == "error"


def test_execute_graph_exception_has_audit(monkeypatch):
    """graph.ainvoke 抛出未预期异常时存在 error Audit，响应 500 携带 query_id。"""
    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load(open(os.path.join(FIXTURES, "metrics_test.yaml"), encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
    }

    class _RaisingGraph:
        async def ainvoke(self, state, config):
            raise RuntimeError("simulated graph framework failure")

    # 替换 build_graph，使 app 内的 query_graph.ainvoke 抛异常。
    import nl2dsl.api_factory as api_factory_mod
    monkeypatch.setattr(api_factory_mod, "build_graph", lambda **kw: _RaisingGraph())

    app = create_app(
        engine=engine,
        registry_dict=registry,
        permissions={},
        enable_clarification=False,
        llm_client=None,
        generator_mode="rule",
        enable_optimizer=False,
    )
    c = TestClient(app)
    resp = c.post("/api/v1/query/execute", json={
        "dsl": {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}], "limit": 10},
        "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 500
    body = resp.json()
    assert body["query_id"]
    assert body["error_code"] == "INTERNAL_ERROR"
    detail = c.get(f"/api/v1/admin/audit/queries/{body['query_id']}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    item = detail.json()["item"]
    assert item["status"] == "error"
    assert item["error_code"] == "INTERNAL_ERROR"


def test_execute_success_single_query_id(client):
    """成功请求只对应同一个 query_id 的审计记录。"""
    resp = _execute(client)
    qid = resp.json()["query_id"]
    detail = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    assert detail.json()["item"]["query_id"] == qid
    assert detail.json()["item"]["status"] == "success"


def test_sse_final_result_has_query_id(client):
    resp = client.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200
    body = resp.read().decode("utf-8")
    # 最终 done 事件必须携带 query_id
    assert "query_id" in body
    # 解析 done 事件拿到 query_id，验证可查询审计
    qid = None
    for line in body.splitlines():
        if line.startswith("data:") and "query_id" in line:
            import json as _json
            try:
                payload = _json.loads(line[len("data:"):].strip())
                if isinstance(payload, dict) and payload.get("query_id"):
                    qid = payload["query_id"]
                    break
            except Exception:
                continue
    assert qid, "SSE 未返回 query_id"
    detail = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    assert detail.json()["item"]["query_id"] == qid


# --- 正式入口契约 ---

def test_official_app_feedback_request_model_has_required_fields():
    """正式入口 FeedbackRequest 必须包含 tenant_id / is_correct / issue_type。"""
    from nl2dsl.api_factory import FeedbackRequest
    fields = set(FeedbackRequest.model_fields.keys())
    assert {"query_id", "user_id", "tenant_id", "is_correct", "issue_type"}.issubset(fields)


def test_official_app_uses_create_app():
    """uvicorn nl2dsl.api:app 与测试 app 同一实现。"""
    from nl2dsl.api import app as official_app
    from nl2dsl.api_factory import create_app
    # 官方 app 由 create_app 产出，路由一致
    official_paths = {r.path for r in official_app.routes if hasattr(r, "path")}
    assert "/api/v1/query" in official_paths
    assert "/api/v1/feedback" in official_paths


# --- 第二轮审阅 P0：详情接口租户隔离 ---

def _make_feedback(client, tenant="t001"):
    data = _query(client)
    fb = client.post("/api/v1/feedback", json={
        "query_id": data["query_id"], "user_id": "u001", "tenant_id": tenant,
        "is_correct": False, "issue_type": "metric", "comment": "口径不对",
    }).json()
    return data["query_id"], fb["feedback_id"]


def test_feedback_detail_requires_tenant(client):
    """缺少 tenant_id 时拒绝读取反馈详情。"""
    _, fb_id = _make_feedback(client)
    resp = client.get(f"/api/v1/admin/feedback/{fb_id}")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_feedback_detail_rejects_blank_tenant(client):
    """tenant_id 为空白时拒绝读取反馈详情。"""
    _, fb_id = _make_feedback(client)
    resp = client.get(f"/api/v1/admin/feedback/{fb_id}", params={"tenant_id": "   "})
    assert resp.status_code == 400


def test_feedback_detail_correct_tenant_succeeds(client):
    """正确租户可以读取反馈详情。"""
    _, fb_id = _make_feedback(client)
    resp = client.get(f"/api/v1/admin/feedback/{fb_id}", params={"tenant_id": "t001"})
    assert resp.status_code == 200
    assert resp.json()["item"]["feedback_id"] == fb_id


def test_feedback_detail_wrong_tenant_returns_404(client):
    """错误租户读取 feedback detail 返回 404，且不泄露其他租户内容。"""
    _, fb_id = _make_feedback(client, tenant="t001")
    resp = client.get(f"/api/v1/admin/feedback/{fb_id}", params={"tenant_id": "t-hacker"})
    assert resp.status_code == 404
    # 响应体不得包含其他租户的反馈内容
    body = resp.text
    assert "口径不对" not in body
    assert "t001" not in body


def test_audit_detail_requires_tenant(client):
    """缺少 tenant_id 时拒绝读取审计详情。"""
    data = _query(client)
    resp = client.get(f"/api/v1/admin/audit/queries/{data['query_id']}")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_audit_detail_rejects_blank_tenant(client):
    """tenant_id 为空白时拒绝读取审计详情。"""
    data = _query(client)
    resp = client.get(
        f"/api/v1/admin/audit/queries/{data['query_id']}", params={"tenant_id": "  "}
    )
    assert resp.status_code == 400


def test_audit_detail_wrong_tenant_returns_404(client):
    """错误租户读取 audit detail 返回 404，不泄露其他租户 SQL/DSL/Trace/问题文本。"""
    data = _query(client, question="查询销售额", user="u001", tenant="t001")
    qid = data["query_id"]
    resp = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t-hacker"})
    assert resp.status_code == 404
    body = resp.text
    # 不得包含其他租户的 SQL / DSL / Trace / 问题文本
    assert "查询销售额" not in body
    assert "sales_amount" not in body
    assert "SELECT" not in body


def test_audit_detail_correct_tenant_succeeds(client):
    """正确租户可以读取审计详情，含 DSL/SQL/Trace。"""
    data = _query(client, question="查询销售额", user="u001", tenant="t001")
    resp = client.get(
        f"/api/v1/admin/audit/queries/{data['query_id']}", params={"tenant_id": "t001"}
    )
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["tenant_id"] == "t001"
    assert item["question"] == "查询销售额"


# --- 第二轮审阅 P1：简单 SSE 最终状态与异常审计 ---

def _build_app_with_fake_graph(monkeypatch, fake_graph):
    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load(open(os.path.join(FIXTURES, "metrics_test.yaml"), encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
    }
    import nl2dsl.api_factory as api_factory_mod
    monkeypatch.setattr(api_factory_mod, "build_graph", lambda **kw: fake_graph)
    app = create_app(
        engine=engine,
        registry_dict=registry,
        permissions={},
        enable_clarification=False,
        llm_client=None,
        generator_mode="rule",
        enable_optimizer=False,
    )
    return TestClient(app)


class _FakeStreamGraph:
    """Fake graph: astream yields predetermined update chunks; ainvoke unused."""

    def __init__(self, chunks, raise_exc=None):
        self._chunks = chunks
        self._raise = raise_exc

    async def astream(self, state, config, stream_mode="updates"):
        if self._raise is not None:
            raise self._raise
        for ch in self._chunks:
            yield ch


class _FakeWarningGraph:
    async def ainvoke(self, state, config):
        from nl2dsl.dsl.models import Aggregation, DSL

        return {
            "status": "warning",
            "data": [
                {"region": "华东", "sales_amount": 100},
                {"region": "华南", "sales_amount": 80},
                {"region": "华北", "sales_amount": 60},
            ],
            "dsl": DSL(
                data_source="orders",
                metrics=[Aggregation(func="sum", field="pay_amount", alias="sales_amount")],
                dimensions=["region"],
            ),
            "sql": "SELECT region, SUM(pay_amount) AS sales_amount FROM orders GROUP BY region",
            "explanation": "查询成功，但优化器发现非阻断警告。",
            "confidence": 0.72,
            "trace": [{"step": "execute_sql", "status": "success", "rows_returned": 3}],
        }


def test_warning_query_preserves_successful_rows(monkeypatch):
    """A non-blocking warning must not discard rows returned by successful SQL."""
    c = _build_app_with_fake_graph(monkeypatch, _FakeWarningGraph())

    resp = c.post("/api/v1/query", json={
        "question": "按地区查询销售额",
        "user_id": "u001",
        "tenant_id": "t001",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "warning"
    assert len(body["data"]) == 3
    assert body["data"][0]["sales_amount"] == 100
    assert body["sql"].startswith("SELECT region")
    assert body["explanation"] == "查询成功，但优化器发现非阻断警告。"
    assert body["confidence"] == 0.72


def test_sse_result_has_real_final_state_not_last_chunk(monkeypatch):
    """最后一个 update chunk 不是完整状态时，result 仍包含真实最终状态（合并所有 chunk）。"""
    chunks = [
        {"generate_dsl": {"dsl": {"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}]}, "status": "success"}},
        # 最后一个 chunk 只含 sql，不含 status/dsl —— 旧实现会把它当成完整状态。
        {"execute_sql": {"sql": "SELECT sum(pay_amount) FROM orders", "data": [{"sales_amount": 100}]}},
    ]
    c = _build_app_with_fake_graph(monkeypatch, _FakeStreamGraph(chunks))
    resp = c.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.read().decode("utf-8"))
    result = next(d for ev, d in events if ev == "result")
    # 合并后应同时包含 dsl（来自第一个 chunk）和 sql（来自最后一个 chunk）
    assert result["status"] == "success"
    assert result["sql"] == "SELECT sum(pay_amount) FROM orders"
    assert result["dsl"] is not None
    assert result["rows_returned"] == 1


def test_sse_success_audit_contains_dsl_sql_trace(client):
    """简单 SSE 成功审计包含 DSL、SQL 和 Trace。"""
    resp = client.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.read().decode("utf-8"))
    result = next(d for ev, d in events if ev == "result")
    qid = result["query_id"]
    detail = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    item = detail.json()["item"]
    assert item["status"] == "success"
    assert item["dsl"] is not None
    assert item["sql"] is not None
    assert isinstance(item["trace"], list) and item["trace"]


def test_sse_graph_error_audit_is_error(monkeypatch):
    """简单 SSE 图返回 error 时审计状态为 error，result 事件含 error。"""
    chunks = [{"execute_sql": {"status": "error", "error": "boom", "error_code": "QUERY_ERROR"}}]
    c = _build_app_with_fake_graph(monkeypatch, _FakeStreamGraph(chunks))
    resp = c.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    events = _parse_sse(resp.read().decode("utf-8"))
    result = next(d for ev, d in events if ev == "result")
    assert result["status"] == "error"
    assert result["error"] == "boom"
    qid = result["query_id"]
    detail = c.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.json()["item"]["status"] == "error"


def test_sse_astream_exception_emits_error_event_and_audit(monkeypatch):
    """astream() 抛异常时客户端收到 error 事件，Audit 中存在同 query_id 的 error 记录。"""
    c = _build_app_with_fake_graph(
        monkeypatch, _FakeStreamGraph([], raise_exc=RuntimeError("stream blew up"))
    )
    resp = c.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.read().decode("utf-8"))
    err = next(d for ev, d in events if ev == "error")
    assert err["query_id"]
    assert "stream blew up" in err["error"]
    done = next(d for ev, d in events if ev == "done")
    assert done["query_id"] == err["query_id"]
    # Audit 中存在同 query_id 的 error 记录
    detail = c.get(f"/api/v1/admin/audit/queries/{err['query_id']}", params={"tenant_id": "t001"})
    assert detail.status_code == 200
    item = detail.json()["item"]
    assert item["status"] == "error"
    assert item["error_code"] == "INTERNAL_ERROR"


def test_sse_result_done_query_id_consistent_with_audit(client):
    """result/done 中 query_id 与 Audit 一致。"""
    resp = client.post("/api/v1/query/stream", json={
        "question": "查询销售额", "user_id": "u001", "tenant_id": "t001",
    })
    events = _parse_sse(resp.read().decode("utf-8"))
    result = next(d for ev, d in events if ev == "result")
    done = next(d for ev, d in events if ev == "done")
    assert result["query_id"] == done["query_id"]
    detail = client.get(
        f"/api/v1/admin/audit/queries/{result['query_id']}", params={"tenant_id": "t001"}
    )
    assert detail.status_code == 200
    assert detail.json()["item"]["query_id"] == result["query_id"]


# --- 第二轮审阅 P1：Agent Trace 生产与完整率一致 ---

def _audit_trace_steps(client, qid):
    detail = client.get(f"/api/v1/admin/audit/queries/{qid}", params={"tenant_id": "t001"})
    assert detail.status_code == 200, detail.text
    return detail.json()["item"]["trace"]


def test_complex_query_agent_trace_is_complete(client):
    """真实复杂查询产生的 Agent Trace 被质量分析器判为完整。"""
    from nl2dsl.quality.analyzer import (
        _classify_path, _path_complete, _trace_items, _trace_steps,
    )

    resp = client.post("/api/v1/query", json={
        "question": "对比华东和华南的销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200, resp.text
    qid = resp.json()["query_id"]
    trace = _audit_trace_steps(client, qid)
    steps = _trace_steps(trace)
    status = resp.json().get("status", "success")
    # 成功路径必须看到 sub_query_end（start 只证明开始，不能替代结束）
    assert "agent" in steps
    assert "sub_query_end" in steps
    # 质量分析器判定为完整（按 sub_query_id 配对校验）
    path = _classify_path(steps, status)
    assert path == "agent"
    assert _path_complete(path, _trace_items(trace), status, optimizer_enabled_hint=False)


def test_complex_query_trace_core_steps_present(client):
    """正常复杂查询 Trace 至少体现 agent / plan / 子查询 / aggregation / explanation。"""
    resp = client.post("/api/v1/query", json={
        "question": "对比华东和华南的销售额", "user_id": "u001", "tenant_id": "t001",
    })
    assert resp.status_code == 200, resp.text
    trace = _audit_trace_steps(client, resp.json()["query_id"])
    steps = {e.get("step") for e in trace}
    # 核心步骤齐全；成功路径必须看到 sub_query_end，不接受 start 替代
    assert "agent" in steps
    assert "plan" in steps
    assert "sub_query_end" in steps
    assert "aggregation" in steps or "explanation" in steps


def test_complex_query_and_sse_trace_consistent(client):
    """普通复杂查询与复杂 SSE 的 Trace 核心步骤一致。"""
    from nl2dsl.quality.analyzer import _trace_steps

    # 普通复杂查询
    r1 = client.post("/api/v1/query", json={
        "question": "对比华东和华南的销售额", "user_id": "u001", "tenant_id": "t001",
    })
    trace_http = _audit_trace_steps(client, r1.json()["query_id"])

    # 复杂 SSE
    r2 = client.post("/api/v1/query/stream", json={
        "question": "对比华东和华南的销售额", "user_id": "u001", "tenant_id": "t001",
    })
    events = _parse_sse(r2.read().decode("utf-8"))
    result_ev = next(d for ev, d in events if ev == "result")
    trace_sse = _audit_trace_steps(client, result_ev["query_id"])

    steps_http = _trace_steps(trace_http)
    steps_sse = _trace_steps(trace_sse)
    # 核心步骤集合一致（都含 agent + sub_query_end）
    core = {"agent", "sub_query_end"}
    assert core.issubset(steps_http)
    assert core.issubset(steps_sse)
    assert (steps_http & {"sub_query_end", "sub_query_start"}) == (steps_sse & {"sub_query_end", "sub_query_start"})
