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
