"""NL2DSL Evaluation Framework.

Provides tools for benchmarking and measuring the accuracy of the NL2DSL
pipeline across multiple dimensions: intent, metrics, dimensions, filters,
joins, ordering, and SQL execution.

Usage:
    from nl2dsl.evaluation.runner import EvaluationRunner
    from nl2dsl.evaluation.scoring import ScoringEngine
    from nl2dsl.evaluation.dataset import DatasetLoader

    loader = DatasetLoader("tests/evaluation/dataset")
    cases = loader.load_all()

    runner = EvaluationRunner(api_client, ScoringEngine())
    results = runner.run_batch(cases)
    report = runner.generate_report(results)
"""

from __future__ import annotations

__all__ = [
    "DatasetLoader",
    "EvaluationRunner",
    "ReportGenerator",
    "ScoringEngine",
    "ScoreBreakdown",
    "EvalTestCase",
    "TestResult",
    "EvaluationReport",
    "GovernanceInfo",
]

from nl2dsl.evaluation.dataset import DatasetLoader
from nl2dsl.evaluation.models import (
    EvaluationReport,
    EvalTestCase,
    ScoreBreakdown,
    TestResult,
)
from nl2dsl.evaluation.report import ReportGenerator
from nl2dsl.evaluation.runner import EvaluationRunner
from nl2dsl.evaluation.scoring import ScoringEngine
