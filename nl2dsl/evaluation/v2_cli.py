"""V2 语义基准测试 CLI 入口点 — 支持 Semantic Optimizer。"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

from nl2dsl.evaluation.dataset import V2DatasetLoader
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner, DEFAULT_WEIGHTS
from nl2dsl.evaluation.v2_reporter import V2Reporter
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer
from nl2dsl.utils.logger import get_logger
import yaml

logger = get_logger("evaluation.v2_cli")


def _load_config(config_path: Path) -> dict:
    """从 YAML 加载项目配置。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_scorers(resolver: CanonicalResolver) -> dict:
    """构建评分器实例。"""
    return {
        "intent_scorer": IntentScorer(),
        "metric_scorer": MetricScorer(resolver.metric),
        "filter_scorer": FilterScorer(resolver),
        "planner_scorer": PlannerScorer(resolver),
        "governance_scorer": GovernanceScorer(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 V2 语义查询基准测试（支持 Semantic Optimizer）",
    )
    parser.add_argument(
        "--dataset", type=Path, required=True, help="V2 数据集目录路径",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/metrics.yaml"),
        help="项目配置文件路径（默认：configs/metrics.yaml）",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/v2"),
        help="输出目录（默认：reports/v2）",
    )
    parser.add_argument(
        "--format", choices=["console", "markdown", "json"], default="console",
        help="输出格式",
    )

    # Optimizer flags
    parser.add_argument(
        "--optimizer", choices=["on", "off"], default="off",
        help="启用 Semantic Optimizer（默认：off）",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="对比模式：同时运行 Baseline（optimizer off）和 Optimized（optimizer on），输出对比报告",
    )
    parser.add_argument(
        "--rules", type=str, default=None,
        help="仅启用指定的规则（逗号分隔，如 M001,F001,P003）",
    )
    parser.add_argument(
        "--disable-rules", type=str, default=None,
        help="禁用指定的规则（逗号分隔，如 A001,A002）",
    )
    parser.add_argument(
        "--verbose-optimizer", action="store_true",
        help="输出每个用例的 OptimizationReport 详情",
    )

    args = parser.parse_args(argv)

    # 加载配置并构建解析器
    config = _load_config(args.config)
    resolver = CanonicalResolver.from_config(config)
    scorers = _build_scorers(resolver)

    # 加载数据集
    loader = V2DatasetLoader(args.dataset)
    cases = loader.load_all()
    if not cases:
        print("错误：未找到测试用例。", file=sys.stderr)
        return 1
    print(f"已加载 {len(cases)} 条测试用例")

    # Parse rule filters
    enabled_rules = None
    disabled_rules = None
    if args.rules:
        enabled_rules = [r.strip() for r in args.rules.split(",")]
    if args.disable_rules:
        disabled_rules = [r.strip() for r in args.disable_rules.split(",")]

    use_optimizer = args.optimizer == "on" or args.compare

    if args.compare:
        print("\n=== 对比模式：Baseline vs Optimized ===")
        runner = V2BenchmarkRunner(scorers)

        # Run baseline
        print("\n--- Baseline (Optimizer OFF) ---")
        baseline_results = runner.run_batch_with_optimizer(
            cases, config, resolver,
            use_optimizer=False,
            verbose_optimizer=args.verbose_optimizer,
        )

        # Run optimized
        print("\n--- Optimized (Optimizer ON) ---")
        optimized_results = runner.run_batch_with_optimizer(
            cases, config, resolver,
            use_optimizer=True,
            enabled_rules=enabled_rules,
            disabled_rules=disabled_rules,
            verbose_optimizer=args.verbose_optimizer,
        )

        # Generate comparison report
        reporter = V2Reporter()
        comparison = reporter.build_comparison(baseline_results, optimized_results)
        reporter.print_comparison(comparison, fmt=args.format)

        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            report_path = args.output / "comparison_report.md"
            report_path.write_text(
                reporter.build_comparison_markdown(comparison),
                encoding="utf-8",
            )
            print(f"\n对比报告已保存至：{report_path}")

        # Exit with error if delta is negative
        delta = comparison.get("overall_delta", 0)
        if delta < 0:
            print(f"\n⚠ 优化后得分下降 {abs(delta):.1%}！", file=sys.stderr)
            return 1
        return 0

    elif use_optimizer:
        print(f"\n=== Semantic Optimizer {'ON' if args.optimizer == 'on' else 'OFF'} ===")
        if enabled_rules:
            print(f"启用的规则：{enabled_rules}")
        if disabled_rules:
            print(f"禁用的规则：{disabled_rules}")

        runner = V2BenchmarkRunner(scorers)
        results = runner.run_batch_with_optimizer(
            cases, config, resolver,
            use_optimizer=(args.optimizer == "on"),
            enabled_rules=enabled_rules,
            disabled_rules=disabled_rules,
            verbose_optimizer=args.verbose_optimizer,
        )

        reporter = V2Reporter()
        summary = reporter.build_summary(results)
        reporter.print_summary(summary, fmt=args.format)

        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            fmt_ext = {"console": "md", "markdown": "md", "json": "json"}[args.format]
            report_path = args.output / f"benchmark_report.{fmt_ext}"
            if args.format == "json":
                report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                report_path.write_text(reporter.build_summary_markdown(summary), encoding="utf-8")
            print(f"\n报告已保存至：{report_path}")

        return 0

    else:
        # Original behavior: no optimizer
        print("\nV2 基准测试就绪！")
        print(f"用例数：{len(cases)}")
        print(f"评分器：{list(scorers.keys())}")
        print("\n提示：使用 --optimizer on 启用 Semantic Optimizer")
        print("      使用 --compare 对比 Optimizer ON/OFF 效果")
        return 0


if __name__ == "__main__":
    sys.exit(main())
