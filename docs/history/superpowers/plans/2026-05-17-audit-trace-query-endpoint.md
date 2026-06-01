# 历史查询链路接口 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给现有审计表加 2 个只读 HTTP 接口,让外部能查历史查询的完整链路。

**Architecture:** 在 `AuditLogger` 上加两个查询方法,在 `api.py` / `api_factory.py` 上各加两个路由(列表 + 详情)。不动表 schema、不动 `_audit_logger.log()`、不动现有路由。

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 (text() 参数化查询) + pytest.

**Spec:** `docs/superpowers/specs/2026-05-17-audit-trace-query-endpoint-design.md`

---

## 文件清单

| 文件 | 操作 |
|------|------|
| `nl2dsl/exceptions.py` | 加 `NotFoundError` |
| `nl2dsl/audit/logger.py` | 在 `AuditLogger` 加 `get_query()` 和 `list_queries()` |
| `nl2dsl/api_factory.py` | 加 2 路由 + Pydantic 响应模型(测试主入口) |
| `nl2dsl/api.py` | 镜像同样的 2 路由(线上 server 入口) |
| `tests/unit/test_audit_logger.py` | 追加 `get_query` / `list_queries` 单测 |
| `tests/e2e/test_audit_query_api.py` | 新建 e2e 测试 |

---

## Task 1: NotFoundError 异常

**Files:**
- Modify: `nl2dsl/exceptions.py`
- Modify: `tests/unit/test_exceptions.py`

- [ ] **Step 1: Write failing test**

在 `tests/unit/test_exceptions.py` 文件顶部 import 处增加 `NotFoundError`,文件底部追加:

```python
def test_not_found_error():
    exc = NotFoundError("audit record not found")
    assert exc.error_code == "NOT_FOUND"
    assert exc.status_code == 404
```

- [ ] **Step 2: Verify fail**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_exceptions.py::test_not_found_error -v
```
Expected: `ImportError: cannot import name 'NotFoundError'`

- [ ] **Step 3: Implement**

在 `nl2dsl/exceptions.py` 末尾追加:

```python
class NotFoundError(NL2DSLException):
    error_code = "NOT_FOUND"
    status_code = 404
```

- [ ] **Step 4: Verify pass**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_exceptions.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit (跳过此步如果用户未要求提交)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/exceptions.py tests/unit/test_exceptions.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat: add NotFoundError exception"
```

---

## Task 2: AuditLogger.get_query

**Files:**
- Modify: `nl2dsl/audit/logger.py`
- Modify: `tests/unit/test_audit_logger.py`

- [ ] **Step 1: Write failing tests**

在 `tests/unit/test_audit_logger.py` 末尾追加:

```python
def test_get_query_returns_full_record(logger):
    trace = [{"step": "dsl_generate", "status": "success", "duration_ms": 1}]
    dsl = {"data_source": "orders"}
    logger.log(
        query_id="q-001",
        user_id="u1",
        tenant_id="t1",
        question="问题",
        dsl_json=dsl,
        sql_text="SELECT 1",
        status="success",
        execution_time_ms=5,
        rows_returned=3,
        trace_json=trace,
    )

    row = logger.get_query("q-001")

    assert row is not None
    assert row["query_id"] == "q-001"
    assert row["dsl"] == dsl
    assert row["sql"] == "SELECT 1"
    assert row["trace"] == trace
    assert row["rows_returned"] == 3
    assert row["status"] == "success"


def test_get_query_missing_returns_none(logger):
    assert logger.get_query("does-not-exist") is None


def test_get_query_legacy_null_trace(logger):
    """旧记录 trace_json 为 NULL,返回 trace=[] 而不是 None。"""
    logger.log(
        query_id="q-legacy",
        user_id="u1",
        question="老问题",
        status="success",
    )
    row = logger.get_query("q-legacy")
    assert row is not None
    assert row["trace"] == []
    assert row["dsl"] is None
```

- [ ] **Step 2: Verify fail**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_audit_logger.py -v
```
Expected: 3 new tests FAIL with `AttributeError: 'AuditLogger' object has no attribute 'get_query'`.

- [ ] **Step 3: Implement**

在 `nl2dsl/audit/logger.py` 的 `AuditLogger` 类内,`query()` 方法之后追加:

```python
    def get_query(self, query_id: str) -> dict | None:
        """Return one audit record (with dsl/sql/trace decoded), or None."""
        with self._engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM nl2dsl_audit_log WHERE query_id = :qid"),
                {"qid": query_id},
            )
            row = result.first()
        if row is None:
            return None
        record = dict(row._mapping)
        record["dsl"] = json.loads(record.pop("dsl_json")) if record.get("dsl_json") else None
        record["sql"] = record.pop("sql_text")
        record["trace"] = json.loads(record.pop("trace_json")) if record.get("trace_json") else []
        return record
```

- [ ] **Step 4: Verify pass**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_audit_logger.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit (按需)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/audit/logger.py tests/unit/test_audit_logger.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat(audit): add AuditLogger.get_query"
```

---

## Task 3: AuditLogger.list_queries

**Files:**
- Modify: `nl2dsl/audit/logger.py`
- Modify: `tests/unit/test_audit_logger.py`

- [ ] **Step 1: Write failing tests**

在 `tests/unit/test_audit_logger.py` 末尾追加(`_seed_records` 用 `prefix` + `user` 拼 query_id,从一开始就避免主键冲突):

```python
import time as _time


def _seed_records(
    logger,
    n: int = 3,
    user: str = "u1",
    tenant: str = "t1",
    prefix: str = "q",
):
    for i in range(n):
        logger.log(
            query_id=f"{prefix}-{user}-{i:03d}",
            user_id=user,
            tenant_id=tenant,
            question=f"问题-{prefix}-{i}",
            dsl_json={"data_source": "orders"},
            sql_text=f"SELECT {i}",
            status="success" if i % 2 == 0 else "error",
            execution_time_ms=10 + i,
            rows_returned=i,
            trace_json=[{"step": "dsl_generate", "status": "success", "duration_ms": 0}],
        )
        _time.sleep(0.01)  # 让 created_at 有差异(SQLite 默认到秒)


def test_list_queries_basic(logger):
    _seed_records(logger, n=3)
    items, total = logger.list_queries(limit=20, offset=0)
    assert total == 3
    assert len(items) == 3
    # 列表项不带大字段
    for it in items:
        assert "dsl" not in it
        assert "sql" not in it
        assert "trace" not in it
    qids = {it["query_id"] for it in items}
    assert qids == {"q-u1-000", "q-u1-001", "q-u1-002"}


def test_list_queries_user_filter(logger):
    _seed_records(logger, n=2, user="u1", prefix="a")
    _seed_records(logger, n=2, user="u2", prefix="b")
    items, total = logger.list_queries(user_id="u1", limit=20, offset=0)
    assert total == 2
    assert all(it["user_id"] == "u1" for it in items)


def test_list_queries_status_filter(logger):
    _seed_records(logger, n=3)  # i=0,2 success, i=1 error
    items, total = logger.list_queries(status="success")
    assert total == 2


def test_list_queries_question_like(logger):
    _seed_records(logger, n=3)
    items, total = logger.list_queries(question_like="q-1")
    assert total == 1
    assert "q-1" in items[0]["question"]


def test_list_queries_pagination(logger):
    _seed_records(logger, n=5)
    items, total = logger.list_queries(limit=2, offset=0)
    assert total == 5
    assert len(items) == 2
    items2, _ = logger.list_queries(limit=2, offset=2)
    assert len(items2) == 2
    # 第二页和第一页 query_id 不重叠
    assert {it["query_id"] for it in items}.isdisjoint({it["query_id"] for it in items2})
```

- [ ] **Step 2: Verify fail**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_audit_logger.py -v
```
Expected: 5 new tests FAIL with `AttributeError: 'AuditLogger' object has no attribute 'list_queries'`.

- [ ] **Step 3: Implement**

在 `nl2dsl/audit/logger.py` 的 `AuditLogger` 内,`get_query()` 之后追加:

```python
    _LIST_COLUMNS = (
        "query_id, user_id, tenant_id, question, status, "
        "execution_time_ms, rows_returned, error_code, created_at"
    )

    def list_queries(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        question_like: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: dict = {}

        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if start_time is not None:
            clauses.append("created_at >= :start_time")
            params["start_time"] = start_time
        if end_time is not None:
            clauses.append("created_at <= :end_time")
            params["end_time"] = end_time
        if question_like is not None:
            clauses.append("question LIKE :q_like")
            params["q_like"] = f"%{question_like}%"

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        list_sql = (
            f"SELECT {self._LIST_COLUMNS} FROM nl2dsl_audit_log {where} "
            f"ORDER BY created_at DESC, query_id DESC "
            f"LIMIT :limit OFFSET :offset"
        )
        count_sql = f"SELECT COUNT(*) FROM nl2dsl_audit_log {where}"

        with self._engine.connect() as conn:
            list_params = {**params, "limit": limit, "offset": offset}
            items = [dict(r._mapping) for r in conn.execute(text(list_sql), list_params)]
            total = conn.execute(text(count_sql), params).scalar() or 0

        return items, int(total)
```

- [ ] **Step 4: Verify pass**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/unit/test_audit_logger.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit (按需)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/audit/logger.py tests/unit/test_audit_logger.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat(audit): add AuditLogger.list_queries with filters/pagination"
```

---

## Task 4: 详情接口(api_factory.py + TDD)

**Files:**
- Create: `tests/e2e/test_audit_query_api.py`
- Modify: `nl2dsl/api_factory.py`

- [ ] **Step 1: Write failing e2e tests**

新建 `tests/e2e/test_audit_query_api.py`:

```python
"""E2E tests for /api/v1/admin/audit/queries{,/{id}} endpoints."""

from __future__ import annotations

import uuid

from sqlalchemy import text


def _make_one_query(client, question_suffix: str, user: str = "u001", tenant: str = "t001") -> str:
    """Hit /api/v1/query to produce an audit record. Return the audit row's query_id."""
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
            text("SELECT query_id FROM nl2dsl_audit_log WHERE question = :q ORDER BY created_at DESC LIMIT 1"),
            {"q": question},
        ).first()
    assert row is not None
    return row[0]


# --- Detail endpoint ---


def test_audit_detail_returns_full_trace(mock_api_client, mock_engine):
    question = _make_one_query(mock_api_client, uuid.uuid4().hex[:8])
    query_id = _find_query_id(mock_engine, question)

    resp = mock_api_client.get(f"/api/v1/admin/audit/queries/{query_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    item = data["item"]
    assert item["query_id"] == query_id
    assert item["question"] == question
    assert isinstance(item["dsl"], dict)
    assert "SELECT" in item["sql"]
    assert isinstance(item["trace"], list)
    assert len(item["trace"]) == 8
    assert item["trace"][0]["step"] == "dsl_generate"


def test_audit_detail_404_when_missing(mock_api_client):
    resp = mock_api_client.get("/api/v1/admin/audit/queries/does-not-exist")
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == "error"
    assert data["error_code"] == "NOT_FOUND"


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

    resp = mock_api_client.get(f"/api/v1/admin/audit/queries/{legacy_id}")
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["trace"] == []
    assert item["dsl"] is None
    assert item["sql"] is None
```

- [ ] **Step 2: Verify fail**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/e2e/test_audit_query_api.py -v
```
Expected: 3 tests FAIL with 404 (route not registered).

- [ ] **Step 3: Implement**

3a. 在 `nl2dsl/api_factory.py` 顶部 imports 区:

```python
from nl2dsl.exceptions import NL2DSLException, NotFoundError
```

3b. 在 `api_factory.py` 的 Response 模型区(`class RefreshEnumsResponse` 后)追加:

```python
class AuditQueryDetailItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str | None = None
    question: str
    dsl: dict | None = None
    sql: str | None = None
    status: str
    execution_time_ms: int | None = None
    rows_scanned: int | None = None
    rows_returned: int | None = None
    trace: list[dict] = []
    error_code: str | None = None
    error_message: str | None = None
    created_at: str


class AuditQueryDetailResponse(BaseModel):
    status: str = "success"
    item: AuditQueryDetailItem
```

3c. 在 `create_app()` 内的路由区(`/admin/enums/refresh` 旁,exception_handler 之前)追加:

```python
@app.get("/api/v1/admin/audit/queries/{query_id}")
async def get_audit_query(query_id: str) -> AuditQueryDetailResponse:
    row = audit_logger.get_query(query_id)
    if row is None:
        raise NotFoundError(f"audit record not found: query_id={query_id}")
    # created_at 在 SQLite 里是 datetime,转 str 保证序列化
    row["created_at"] = str(row.get("created_at") or "")
    return AuditQueryDetailResponse(item=AuditQueryDetailItem(**row))
```

- [ ] **Step 4: Verify pass**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/e2e/test_audit_query_api.py -v
```
Expected: 3 detail tests PASS.

- [ ] **Step 5: Commit (按需)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/api_factory.py tests/e2e/test_audit_query_api.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat(api): add GET /admin/audit/queries/{id} detail endpoint"
```

---

## Task 5: 列表接口(api_factory.py + TDD)

**Files:**
- Modify: `tests/e2e/test_audit_query_api.py`
- Modify: `nl2dsl/api_factory.py`

- [ ] **Step 1: Write failing e2e tests**

在 `tests/e2e/test_audit_query_api.py` 末尾追加:

```python
# --- List endpoint ---


def test_audit_list_basic(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel)
    _make_one_query(mock_api_client, sentinel)
    _make_one_query(mock_api_client, sentinel)

    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"q": sentinel})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total"] == 3
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["items"]) == 3
    for it in data["items"]:
        # 列表项不带大字段
        assert "dsl" not in it
        assert "sql" not in it
        assert "trace" not in it


def test_audit_list_user_filter(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    _make_one_query(mock_api_client, sentinel, user="u-alpha")
    _make_one_query(mock_api_client, sentinel, user="u-beta")

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "user_id": "u-alpha"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["user_id"] == "u-alpha"


def test_audit_list_status_filter(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    # 制造一条 success
    _make_one_query(mock_api_client, sentinel)
    # 制造一条 error: 用一个不存在的 data_source
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

    # 只看错误那条
    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "status": "error"},
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
        params={"q": sentinel, "limit": 2, "offset": 0},
    ).json()
    page2 = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "limit": 2, "offset": 2},
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

    # 拿一条记录的 created_at,围绕它构造窗口
    with mock_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT query_id, created_at FROM nl2dsl_audit_log "
                "WHERE question LIKE :q ORDER BY created_at ASC"
            ),
            {"q": f"%{sentinel}%"},
        ).fetchall()
    assert len(rows) == 2
    # SQLite 的 created_at 是 'YYYY-MM-DD HH:MM:SS' 字符串
    earliest = str(rows[0][1])
    latest = str(rows[1][1])

    # 用 latest 作为 start_time → 只剩第二条(>=)
    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "start_time": latest},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["created_at"] >= latest

    # 用 earliest 作为 end_time → 不丢任何(<=)
    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": sentinel, "end_time": latest},
    )
    assert resp.status_code == 200
    for it in resp.json()["items"]:
        assert it["created_at"] <= latest


def test_audit_list_sql_injection_safe(mock_api_client, mock_engine):
    """spec §6.3: q 含单引号不应导致 SQL 注入,接口应正常返回(空结果)。"""
    # 这一串里含单引号、`OR 1=1`,如果未参数化会拿出全表
    malicious = "'; DROP TABLE nl2dsl_audit_log; --"

    resp = mock_api_client.get(
        "/api/v1/admin/audit/queries",
        params={"q": malicious, "limit": 10},
    )
    assert resp.status_code == 200
    # 没有 question 会精确等于这串恶意串,所以应该是 0
    assert resp.json()["total"] == 0

    # 表还在(没被注入 drop 掉)
    with mock_engine.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM nl2dsl_audit_log")).scalar()
    assert cnt is not None and cnt >= 0


def test_audit_list_invalid_limit_400(mock_api_client):
    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"limit": 0})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"

    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"limit": 1000})
    assert resp.status_code == 400


def test_audit_list_invalid_offset_400(mock_api_client):
    """spec §6.1#7: offset=-1 应返回 400 VALIDATION_ERROR。"""
    resp = mock_api_client.get("/api/v1/admin/audit/queries", params={"offset": -1})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: Verify fail**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/e2e/test_audit_query_api.py -v
```
Expected: 8 list tests FAIL with 404.

- [ ] **Step 3: Implement**

3a. 在 `api_factory.py` 的 imports 区,补充 `ValidationError`:

```python
from nl2dsl.exceptions import NL2DSLException, NotFoundError, ValidationError
```

3b. 在 Response 模型区(详情模型旁)追加:

```python
class AuditQueryListItem(BaseModel):
    query_id: str
    user_id: str
    tenant_id: str | None = None
    question: str
    status: str
    execution_time_ms: int | None = None
    rows_returned: int | None = None
    error_code: str | None = None
    created_at: str


class AuditQueryListResponse(BaseModel):
    status: str = "success"
    total: int
    limit: int
    offset: int
    items: list[AuditQueryListItem]
```

3c. 在 `create_app()` 内,详情路由旁追加:

```python
from fastapi import Query as _FQuery


@app.get("/api/v1/admin/audit/queries")
async def list_audit_queries(
    user_id: str | None = None,
    tenant_id: str | None = None,
    status_: str | None = _FQuery(None, alias="status"),
    start_time: str | None = None,
    end_time: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AuditQueryListResponse:
    if not (1 <= limit <= 100):
        raise ValidationError("limit must be between 1 and 100")
    if offset < 0:
        raise ValidationError("offset must be >= 0")

    items, total = audit_logger.list_queries(
        user_id=user_id,
        tenant_id=tenant_id,
        status=status_,
        start_time=start_time,
        end_time=end_time,
        question_like=q,
        limit=limit,
        offset=offset,
    )
    for it in items:
        it["created_at"] = str(it.get("created_at") or "")
    return AuditQueryListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditQueryListItem(**r) for r in items],
    )
```

**注**:`from fastapi import Query as _FQuery` 已在文件顶部 import 过 `Query`?如果是,直接用 `Query`;否则在顶部 imports 加 `from fastapi import Query`(在 `FastAPI, Request` 旁)。检查后选一种方式。

- [ ] **Step 4: Verify pass**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest tests/e2e/test_audit_query_api.py -v
```
Expected: 全部 11 个测试 PASS(3 详情 + 8 列表)。

- [ ] **Step 5: 跑全套防回归**

```bash
cd "/d/demo/db-gpt/NL2DSL" && python -m pytest -q
```
Expected: 全 PASS。

- [ ] **Step 6: Commit (按需)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/api_factory.py tests/e2e/test_audit_query_api.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat(api): add GET /admin/audit/queries list endpoint"
```

---

## Task 6: 镜像到 api.py(线上 server)

**Files:**
- Modify: `nl2dsl/api.py`

api.py 没有 e2e fixture,直接镜像两条路由 + 模型即可。测试由 api_factory 那套覆盖。

- [ ] **Step 1: 在 imports 区追加**

```python
from nl2dsl.exceptions import NL2DSLException, NotFoundError, ValidationError
from fastapi import Query  # 若已 import 则跳过
```

- [ ] **Step 2: 在 Response 模型区追加 4 个模型**

把 Task 4 的 `AuditQueryDetailItem`, `AuditQueryDetailResponse` 和 Task 5 的 `AuditQueryListItem`, `AuditQueryListResponse` 完整复制到 `api.py` 的对应位置(`class RefreshEnumsResponse` 之后)。

- [ ] **Step 3: 在路由区追加 2 路由**

复制 Task 4 / Task 5 的路由实现到 `api.py`,**改两处**:
- `audit_logger.get_query` → `_audit_logger.get_query`
- `audit_logger.list_queries` → `_audit_logger.list_queries`

- [ ] **Step 4: 重启 server 验证**

杀掉旧 uvicorn,重启:
```bash
cd "/d/demo/db-gpt/NL2DSL" && uvicorn nl2dsl.api:app --host 0.0.0.0 --port 8000
```
然后:
```bash
# 先跑一次 query 产生记录
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/q.json | python -m json.tool --no-ensure-ascii | head -20

# 列表
curl -s "http://localhost:8000/api/v1/admin/audit/queries?limit=3" | python -m json.tool --no-ensure-ascii

# 详情(用列表里的 query_id)
curl -s "http://localhost:8000/api/v1/admin/audit/queries/<query_id>" | python -m json.tool --no-ensure-ascii
```
Expected: 列表返回 items,详情返回带 8 个 trace 步骤的完整结构。

- [ ] **Step 5: Commit (按需)**

```bash
git -C "/d/demo/db-gpt/NL2DSL" add nl2dsl/api.py
git -C "/d/demo/db-gpt/NL2DSL" commit -m "feat(api): mirror audit query endpoints in api.py"
```

---

## Self-Review Checklist(我已对照 spec 过一遍)

- [x] Spec §3.1 列表参数 → Task 5 全覆盖(user/tenant/status/start_time/end_time/q/limit/offset)
- [x] Spec §3.2 详情字段 → Task 4 (item 含 dsl/sql/trace/...)
- [x] Spec §4.2 AuditLogger 方法签名 → Task 2 + Task 3
- [x] Spec §5 向后兼容 → Task 2 `test_get_query_legacy_null_trace` + Task 4 `test_audit_detail_legacy_record_returns_empty_trace`
- [x] Spec §6.1 列表测试 → Task 5(basic / user_filter / status_filter / `q` 模糊 / 时间窗口 / 分页 / `limit` 边界 / `offset=-1`)
- [x] Spec §6.2 详情测试 → Task 4(存在 / 不存在 / 老记录 NULL 兼容)
- [x] Spec §6.3 安全 → Task 5 `test_audit_list_sql_injection_safe`
- [x] 错误响应 400 / 404 → Task 4 / Task 5 各覆盖一条
- [x] api.py 镜像 → Task 6

**类型一致性自查**:`get_query` 返回 dict 里 `dsl`/`sql`/`trace` 三个键 ↔ `AuditQueryDetailItem` 的 `dsl`/`sql`/`trace` 字段名一致 ✓。`list_queries` 返回的 `_LIST_COLUMNS` ↔ `AuditQueryListItem` 字段一一对应 ✓。
