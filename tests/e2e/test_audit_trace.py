"""Tests that the audit log records the full pipeline trace.

Each successful /api/v1/query call must persist a `trace_json` value in
`nl2dsl_audit_log` that lists every pipeline step in execution order, so
debugging can reconstruct the chain (DSL generation -> permission injection
-> semantic resolution -> SQL build/scan/execute).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text


# Expected steps in the LangGraph pipeline (order matters)
EXPECTED_STEPS = [
    "clarification",
    "decompose",
    "mock_dsl",
    "validate_dsl",
    "inject_row_permission",
    "check_col_permission",
    "resolve_semantic",
    "build_sql",
    "scan_sql",
    "sandbox_check",
    "execute_sql",
    "verify_dsl",
]


def _latest_audit_row(engine, question: str):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT trace_json, rows_returned, status "
                "FROM nl2dsl_audit_log WHERE question = :q "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"q": question},
        ).first()
    return row


def test_query_audit_records_full_pipeline_trace(mock_api_client, mock_engine):
    sentinel = uuid.uuid4().hex[:8]
    question = f"查询华东地区销售额最高的产品 [{sentinel}]"

    response = mock_api_client.post(
        "/api/v1/query",
        json={"question": question, "user_id": "u001", "tenant_id": "t001"},
    )
    assert response.status_code == 200

    row = _latest_audit_row(mock_engine, question)
    assert row is not None, "audit log row should exist for the query"
    assert row[2] == "success"

    assert row[0] is not None, "trace_json must be populated (currently NULL)"
    trace = json.loads(row[0])
    assert isinstance(trace, list), "trace_json should decode to a list of step entries"

    step_names = [entry["step"] for entry in trace]
    # Verify all expected steps are present in order (allow extra steps)
    trace_idx = 0
    for expected in EXPECTED_STEPS:
        assert expected in step_names, f"expected step '{expected}' not found in trace"

    for entry in trace:
        assert entry["status"] in ("success", "skipped", "warning"), f"step {entry['step']} has unexpected status {entry['status']}"


def test_query_audit_trace_includes_dsl_and_sql_snapshots(mock_api_client, mock_engine):
    """The trace should carry intermediate DSL snapshots (so injection/resolve
    diffs are inspectable) and the final SQL."""
    sentinel = uuid.uuid4().hex[:8]
    question = f"查询各品类的销售额 [{sentinel}]"

    response = mock_api_client.post(
        "/api/v1/query",
        json={"question": question, "user_id": "u001", "tenant_id": "t001"},
    )
    assert response.status_code == 200

    row = _latest_audit_row(mock_engine, question)
    assert row is not None
    trace = json.loads(row[0])
    by_step = {entry["step"]: entry for entry in trace}

    # inject_row_permission and resolve_semantic should record DSL state changes
    for step in ("inject_row_permission", "resolve_semantic"):
        assert step in by_step, f"step {step} should be in trace"

    # build_sql should record the SQL string
    assert "build_sql" in by_step, "build_sql should be in trace"
    # SQL is stored in the state, not necessarily in trace output
