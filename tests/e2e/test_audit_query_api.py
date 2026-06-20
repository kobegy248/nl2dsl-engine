"""E2E tests for /api/v1/admin/audit/queries{,/{id}} endpoints."""

from __future__ import annotations

import uuid

from sqlalchemy import text


def _make_one_query(client, question_suffix: str, user: str = "u001", tenant: str = "t001") -> str:
    """Hit /api/v1/query to produce an audit record. Return the question used."""
    question = f"查询华东地区销售额最高的产品 [{question_suffix}]"
    resp = client.post(
        "/api/v1/query",
        json={"question": question, "user_id": user, "tenant_id": tenant},
    )
    assert resp.status_code == 200, resp.text
    return question


def _find_query_id(engine, question: str) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT query_id FROM nl2dsl_audit_log WHERE question = :q ORDER BY created_at DESC LIMIT 1"
            ),
            {"q": question},
        ).first()
    assert row is not None
    return row[0]


# --- Detail endpoint ---


def test_audit_detail_returns_full_trace(mock_api_client, mock_engine):
    question = _make_one_query(mock_api_client, uuid.uuid4().hex[:8])
    query_id = _find_query_id(mock_engine, question)

    resp = mock_api_client.get(f"/api/v1/admin/audit/queries/{query_id}", params={"tenant_id": "t001"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    item = data["item"]
    assert item["query_id"] == query_id
    assert item["question"] == question
    assert isinstance(item["dsl"], dict)
    assert "SELECT" in item["sql"]
    assert isinstance(item["trace"], list)
    # LangGraph pipeline produces ~12 steps (clarification, decompose, mock_dsl,
    # validate_dsl, inject_row_permission, check_col_permission, resolve_semantic,
    # build_sql, scan_sql, sandbox_check, execute_sql, verify_dsl)
    assert len(item["trace"]) >= 10
    assert item["trace"][0]["step"] == "clarification"


def test_audit_detail_404_when_missing(mock_api_client):
    resp = mock_api_client.get("/api/v1/admin/audit/queries/does-not-exist", params={"tenant_id": "t001"})
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == "error"
    assert data["error_code"] == "NOT_FOUND"


def test_audit_detail_requires_tenant(mock_api_client):
    """详情接口缺少 tenant_id 时拒绝（400），与列表接口租户边界一致。"""
    resp = mock_api_client.get("/api/v1/admin/audit/queries/does-not-exist")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_audit_detail_legacy_record_returns_empty_trace(mock_api_client, mock_engine):
    """旧记录 trace_json/dsl_json 为 NULL → trace=[] dsl=None,接口正常返回。"""
    legacy_id = f"legacy-{uuid.uuid4().hex[:8]}"
    with mock_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO nl2dsl_audit_log (query_id, user_id, tenant_id, question, status, execution_time_ms) "
                "VALUES (:qid, 'u-old', 't-old', '老问题', 'success', 12)"
            ),
            {"qid": legacy_id},
        )
        conn.commit()

    resp = mock_api_client.get(f"/api/v1/admin/audit/queries/{legacy_id}", params={"tenant_id": "t-old"})
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["trace"] == []
    assert item["dsl"] is None
    assert item["sql"] is None


# --- List endpoint ---


def test_audit_list_basic(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel)
    _make_one_query(mock_api_client, sentinel)
    _make_one_query(mock_api_client, sentinel)

    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"q": sentinel, "tenant_id": "t001"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total"] == 3
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["items"]) == 3
    for it in data["items"]:
        assert "dsl" not in it
        assert "sql" not in it
        assert "trace" not in it


def test_audit_list_user_filter(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel, user="u-alpha")
    _make_one_query(mock_api_client, sentinel, user="u-beta")

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "user_id": "u-alpha", "tenant_id": "t001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["user_id"] == "u-alpha"


def test_audit_list_status_filter(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel)
    bad_resp = mock_api_client.post(
        "/api/v1/query",
        json={
            "question": f"bad-question-{sentinel}",
            "user_id": "u001",
            "tenant_id": "t001",
            "data_source": "nonexistent_for_audit_test",
        },
    )
    assert bad_resp.status_code in (400, 422)

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "status": "error", "tenant_id": "t001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["status"] == "error"


def test_audit_list_pagination(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    for _ in range(4):
        _make_one_query(mock_api_client, sentinel)

    page1 = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "limit": 2, "offset": 0, "tenant_id": "t001"},
    ).json()
    page2 = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "limit": 2, "offset": 2, "tenant_id": "t001"},
    ).json()

    assert page1["total"] == 4
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    ids1 = {it["query_id"] for it in page1["items"]}
    ids2 = {it["query_id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)


def test_audit_list_time_window(mock_api_client, mock_engine):
    """spec §6.1#5: start_time / end_time 时间窗口过滤生效。"""
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel)
    _make_one_query(mock_api_client, sentinel)

    with mock_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT query_id, created_at FROM nl2dsl_audit_log "
                "WHERE question LIKE :q ORDER BY created_at ASC"
            ),
            {"q": f"%{sentinel}%"},
        ).fetchall()
    assert len(rows) == 2
    earliest = str(rows[0][1])
    latest = str(rows[1][1])

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "start_time": latest, "tenant_id": "t001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["created_at"] >= latest

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "end_time": latest, "tenant_id": "t001"},
    )
    assert resp.status_code == 200
    for it in resp.json()["items"]:
        assert it["created_at"] <= latest


def test_audit_list_sql_injection_safe(mock_api_client, mock_engine):
    """spec §6.3: q 含单引号不应导致 SQL 注入,接口应正常返回(空结果)。"""
    malicious = "'; DROP TABLE nl2dsl_audit_log; --"

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": malicious, "limit": 10, "tenant_id": "t001"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    with mock_engine.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM nl2dsl_audit_log")).scalar()
    assert cnt is not None and cnt >= 0


def test_audit_list_invalid_limit_400(mock_api_client):
    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"limit": 0, "tenant_id": "t001"})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"

    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"limit": 1000, "tenant_id": "t001"})
    assert resp.status_code == 400


def test_audit_list_invalid_offset_400(mock_api_client):
    """spec §6.1#7: offset=-1 应返回 400 VALIDATION_ERROR。"""
    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"offset": -1, "tenant_id": "t001"})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"
