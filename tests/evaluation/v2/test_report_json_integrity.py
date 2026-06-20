"""P1: generated reports must be strictly valid JSON (third review).

PowerShell ``ConvertFrom-Json`` failed to parse the bank/supply_chain reports.
Reports must round-trip through Python ``json.load()``, survive multiline
exception messages and Chinese query/error content, and an interrupted write
must not corrupt a previously valid report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nl2dsl.evaluation.v2_reporter import V2Reporter
from nl2dsl.evaluation.v2_cli import _write_and_verify_json


def _scores(overall=1.0):
    return type("Scores", (), {
        "intent": 1.0, "metric": 1.0, "filter": 1.0,
        "planner": 1.0, "governance": 1.0, "overall": overall,
    })()


def _result(case_id, *, overall=1.0, passed=True, status="success",
            query="q", error=None, domain="ecommerce"):
    return {
        "test_case": {"id": case_id, "query": query, "tags": ["basic"]},
        "passed": passed,
        "scores": _scores(overall),
        "status": status,
        "generator_mode": "rule",
        "optimizer_enabled": False,
        "domain": domain,
        "execution_time_ms": 10,
        "observation": {"error": error},
    }


def test_multiline_error_report_parses_with_json_load():
    """含多行异常信息的报告可被 json.load() 解析。"""
    multiline_error = (
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in run\n"
        "    raise RuntimeError(\"boom\")\n"
        "RuntimeError: boom\n"
        "Recursion limit of 10007 reached"
    )
    results = [
        _result("c1", passed=False, status="error", error=multiline_error,
                query="查询客户数量"),
        _result("c2", overall=0.9, query="各账户类型的平均余额"),
    ]
    report = V2Reporter().build_matrix_report(results)
    text = V2Reporter().matrix_report_to_json(report)
    parsed = json.loads(text)  # must not raise
    assert parsed["summary"]["execution_errors"] == 1


def test_chinese_query_and_error_round_trip(tmp_path):
    """中文 query / error 可正确写入并读取。"""
    results = [
        _result("c1", passed=False, status="error",
                error="查询失败：数据源 'customers' 列 'org_name' 不存在",
                query="查询各风险等级的客户数量"),
    ]
    report = V2Reporter().build_matrix_report(results)
    out = tmp_path / "benchmark_report.json"
    assert _write_and_verify_json(out, V2Reporter().matrix_report_to_json(report))
    reparsed = json.loads(out.read_text(encoding="utf-8"))
    fc = reparsed["failed_cases"][0]
    assert fc["query"] == "查询各风险等级的客户数量"
    assert "查询失败" in fc["error"]


def test_write_does_not_overwrite_existing_valid_report_on_failure(tmp_path):
    """写入中断（校验失败）不覆盖上一份有效报告。"""
    out = tmp_path / "benchmark_report.json"
    # 先写一份有效报告
    good = json.dumps({"summary": {"passed": 5}, "cases": {}}, ensure_ascii=False)
    assert _write_and_verify_json(out, good)
    original = out.read_text(encoding="utf-8")

    # 尝试写入非法 JSON：必须失败且不覆盖已有文件
    bad = "{ this is not valid json "
    assert _write_and_verify_json(out, bad) is False
    assert out.read_text(encoding="utf-8") == original


def test_recursion_error_counted_in_summary(tmp_path):
    results = [
        _result("c1", passed=False, status="error",
                error="Recursion limit of 10007 reached without hitting a stop condition. GRAPH_RECURSION_LIMIT"),
    ]
    report = V2Reporter().build_matrix_report(results)
    assert report["summary"]["recursion_errors"] == 1
    assert report["summary"]["execution_errors"] == 1


def test_markdown_distinguishes_execution_errors_from_score_failures():
    results = [
        # 语义低分失败（success 但分数低）
        _result("low1", overall=0.2, passed=False, status="success", query="q1"),
        # 执行错误失败
        _result("err1", passed=False, status="error", error="boom", query="q2"),
    ]
    report = V2Reporter().build_matrix_report(results)
    md = V2Reporter().matrix_report_to_markdown(report)
    assert "执行错误" in md
    assert "评测链路异常" in md
