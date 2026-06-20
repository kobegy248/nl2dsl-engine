"""Phase 2：Baseline 保存/读取/回归门禁测试。"""

from __future__ import annotations

from nl2dsl.evaluation.baseline import (
    BASELINE_SCHEMA_VERSION,
    compute_dataset_hash,
    evaluate_regression,
    load_baseline,
    save_baseline,
)


def _report(overall=0.9, cases=None, dims=None):
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "dataset_hash": "h",
        "matrix_combos": [{"generator": "rule", "optimizer": "on"}],
        "summary": {
            "overall_score": overall,
            "by_dimension": dims or {"intent": 0.9, "metric": 0.9, "filter": 0.9, "planner": 0.9, "governance": 1.0},
        },
        "cases": cases or {
            "C1": {"overall": 0.9, "passed": True, "status": "success"},
            "C2": {"overall": 0.8, "passed": True, "status": "success"},
        },
    }


def _cases():
    C = type("C", (), {})
    c1, c2 = C(), C()
    c1.id, c1.query = "C1", "q1"
    c2.id, c2.query = "C2", "q2"
    return [c1, c2]


def test_save_and_load_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    save_baseline(_report(), _cases(), path, matrix={"generator": "rule", "optimizer": "on"})
    loaded = load_baseline(path)
    assert loaded["schema_version"] == BASELINE_SCHEMA_VERSION
    assert "dataset_hash" in loaded
    assert loaded["matrix"] == {"generator": "rule", "optimizer": "on"}
    assert loaded["summary"]["overall_score"] == 0.9


def test_dataset_hash_stable():
    h1 = compute_dataset_hash(_cases())
    h2 = compute_dataset_hash(_cases())
    assert h1 == h2


# --- P1-5: dataset hash 覆盖 expected/domain/tags，且对键顺序稳定 ---

def _v2case(cid, *, domain="ecommerce", query="q", expected=None, tags=None, category="basic", difficulty="easy"):
    C = type("C", (), {})
    c = C()
    c.id = cid
    c.domain = domain
    c.query = query
    c.expected = expected if expected is not None else {"metric": "sales_amount"}
    c.tags = tags if tags is not None else ["aggregation"]
    c.category = category
    c.difficulty = difficulty
    return c


def test_hash_changes_when_expected_changes():
    base = [_v2case("C1", expected={"metric": "sales_amount"})]
    changed = [_v2case("C1", expected={"metric": "order_count"})]
    assert compute_dataset_hash(base) != compute_dataset_hash(changed)


def test_hash_changes_when_domain_or_tags_change():
    h_domain = compute_dataset_hash([_v2case("C1", domain="bank")])
    h_base = compute_dataset_hash([_v2case("C1", domain="ecommerce")])
    assert h_domain != h_base

    h_tags = compute_dataset_hash([_v2case("C1", tags=["ranking"])])
    h_base_tags = compute_dataset_hash([_v2case("C1", tags=["aggregation"])])
    assert h_tags != h_base_tags


def test_hash_invariant_to_dict_key_order():
    c1 = _v2case("C1", expected={"metric": "sales_amount", "filters": []})
    c2 = _v2case("C1", expected={"filters": [], "metric": "sales_amount"})
    assert compute_dataset_hash([c1]) == compute_dataset_hash([c2])


def test_hash_invariant_to_case_order():
    a = [_v2case("C1"), _v2case("C2")]
    b = [_v2case("C2"), _v2case("C1")]
    assert compute_dataset_hash(a) == compute_dataset_hash(b)


def test_regression_missing_baseline_case_fails():
    """当前缺少 Baseline 用例（组合）时门禁失败。"""
    baseline = {
        "schema_version": "1.0",
        "dataset_hash": "h",
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {"ecommerce|C1|rule|off": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    current = {
        "schema_version": "1.0",
        "dataset_hash": "h",
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {},  # 缺失该组合
    }
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert len(reg["missing_cases"]) == 1


def test_regression_matrix_mismatch_fails_with_reason():
    """matrix 组合不一致时门禁失败并给出明确原因。"""
    baseline = {
        "schema_version": "1.0",
        "dataset_hash": "h",
        "matrix_combos": [{"generator": "rule", "optimizer": "off"}],
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {"ecommerce|C1|rule|off": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    current = {
        "schema_version": "1.0",
        "dataset_hash": "h",
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "by_matrix": [{"generator": "rule", "optimizer": "on"}],
        "cases": {"ecommerce|C1|rule|on": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("matrix" in r for r in reg["reasons"])


def test_regression_dataset_hash_mismatch_fails():
    baseline = {
        "schema_version": "1.0",
        "dataset_hash": "h-old",
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {"C1": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    current = {
        "schema_version": "1.0",
        "dataset_hash": "h-new",
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {"C1": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("dataset_hash" in r for r in reg["reasons"])


def test_regression_same_results_delta_zero():
    baseline = _report(overall=0.9, cases={
        "C1": {"overall": 0.9, "passed": True, "status": "success"},
    })
    current = _report(overall=0.9, cases={
        "C1": {"overall": 0.9, "passed": True, "status": "success"},
    })
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is True
    assert reg["overall_delta"] == 0.0


def test_regression_new_failure_fails():
    baseline = _report(overall=0.9, cases={
        "C1": {"overall": 0.9, "passed": True, "status": "success"},
    })
    current = _report(overall=0.9, cases={
        "C1": {"overall": 0.4, "passed": False, "status": "error"},
    })
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert len(reg["new_failures"]) == 1


def test_regression_dimension_drop_fails():
    baseline = _report(overall=0.9, dims={"metric": 0.95})
    current = _report(overall=0.9, dims={"metric": 0.80})
    reg = evaluate_regression(current, baseline, max_dimension_drop=0.02)
    assert reg["passed"] is False
    assert any(d["dimension"] == "metric" for d in reg["dimension_regressions"])


def test_regression_case_drop_fails():
    baseline = _report(cases={"C1": {"overall": 0.9, "passed": True, "status": "success"}})
    current = _report(cases={"C1": {"overall": 0.75, "passed": True, "status": "success"}})
    reg = evaluate_regression(current, baseline, max_case_drop=0.10)
    assert reg["passed"] is False
    assert len(reg["case_regressions"]) == 1


def test_regression_overall_drop_fails():
    baseline = _report(overall=0.9)
    current = _report(overall=0.85)
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert reg["overall_delta"] < 0


# --- 第二轮审阅 P1：Baseline 身份校验 fail-closed ---

def _identity_report(*, schema="1.0", hash="h", combos=None, with_combos_key=True):
    """构造带身份字段的报告；combos=None 且 with_combos_key=False 表示字段缺失。"""
    rep = {
        "schema_version": schema,
        "dataset_hash": hash,
        "summary": {"overall_score": 0.9, "by_dimension": {}},
        "cases": {"C1": {"overall": 0.9, "passed": True, "case_id": "C1"}},
    }
    if with_combos_key:
        rep["matrix_combos"] = combos if combos is not None else [{"generator": "rule", "optimizer": "on"}]
    return rep


def test_baseline_missing_schema_version_fails():
    """Baseline 缺失 schema_version 时门禁失败（fail-closed）。"""
    baseline = _identity_report()
    del baseline["schema_version"]
    current = _identity_report()
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("schema_version" in r and "Baseline 不兼容或损坏" in r for r in reg["reasons"])


def test_baseline_missing_dataset_hash_fails():
    """Baseline 缺失 dataset_hash 时门禁失败（不得默认零分继续比较）。"""
    baseline = _identity_report()
    del baseline["dataset_hash"]
    current = _identity_report()
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("dataset_hash" in r and "Baseline 不兼容或损坏" in r for r in reg["reasons"])


def test_baseline_missing_matrix_combos_fails():
    """Baseline 缺失 matrix_combos 字段时门禁失败（与空列表 [] 区分）。"""
    baseline = _identity_report(with_combos_key=False)
    current = _identity_report()
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("matrix_combos" in r and "Baseline 不兼容或损坏" in r for r in reg["reasons"])


def test_baseline_empty_matrix_combos_distinct_from_missing():
    """matrix_combos=[] 是合法的空矩阵身份，与字段缺失区分：双方均为 [] 且其余身份一致 → 通过身份校验。"""
    baseline = _identity_report(combos=[])
    current = _identity_report(combos=[])
    reg = evaluate_regression(current, baseline)
    # 身份校验通过（无 compatibility 项），分数一致 → 门禁通过
    assert reg["compatibility"] == []
    assert reg["passed"] is True


def test_current_missing_identity_field_fails():
    """当前报告缺失对应身份字段（dataset_hash）时门禁失败。"""
    baseline = _identity_report()
    current = _identity_report()
    del current["dataset_hash"]
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("当前报告缺少 dataset_hash" in r for r in reg["reasons"])


def test_unsupported_schema_version_fails():
    """不支持的 schema_version 明确失败。"""
    baseline = _identity_report(schema="0.9-beta")
    current = _identity_report()
    reg = evaluate_regression(current, baseline)
    assert reg["passed"] is False
    assert any("不支持的 schema_version" in r for r in reg["reasons"])


def test_full_consistent_identity_enters_score_comparison():
    """完整且一致的身份字段能正常进入分数比较（一致 → 通过）。"""
    baseline = _identity_report()
    current = _identity_report()
    reg = evaluate_regression(current, baseline)
    assert reg["compatibility"] == []
    assert reg["passed"] is True
    assert reg["overall_delta"] == 0.0
