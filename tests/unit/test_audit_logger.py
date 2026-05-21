import pytest
from sqlalchemy import create_engine
from nl2dsl.audit.logger import AuditLogger


@pytest.fixture
def logger():
    engine = create_engine("sqlite:///:memory:")
    return AuditLogger(engine)


def test_log_query(logger):
    logger.log(
        query_id="test-001",
        user_id="u123",
        tenant_id="t001",
        question="查询销售额",
        status="success",
        execution_time_ms=150,
    )

    rows = logger.query("SELECT * FROM nl2dsl_audit_log")
    assert len(rows) == 1
    assert rows[0]["query_id"] == "test-001"
    assert rows[0]["status"] == "success"


def test_log_with_trace(logger):
    trace = [{"node": "llm_generate", "status": "success", "duration_ms": 100}]
    logger.log(
        query_id="test-002",
        user_id="u123",
        question="查询销售额",
        status="success",
        trace_json=trace,
    )

    rows = logger.query("SELECT * FROM nl2dsl_audit_log WHERE query_id = 'test-002'")
    assert len(rows) == 1
    import json
    assert json.loads(rows[0]["trace_json"])[0]["node"] == "llm_generate"


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
        _time.sleep(0.01)


def test_list_queries_basic(logger):
    _seed_records(logger, n=3)
    items, total = logger.list_queries(limit=20, offset=0)
    assert total == 3
    assert len(items) == 3
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
    _seed_records(logger, n=3)
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
    assert {it["query_id"] for it in items}.isdisjoint({it["query_id"] for it in items2})
