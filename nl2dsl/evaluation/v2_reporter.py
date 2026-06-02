"""V2 评测报告器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class V2Report:
    """V2 评测报告。"""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    overall_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    metric_accuracy: float = 0.0
    filter_accuracy: float = 0.0
    planner_accuracy: float = 0.0
    governance_accuracy: float = 0.0
    failed_cases: list[dict] = None

    def __post_init__(self):
        if self.failed_cases is None:
            self.failed_cases = []


class V2Reporter:
    """生成 V2 评测报告。"""

    def generate(self, results: list[dict]) -> V2Report:
        """根据结果生成报告。"""
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        failed = total - passed

        if total == 0:
            return V2Report()

        scores_list = [r["scores"] for r in results]

        return V2Report(
            total_cases=total,
            passed=passed,
            failed=failed,
            overall_accuracy=sum(s.overall for s in scores_list) / total,
            intent_accuracy=sum(s.intent for s in scores_list) / total,
            metric_accuracy=sum(s.metric for s in scores_list) / total,
            filter_accuracy=sum(s.filter for s in scores_list) / total,
            planner_accuracy=sum(s.planner for s in scores_list) / total,
            governance_accuracy=sum(s.governance for s in scores_list) / total,
            failed_cases=[r for r in results if not r["passed"]],
        )

    def to_console(self, results: list[dict]) -> str:
        """格式化报告为控制台输出。"""
        report = self.generate(results)

        lines = [
            "=" * 50,
            "语义查询基准测试",
            "=" * 50,
            f"总用例数：{report.total_cases}",
            f"通过：{report.passed}",
            f"失败：{report.failed}",
            f"准确率：{report.overall_accuracy:.1%}",
            "-" * 50,
            f"意图准确率：      {report.intent_accuracy:.1%}",
            f"指标准确率：      {report.metric_accuracy:.1%}",
            f"过滤条件准确率：  {report.filter_accuracy:.1%}",
            f"规划器准确率：    {report.planner_accuracy:.1%}",
            f"治理准确率：      {report.governance_accuracy:.1%}",
            "=" * 50,
        ]

        if report.failed_cases:
            lines.extend(["", "失败用例", "-" * 50])
            for r in report.failed_cases:
                tc = r["test_case"]
                lines.extend([
                    f"用例：{tc['id']}",
                    f"查询：{tc['query']}",
                    f"总分：{r['scores'].overall:.1%}",
                    "-" * 50,
                ])

        return "\n".join(lines)

    def to_markdown(self, results: list[dict]) -> str:
        """格式化报告为 Markdown。"""
        report = self.generate(results)

        lines = [
            "# 语义查询基准测试报告",
            "",
            f"| 指标 | 数值 |",
            f"|--------|-------|",
            f"| 总用例数 | {report.total_cases} |",
            f"| 通过 | {report.passed} |",
            f"| 失败 | {report.failed} |",
            f"| 整体准确率 | {report.overall_accuracy:.1%} |",
            "",
            "## 各维度得分",
            "",
            f"| 维度 | 准确率 |",
            f"|-----------|----------|",
            f"| 意图 | {report.intent_accuracy:.1%} |",
            f"| 指标 | {report.metric_accuracy:.1%} |",
            f"| 过滤条件 | {report.filter_accuracy:.1%} |",
            f"| 规划器 | {report.planner_accuracy:.1%} |",
            f"| 治理 | {report.governance_accuracy:.1%} |",
        ]

        if report.failed_cases:
            lines.extend(["", "## 失败用例", ""])
            for r in report.failed_cases:
                tc = r["test_case"]
                lines.extend([
                    f"### {tc['id']}: {tc['query']}",
                    f"- **总分**：{r['scores'].overall:.1%}",
                    f"- **意图**：{r['scores'].intent:.1%}",
                    f"- **指标**：{r['scores'].metric:.1%}",
                    f"- **过滤条件**：{r['scores'].filter:.1%}",
                    "",
                ])

        return "\n".join(lines)
