import pytest
from nl2dsl.evaluation.v2_reporter import V2Reporter


def test_reporter_format():
    reporter = V2Reporter()
    results = [
        {
            "test_case": {"id": "BASIC_001", "query": "查询销售额"},
            "passed": False,
            "scores": type("Scores", (), {
                "intent": 1.0, "metric": 0.0, "filter": 1.0,
                "planner": 1.0, "governance": 1.0, "overall": 0.9,
            })(),
        }
    ]
    output = reporter.to_console(results)
    # BASIC_001 appears in failures section
    assert "BASIC_001" in output


def test_reporter_markdown():
    reporter = V2Reporter()
    results = [
        {
            "test_case": {"id": "BASIC_001", "query": "查询销售额"},
            "passed": True,
            "scores": type("Scores", (), {
                "intent": 1.0, "metric": 1.0, "filter": 1.0,
                "planner": 1.0, "governance": 1.0, "overall": 1.0,
            })(),
        }
    ]
    output = reporter.to_markdown(results)
    assert "整体准确率" in output
    assert "100.0%" in output
