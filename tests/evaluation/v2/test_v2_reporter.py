import pytest
from nl2dsl.evaluation.v2_reporter import V2Reporter


def _scores(overall=1.0):
    return type("Scores", (), {
        "intent": 1.0, "metric": 1.0, "filter": 1.0,
        "planner": 1.0, "governance": 1.0, "overall": overall,
    })()


def _result(case_id, generator, optimizer, overall=1.0, passed=True, status="success", domain="ecommerce"):
    return {
        "test_case": {"id": case_id, "query": "q", "tags": ["basic"]},
        "passed": passed,
        "scores": _scores(overall),
        "status": status,
        "generator_mode": generator,
        "optimizer_enabled": optimizer == "on",
        "domain": domain,
        "execution_time_ms": 10,
        "observation": {},
    }


# --- P1-4: 矩阵组合复合键，四条结果互不覆盖 ---

def test_matrix_keeps_all_four_combos_for_same_case():
    reporter = V2Reporter()
    case_id = "BASIC_001"
    combos = [("rule", "off"), ("rule", "on"), ("llm", "off"), ("llm", "on")]
    results = [_result(case_id, g, o) for g, o in combos]
    report = reporter.build_matrix_report(results, matrix_runs=[
        {"generator_mode": g, "optimizer_enabled": (o == "on"), "results": [_result(case_id, g, o)]}
        for g, o in combos
    ])
    # 四条结果必须全部保留（复合键）
    assert len(report["cases"]) == 4
    keys = set(report["cases"].keys())
    for g, o in combos:
        assert f"ecommerce|{case_id}|{g}|{o}" in keys
    # by_matrix 也保留四个组合
    assert len(report["by_matrix"]) == 4


def test_regression_reports_specific_combo_only():
    """某一个组合回退时，门禁只报告该组合，其他组合不掩盖也不误报。"""
    from nl2dsl.evaluation.baseline import evaluate_regression
    case_id = "BASIC_001"
    combos = [("rule", "off"), ("rule", "on"), ("llm", "off"), ("llm", "on")]

    def _build(passing_combo_overall):
        results = []
        for g, o in combos:
            overall = passing_combo_overall if (g, o) == ("rule", "on") else 1.0
            passed = overall >= 0.8
            results.append(_result(case_id, g, o, overall=overall, passed=passed))
        rep = V2Reporter().build_matrix_report(results)
        rep["dataset_hash"] = "h"
        return rep

    baseline = _build(1.0)
    current = _build(0.3)  # rule/on 回退
    reg = evaluate_regression(current, baseline, max_case_drop=0.10)
    assert reg["passed"] is False
    # 只有 rule/on 这一条组合出现在回退里
    reg_keys = {c["key"] for c in reg["case_regressions"]}
    assert reg_keys == {f"ecommerce|{case_id}|rule|on"}
    # 其他三条组合未被覆盖、未被误报
    assert len(reg["case_regressions"]) == 1


def test_missing_combo_in_current_is_regression():
    """当前缺失 Baseline 中存在的组合 → 回退。"""
    from nl2dsl.evaluation.baseline import evaluate_regression
    case_id = "BASIC_001"
    combos = [("rule", "off"), ("rule", "on")]
    base_results = [_result(case_id, g, o) for g, o in combos]
    baseline = V2Reporter().build_matrix_report(base_results)
    baseline["dataset_hash"] = "h"
    # 当前只剩 rule/off
    current = V2Reporter().build_matrix_report([_result(case_id, "rule", "off")])
    current["dataset_hash"] = "h"
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert len(reg["missing_cases"]) == 1
    assert reg["missing_cases"][0]["key"] == f"ecommerce|{case_id}|rule|on"


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
