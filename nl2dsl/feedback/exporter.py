"""反馈转候选评测用例导出器。

Phase 5：将负反馈中的 ``corrected_dsl`` 沉淀为待人工审核的候选评测用例。

约束
----
- 仅 ``corrected_dsl`` 非空的负反馈生成候选 DSL。
- 只有 comment 的反馈进入“待分析”列表，不猜测 expected DSL。
- 相同 query + corrected DSL 合并来源反馈 ID。
- 不直接写正式 Evaluation Dataset。
- 不自动修改 Prompt / RAG / 业务 YAML。
- 敏感 SQL / Trace 不进入候选文件。
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.feedback.store import FeedbackStore
from nl2dsl.utils.logger import get_logger

logger = get_logger("feedback.exporter")


def _candidate_key(query: str, corrected_dsl: dict | None) -> str:
    """对 query + corrected_dsl 计算稳定去重键。"""
    payload = json.dumps(
        {"query": query or "", "corrected_dsl": corrected_dsl or {}},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate_id(query: str, corrected_dsl: dict | None) -> str:
    """根据 query + corrected_dsl 生成稳定候选 ID。

    仅用 query 会导致“同一问题不同修正”共享同一 ID；纳入 corrected_dsl
    可区分不同修正方案，避免候选 ID 冲突。
    """
    payload = json.dumps(
        {"query": query or "", "corrected_dsl": corrected_dsl or {}},
        ensure_ascii=False,
        sort_keys=True,
    )
    short = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"candidate_{short}"


def export_candidates(
    store: FeedbackStore,
    audit_logger: AuditLogger,
    output: Path | str,
    *,
    review_status: str | None = "pending",
    tenant_id: str | None = None,
) -> dict:
    """导出候选评测用例到 ``output``（YAML），返回统计摘要。

    - 仅 ``corrected_dsl`` 非空的负反馈生成候选 DSL。
    - comment-only 进入“待分析”列表，不猜测 expected DSL。
    - 相同 query + corrected DSL 合并来源反馈 ID。
    - 不直接写正式 Evaluation Dataset。
    - 不自动修改 Prompt / RAG / 业务 YAML。
    - 敏感 SQL / Trace 不进入候选文件。
    - ``tenant_id`` 可限定租户范围；未提供则导出全部（需调用方确保已获授权）。
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    records, _ = store.list(
        review_status=review_status, tenant_id=tenant_id, limit=100000, offset=0,
    )

    candidates: dict[str, OrderedDict] = OrderedDict()
    pending_analysis: list[dict] = []

    for rec in records:
        audit = audit_logger.get_query(rec.query_id) or {}
        question = audit.get("question") or ""
        original_dsl = audit.get("dsl")

        # 仅负反馈处理
        if rec.is_correct:
            continue

        if rec.corrected_dsl:
            key = _candidate_key(question, rec.corrected_dsl)
            if key in candidates:
                # 合并来源反馈 ID
                existing = candidates[key]
                if rec.feedback_id not in existing["source_feedback_ids"]:
                    existing["source_feedback_ids"].append(rec.feedback_id)
                continue

            candidate = OrderedDict()
            candidate["candidate_id"] = _candidate_id(question, rec.corrected_dsl)
            candidate["review_status"] = rec.review_status
            candidate["source_feedback_ids"] = [rec.feedback_id]
            # 审计记录不存储业务 domain；不把 DSL.data_source 误当作 domain。
            # domain 留空，待人工审核时根据 query 归属领域补全。
            candidate["domain"] = None
            candidate["query"] = question
            candidate["original_dsl"] = original_dsl
            candidate["expected"] = _build_expected(rec.corrected_dsl, rec.issue_type)
            candidate["issue_type"] = rec.issue_type or "other"
            candidates[key] = candidate
        else:
            # comment-only：进入待分析列表，不生成 expected
            if not (rec.comment or "").strip():
                continue
            pending_analysis.append(OrderedDict([
                ("source_feedback_id", rec.feedback_id),
                ("query", question),
                ("issue_type", rec.issue_type or "other"),
                ("comment", rec.comment),
            ]))

    # 稳定排序输出
    candidate_list = [candidates[k] for k in sorted(candidates.keys())]
    pending_analysis.sort(key=lambda d: (d.get("query") or "", d.get("source_feedback_id") or ""))
    payload = OrderedDict([
        ("schema_version", "1.0"),
        ("candidates", candidate_list),
        ("pending_analysis", pending_analysis),
    ])

    output.write_text(
        yaml.safe_dump(_to_plain(payload), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(
        "候选用例已导出至 %s（候选 %d，待分析 %d）",
        output, len(candidate_list), len(pending_analysis),
    )
    return {
        "candidates": len(candidate_list),
        "pending_analysis": len(pending_analysis),
        "output": str(output),
    }


def _build_expected(corrected_dsl: dict | None, issue_type: str | None) -> dict:
    """从 corrected_dsl 提取 expected 视图（仅必要字段）。

    不原样复制整份 DSL，避免把执行细节（limit/offset 等）当作语义期望。
    """
    if not corrected_dsl:
        return {}
    expected: dict = {}
    metrics = corrected_dsl.get("metrics") or []
    if metrics:
        m = metrics[0]
        expected["metric"] = m.get("alias") or m.get("field")
    dims = corrected_dsl.get("dimensions") or []
    if dims:
        expected["dimensions"] = dims
    filters = corrected_dsl.get("filters")
    if filters:
        expected["filters"] = filters
    post_process = corrected_dsl.get("post_process")
    if post_process:
        expected["planner"] = {"post_process": post_process}
    return expected


def _to_plain(obj: Any) -> Any:
    """将 OrderedDict 递归转为普通 dict，便于 yaml 序列化稳定。"""
    if isinstance(obj, OrderedDict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def main(argv: list[str] | None = None) -> int:
    """``python -m nl2dsl.feedback.exporter`` 命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="导出反馈候选评测用例为 YAML")
    parser.add_argument("--output", type=Path, default=Path("reports/feedback/candidates.yaml"))
    parser.add_argument("--status", type=str, default="pending", help="按 review_status 过滤")
    parser.add_argument(
        "--db-url", type=str, required=True,
        help="审计/反馈数据库连接串（必填，指向真实持久化数据库）",
    )
    parser.add_argument(
        "--tenant-id", type=str, default=None,
        help="限定租户范围（推荐）；未提供则导出全部租户的反馈",
    )
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine
    engine = create_engine(args.db_url)

    from nl2dsl.audit.logger import AuditLogger
    store = FeedbackStore(engine)
    audit_logger = AuditLogger(engine)

    summary = export_candidates(
        store, audit_logger, args.output,
        review_status=args.status, tenant_id=args.tenant_id,
    )
    print(f"候选 {summary['candidates']}，待分析 {summary['pending_analysis']}，输出至 {summary['output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
