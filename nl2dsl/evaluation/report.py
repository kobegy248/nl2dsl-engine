"""Report generation in JSON and Markdown formats."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nl2dsl.evaluation.models import EvaluationReport
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.report")


class ReportGenerator:
    """Generate evaluation reports in JSON and Markdown formats."""

    def generate_json(self, report: EvaluationReport, output_path: Path) -> None:
        """Write report as JSON file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            report.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        logger.info("JSON report saved: %s", output_path)

    def generate_markdown(self, report: EvaluationReport, output_path: Path) -> None:
        """Write human-readable Markdown report."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self._format_markdown(report),
            encoding="utf-8",
        )
        logger.info("Markdown report saved: %s", output_path)

    def _format_markdown(self, report: EvaluationReport) -> str:
        """Format report as Markdown string."""
        bd = report.by_dimension

        lines: list[str] = [
            "# NL2DSL Evaluation Report",
            "",
            f"**Generated:** {report.generated_at}",
            f"**Total Cases:** {report.total_cases}",
            f"**Execution Time:** {report.execution_time_ms / 1000:.1f}s",
            "",
            "---",
            "",
            "## Overall Score",
            "",
            f"### {report.overall_score:.1%}",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Passed | {report.passed} |",
            f"| Failed | {report.failed} |",
            f"| Pass Rate | {report.passed / report.total_cases:.1%}" if report.total_cases else "| Pass Rate | N/A |",
            "",
            "---",
            "",
            "## By Category",
            "",
            "| Category | Weight | Score |",
            "|----------|--------|-------|",
            f"| Semantic | 56% | {bd.semantic_score:.1%} |",
            f"| Planning | 14% | {bd.planning_score:.1%} |",
            f"| Execution | 20% | {bd.execution_score:.1%} |",
            f"| Governance | 10% | {bd.governance_score:.1%} |",
            "",
            "### Category Detail",
            "",
        ]

        # Semantic sub-dimensions
        lines.extend([
            "#### Semantic",
            "",
            "| Dimension | Weight | Score |",
            "|-----------|--------|-------|",
            f"| Intent | 8% | {bd.intent:.1%} |",
            f"| Metric | 20% | {bd.metric:.1%} |",
            f"| Dimension | 12% | {bd.dimension:.1%} |",
            f"| Filter | 16% | {bd.filter:.1%} |",
            "",
        ])

        # Planning sub-dimensions
        lines.extend([
            "#### Planning",
            "",
            "| Dimension | Weight | Score |",
            "|-----------|--------|-------|",
            f"| Join | 7% | {bd.join:.1%} |",
            f"| Limit | 4% | {bd.limit:.1%} |",
            f"| OrderBy | 3% | {bd.order_by:.1%} |",
            "",
        ])

        # Execution sub-dimensions
        lines.extend([
            "#### Execution",
            "",
            "| Dimension | Weight | Score |",
            "|-----------|--------|-------|",
            f"| SQL Success | 10% | {bd.sql_success:.1%} |",
            f"| Result Accuracy | 10% | {bd.result_accuracy:.1%} |",
            "",
        ])

        # Governance sub-dimensions
        lines.extend([
            "#### Governance",
            "",
            "| Dimension | Weight | Score |",
            "|-----------|--------|-------|",
            f"| Permission | 4% | {bd.permission:.1%} |",
            f"| Masking | 3% | {bd.masking:.1%} |",
            f"| Audit | 3% | {bd.audit:.1%} |",
            "",
        ])

        # ASCII bar chart for all dimensions
        lines.extend([
            "### Dimension Chart",
            "",
        ])

        dimensions = [
            ("Intent", bd.intent, "Semantic"),
            ("Metric", bd.metric, "Semantic"),
            ("Dimension", bd.dimension, "Semantic"),
            ("Filter", bd.filter, "Semantic"),
            ("Join", bd.join, "Planning"),
            ("Limit", bd.limit, "Planning"),
            ("OrderBy", bd.order_by, "Planning"),
            ("SQL Success", bd.sql_success, "Execution"),
            ("Result Acc", bd.result_accuracy, "Execution"),
            ("Permission", bd.permission, "Governance"),
            ("Masking", bd.masking, "Governance"),
            ("Audit", bd.audit, "Governance"),
        ]
        for name, score, category in dimensions:
            bar_len = int(score * 40)
            bar = "█" * bar_len
            cat_tag = f"[{category[:3]}]"
            lines.append(f"{cat_tag} {name:12s} {bar} {score:.1%}")

        lines.extend([
            "",
            "---",
            "",
            "## By Domain",
            "",
            "| Domain | Cases | Passed | Failed | Avg Score |",
            "|--------|-------|--------|--------|-----------|",
        ])
        for domain, summary in sorted(report.by_domain.items()):
            lines.append(
                f"| {domain} | {summary.total_cases} | {summary.passed} | "
                f"{summary.failed} | {summary.average_score:.1%} |"
            )

        if report.by_tag:
            lines.extend([
                "",
                "---",
                "",
                "## By Tag",
                "",
                "| Tag | Cases | Passed | Failed | Avg Score |",
                "|-----|-------|--------|--------|-----------|",
            ])
            for tag, summary in sorted(report.by_tag.items()):
                lines.append(
                    f"| {tag} | {summary.total_cases} | {summary.passed} | "
                    f"{summary.failed} | {summary.average_score:.1%} |"
                )

        if report.failed_cases:
            lines.extend([
                "",
                "---",
                "",
                f"## Failed Cases ({len(report.failed_cases)})",
                "",
            ])
            for result in report.failed_cases:
                tc = result.test_case
                sc = result.scores
                lines.extend([
                    f"### {tc.id}: {tc.query}",
                    "",
                    f"- **Domain:** {tc.domain}",
                    f"- **Tags:** {', '.join(tc.tags)}",
                    f"- **Overall Score:** {result.scores.overall:.1%}",
                    f"- **Execution Time:** {result.execution_time_ms}ms",
                    "",
                    "**Category Breakdown:**",
                    "",
                    "| Category | Score |",
                    "|----------|-------|",
                    f"| Semantic | {sc.semantic_score:.1%} |",
                    f"| Planning | {sc.planning_score:.1%} |",
                    f"| Execution | {sc.execution_score:.1%} |",
                    f"| Governance | {sc.governance_score:.1%} |",
                    "",
                    "**Dimension Breakdown:**",
                    "",
                    "| Dimension | Score |",
                    "|-----------|-------|",
                ])
                dims = [
                    ("Intent", sc.intent),
                    ("Metric", sc.metric),
                    ("Dimension", sc.dimension),
                    ("Filter", sc.filter),
                    ("Join", sc.join),
                    ("Limit", sc.limit),
                    ("OrderBy", sc.order_by),
                    ("SQL Success", sc.sql_success),
                    ("Result Acc", sc.result_accuracy),
                    ("Permission", sc.permission),
                    ("Masking", sc.masking),
                    ("Audit", sc.audit),
                ]
                for name, score in dims:
                    marker = "✓" if score >= 0.8 else "✗"
                    lines.append(f"| {name} | {score:.1%} {marker} |")

                lines.append("")

                # Governance details
                if result.governance and result.governance.sensitive_fields_accessed:
                    lines.extend([
                        "**Governance:**",
                        f"- Sensitive fields accessed: {result.governance.sensitive_fields_accessed}",
                        f"- Permission error: {result.governance.permission_error}",
                        f"- Masked fields: {list(result.governance.masked_fields.keys())}",
                        f"- Audit logged: {result.governance.audit_logged}",
                        "",
                    ])

                if result.error:
                    lines.extend([
                        "**Error:**",
                        f"```\n{result.error}\n```",
                        "",
                    ])

                if result.actual_dsl:
                    lines.extend([
                        "**Expected DSL:**",
                        f"```json\n{json.dumps(tc.expected_dsl, ensure_ascii=False, indent=2)}\n```",
                        "",
                        "**Actual DSL:**",
                        f"```json\n{json.dumps(result.actual_dsl, ensure_ascii=False, indent=2)}\n```",
                        "",
                    ])

                if result.actual_sql:
                    lines.extend([
                        "**Generated SQL:**",
                        f"```sql\n{result.actual_sql}\n```",
                        "",
                    ])

                lines.append("---")

        return "\n".join(lines) + "\n"
