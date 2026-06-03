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

    @staticmethod
    def _get_id(tc) -> str:
        """兼容 dict 和 dataclass 的 test_case 访问。"""
        if isinstance(tc, dict):
            return tc.get("id", "")
        return getattr(tc, "id", "")

    @staticmethod
    def _get_query(tc) -> str:
        """兼容 dict 和 dataclass 的 test_case 访问。"""
        if isinstance(tc, dict):
            return tc.get("query", "")
        return getattr(tc, "query", "")

    @staticmethod
    def _get_score_attr(scores, attr: str) -> float:
        """兼容 dict 和 dataclass 的 scores 访问。"""
        if isinstance(scores, dict):
            return float(scores.get(attr, 0.0))
        return float(getattr(scores, attr, 0.0))

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
                    f"用例：{self._get_id(tc)}",
                    f"查询：{self._get_query(tc)}",
                    f"总分：{self._get_score_attr(r['scores'], 'overall'):.1%}",
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
                    f"### {self._get_id(tc)}: {self._get_query(tc)}",
                    f"- **总分**：{self._get_score_attr(r['scores'], 'overall'):.1%}",
                    f"- **意图**：{self._get_score_attr(r['scores'], 'intent'):.1%}",
                    f"- **指标**：{self._get_score_attr(r['scores'], 'metric'):.1%}",
                    f"- **过滤条件**：{self._get_score_attr(r['scores'], 'filter'):.1%}",
                    "",
                ])

        return "\n".join(lines)

    def build_comparison(self, baseline_results: list[dict], optimized_results: list[dict]) -> dict:
        """Build a comparison report between baseline and optimized runs."""
        baseline_avg = self._compute_avg_scores(baseline_results)
        optimized_avg = self._compute_avg_scores(optimized_results)

        return {
            "baseline": baseline_avg,
            "optimized": optimized_avg,
            "overall_delta": optimized_avg.get("overall", 0) - baseline_avg.get("overall", 0),
            "deltas": {
                k: optimized_avg.get(k, 0) - baseline_avg.get(k, 0)
                for k in baseline_avg if k != "overall"
            },
            "optimizer_stats": self._compute_optimizer_stats(optimized_results),
        }

    def _compute_avg_scores(self, results: list[dict]) -> dict:
        """Compute average scores across all results."""
        if not results:
            return {}
        keys = ["overall", "intent", "metric", "filter", "planner", "governance"]
        avgs = {}
        for key in keys:
            values = [r.get("scores", {}).__dict__.get(key, 0) if hasattr(r.get("scores", {}), '__dict__') else 0 for r in results]
            avgs[key] = sum(values) / len(values) if values else 0
        return avgs

    def _compute_optimizer_stats(self, results: list[dict]) -> dict:
        """Compute aggregate optimizer statistics."""
        total_fixes = sum(r.get("optimizer", {}).get("fixes_applied", 0) for r in results)
        total_warnings = sum(r.get("optimizer", {}).get("warnings_issued", 0) for r in results)
        total_rejections = sum(r.get("optimizer", {}).get("rejections", 0) for r in results)
        avg_elapsed = sum(r.get("optimizer", {}).get("elapsed_ms", 0) for r in results) / max(len(results), 1)
        return {
            "avg_fixes": total_fixes / max(len(results), 1),
            "avg_warnings": total_warnings / max(len(results), 1),
            "avg_rejections": total_rejections / max(len(results), 1),
            "avg_elapsed_ms": avg_elapsed,
        }

    def print_comparison(self, comparison: dict, fmt: str = "console") -> None:
        """Print a comparison report to console."""
        baseline = comparison["baseline"]
        optimized = comparison["optimized"]
        delta = comparison["overall_delta"]

        print("\n" + "=" * 60)
        print("NL2DSL Evaluation — Optimizer Comparison")
        print("=" * 60)
        print(f"\nOverall Score:")
        print(f"  Baseline:  {baseline.get('overall', 0):.1%}")
        print(f"  Optimized: {optimized.get('overall', 0):.1%}")
        print(f"  Delta:     {delta:+.1%} {'✓' if delta >= 0 else '✗'}")
        print(f"\nBy Category:")
        print(f"  {'Category':<15} {'Baseline':>10} {'Optimized':>10} {'Delta':>10}")
        print(f"  {'-'*45}")
        for cat, d in comparison.get("deltas", {}).items():
            b = baseline.get(cat, 0)
            o = optimized.get(cat, 0)
            print(f"  {cat:<15} {b:>10.1%} {o:>10.1%} {d:>+10.1%}")
        print(f"\nOptimizer Stats (avg per case):")
        stats = comparison.get("optimizer_stats", {})
        print(f"  Fixes:     {stats.get('avg_fixes', 0):.1f}")
        print(f"  Warnings:  {stats.get('avg_warnings', 0):.1f}")
        print(f"  Rejections:{stats.get('avg_rejections', 0):.1f}")
        print(f"  Latency:   {stats.get('avg_elapsed_ms', 0):.1f} ms")

    def build_summary(self, results: list[dict]) -> dict:
        """Build a summary from results."""
        avg_scores = self._compute_avg_scores(results)
        return {
            "total_cases": len(results),
            "avg_scores": avg_scores,
            "passed": sum(1 for r in results if r.get("passed", False)),
            "failed": sum(1 for r in results if not r.get("passed", False)),
            "optimizer_stats": self._compute_optimizer_stats(results) if any("optimizer" in r for r in results) else None,
        }

    def print_summary(self, summary: dict, fmt: str = "console") -> None:
        """Print a summary to console."""
        print("\n" + "=" * 50)
        print("NL2DSL Benchmark Results")
        print("=" * 50)
        print(f"Cases:  {summary['total_cases']}")
        print(f"Passed: {summary['passed']} | Failed: {summary['failed']}")
        scores = summary.get("avg_scores", {})
        print(f"Overall: {scores.get('overall', 0):.1%}")
        for k, v in scores.items():
            if k != "overall":
                print(f"  {k}: {v:.1%}")

    def build_summary_markdown(self, summary: dict) -> str:
        """Build markdown summary."""
        lines = ["# NL2DSL Benchmark Results", ""]
        lines.append(f"- Cases: {summary['total_cases']}")
        lines.append(f"- Passed: {summary['passed']} | Failed: {summary['failed']}")
        lines.append("")
        scores = summary.get("avg_scores", {})
        for k, v in scores.items():
            lines.append(f"- {k}: {v:.1%}")
        return "\n".join(lines)

    def build_comparison_markdown(self, comparison: dict) -> str:
        """Build markdown comparison report."""
        lines = ["# NL2DSL Evaluation — Optimizer Comparison", ""]
        baseline = comparison["baseline"]
        optimized = comparison["optimized"]
        delta = comparison["overall_delta"]
        lines.append(f"## Overall Score")
        lines.append(f"- Baseline:  {baseline.get('overall', 0):.1%}")
        lines.append(f"- Optimized: {optimized.get('overall', 0):.1%}")
        lines.append(f"- Delta:     {delta:+.1%}")
        lines.append("")
        lines.append("## By Category")
        lines.append("| Category | Baseline | Optimized | Delta |")
        lines.append("|----------|----------|-----------|-------|")
        for cat, d in comparison.get("deltas", {}).items():
            b = baseline.get(cat, 0)
            o = optimized.get(cat, 0)
            lines.append(f"| {cat} | {b:.1%} | {o:.1%} | {d:+.1%} |")
        stats = comparison.get("optimizer_stats", {})
        lines.append("")
        lines.append("## Optimizer Stats")
        lines.append(f"- Avg Fixes: {stats.get('avg_fixes', 0):.1f}")
        lines.append(f"- Avg Warnings: {stats.get('avg_warnings', 0):.1f}")
        lines.append(f"- Avg Latency: {stats.get('avg_elapsed_ms', 0):.1f} ms")
        return "\n".join(lines)
