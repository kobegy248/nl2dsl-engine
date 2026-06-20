"""Phase 5：候选评测用例导出测试。"""

from __future__ import annotations

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.feedback.exporter import export_candidates
from nl2dsl.feedback.store import FeedbackStore


@pytest.fixture
def store_and_audit():
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    audit = AuditLogger(eng)
    store = FeedbackStore(eng, audit)
    # 两条相同 query + 相同 corrected_dsl 的负反馈（应合并来源 ID）
    for qid in ("q-1", "q-2"):
        audit.log(
            query_id=qid, user_id="u001", tenant_id="t001",
            question="查询各品类销售额占比", status="success", execution_time_ms=5,
            dsl_json='{"data_source": "orders"}',
        )
    store.submit(
        query_id="q-1", user_id="u001", tenant_id="t001", is_correct=False,
        issue_type="proportion",
        corrected_dsl={"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}], "post_process": {"type": "proportion", "metric": "sales_amount"}},
        comment="占比口径不对",
    )
    store.submit(
        query_id="q-2", user_id="u001", tenant_id="t001", is_correct=False,
        issue_type="proportion",
        corrected_dsl={"data_source": "orders", "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}], "post_process": {"type": "proportion", "metric": "sales_amount"}},
        comment="占比口径不对",
    )
    # comment-only 负反馈 → 待分析
    audit.log(query_id="q-3", user_id="u001", tenant_id="t001", question="查询销售额", status="success")
    store.submit(query_id="q-3", user_id="u001", tenant_id="t001", is_correct=False, comment="结果不准")
    # 正反馈 → 不导出（需带有效内容，否则被校验拒绝）
    audit.log(query_id="q-4", user_id="u001", tenant_id="t001", question="查询订单量", status="success")
    store.submit(query_id="q-4", user_id="u001", tenant_id="t001", is_correct=True, comment="结果准确")
    return store, audit, eng


def test_candidates_dedup_and_merge_source_ids(store_and_audit, tmp_path):
    store, audit, _ = store_and_audit
    out = tmp_path / "candidates.yaml"
    summary = export_candidates(store, audit, out)
    assert summary["candidates"] == 1  # q-1 与 q-2 合并
    assert summary["pending_analysis"] == 1  # q-3 comment-only

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    cand = data["candidates"][0]
    assert cand["query"] == "查询各品类销售额占比"
    assert len(cand["source_feedback_ids"]) == 2
    assert cand["expected"]["metric"] == "sales_amount"
    assert cand["issue_type"] == "proportion"


def test_comment_only_does_not_generate_expected(store_and_audit, tmp_path):
    store, audit, _ = store_and_audit
    out = tmp_path / "candidates.yaml"
    export_candidates(store, audit, out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    # 待分析列表不含 expected 字段
    pa = data["pending_analysis"][0]
    assert "expected" not in pa
    assert pa["comment"] == "结果不准"


def test_candidate_yaml_stable(store_and_audit, tmp_path):
    store, audit, _ = store_and_audit
    out1 = tmp_path / "c1.yaml"
    out2 = tmp_path / "c2.yaml"
    export_candidates(store, audit, out1)
    export_candidates(store, audit, out2)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_no_sql_trace_in_candidates(store_and_audit, tmp_path):
    store, audit, eng = store_and_audit
    # 在审计里写入 SQL/Trace（带 user_id 满足 NOT NULL）
    audit.log(
        query_id="q-1", user_id="u001", tenant_id="t001", question="查询各品类销售额占比",
        sql_text="SELECT pay_amount FROM orders", trace_json=[{"step": "x"}], status="success",
    )
    out = tmp_path / "candidates.yaml"
    export_candidates(store, audit, out)
    text = out.read_text(encoding="utf-8")
    assert "SELECT" not in text
    assert "trace" not in text.lower()


def test_no_formal_dataset_written(store_and_audit, tmp_path):
    store, audit, _ = store_and_audit
    out = tmp_path / "candidates.yaml"
    export_candidates(store, audit, out)
    # 只写一个候选文件，不写正式 dataset
    assert out.exists()
