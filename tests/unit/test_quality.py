"""Phase 6：质量报告分析器与报告生成测试。"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.feedback.store import FeedbackStore
from nl2dsl.quality.analyzer import (
    analyze_audit,
    analyze_evaluation,
    analyze_feedback,
)
from nl2dsl.quality.report import (
    build_quality_report,
    quality_report_to_json,
    quality_report_to_markdown,
)


def _engine():
    return create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


def _seed_success_audit(audit, qid, with_optimizer=False):
    steps = [
        {"step": "generate_dsl", "status": "success"},
        {"step": "validate_dsl", "status": "success"},
        {"step": "resolve_semantic", "status": "success"},
        {"step": "build_sql", "status": "success"},
        {"step": "scan_sql", "status": "success"},
        {"step": "execute_sql", "status": "success"},
    ]
    if with_optimizer:
        steps.insert(3, {"step": "optimize_dsl", "status": "success"})
    audit.log(
        query_id=qid, user_id="u001", tenant_id="t001",
        question="q", status="success", execution_time_ms=20,
        dsl_json='{"data_source": "orders"}', sql_text="SELECT 1",
        trace_json=steps,
    )


def test_trace_completeness_by_path():
    eng = _engine()
    audit = AuditLogger(eng)
    _seed_success_audit(audit, "q1", with_optimizer=False)
    _seed_success_audit(audit, "q2", with_optimizer=True)
    # incomplete trace (missing execute_sql)
    audit.log(
        query_id="q3", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=5, dsl_json='{"data_source":"orders"}', sql_text="SELECT 1",
        trace_json=[{"step": "generate_dsl"}, {"step": "validate_dsl"}],
    )
    # clarification path
    audit.log(
        query_id="q4", user_id="u001", tenant_id="t001", question="q", status="clarification",
        execution_time_ms=2, trace_json=[{"step": "clarification"}],
    )
    stats = analyze_audit(audit)
    assert stats["total_queries"] == 4
    # q1(success complete), q2(success+optimizer complete), q3(success path but
    # incomplete trace), q4(clarification complete) → completeness = 3/4
    assert abs(stats["trace_completeness"] - 0.75) < 1e-6
    assert stats["path_distribution"]["success"] == 2  # q1 + q3
    assert stats["path_distribution"]["success_with_optimizer"] == 1  # q2
    assert stats["path_distribution"]["clarification"] == 1  # q4
    assert stats["field_completeness"]["sql"] == 0.75


def test_latency_percentiles():
    eng = _engine()
    audit = AuditLogger(eng)
    for i, ms in enumerate([10, 20, 30, 40, 100]):
        audit.log(query_id=f"q{i}", user_id="u001", tenant_id="t001", question="q", status="success", execution_time_ms=ms)
    stats = analyze_audit(audit)
    # median of [10,20,30,40,100] = 30
    assert stats["latency"]["p50_ms"] == 30.0
    # p95 interpolation between 40 and 100 -> 88.0
    assert abs(stats["latency"]["p95_ms"] - 88.0) < 1e-6


def test_feedback_stats():
    eng = _engine()
    audit = AuditLogger(eng)
    store = FeedbackStore(eng, audit)
    audit.log(query_id="q1", user_id="u001", tenant_id="t001", question="q", status="success")
    audit.log(query_id="q2", user_id="u001", tenant_id="t001", question="q", status="success")
    store.submit(query_id="q1", user_id="u001", tenant_id="t001", is_correct=False, issue_type="metric", corrected_dsl={"data_source": "orders"})
    store.submit(query_id="q2", user_id="u001", tenant_id="t001", is_correct=True, comment="结果准确")
    stats = analyze_feedback(store, audit)
    assert stats["total"] == 2
    assert stats["negative_rate"] == 0.5
    assert stats["audit_link_rate"] == 1.0
    assert stats["candidates"] == 1
    assert stats["issue_type_top"][0]["issue_type"] == "metric"


def test_analyze_evaluation_empty():
    assert analyze_evaluation(None) == {"available": False}


# --- P1-7: Trace 完整率按路径正确判定 ---

def test_agent_single_node_trace_incomplete():
    """只有一个 agent 节点的 Trace 不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qa", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10, trace_json=[{"step": "agent", "status": "success"}],
    )
    stats = analyze_audit(audit)
    pc = stats["path_completeness"]["agent"]
    assert pc["total"] == 1
    assert pc["complete"] == 0
    assert pc["rate"] == 0.0


def test_agent_complete_path():
    """完整 Agent 路径：agent + plan + 每个 start 有匹配 sub_query_end + aggregation/explanation。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qa2", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "sub_query_end", "sub_query_id": "sq-1", "status": "success"},
            {"step": "aggregation", "status": "success"},
            {"step": "explanation", "status": "success"},
        ],
    )
    stats = analyze_audit(audit)
    pc = stats["path_completeness"]["agent"]
    assert pc["complete"] == 1
    assert pc["rate"] == 1.0


def test_agent_start_without_end_incomplete():
    """只有 agent + sub_query_start（无匹配 end）判为不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qb1", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "aggregation", "status": "success"},
        ],
    )
    stats = analyze_audit(audit)
    assert stats["path_completeness"]["agent"]["complete"] == 0


def test_agent_start_end_count_mismatch_incomplete():
    """start/end 数量不匹配判为不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qb2", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "sub_query_start", "sub_query_id": "sq-2"},
            {"step": "sub_query_end", "sub_query_id": "sq-1", "status": "success"},
            {"step": "aggregation", "status": "success"},
            {"step": "explanation", "status": "success"},
        ],
    )
    stats = analyze_audit(audit)
    assert stats["path_completeness"]["agent"]["complete"] == 0


def test_agent_subquery_id_mismatch_incomplete():
    """start 与 end 的 sub_query_id 不匹配判为不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qb3", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "sub_query_end", "sub_query_id": "sq-2", "status": "success"},
            {"step": "aggregation", "status": "success"},
            {"step": "explanation", "status": "success"},
        ],
    )
    stats = analyze_audit(audit)
    assert stats["path_completeness"]["agent"]["complete"] == 0


def test_agent_error_path_preserves_failure():
    """带失败 sub_query_end 的 error 路径保留失败信息，计为完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qb4", user_id="u001", tenant_id="t001", question="q", status="error",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "sub_query_end", "sub_query_id": "sq-1", "status": "error", "error": "blocked"},
        ],
    )
    stats = analyze_audit(audit)
    assert stats["status_distribution"].get("error") == 1
    pc = stats["path_completeness"]["agent"]
    assert pc["complete"] == 1


# --- 第二轮审阅 P1：Agent Trace 生产步骤名与完整率一致 ---

def test_agent_trace_with_subquery_end_complete():
    """AgentOrchestrator 实际生产 sub_query_end 步骤，应被识别为执行证据。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qas", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=10,
        trace_json=[
            {"step": "agent", "status": "start"},
            {"step": "plan", "status": "success"},
            {"step": "sub_query_start", "sub_query_id": "sq-1"},
            {"step": "sub_query_end", "sub_query_id": "sq-1", "status": "success"},
            {"step": "aggregation", "status": "success"},
            {"step": "explanation", "status": "success"},
        ],
    )
    stats = analyze_audit(audit)
    pc = stats["path_completeness"]["agent"]
    assert pc["complete"] == 1
    assert pc["rate"] == 1.0


def test_agent_trace_subquery_failure_not_faked_success():
    """某个子查询失败时 Trace 体现失败（sub_query_end status=error），审计状态为 error，不伪装成功。"""
    eng = _engine()
    audit = AuditLogger(eng)
    trace = [
        {"step": "agent", "status": "start"},
        {"step": "plan", "status": "success"},
        {"step": "sub_query_start", "sub_query_id": "sq-1"},
        {"step": "sub_query_end", "sub_query_id": "sq-1", "status": "error", "error": "blocked"},
        {"step": "aggregation", "status": "skipped", "reason": "all_subqueries_blocked"},
    ]
    audit.log(
        query_id="qaf", user_id="u001", tenant_id="t001", question="q", status="error",
        execution_time_ms=10, trace_json=trace,
    )
    stats = analyze_audit(audit)
    # 状态分布体现失败，不是 success
    assert stats["status_distribution"].get("error") == 1
    assert stats["status_distribution"].get("success", 0) == 0
    # Trace 仍被判定为完整（捕获了失败证据），但状态是 error
    pc = stats["path_completeness"]["agent"]
    assert pc["complete"] == 1
    # 失败证据真实存在于 Trace
    steps = {e["step"] for e in trace}
    assert "sub_query_end" in steps


def test_empty_trace_incomplete():
    """空 Trace 必须计为不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qe", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=5, trace_json=[],
    )
    stats = analyze_audit(audit)
    assert stats["trace_completeness"] == 0.0
    assert stats["path_distribution"].get("unknown") == 1


def test_unknown_path_incomplete():
    """无法识别的路径默认计为不完整。"""
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qu", user_id="u001", tenant_id="t001", question="q", status="success",
        execution_time_ms=5, trace_json=[{"step": "mystery_node"}],
    )
    stats = analyze_audit(audit)
    assert stats["path_distribution"].get("unknown") == 1
    assert stats["path_completeness"]["unknown"]["complete"] == 0


def test_error_path_empty_trace_incomplete():
    eng = _engine()
    audit = AuditLogger(eng)
    audit.log(
        query_id="qerr", user_id="u001", tenant_id="t001", question="q", status="error",
        execution_time_ms=5, trace_json=[],
    )
    stats = analyze_audit(audit)
    assert stats["path_distribution"].get("error") == 1
    assert stats["path_completeness"]["error"]["complete"] == 0


def test_quality_report_markdown_and_json():
    eng = _engine()
    audit = AuditLogger(eng)
    _seed_success_audit(audit, "q1", with_optimizer=True)
    store = FeedbackStore(eng, audit)
    audit.log(query_id="q1b", user_id="u001", tenant_id="t001", question="q", status="success")
    store.submit(query_id="q1b", user_id="u001", tenant_id="t001", is_correct=False, issue_type="metric", corrected_dsl={"data_source": "orders"})

    evaluation = {
        "available": True, "overall_score": 0.82, "total_cases": 10,
        "passed": 8, "failed": 2, "unavailable": 0,
        "by_dimension": {"metric": 0.9}, "by_matrix": [{"generator": "rule", "optimizer": "on", "overall_score": 0.82, "passed": 8, "total": 10}],
        "optimizer_stats": None, "failed_cases": 2,
    }
    report = build_quality_report(
        evaluation=evaluation, audit=analyze_audit(audit), feedback=analyze_feedback(store, audit),
    )
    js = quality_report_to_json(report)
    md = quality_report_to_markdown(report)
    parsed = json.loads(js)
    assert parsed["evaluation"]["overall_score"] == 0.82
    assert "质量报告" in md
    assert "Trace 完整率" in md
    assert "负反馈率" in md
