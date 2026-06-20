"""质量报告生成：JSON + Markdown，字段顺序稳定。"""

from __future__ import annotations

import json
from datetime import datetime


def build_quality_report(
    *,
    evaluation: dict,
    audit: dict,
    feedback: dict,
) -> dict:
    """组装结构化质量报告。"""
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "evaluation": evaluation,
        "audit": audit,
        "feedback": feedback,
    }


def quality_report_to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def _fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def quality_report_to_markdown(report: dict) -> str:
    lines = [
        "# NL2DSL 质量报告",
        "",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- schema_version：{report.get('schema_version', '')}",
        "",
        "## Evaluation",
        "",
    ]
    ev = report.get("evaluation", {})
    if ev.get("available"):
        lines += [
            f"- 整体准确率：{ev.get('overall_score', 0):.1%}",
            f"- 用例数：{ev.get('total_cases')}（通过 {ev.get('passed')} / 失败 {ev.get('failed')} / 不可用 {ev.get('unavailable')}）",
            f"- 失败用例数：{ev.get('failed_cases')}",
            "",
            "### 各维度",
            "",
            "| 维度 | 准确率 |",
            "|------|--------|",
        ]
        for dim, val in (ev.get("by_dimension") or {}).items():
            lines.append(f"| {dim} | {val:.1%} |")
        if ev.get("by_matrix"):
            lines += ["", "### 矩阵", "",
                      "| Generator | Optimizer | Overall | Passed | Total |",
                      "|-----------|-----------|---------|--------|-------|"]
            for m in ev["by_matrix"]:
                lines.append(
                    f"| {m.get('generator')} | {m.get('optimizer')} | "
                    f"{m.get('overall_score', 0):.1%} | {m.get('passed')} | {m.get('total')} |"
                )
    else:
        lines.append("- 未提供 Evaluation 报告")

    audit = report.get("audit", {})
    lines += ["", "## Audit", "",
              f"- 查询总数：{audit.get('total_queries', 0)}",
              f"- 状态分布：{audit.get('status_distribution', {})}",
              f"- 路径分布：{audit.get('path_distribution', {})}",
              f"- 延迟 P50：{audit.get('latency', {}).get('p50_ms', 0):.1f} ms | P95：{audit.get('latency', {}).get('p95_ms', 0):.1f} ms",
              f"- Trace 完整率：{audit.get('trace_completeness', 0):.1%}",
              f"- 字段完整率：DSL {audit.get('field_completeness', {}).get('dsl', 0):.1%} / SQL {audit.get('field_completeness', {}).get('sql', 0):.1%} / Trace {audit.get('field_completeness', {}).get('trace', 0):.1%}"]

    fb = report.get("feedback", {})
    lines += ["", "## Feedback", "",
              f"- 反馈总数：{fb.get('total', 0)}",
              f"- 负反馈率：{fb.get('negative_rate', 0):.1%}",
              f"- 审计关联率：{fb.get('audit_link_rate', 0):.1%}",
              f"- corrected_dsl 覆盖率：{fb.get('corrected_dsl_coverage', 0):.1%}",
              f"- 候选评测用例数：{fb.get('candidates', 0)}"]
    top = fb.get("issue_type_top") or []
    if top:
        lines += ["", "### issue_type Top N", "",
                  "| issue_type | count |", "|------------|-------|"]
        for it in top:
            lines.append(f"| {it['issue_type']} | {it['count']} |")

    return "\n".join(lines)
