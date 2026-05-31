"""Integration tests for the NL2DSL evaluation framework."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from nl2dsl.api_factory import create_app
from nl2dsl.dsl.models import Aggregation, DSL, Filter, OrderBy
from nl2dsl.evaluation.dataset import DatasetLoader
from nl2dsl.evaluation.models import EvalTestCase, GovernanceInfo, ScoreBreakdown
from nl2dsl.evaluation.report import ReportGenerator
from nl2dsl.evaluation.runner import EvaluationRunner
from nl2dsl.evaluation.scoring import ScoringEngine
from tests.e2e.mock_data import create_mock_database


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_api_client():
    """Create a TestClient with mock ecommerce data."""
    engine, *_ = create_mock_database("sqlite:///:memory:")
    # Load test fixtures
    fixtures_dir = Path(__file__).parent.parent / "e2e" / "fixtures"
    metrics_path = fixtures_dir / "metrics_test.yaml"
    perm_path = fixtures_dir / "permissions_test.yaml"

    import yaml
    with open(metrics_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    registry = {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }

    permissions = {}
    sensitive_columns = {}
    masking_rules = {}
    if perm_path.exists():
        with open(perm_path, "r", encoding="utf-8") as f:
            perm = yaml.safe_load(f)
        permissions = perm.get("users", {})
        sensitive_columns = perm.get("sensitive_columns", {})
        masking_rules = perm.get("masking_rules", {})

    app = create_app(
        engine=engine,
        registry_dict=registry,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    return TestClient(app)


@pytest.fixture
def sample_dataset_dir(tmp_path):
    """Create a temporary dataset directory with test YAML files."""
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()

    # Create ecommerce test file
    eco_dir = dataset_dir / "ecommerce"
    eco_dir.mkdir()
    eco_file = eco_dir / "basic.yaml"
    eco_data = {
        "version": "1.0",
        "domain": "ecommerce",
        "description": "Test ecommerce queries",
        "test_cases": [
            {
                "id": "ec_001",
                "query": "查询销售额",
                "description": "Simple sales query",
                "tags": ["aggregation", "basic"],
                "expected_dsl": {
                    "data_source": "orders",
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                    ],
                    "dimensions": [],
                    "filters": [],
                    "order_by": [],
                    "limit": 10,
                },
            },
            {
                "id": "ec_002",
                "query": "各品类的销售额",
                "description": "Sales by category",
                "tags": ["aggregation", "dimension"],
                "expected_dsl": {
                    "data_source": "orders",
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                    ],
                    "dimensions": ["category"],
                    "filters": [],
                    "order_by": [],
                    "limit": 10,
                },
            },
        ],
    }
    eco_file.write_text(yaml.dump(eco_data, allow_unicode=True), encoding="utf-8")

    # Create bank test file
    bank_dir = dataset_dir / "bank"
    bank_dir.mkdir()
    bank_file = bank_dir / "basic.yaml"
    bank_data = {
        "version": "1.0",
        "domain": "bank",
        "description": "Test bank queries",
        "test_cases": [
            {
                "id": "bank_001",
                "query": "查询客户数量",
                "description": "Customer count",
                "tags": ["count", "basic"],
                "expected_dsl": {
                    "data_source": "customers",
                    "metrics": [
                        {"func": "count", "field": "cif_no", "alias": "customer_count"}
                    ],
                    "dimensions": [],
                    "filters": [],
                    "order_by": [],
                    "limit": 10,
                },
            },
        ],
    }
    bank_file.write_text(yaml.dump(bank_data, allow_unicode=True), encoding="utf-8")

    return dataset_dir


@pytest.fixture
def scoring_engine():
    """Create a default scoring engine."""
    return ScoringEngine()


# =============================================================================
# Dataset Loader Tests
# =============================================================================


class TestDatasetLoader:
    def test_load_all(self, sample_dataset_dir):
        loader = DatasetLoader(sample_dataset_dir)
        cases = loader.load_all()

        assert len(cases) == 3
        assert all(isinstance(c, EvalTestCase) for c in cases)

        # Check IDs
        ids = {c.id for c in cases}
        assert ids == {"ec_001", "ec_002", "bank_001"}

    def test_load_domain(self, sample_dataset_dir):
        loader = DatasetLoader(sample_dataset_dir)
        eco_cases = loader.load_domain("ecommerce")
        bank_cases = loader.load_domain("bank")

        assert len(eco_cases) == 2
        assert len(bank_cases) == 1
        assert all(c.domain == "ecommerce" for c in eco_cases)
        assert all(c.domain == "bank" for c in bank_cases)

    def test_load_nonexistent_domain(self, sample_dataset_dir):
        loader = DatasetLoader(sample_dataset_dir)
        cases = loader.load_domain("nonexistent")
        assert cases == []

    def test_filter_by_tags(self, sample_dataset_dir):
        loader = DatasetLoader(sample_dataset_dir)
        cases = loader.load_all()

        filtered = loader.filter_by_tags(cases, ["basic"])
        assert len(filtered) == 2  # ec_001 and bank_001

        filtered = loader.filter_by_tags(cases, ["dimension"])
        assert len(filtered) == 1  # ec_002

        filtered = loader.filter_by_tags(cases, ["nonexistent"])
        assert len(filtered) == 0


# =============================================================================
# Scoring Engine Tests
# =============================================================================


class TestScoringEngine:
    def test_score_intent_exact_match(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.intent == 1.0

    def test_score_intent_mismatch(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "inventory", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.intent == 0.0

    def test_score_metrics_exact_match(self, scoring_engine):
        expected = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
            ],
        }
        actual = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
            ],
        }
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.metric == 1.0

    def test_score_metrics_wrong_alias(self, scoring_engine):
        expected = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
            ],
        }
        actual = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "revenue"}
            ],
        }
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        # func=0.4 + field=0.4 + alias=0.0 = 0.8, no extra, denom=1
        assert scores.metric == 0.8

    def test_score_metrics_extra_penalty(self, scoring_engine):
        expected = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
            ],
        }
        actual = {
            "data_source": "orders",
            "metrics": [
                {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                {"func": "count", "field": "id", "alias": "order_count"},
            ],
        }
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        # 1.0 / 2 - 0.1 = 0.4
        assert scores.metric == pytest.approx(0.4, abs=0.01)

    def test_score_dimensions_jaccard(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": [], "dimensions": ["a", "b", "c"]}
        actual = {"data_source": "orders", "metrics": [], "dimensions": ["a", "b"]}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        # Jaccard = 2/3
        assert scores.dimension == pytest.approx(2 / 3, abs=0.01)

    def test_score_dimensions_empty_both(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.dimension == 1.0

    def test_score_filters_exact_match(self, scoring_engine):
        expected = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        }
        actual = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        }
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.filter == 1.0

    def test_score_filters_partial_match(self, scoring_engine):
        expected = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        }
        actual = {
            "data_source": "orders",
            "metrics": [],
            "filters": [{"field": "region", "operator": "=", "value": "华南"}],
        }
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        # field=0.4 + operator=0.3 + value=0.0 = 0.7
        assert scores.filter == 0.7

    def test_score_limit_exact_match(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": [], "limit": 10}
        actual = {"data_source": "orders", "metrics": [], "limit": 10}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.limit == 1.0

    def test_score_limit_mismatch(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": [], "limit": 10}
        actual = {"data_source": "orders", "metrics": [], "limit": 50}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.limit == 0.0

    def test_score_limit_default_match(self, scoring_engine):
        """Both None (defaults to 100) should match."""
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.limit == 1.0

    def test_score_sql_success(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql="SELECT 1", error=None)
        assert scores.sql_success == 1.0

    def test_score_sql_failure(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        actual = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, actual, sql=None, error="Some error")
        assert scores.sql_success == 0.0

    def test_score_result_accuracy_with_expected_data(self, scoring_engine):
        expected_data = [{"region": "华东", "sales": 100}]
        actual_data = [{"region": "华东", "sales": 100}]
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            expected_data=expected_data,
            actual_data=actual_data,
        )
        assert scores.result_accuracy == 1.0

    def test_score_result_accuracy_mismatch(self, scoring_engine):
        expected_data = [{"region": "华东", "sales": 100}]
        actual_data = [{"region": "华南", "sales": 200}]
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            expected_data=expected_data,
            actual_data=actual_data,
        )
        # Columns match (same keys) = 0.3, rows differ = 0.0, weighted = 0.3
        assert scores.result_accuracy == 0.3

    def test_score_result_accuracy_no_expected(self, scoring_engine):
        """Without expected_data, result accuracy falls back to heuristic."""
        actual_data = [{"region": "华东", "sales": 100}]
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            actual_data=actual_data,
        )
        assert scores.result_accuracy == 0.5  # Partial credit heuristic

    def test_score_permission_no_sensitive(self, scoring_engine):
        """No sensitive fields involved = permission score is 1.0 (N/A)."""
        gov = GovernanceInfo(sensitive_fields_accessed=[], permission_error=False)
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            governance=gov,
        )
        assert scores.permission == 1.0

    def test_score_permission_blocked(self, scoring_engine):
        """Sensitive fields involved and query blocked = 1.0."""
        gov = GovernanceInfo(
            sensitive_fields_accessed=["phone"],
            permission_error=True,
        )
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql=None,
            error="Permission denied: unauthorized access to sensitive field",
            governance=gov,
        )
        assert scores.permission == 1.0

    def test_score_permission_leaked(self, scoring_engine):
        """Sensitive fields involved but query succeeded = 0.0."""
        gov = GovernanceInfo(
            sensitive_fields_accessed=["phone"],
            permission_error=False,
        )
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT phone FROM users",
            error=None,
            governance=gov,
        )
        assert scores.permission == 0.0

    def test_score_masking_no_sensitive(self, scoring_engine):
        """No sensitive fields = masking score is 1.0 (N/A)."""
        gov = GovernanceInfo(sensitive_fields_accessed=[])
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            governance=gov,
        )
        assert scores.masking == 1.0

    def test_score_masking_properly_masked(self, scoring_engine):
        """Sensitive fields are properly masked = 1.0."""
        gov = GovernanceInfo(
            sensitive_fields_accessed=["phone"],
            masked_fields={"phone": "138****8888"},
        )
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            governance=gov,
        )
        assert scores.masking == 1.0

    def test_score_audit_logged(self, scoring_engine):
        gov = GovernanceInfo(audit_logged=True)
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            governance=gov,
        )
        assert scores.audit == 1.0

    def test_score_audit_not_logged(self, scoring_engine):
        gov = GovernanceInfo(audit_logged=False)
        scores = scoring_engine.score(
            {"data_source": "orders", "metrics": []},
            {"data_source": "orders", "metrics": []},
            sql="SELECT 1",
            error=None,
            governance=gov,
        )
        assert scores.audit == 0.0

    def test_score_none_actual(self, scoring_engine):
        expected = {"data_source": "orders", "metrics": []}
        scores = scoring_engine.score(expected, None, sql=None, error="Error")
        assert scores.sql_success == 0.0
        # Overall includes governance scores: permission(1.0*0.04) + masking(1.0*0.03) + audit(0.0*0.03) = 0.07
        assert scores.overall == pytest.approx(0.07, abs=0.01)

    def test_compute_overall(self, scoring_engine):
        scores = ScoreBreakdown(
            intent=1.0,
            metric=0.8,
            dimension=0.6,
            filter=0.4,
            join=0.2,
            limit=1.0,
            order_by=1.0,
            sql_success=0.9,
            result_accuracy=0.85,
            permission=1.0,
            masking=1.0,
            audit=0.5,
        )
        overall = scoring_engine._compute_overall(scores)
        expected = (
            1.0 * 0.08
            + 0.8 * 0.20
            + 0.6 * 0.12
            + 0.4 * 0.16
            + 0.2 * 0.07
            + 1.0 * 0.04
            + 1.0 * 0.03
            + 0.9 * 0.10
            + 0.85 * 0.10
            + 1.0 * 0.04
            + 1.0 * 0.03
            + 0.5 * 0.03
        )
        assert overall == pytest.approx(expected, abs=0.01)

    def test_category_scores(self, scoring_engine):
        """Test that category score properties work correctly."""
        scores = ScoreBreakdown(
            intent=1.0,
            metric=1.0,
            dimension=1.0,
            filter=1.0,
            join=1.0,
            limit=1.0,
            order_by=1.0,
            sql_success=1.0,
            result_accuracy=1.0,
            permission=1.0,
            masking=1.0,
            audit=1.0,
        )
        assert scores.semantic_score == 1.0
        assert scores.planning_score == 1.0
        assert scores.execution_score == 1.0
        assert scores.governance_score == 1.0

        # Test with some failures
        scores2 = ScoreBreakdown(
            intent=0.0,
            metric=0.0,
            dimension=0.0,
            filter=0.0,
            join=0.0,
            limit=0.0,
            order_by=0.0,
            sql_success=0.0,
            result_accuracy=0.0,
            permission=0.0,
            masking=0.0,
            audit=0.0,
        )
        assert scores2.semantic_score == 0.0
        assert scores2.planning_score == 0.0
        assert scores2.execution_score == 0.0
        assert scores2.governance_score == 0.0


# =============================================================================
# Report Generator Tests
# =============================================================================


class TestReportGenerator:
    def test_generate_json(self, tmp_path):
        from nl2dsl.evaluation.models import EvaluationReport

        report = EvaluationReport(
            overall_score=0.85,
            total_cases=10,
            passed=8,
            failed=2,
        )
        generator = ReportGenerator()
        output = tmp_path / "test.json"
        generator.generate_json(report, output)

        assert output.exists()
        data = output.read_text(encoding="utf-8")
        assert "0.85" in data
        assert "10" in data

    def test_generate_markdown(self, tmp_path):
        from nl2dsl.evaluation.models import EvaluationReport

        report = EvaluationReport(
            overall_score=0.85,
            total_cases=10,
            passed=8,
            failed=2,
            by_dimension=ScoreBreakdown(
                intent=0.9,
                metric=0.8,
                dimension=0.85,
                filter=0.75,
                join=0.9,
                limit=1.0,
                order_by=0.95,
                sql_success=1.0,
                result_accuracy=0.88,
                permission=1.0,
                masking=0.5,
                audit=1.0,
                overall=0.85,
            ),
        )
        generator = ReportGenerator()
        output = tmp_path / "test.md"
        generator.generate_markdown(report, output)

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "85.0%" in content
        assert "Intent" in content
        assert "Metric" in content
        assert "Semantic" in content
        assert "Planning" in content
        assert "Execution" in content
        assert "Governance" in content


# =============================================================================
# End-to-End Evaluation Test
# =============================================================================


class TestEvaluationRunner:
    def test_run_single_with_mock(self, mock_api_client):
        """Test evaluating a single case against the mock API."""
        engine = ScoringEngine()
        runner = EvaluationRunner(
            api_client=mock_api_client,
            scoring_engine=engine,
        )

        case = EvalTestCase(
            id="test_001",
            query="华东2024年1月产品支付金额",
            description="Test",
            domain="ecommerce",
            tags=["basic"],
            expected_dsl={
                "data_source": "orders",
                "metrics": [
                    {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                ],
                "dimensions": [],
                "filters": [
                    {"field": "region", "operator": "=", "value": "华东"},
                ],
                "order_by": [],
                "limit": 10,
            },
        )

        result = runner.run_single(case)

        assert result.test_case.id == "test_001"
        assert result.execution_time_ms >= 0
        # Note: Mock pipeline may return clarification for some queries,
        # so we only verify the runner produces a valid result struct

    def test_run_batch(self, mock_api_client):
        """Test evaluating multiple cases."""
        engine = ScoringEngine()
        runner = EvaluationRunner(
            api_client=mock_api_client,
            scoring_engine=engine,
        )

        cases = [
            EvalTestCase(
                id="test_001",
                query="华东2024年1月产品支付金额",
                description="Test 1",
                domain="ecommerce",
                tags=["basic"],
                expected_dsl={
                    "data_source": "orders",
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                    ],
                    "filters": [
                        {"field": "region", "operator": "=", "value": "华东"},
                    ],
                },
            ),
            EvalTestCase(
                id="test_002",
                query="各品类2024年1月支付金额",
                description="Test 2",
                domain="ecommerce",
                tags=["dimension"],
                expected_dsl={
                    "data_source": "orders",
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                    ],
                    "dimensions": ["category"],
                },
            ),
        ]

        results = runner.run_batch(cases)
        assert len(results) == 2
        # Runner returns results regardless of pipeline status

    def test_generate_report(self, mock_api_client):
        """Test report generation from results."""
        engine = ScoringEngine()
        runner = EvaluationRunner(
            api_client=mock_api_client,
            scoring_engine=engine,
        )

        cases = [
            EvalTestCase(
                id="test_001",
                query="查询销售额",
                description="Test",
                domain="ecommerce",
                tags=["basic"],
                expected_dsl={
                    "data_source": "orders",
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"}
                    ],
                },
            ),
        ]

        results = runner.run_batch(cases)
        report = runner.generate_report(results)

        assert report.total_cases == 1
        assert report.passed + report.failed == 1
        assert report.overall_score >= 0.0
        assert report.overall_score <= 1.0
        assert "ecommerce" in report.by_domain

    def test_governance_collection(self, scoring_engine):
        """Test governance info collection with mock data."""
        gov = GovernanceInfo(
            permission_error=True,
            sensitive_fields_accessed=["phone"],
            masked_fields={"phone": "138****8888"},
            audit_logged=True,
            query_id="test-qid",
        )

        scores = scoring_engine.score(
            expected_dsl={"data_source": "orders", "metrics": [], "dimensions": ["phone"]},
            actual_dsl=None,
            sql=None,
            error="Permission denied",
            governance=gov,
        )

        assert scores.permission == 1.0  # Blocked correctly
        assert scores.masking == 1.0     # Masked properly
        assert scores.audit == 1.0       # Logged


# =============================================================================
# CLI Tests
# =============================================================================


class TestCLI:
    def test_cli_help(self):
        from nl2dsl.evaluation.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_cli_invalid_dataset(self):
        from nl2dsl.evaluation.cli import main

        result = main(["--dataset", "/nonexistent/path"])
        assert result == 1
