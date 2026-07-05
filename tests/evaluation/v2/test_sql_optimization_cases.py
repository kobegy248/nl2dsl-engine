"""Test cases for the three statistics-driven SQL optimization points (Task 6).

These tests load the V2 evaluation dataset cases that cover:
  - LIKE_INDEXED_001: like prefix match on indexed+high-selectivity column
  - JOIN_SMALL_001:   join small-drives-large reorder
  - FILTER_TYPE_001:  filter value type alignment (numeric column + string value → int)

The V2 evaluation framework scores at the DSL/Planner level and does not support
``sql_contains`` / ``sql_not_contains`` SQL-string assertions.  These tests
therefore verify that:
  1. The dataset cases load with the correct schema.
  2. The cases execute through the real pipeline without error.
  3. The expected DSL fields (filters / planner.joins / planner.time_range) that
     feed the SQL-builder optimizations are present.

The SQL-level optimization correctness (like prefix compilation, join reorder,
string→int type conversion) is verified directly in
``tests/unit/test_sql_builder.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nl2dsl.evaluation.dataset import V2DatasetLoader
from nl2dsl.evaluation.execution import (
    ApiEvaluationExecutor,
    ExecutorConfig,
)
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver

FIXTURES = Path(__file__).resolve().parents[2] / "e2e" / "fixtures"
DATASET_V2 = Path(__file__).resolve().parents[2] / "evaluation" / "dataset" / "v2"


@pytest.fixture(scope="module")
def executor_config() -> ExecutorConfig:
    from tests.e2e.mock_data import create_mock_database

    engine, *_ = create_mock_database("sqlite:///:memory:")
    metrics = yaml.safe_load((FIXTURES / "metrics_test.yaml").read_text(encoding="utf-8"))
    perm = yaml.safe_load((FIXTURES / "permissions_test.yaml").read_text(encoding="utf-8"))
    registry = {
        "metrics": metrics.get("metrics", {}),
        "dimensions": metrics.get("dimensions", {}),
        "data_sources": metrics.get("data_sources", {}),
        "permissions": perm.get("users", {}),
    }
    return ExecutorConfig(
        engine=engine,
        registry_dict=registry,
        permissions=perm.get("users", {}),
        sensitive_columns=perm.get("sensitive_columns", {}),
        masking_rules=perm.get("masking_rules", {}),
        llm_client=None,
    )


def _load_v2_cases():
    return V2DatasetLoader(DATASET_V2).load_all()


def _find_case(case_id: str):
    cases = _load_v2_cases()
    return next(c for c in cases if c.id == case_id)


# =============================================================================
# Case loading + schema validation
# =============================================================================


class TestSqlOptimizationCasesLoad:
    """Verify the three dataset cases load with valid schema."""

    def test_like_indexed_case_loads(self):
        case = _find_case("LIKE_INDEXED_001")
        assert case.query == "2026年7月的销售额"
        assert case.expected["intent"] == "aggregate"
        assert case.expected["metric"] == "sales_amount"
        planner = case.expected.get("planner", {})
        assert planner.get("time_field") == "order_date"
        assert planner.get("time_range") == ["2026-07-01", "2026-07-31"]

    def test_join_small_case_loads(self):
        case = _find_case("JOIN_SMALL_001")
        assert case.query == "按供应商统计销售额"
        assert case.expected["intent"] == "aggregate"
        assert case.expected["metric"] == "sales_amount"
        assert "supplier_name" in (case.expected.get("dimensions") or [])
        planner = case.expected.get("planner", {})
        joins = planner.get("joins") or []
        join_tables = {j.get("table") for j in joins}
        # supplier_dim is the small table that should drive the large order_fact
        assert "supplier_dim" in join_tables
        assert "product_dim" in join_tables

    def test_filter_type_case_loads(self):
        case = _find_case("FILTER_TYPE_001")
        assert case.query == "价格大于100的销售额"
        assert case.expected["intent"] == "aggregate"
        assert case.expected["metric"] == "sales_amount"
        filters = case.expected.get("filters") or []
        assert len(filters) == 1
        assert filters[0]["field"] == "price"
        assert filters[0]["operator"] == ">"
        assert filters[0]["value"] == 100


# =============================================================================
# Pipeline execution (cases don't crash, produce valid DSL)
# =============================================================================


class TestSqlOptimizationCasesExecute:
    """Verify the cases execute through the real pipeline without error."""

    def test_like_indexed_prefix_match_executes(self, executor_config):
        """LIKE_INDEXED_001 exercises the order_date (indexed+high selectivity) path.

        The rule-based generator resolves '2026年7月' into a time_range on
        order_date. The SQL builder applies prefix-match optimization for
        like filters on indexed+high-selectivity columns (verified in
        test_sql_builder.py::test_like_prefix_match_for_indexed_high_selectivity).
        """
        case = _find_case("LIKE_INDEXED_001")
        executor = ApiEvaluationExecutor(executor_config)
        obs = executor.execute(case, generator_mode="rule", optimizer_enabled=False)
        assert obs.status != "error", f"Pipeline error: {obs.error}"

    def test_join_small_drives_large_executes(self, executor_config):
        """JOIN_SMALL_001 exercises the multi-table join path.

        The planner derives joins to supplier_dim (small) via product_dim.
        The SQL builder reorders so small tables drive the large fact table
        (verified in test_sql_builder.py::test_join_reordered_small_drives_large).
        """
        case = _find_case("JOIN_SMALL_001")
        executor = ApiEvaluationExecutor(executor_config)
        obs = executor.execute(case, generator_mode="rule", optimizer_enabled=False)
        assert obs.status != "error", f"Pipeline error: {obs.error}"

    def test_filter_type_alignment_executes(self, executor_config):
        """FILTER_TYPE_001 exercises the numeric filter path on price.

        The rule-based generator produces a numeric filter (price > 100).
        The SQL builder aligns string values to the column's numeric type
        (verified in test_sql_builder.py::test_filter_value_type_aligned_numeric_string_to_int).
        """
        case = _find_case("FILTER_TYPE_001")
        executor = ApiEvaluationExecutor(executor_config)
        obs = executor.execute(case, generator_mode="rule", optimizer_enabled=False)
        assert obs.status != "error", f"Pipeline error: {obs.error}"
