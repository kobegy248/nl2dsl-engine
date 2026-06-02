import pytest
from nl2dsl.evaluation.v2_runner import V2BenchmarkRunner


def test_runner_initialization():
    runner = V2BenchmarkRunner({})
    assert runner is not None
