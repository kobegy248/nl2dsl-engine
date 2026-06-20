"""Phase 4：数据库 FeedbackStore 校验与去重测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.exceptions import NotFoundError, ValidationError
from nl2dsl.feedback.store import FeedbackStore, compute_dedup_hash


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    return eng


@pytest.fixture
def audit(engine):
    return AuditLogger(engine)


@pytest.fixture
def store(engine, audit):
    return FeedbackStore(engine, audit)


def _seed_audit(audit, query_id="q-1", user_id="u001", tenant_id="t001", question="查询销售额"):
    audit.log(
        query_id=query_id, user_id=user_id, tenant_id=tenant_id,
        question=question, status="success", execution_time_ms=10,
    )


def test_submit_success_returns_feedback_id(store, audit):
    _seed_audit(audit)
    fb_id, deduped = store.submit(
        query_id="q-1", user_id="u001", tenant_id="t001",
        is_correct=False, issue_type="metric",
        corrected_dsl={"data_source": "orders"}, comment="口径不对",
    )
    assert fb_id.startswith("fb-")
    assert deduped is False


def test_submit_rejects_missing_audit(store):
    with pytest.raises(NotFoundError):
        store.submit(query_id="nope", user_id="u001", tenant_id="t001", comment="x")


def test_submit_rejects_wrong_user(store, audit):
    _seed_audit(audit, user_id="u001")
    with pytest.raises(ValidationError):
        store.submit(query_id="q-1", user_id="u999", tenant_id="t001", comment="x")


def test_submit_rejects_wrong_tenant(store, audit):
    _seed_audit(audit, tenant_id="t001")
    with pytest.raises(ValidationError):
        store.submit(query_id="q-1", user_id="u001", tenant_id="t999", comment="x")


def test_submit_rejects_blank_tenant(store, audit):
    """Store 层防御性校验：空 / 全空格 tenant_id 直接拒绝，不依赖 API 层。"""
    _seed_audit(audit, tenant_id="t001")
    for blank in ["", "   "]:
        with pytest.raises(ValidationError):
            store.submit(query_id="q-1", user_id="u001", tenant_id=blank, is_correct=False, comment="x")


def test_submit_rejects_when_audit_lacks_tenant(store, audit):
    """审计记录缺少 tenant_id 时拒绝，避免跨租户写入。"""
    audit.log(query_id="q-2", user_id="u001", tenant_id="", question="q", status="success")
    with pytest.raises(ValidationError):
        store.submit(query_id="q-2", user_id="u001", tenant_id="t001", is_correct=False, comment="x")


def test_dedup_returns_original_feedback_id(store, audit):
    _seed_audit(audit)
    args = dict(
        query_id="q-1", user_id="u001", tenant_id="t001",
        is_correct=False, issue_type="metric",
        corrected_dsl={"data_source": "orders"}, comment="口径不对",
    )
    fb1, d1 = store.submit(**args)
    fb2, d2 = store.submit(**args)
    assert d1 is False
    assert d2 is True
    assert fb1 == fb2

    # 表里只有一条
    records, total = store.list(query_id="q-1")
    assert total == 1


def test_invalid_corrected_dsl_rejected(store, audit):
    _seed_audit(audit)
    with pytest.raises(ValidationError):
        store.submit(
            query_id="q-1", user_id="u001", tenant_id="t001",
            corrected_dsl={"filters": "not-a-list-or-tree"}, comment="x",
        )


def test_invalid_issue_type_rejected(store, audit):
    _seed_audit(audit)
    with pytest.raises(ValidationError):
        store.submit(
            query_id="q-1", user_id="u001", tenant_id="t001",
            is_correct=False, issue_type="bogus", comment="x",
        )


def test_empty_feedback_rejected(store, audit):
    _seed_audit(audit)
    # is_correct=True 且无 dsl 无 comment → 无有效反馈
    with pytest.raises(ValidationError):
        store.submit(query_id="q-1", user_id="u001", tenant_id="t001")


def test_comment_only_accepted(store, audit):
    _seed_audit(audit)
    fb_id, _ = store.submit(
        query_id="q-1", user_id="u001", tenant_id="t001",
        is_correct=False, comment="结果不对",
    )
    assert fb_id.startswith("fb-")


def test_dedup_hash_stable():
    h1 = compute_dedup_hash(
        query_id="q", user_id="u", tenant_id="t", is_correct=False,
        issue_type="metric", corrected_dsl={"a": 1, "b": 2}, comment="c",
    )
    h2 = compute_dedup_hash(
        query_id="q", user_id="u", tenant_id="t", is_correct=False,
        issue_type="metric", corrected_dsl={"b": 2, "a": 1}, comment="c",
    )
    assert h1 == h2


def test_feedback_table_does_not_store_sql_trace(store, audit, engine):
    _seed_audit(audit)
    # 在审计里写入 SQL/Trace（带 user_id 以满足 NOT NULL）
    audit.log(
        query_id="q-1", user_id="u001", tenant_id="t001", question="查询销售额",
        sql_text="SELECT 1", trace_json=[{"step": "x"}], status="success",
    )
    store.submit(query_id="q-1", user_id="u001", tenant_id="t001", is_correct=False, comment="x")
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(nl2dsl_feedback)")).fetchall()]
    assert "sql_text" not in cols
    assert "trace_json" not in cols
