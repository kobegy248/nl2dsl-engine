"""CLI entry point for running NL2DSL evaluation.

Usage:
    python -m nl2dsl.evaluation.cli \
        --dataset tests/evaluation/dataset \
        --output reports/ \
        --format both

Or after installation:
    nl2dsl-eval --dataset tests/evaluation/dataset --output reports/
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from nl2dsl.api_factory import create_app
from nl2dsl.evaluation.dataset import DatasetLoader
from nl2dsl.evaluation.report import ReportGenerator
from nl2dsl.evaluation.runner import EvaluationRunner
from nl2dsl.evaluation.scoring import ScoringEngine
from nl2dsl.testing.sample_data import (
    create_mock_bank_database,
    create_mock_database,
    create_mock_supply_chain_database,
)
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.cli")


def _load_config_for_domain(domain: str):
    """Load registry dict and permissions for a given domain."""
    import yaml

    samples_dir = Path(__file__).parent / "samples"

    prefix = "" if domain == "ecommerce" else f"{domain}_"
    metrics_path = samples_dir / f"{prefix}metrics.yaml"
    perm_path = samples_dir / f"{prefix}permissions.yaml"

    # Fallback for missing files
    if not metrics_path.exists() and domain != "ecommerce":
        metrics_path = samples_dir / "metrics.yaml"
    if not perm_path.exists() and domain != "ecommerce":
        perm_path = samples_dir / "permissions.yaml"

    with open(metrics_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    registry = {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }

    permissions: dict = {}
    sensitive_columns: dict = {}
    masking_rules: dict = {}
    if perm_path.exists():
        with open(perm_path, "r", encoding="utf-8") as f:
            perm = yaml.safe_load(f)
        permissions = perm.get("users", {})
        sensitive_columns = perm.get("sensitive_columns", {})
        masking_rules = perm.get("masking_rules", {})

    return registry, permissions, sensitive_columns, masking_rules


def _create_client_for_domain(domain: str):
    """Create a TestClient for the given domain with mock data."""
    if domain == "bank":
        engine, *_ = create_mock_bank_database("sqlite:///:memory:")
    elif domain == "supply_chain":
        engine, *_ = create_mock_supply_chain_database("sqlite:///:memory:")
    else:
        engine, *_ = create_mock_database("sqlite:///:memory:")

    registry, permissions, sensitive_columns, masking_rules = _load_config_for_domain(domain)

    # Initialize LLM client from the active provider (switchable via
    # NL2DSL_LLM_PROVIDER / set_active_provider).
    llm_client = None
    try:
        from nl2dsl.llm.providers import get_llm_client, active_provider

        llm_client = get_llm_client()
        if llm_client is not None:
            logger.info(
                "LLM client initialized for domain=%s provider=%s model=%s",
                domain, active_provider(), llm_client.model_name,
            )
        else:
            logger.warning("Active LLM provider not configured, running without LLM")
    except Exception as exc:
        logger.error("Failed to initialize LLM client: %s", exc)

    app = create_app(
        engine=engine,
        registry_dict=registry,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
        llm_client=llm_client,
        enable_clarification=True,
    )
    from fastapi.testclient import TestClient

    return TestClient(app)


def _progress(current: int, total: int) -> None:
    """Print progress bar (ASCII-safe for Windows terminals)."""
    pct = current / total * 100
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%)", end="", flush=True)
    if current == total:
        print()


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    # Disable Windows system proxy for Python HTTP clients
    # (avoids Connection refused when a local proxy port is configured but not running)
    import os
    os.environ["HTTP_PROXY"] = ""
    os.environ["HTTPS_PROXY"] = ""
    os.environ["ALL_PROXY"] = ""
    os.environ["NO_PROXY"] = "*"

    parser = argparse.ArgumentParser(
        description="Evaluate NL2DSL pipeline accuracy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dataset tests/evaluation/dataset --output reports/
  %(prog)s --dataset tests/evaluation/dataset --domain ecommerce --format markdown
  %(prog)s --dataset tests/evaluation/dataset --tags filter aggregation
        """,
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to evaluation dataset directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports"),
        help="Output directory for reports (default: reports/)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        help="Run only tests for specified domain",
    )
    parser.add_argument(
        "--tags",
        type=str,
        nargs="+",
        help="Filter by tags (any match)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="both",
        help="Report output format (default: both)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Passing threshold for overall score (default: 0.8)",
    )
    parser.add_argument(
        "--weights",
        type=str,
        nargs="+",
        help="Custom weights as key=value pairs, e.g., metric=0.3 filter=0.15",
    )

    args = parser.parse_args(argv)

    # Validate dataset directory
    if not args.dataset.exists():
        print(f"Error: Dataset directory not found: {args.dataset}", file=sys.stderr)
        return 1

    # Load dataset
    loader = DatasetLoader(args.dataset)
    if args.domain:
        test_cases = loader.load_domain(args.domain)
    else:
        test_cases = loader.load_all()

    if not test_cases:
        print("Error: No test cases found.", file=sys.stderr)
        return 1

    # Filter by tags
    if args.tags:
        test_cases = loader.filter_by_tags(test_cases, args.tags)
        if not test_cases:
            print(f"Error: No test cases match tags: {args.tags}", file=sys.stderr)
            return 1

    print(f"Loaded {len(test_cases)} test cases")

    # Custom weights
    weights: dict[str, float] | None = None
    if args.weights:
        weights = {}
        for pair in args.weights:
            if "=" not in pair:
                print(f"Error: Invalid weight format: {pair}", file=sys.stderr)
                return 1
            key, val = pair.split("=", 1)
            try:
                weights[key] = float(val)
            except ValueError:
                print(f"Error: Invalid weight value: {val}", file=sys.stderr)
                return 1

    scoring = ScoringEngine(weights=weights, threshold=args.threshold)

    # Group cases by domain and create per-domain clients
    domain_cases: dict[str, list] = {}
    for case in test_cases:
        domain_cases.setdefault(case.domain, []).append(case)

    all_results = []
    for domain, cases in domain_cases.items():
        print(f"\nEvaluating {len(cases)} cases for domain '{domain}'...")
        client = _create_client_for_domain(domain)
        _, _, sensitive_columns, masking_rules = _load_config_for_domain(domain)
        runner = EvaluationRunner(
            api_client=client,
            scoring_engine=scoring,
            sensitive_columns=sensitive_columns,
            masking_rules=masking_rules,
        )
        results = runner.run_batch(cases, progress_callback=_progress)
        all_results.extend(results)

    # Generate report
    # We need a runner instance for generate_report, so create one with any client
    _, _, sensitive_columns, masking_rules = _load_config_for_domain("ecommerce")
    runner = EvaluationRunner(
        api_client=_create_client_for_domain("ecommerce"),
        scoring_engine=scoring,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    report_obj = runner.generate_report(all_results)

    # Output
    args.output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    generator = ReportGenerator()

    if args.format in ("json", "both"):
        json_path = args.output / f"evaluation_{timestamp}.json"
        generator.generate_json(report_obj, json_path)
        print(f"\nJSON report: {json_path}")

    if args.format in ("markdown", "both"):
        md_path = args.output / f"evaluation_{timestamp}.md"
        generator.generate_markdown(report_obj, md_path)
        print(f"Markdown report: {md_path}")

    # Summary
    print("\n" + "=" * 50)
    print(f"Overall Score: {report_obj.overall_score:.1%}")
    print(f"Passed: {report_obj.passed} / {report_obj.total_cases}")
    print(f"Failed: {report_obj.failed}")
    print("=" * 50)

    # Per-domain summary
    if len(report_obj.by_domain) > 1:
        print("\nPer Domain:")
        for domain, summary in sorted(report_obj.by_domain.items()):
            print(f"  {domain:20s} {summary.average_score:.1%} ({summary.passed}/{summary.total_cases})")

    # Per-category summary
    bd = report_obj.by_dimension
    print("\nBy Category:")
    print(f"  {'Semantic':20s} {bd.semantic_score:.1%} (Intent {bd.intent:.0%} | Metric {bd.metric:.0%} | Dimension {bd.dimension:.0%} | Filter {bd.filter:.0%})")
    print(f"  {'Planning':20s} {bd.planning_score:.1%} (Join {bd.join:.0%} | Limit {bd.limit:.0%} | OrderBy {bd.order_by:.0%})")
    print(f"  {'Execution':20s} {bd.execution_score:.1%} (SQL {bd.sql_success:.0%} | Result Acc {bd.result_accuracy:.0%})")
    print(f"  {'Governance':20s} {bd.governance_score:.1%} (Permission {bd.permission:.0%} | Masking {bd.masking:.0%} | Audit {bd.audit:.0%})")

    # Per-dimension summary (legacy flat view)
    print("\nBy Dimension (detailed):")
    dims = [
        ("Intent", bd.intent),
        ("Metric", bd.metric),
        ("Dimension", bd.dimension),
        ("Filter", bd.filter),
        ("Join", bd.join),
        ("Limit", bd.limit),
        ("OrderBy", bd.order_by),
        ("SQL Success", bd.sql_success),
        ("Result Accuracy", bd.result_accuracy),
        ("Permission", bd.permission),
        ("Masking", bd.masking),
        ("Audit", bd.audit),
    ]
    for name, score in dims:
        print(f"  {name:20s} {score:.1%}")

    # Failed case IDs
    if report_obj.failed_cases:
        print(f"\nFailed cases:")
        for r in report_obj.failed_cases:
            print(f"  - {r.test_case.id}: {r.test_case.query} ({r.scores.overall:.1%})")

    return 0 if report_obj.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
