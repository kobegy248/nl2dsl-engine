"""Evaluation runner — orchestrates the full evaluation pipeline."""

from __future__ import annotations

import time
from typing import Callable

from fastapi.testclient import TestClient

from nl2dsl.evaluation.models import (
    DomainSummary,
    EvalTestCase as TestCase,
    EvaluationReport,
    GovernanceInfo,
    ScoreBreakdown,
    TagSummary,
    TestResult,
)
from nl2dsl.evaluation.scoring import ScoringEngine
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.runner")


class EvaluationRunner:
    """Runs evaluation against the NL2DSL pipeline via API calls.

    Usage::

        from nl2dsl.evaluation.runner import EvaluationRunner
        from nl2dsl.evaluation.scoring import ScoringEngine
        from tests.e2e.conftest import create_app

        app = create_app(...)
        client = TestClient(app)
        runner = EvaluationRunner(client, ScoringEngine())

        results = runner.run_batch(cases)
        report = runner.generate_report(results)
    """

    def __init__(
        self,
        api_client: TestClient,
        scoring_engine: ScoringEngine,
        user_id: str = "eval_user",
        tenant_id: str = "eval_tenant",
        sensitive_columns: dict[str, dict] | None = None,
        masking_rules: dict[str, callable] | None = None,
        check_result_accuracy: bool = False,
        check_audit: bool = False,
    ):
        self.client = api_client
        self.scoring = scoring_engine
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.sensitive_columns = sensitive_columns or {}
        self.masking_rules = masking_rules or {}
        self.check_result_accuracy = check_result_accuracy
        self.check_audit = check_audit

    def run_single(self, test_case: TestCase) -> TestResult:
        """Evaluate a single test case.

        Calls POST /api/v1/query with the test case's natural language question,
        then scores the generated DSL against the expected DSL.
        """
        start = time.time()

        payload = {
            "question": test_case.query,
            "domain": test_case.domain,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
        }

        try:
            response = self.client.post("/api/v1/query", json=payload)
            data = response.json()
        except Exception as exc:
            elapsed = int((time.time() - start) * 1000)
            logger.error("[%s] API call failed: %s", test_case.id, exc)
            return TestResult(
                test_case=test_case,
                passed=False,
                scores=ScoreBreakdown(),
                error=str(exc),
                execution_time_ms=elapsed,
            )

        elapsed = int((time.time() - start) * 1000)
        status = data.get("status", "error")

        # Extract actual DSL, SQL, and data from response
        actual_dsl = data.get("dsl")
        actual_sql = data.get("sql")
        actual_data = data.get("data")
        error_msg = data.get("error") if status == "error" else None
        query_id = data.get("query_id")  # May be returned by API

        # Collect governance info
        governance = self._collect_governance(
            expected_dsl=test_case.expected_dsl,
            actual_dsl=actual_dsl,
            actual_data=actual_data,
            error_msg=error_msg,
            query_id=query_id,
        )

        # Optionally check result accuracy by executing expected DSL
        expected_data = None
        if self.check_result_accuracy and status != "error" and actual_dsl is not None:
            expected_data = self._execute_expected_dsl(test_case.expected_dsl)

        # Score
        scores = self.scoring.score(
            expected_dsl=test_case.expected_dsl,
            actual_dsl=actual_dsl,
            sql=actual_sql,
            error=error_msg,
            actual_data=actual_data,
            expected_data=expected_data,
            governance=governance,
        )

        passed = self.scoring.is_passed(scores)

        logger.info(
            "[%s] score=%.2f passed=%s status=%s time=%dms",
            test_case.id,
            scores.overall,
            passed,
            status,
            elapsed,
        )

        return TestResult(
            test_case=test_case,
            passed=passed,
            scores=scores,
            actual_dsl=actual_dsl,
            actual_sql=actual_sql,
            actual_data=actual_data,
            expected_data=expected_data,
            governance=governance,
            error=error_msg,
            execution_time_ms=elapsed,
        )

    def _collect_governance(
        self,
        expected_dsl: dict,
        actual_dsl: dict | None,
        actual_data: list[dict] | None,
        error_msg: str | None,
        query_id: str | None,
    ) -> GovernanceInfo:
        """Collect governance metadata for a test case."""
        gov = GovernanceInfo()

        # Detect sensitive fields accessed
        sensitive_accessed: list[str] = []
        if actual_dsl and actual_dsl.get("dimensions"):
            for dim in actual_dsl.get("dimensions", []):
                if dim in self.sensitive_columns:
                    sensitive_accessed.append(dim)

        # Also check expected DSL for sensitive fields (if actual is None)
        if not sensitive_accessed and expected_dsl.get("dimensions"):
            for dim in expected_dsl.get("dimensions", []):
                if dim in self.sensitive_columns:
                    sensitive_accessed.append(dim)

        gov.sensitive_fields_accessed = sensitive_accessed

        # Check for permission error
        if error_msg:
            error_lower = error_msg.lower()
            gov.permission_error = any(
                kw in error_lower
                for kw in ["permission", "unauthorized", "无权访问", "敏感字段"]
            )

        # Check masking
        if actual_data and sensitive_accessed:
            masked: dict[str, str] = {}
            for field in sensitive_accessed:
                if field in self.masking_rules:
                    # Check if all values for this field are masked
                    # A simple heuristic: compare first value with original
                    values = [str(row.get(field, "")) for row in actual_data if field in row]
                    if values:
                        original = values[0]
                        masked_value = self.masking_rules[field](original)
                        # If any value differs from original, consider it masked
                        if any(str(v) != str(masked_value) for v in values):
                            masked[field] = masked_value
            gov.masked_fields = masked

        # Check audit logging
        if self.check_audit and query_id:
            try:
                audit_resp = self.client.get(f"/api/v1/admin/audit/queries/{query_id}")
                if audit_resp.status_code == 200:
                    audit_data = audit_resp.json()
                    gov.audit_logged = audit_data.get("status") == "success"
            except Exception:
                gov.audit_logged = False
        elif query_id:
            # Best-effort: assume logged if query succeeded and has query_id
            gov.audit_logged = True

        gov.query_id = query_id
        return gov

    def _execute_expected_dsl(self, expected_dsl: dict) -> list[dict] | None:
        """Execute expected DSL via API to get ground-truth result data."""
        try:
            payload = {
                "dsl": expected_dsl,
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
            }
            response = self.client.post("/api/v1/query/execute", json=payload)
            if response.status_code == 200:
                data = response.json()
                return data.get("data")
        except Exception as exc:
            logger.warning("Failed to execute expected DSL for result accuracy: %s", exc)
        return None

    def run_batch(
        self,
        cases: list[TestCase],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[TestResult]:
        """Evaluate a batch of test cases sequentially.

        Args:
            cases: List of test cases to evaluate.
            progress_callback: Optional callback(current, total) for progress reporting.

        Returns:
            List of TestResult, one per test case, in the same order.
        """
        results: list[TestResult] = []
        total = len(cases)

        for i, case in enumerate(cases):
            result = self.run_single(case)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, total)

        return results

    def generate_report(self, results: list[TestResult]) -> EvaluationReport:
        """Generate an aggregate report from a list of test results."""
        if not results:
            return EvaluationReport()

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        total_time = sum(r.execution_time_ms for r in results)

        # Aggregate dimension scores
        by_dimension = self._aggregate_scores([r.scores for r in results])

        # Per-domain breakdown
        by_domain: dict[str, list[TestResult]] = {}
        for r in results:
            by_domain.setdefault(r.test_case.domain, []).append(r)

        domain_summaries: dict[str, DomainSummary] = {}
        for domain, domain_results in by_domain.items():
            d_total = len(domain_results)
            d_passed = sum(1 for r in domain_results if r.passed)
            d_scores = [r.scores for r in domain_results]
            avg_score = sum(s.overall for s in d_scores) / d_total if d_total else 0.0
            domain_summaries[domain] = DomainSummary(
                domain=domain,
                total_cases=d_total,
                passed=d_passed,
                failed=d_total - d_passed,
                average_score=avg_score,
                dimension_scores=self._aggregate_scores(d_scores),
            )

        # Per-tag breakdown
        by_tag: dict[str, list[TestResult]] = {}
        for r in results:
            for tag in r.test_case.tags:
                by_tag.setdefault(tag, []).append(r)

        tag_summaries: dict[str, TagSummary] = {}
        for tag, tag_results in by_tag.items():
            t_total = len(tag_results)
            t_passed = sum(1 for r in tag_results if r.passed)
            t_scores = [r.scores for r in tag_results]
            avg_score = sum(s.overall for s in t_scores) / t_total if t_total else 0.0
            tag_summaries[tag] = TagSummary(
                tag=tag,
                total_cases=t_total,
                passed=t_passed,
                failed=t_total - t_passed,
                average_score=avg_score,
                dimension_scores=self._aggregate_scores(t_scores),
            )

        failed_cases = [r for r in results if not r.passed]
        overall = by_dimension.overall

        return EvaluationReport(
            overall_score=overall,
            total_cases=total,
            passed=passed,
            failed=failed,
            execution_time_ms=total_time,
            by_dimension=by_dimension,
            by_domain=domain_summaries,
            by_tag=tag_summaries,
            failed_cases=failed_cases,
            all_results=results,
        )

    @staticmethod
    def _aggregate_scores(scores_list: list[ScoreBreakdown]) -> ScoreBreakdown:
        """Aggregate a list of ScoreBreakdown into averages."""
        if not scores_list:
            return ScoreBreakdown()

        n = len(scores_list)
        return ScoreBreakdown(
            intent=sum(s.intent for s in scores_list) / n,
            metric=sum(s.metric for s in scores_list) / n,
            dimension=sum(s.dimension for s in scores_list) / n,
            filter=sum(s.filter for s in scores_list) / n,
            join=sum(s.join for s in scores_list) / n,
            limit=sum(s.limit for s in scores_list) / n,
            order_by=sum(s.order_by for s in scores_list) / n,
            sql_success=sum(s.sql_success for s in scores_list) / n,
            result_accuracy=sum(s.result_accuracy for s in scores_list) / n,
            permission=sum(s.permission for s in scores_list) / n,
            masking=sum(s.masking for s in scores_list) / n,
            audit=sum(s.audit for s in scores_list) / n,
            overall=sum(s.overall for s in scores_list) / n,
        )
