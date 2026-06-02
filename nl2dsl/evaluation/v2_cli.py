"""V2 语义基准测试 CLI 入口点。"""

from __future__ import annotations

import argparse
import sys
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
        description="运行 V2 语义查询基准测试",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="V2 数据集目录路径",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/metrics.yaml"),
        help="项目配置文件路径（默认：configs/metrics.yaml）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/v2"),
        help="输出目录（默认：reports/v2）",
    )
    parser.add_argument(
        "--format",
        choices=["console", "markdown", "json"],
        default="console",
        help="输出格式",
    )

    args = parser.parse_args(argv)

    # 加载配置并构建解析器
    config = _load_config(args.config)
    resolver = CanonicalResolver.from_config(config)

    # 加载数据集
    loader = V2DatasetLoader(args.dataset)
    cases = loader.load_all()
    if not cases:
        print("错误：未找到测试用例。", file=sys.stderr)
        return 1
    print(f"已加载 {len(cases)} 条测试用例")

    # 构建评分器和运行器
    scorers = _build_scorers(resolver)
    runner = V2BenchmarkRunner(scorers)

    # 运行（暂时不连 API — 打印预期结构）
    print("\nV2 基准测试就绪！")
    print(f"用例数：{len(cases)}")
    print(f"评分器：{list(scorers.keys())}")
    print("\n连接 API 运行：")
    print("  python -m nl2dsl.evaluation.v2_cli --dataset tests/evaluation/dataset/v2")

    return 0


if __name__ == "__main__":
    sys.exit(main())
