"""质量报告 CLI：``python -m nl2dsl.quality.cli``。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
from nl2dsl.utils.logger import get_logger

logger = get_logger("quality.cli")


def _build_default_engine():
    """构建与评测一致的默认 SQLite 引擎（含样例数据）。

    便于在未提供 --db-url 时仍能读取 audit/feedback 表。生产环境应通过
    --db-url 指向持久化数据库。使用正式包内置样例数据，不依赖 ``tests.*``。
    """
    from nl2dsl.testing.sample_data import create_mock_database
    engine, *_ = create_mock_database("sqlite:///:memory:")
    return engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="汇总 Evaluation / Audit / Feedback 生成固定格式质量报告",
    )
    parser.add_argument(
        "--evaluation", type=Path, default=None,
        help="V2 矩阵报告 JSON 路径（可选）",
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="审计/反馈数据库连接串（默认：构建内存 mock 数据库）",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/quality"),
        help="输出目录（默认：reports/quality）",
    )
    parser.add_argument(
        "--format", choices=["json", "markdown", "both"], default="both",
        help="输出格式",
    )
    args = parser.parse_args(argv)

    # 引擎
    if args.db_url:
        from sqlalchemy import create_engine
        engine = create_engine(args.db_url)
    else:
        engine = _build_default_engine()

    from nl2dsl.audit.logger import AuditLogger
    from nl2dsl.feedback.store import FeedbackStore
    audit_logger = AuditLogger(engine)
    feedback_store = FeedbackStore(engine, audit_logger)

    evaluation_report = None
    if args.evaluation and args.evaluation.exists():
        evaluation_report = json.loads(args.evaluation.read_text(encoding="utf-8"))

    evaluation = analyze_evaluation(evaluation_report)
    audit = analyze_audit(audit_logger)
    feedback = analyze_feedback(feedback_store, audit_logger)

    report = build_quality_report(
        evaluation=evaluation, audit=audit, feedback=feedback,
    )

    args.output.mkdir(parents=True, exist_ok=True)
    if args.format in ("json", "both"):
        (args.output / "quality_report.json").write_text(
            quality_report_to_json(report), encoding="utf-8",
        )
    if args.format in ("markdown", "both"):
        (args.output / "quality_report.md").write_text(
            quality_report_to_markdown(report), encoding="utf-8",
        )

    print(quality_report_to_markdown(report))
    print(f"\n质量报告已保存至：{args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
