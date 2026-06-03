"""Tests for OptimizationReport."""

from nl2dsl.optimizer.base import RuleResult
from nl2dsl.optimizer.report import OptimizationReport


class TestOptimizationReport:
    def test_empty_report(self):
        r = OptimizationReport()
        r.finalize(elapsed_ms=0)
        assert r.total_rules_checked == 0
        assert r.total_rules_triggered == 0
        assert r.fatal is False

    def test_add_fix_result(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="M001", category="Metric", severity="Fix",
            confidence="high", description="Fixed", applied=True,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert len(r.fixes_applied) == 1
        assert len(r.warnings_issued) == 0

    def test_add_fix_bypassed_result(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="M001", category="Metric", severity="Fix",
            confidence="high", description="Fix not applied", applied=False,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert len(r.fixes_bypassed) == 1
        assert len(r.fixes_applied) == 0

    def test_add_warning_result(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="F003", category="Filter", severity="Warn",
            confidence="medium", description="Missing time range",
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert len(r.warnings_issued) == 1
        assert len(r.fixes_applied) == 0

    def test_add_fatal_rejection(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="S001", category="Structural", severity="Reject",
            confidence="high", description="Empty query", is_fatal=True,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert r.fatal is True
        assert r.fatal_rejection is not None

    def test_add_normal_rejection(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="M004", category="Metric", severity="Reject",
            confidence="high", description="Mismatch", is_fatal=False,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert r.fatal is False
        assert len(r.rejections) == 1

    def test_metrics_computation(self):
        r = OptimizationReport()
        r.total_rules_checked = 5
        r.total_rules_triggered = 4
        r.fixes_applied = [{"error_code": "M001"}, {"error_code": "F001"}]
        r.warnings_issued = [{"error_code": "F003"}]
        r.rejections = [{"error_code": "M004"}]
        r.finalize(elapsed_ms=42)
        assert r.fix_rate == 2 / 4
        assert r.warning_rate == 1 / 4
        assert r.rejection_rate == 1 / 4
        assert r.elapsed_ms == 42

    def test_json_serialization(self):
        r = OptimizationReport(query_id="q_001")
        r.total_rules_checked = 3
        r.total_rules_triggered = 1
        r.finalize(elapsed_ms=10)
        json_str = r.to_json()
        assert '"report_id"' in json_str
        assert '"query_id": "q_001"' in json_str
        assert '"elapsed_ms": 10' in json_str

    def test_diff_computation(self):
        r = OptimizationReport()
        r.dsl_before = {"data_source": "", "limit": 100}
        r.dsl_after = {"data_source": "orders", "limit": 50}
        r.compute_diff()
        assert len(r.diff) == 2
        assert any("data_source" in d for d in r.diff)
