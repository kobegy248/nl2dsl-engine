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


EXPECTED_STEPS = [
    "dsl_generate",
    "validate",
    "row_permission_inject",
    "column_permission_check",
    "semantic_resolve",
    "sql_build",
    "sandbox",
    "sql_scan",
    "sql_execute",
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
    assert step_names == EXPECTED_STEPS, (
        f"trace steps mismatch.\n  expected: {EXPECTED_STEPS}\n  got:      {step_names}"
    )

    for entry in trace:
        assert entry["status"] == "success", f"step {entry['step']} not marked success"


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

    # DSL snapshot must appear after each step that mutates it
    for step in ("dsl_generate", "row_permission_inject", "semantic_resolve"):
        assert "dsl" in by_step[step].get("output", {}), (
            f"step {step} should record post-step DSL snapshot in output.dsl"
        )

    # row_permission_inject should add filters that were not in dsl_generate
    initial_filters = by_step["dsl_generate"]["output"]["dsl"].get("filters") or []
    post_inject_filters = by_step["row_permission_inject"]["output"]["dsl"].get("filters") or []
    assert len(post_inject_filters) > len(initial_filters), (
        "row_permission_inject should introduce additional filters (tenant + row-level)"
    )

    # sql_build should record the SQL string
    assert "sql" in by_step["sql_build"].get("output", {}), (
        "sql_build should record the built SQL in output.sql"
    )
    assert "SELECT" in by_step["sql_build"]["output"]["sql"]
