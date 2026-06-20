"""V2 评测报告器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


def _percentile(sorted_values: list[int], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    return float(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


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

    # ------------------------------------------------------------------
    # 结构化矩阵报告（Phase 2）
    # ------------------------------------------------------------------

    @staticmethod
    def _case_id(tc) -> str:
        if isinstance(tc, dict):
            return tc.get("id", "")
        return getattr(tc, "id", "")

    @staticmethod
    def _case_query(tc) -> str:
        if isinstance(tc, dict):
            return tc.get("query", "")
        return getattr(tc, "query", "")

    @staticmethod
    def _case_tags(tc) -> list[str]:
        if isinstance(tc, dict):
            return tc.get("tags", []) or []
        return list(getattr(tc, "tags", []) or [])

    @staticmethod
    def _composite_key(domain: str | None, case_id: str, generator: str | None, optimizer: str | None) -> str:
        """矩阵组合的稳定唯一键：domain + case_id + generator + optimizer。

        保证同一用例在 rule/llm × optimizer on/off 的四条结果互不覆盖。
        """
        return "|".join([
            (domain or "unknown"),
            (case_id or ""),
            (generator or ""),
            (optimizer or ""),
        ])

    def build_matrix_report(
        self,
        results: list[dict],
        *,
        matrix_runs: list[dict] | None = None,
    ) -> dict:
        """从真实评测结果构建结构化报告（JSON 与 Markdown 同源）。"""
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        unavailable = sum(1 for r in results if r.get("status") == "unavailable")
        # 执行错误（status=error）：与“语义低分失败”区分——执行错误意味着评测
        # 链路本身异常（GRAPH_RECURSION_LIMIT / SQL 异常 / 基础设施故障），不应
        # 被视为正常的低分用例。
        execution_errors = sum(1 for r in results if r.get("status") == "error")

        def _is_recursion(r: dict) -> bool:
            err = (r.get("observation") or {}).get("error") or ""
            return "GRAPH_RECURSION_LIMIT" in err or "Recursion limit of" in err

        recursion_errors = sum(1 for r in results if _is_recursion(r))
        failed = total - passed

        scoreables = [r for r in results if r.get("status") not in ("unavailable",)]
        n_score = max(len(scoreables), 1)

        def _avg(attr: str) -> float:
            vals = [
                float(getattr(r.get("scores", None), attr, 0.0) or 0.0)
                for r in scoreables
            ]
            return sum(vals) / n_score if vals else 0.0

        overall_vals = [
            float(getattr(r.get("scores", None), "overall", 0.0) or 0.0)
            for r in scoreables
        ]
        overall_score = sum(overall_vals) / n_score if overall_vals else 0.0

        latencies = sorted(
            int(r.get("execution_time_ms", 0) or 0) for r in results
        )
        avg_latency = sum(latencies) / max(len(latencies), 1)

        # by domain
        by_domain: dict[str, dict] = {}
        for r in results:
            domain = r.get("domain") or "unknown"
            bucket = by_domain.setdefault(domain, {"total": 0, "passed": 0, "failed": 0, "overall": []})
            bucket["total"] += 1
            if r.get("passed"):
                bucket["passed"] += 1
            else:
                bucket["failed"] += 1
            bucket["overall"].append(float(getattr(r.get("scores"), "overall", 0.0) or 0.0))
        for domain, bucket in by_domain.items():
            vals = bucket.pop("overall")
            bucket["overall_score"] = sum(vals) / len(vals) if vals else 0.0

        # by tag
        by_tag: dict[str, dict] = {}
        for r in results:
            tags = self._case_tags(r.get("test_case"))
            if not tags:
                tags = ["untagged"]
            for tag in tags:
                bucket = by_tag.setdefault(tag, {"total": 0, "passed": 0, "failed": 0, "overall": []})
                bucket["total"] += 1
                if r.get("passed"):
                    bucket["passed"] += 1
                else:
                    bucket["failed"] += 1
                bucket["overall"].append(float(getattr(r.get("scores"), "overall", 0.0) or 0.0))
        for tag, bucket in by_tag.items():
            vals = bucket.pop("overall")
            bucket["overall_score"] = sum(vals) / len(vals) if vals else 0.0

        # optimizer stats (only for runs where optimizer enabled)
        opt_runs = [r for r in results if r.get("optimizer_enabled") and r.get("optimizer")]
        optimizer_stats = None
        if opt_runs:
            n = max(len(opt_runs), 1)
            optimizer_stats = {
                "avg_fixes": sum(r["optimizer"].get("fixes_applied", 0) for r in opt_runs) / n,
                "avg_warnings": sum(r["optimizer"].get("warnings_issued", 0) for r in opt_runs) / n,
                "avg_rejections": sum(r["optimizer"].get("rejections", 0) for r in opt_runs) / n,
                "avg_elapsed_ms": sum(r["optimizer"].get("elapsed_ms", 0) for r in opt_runs) / n,
            }

        # by matrix (per generator×optimizer combo)
        by_matrix: list[dict] = []
        if matrix_runs:
            for run in matrix_runs:
                run_results = run.get("results", [])
                rs = [r for r in run_results if r.get("status") != "unavailable"]
                nrm = max(len(rs), 1)
                ov = sum(float(getattr(r.get("scores"), "overall", 0.0) or 0.0) for r in rs) / nrm
                by_matrix.append({
                    "generator": run.get("generator_mode"),
                    "optimizer": "on" if run.get("optimizer_enabled") else "off",
                    "total": len(run_results),
                    "passed": sum(1 for r in run_results if r.get("passed")),
                    "unavailable": sum(1 for r in run_results if r.get("status") == "unavailable"),
                    "overall_score": ov,
                })
        else:
            # single-matrix run
            by_matrix.append({
                "generator": results[0].get("generator_mode") if results else None,
                "optimizer": "on" if (results and results[0].get("optimizer_enabled")) else "off",
                "total": total,
                "passed": passed,
                "unavailable": unavailable,
                "overall_score": overall_score,
            })

        failed_cases = [
            {
                "case_id": self._case_id(r.get("test_case")),
                "domain": r.get("domain") or "unknown",
                "query": self._case_query(r.get("test_case")),
                "status": r.get("status"),
                "overall": float(getattr(r.get("scores"), "overall", 0.0) or 0.0),
                "generator": r.get("generator_mode"),
                "optimizer": "on" if r.get("optimizer_enabled") else "off",
                "error": (r.get("observation") or {}).get("error"),
            }
            for r in results if not r.get("passed")
        ]
        # 稳定排序，保证相同输入产出相同文件
        failed_cases.sort(key=lambda f: (f.get("case_id") or "", f.get("generator") or "", f.get("optimizer") or ""))

        # cases 必须用稳定组合身份（domain + case_id + generator + optimizer）作为键，
        # 否则同一用例在 rule/llm × optimizer on/off 的四条结果会相互覆盖，
        # 导致 Baseline 与 regression gate 比较错误的组合。
        cases: dict[str, dict] = {}
        for r in results:
            case_id = self._case_id(r.get("test_case"))
            domain = r.get("domain") or "unknown"
            generator = r.get("generator_mode")
            optimizer = "on" if r.get("optimizer_enabled") else "off"
            key = self._composite_key(domain, case_id, generator, optimizer)
            cases[key] = {
                "case_id": case_id,
                "domain": domain,
                "overall": float(getattr(r.get("scores"), "overall", 0.0) or 0.0),
                "passed": bool(r.get("passed")),
                "status": r.get("status"),
                "generator": generator,
                "optimizer": optimizer,
                "latency_ms": int(r.get("execution_time_ms", 0) or 0),
            }

        report = {
            "schema_version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_cases": total,
                "passed": passed,
                "failed": failed,
                "unavailable": unavailable,
                "execution_errors": execution_errors,
                "recursion_errors": recursion_errors,
                "overall_score": overall_score,
                "by_dimension": {
                    "intent": _avg("intent"),
                    "metric": _avg("metric"),
                    "filter": _avg("filter"),
                    "planner": _avg("planner"),
                    "governance": _avg("governance"),
                },
                "avg_latency_ms": avg_latency,
                "p50_latency_ms": _percentile(latencies, 0.5),
                "p95_latency_ms": _percentile(latencies, 0.95),
            },
            "by_domain": by_domain,
            "by_tag": by_tag,
            "by_matrix": by_matrix,
            "optimizer_stats": optimizer_stats,
            "failed_cases": failed_cases,
            "cases": cases,
        }
        return report

    def matrix_report_to_json(self, report: dict) -> str:
        import json
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

    def matrix_report_to_markdown(self, report: dict, regression: dict | None = None) -> str:
        """渲染结构化报告为 Markdown，顺序稳定以利于 Git diff。"""
        s = report["summary"]
        lines = [
            "# NL2DSL V2 评测报告",
            "",
            f"- 生成时间：{report.get('generated_at', '')}",
            f"- schema_version：{report.get('schema_version', '')}",
            "",
            "## 总览",
            "",
            f"- 用例数：{s['total_cases']}",
            f"- 通过：{s['passed']} | 失败：{s['failed']} | 不可用：{s.get('unavailable', 0)}",
            f"- 整体准确率：{s['overall_score']:.1%}",
            f"- 平均延迟：{s.get('avg_latency_ms', 0):.1f} ms | P50：{s.get('p50_latency_ms', 0):.1f} ms | P95：{s.get('p95_latency_ms', 0):.1f} ms",
            "",
            "## 各维度",
            "",
            "| 维度 | 准确率 |",
            "|------|--------|",
        ]
        for dim in ["intent", "metric", "filter", "planner", "governance"]:
            lines.append(f"| {dim} | {s['by_dimension'].get(dim, 0):.1%} |")

        lines += ["", "## 按矩阵（generator × optimizer）", "",
                  "| Generator | Optimizer | Total | Passed | Unavailable | Overall |",
                  "|-----------|-----------|-------|--------|-------------|---------|"]
        for m in report.get("by_matrix", []):
            lines.append(
                f"| {m.get('generator')} | {m.get('optimizer')} | {m.get('total')} | "
                f"{m.get('passed')} | {m.get('unavailable', 0)} | {m.get('overall_score', 0):.1%} |"
            )

        lines += ["", "## 按 Domain", "",
                  "| Domain | Total | Passed | Failed | Overall |",
                  "|--------|-------|--------|--------|---------|"]
        for domain in sorted(report.get("by_domain", {})):
            d = report["by_domain"][domain]
            lines.append(f"| {domain} | {d['total']} | {d['passed']} | {d['failed']} | {d['overall_score']:.1%} |")

        lines += ["", "## 按 Tag", "",
                  "| Tag | Total | Passed | Failed | Overall |",
                  "|-----|-------|--------|--------|---------|"]
        for tag in sorted(report.get("by_tag", {})):
            t = report["by_tag"][tag]
            lines.append(f"| {tag} | {t['total']} | {t['passed']} | {t['failed']} | {t['overall_score']:.1%} |")

        opt = report.get("optimizer_stats")
        if opt:
            lines += ["", "## Optimizer 统计", "",
                      f"- 平均 Fix：{opt['avg_fixes']:.2f}",
                      f"- 平均 Warn：{opt['avg_warnings']:.2f}",
                      f"- 平均 Reject：{opt['avg_rejections']:.2f}",
                      f"- 平均耗时：{opt['avg_elapsed_ms']:.1f} ms"]

        if regression is not None:
            lines += ["", "## 回归门禁", "",
                      f"- 结论：{'通过 ✓' if regression['passed'] else '失败 ✗'}",
                      f"- Overall delta：{regression['overall_delta']:+.1%}"]
            for d in regression.get("dimension_regressions", []):
                lines.append(f"- 维度回退 {d['dimension']}：{d['baseline']:.1%} → {d['current']:.1%}（降 {d['drop']:.1%}）")
            for c in regression.get("case_regressions", []):
                lines.append(f"- 用例回退 {c['case_id']}：{c['baseline']:.1%} → {c['current']:.1%}（降 {c['drop']:.1%}）")
            for c in regression.get("new_failures", []):
                lines.append(f"- 新增失败 {c['case_id']}（{c['current_status']}）")

        failed = report.get("failed_cases", [])
        if failed:
            lines += ["", "## 失败用例", "",
                      "| Case ID | Status | Overall | Generator | Optimizer | Query |",
                      "|---------|--------|---------|-----------|-----------|-------|"]
            for f in failed:
                q = (f.get("query") or "").replace("|", "\\|")
                lines.append(
                    f"| {f['case_id']} | {f.get('status')} | {f.get('overall', 0):.1%} | "
                    f"{f.get('generator')} | {f.get('optimizer')} | {q} |"
                )

        # 执行错误单独成节，与语义低分失败区分：执行错误代表评测链路异常
        # （GRAPH_RECURSION_LIMIT / SQL 异常 / 基础设施故障），不是模型语义不准。
        exec_errs = [f for f in failed if f.get("status") == "error"]
        if exec_errs:
            lines += ["", "## 执行错误（评测链路异常，非语义低分）", "",
                      "| Case ID | Generator | Optimizer | Error |",
                      "|---------|-----------|-----------|-------|"]
            for f in exec_errs:
                err = (f.get("error") or "").replace("|", "\\|").replace("\n", " ")
                if len(err) > 200:
                    err = err[:200] + "…"
                lines.append(
                    f"| {f['case_id']} | {f.get('generator')} | {f.get('optimizer')} | {err} |"
                )

        return "\n".join(lines)
