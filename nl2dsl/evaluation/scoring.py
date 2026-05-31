"""Scoring engine for evaluating DSL accuracy."""

from __future__ import annotations

from typing import Any

from nl2dsl.dsl.models import Aggregation, DSL, Filter, Join, OrderBy
from nl2dsl.evaluation.models import GovernanceInfo, ScoreBreakdown
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.scoring")

# Default weights for composite score (12 dimensions, sum = 1.0)
DEFAULT_WEIGHTS: dict[str, float] = {
    # Semantic (56%)
    "intent": 0.08,
    "metric": 0.20,
    "dimension": 0.12,
    "filter": 0.16,
    # Planning (14%)
    "join": 0.07,
    "limit": 0.04,
    "order_by": 0.03,
    # Execution (20%)
    "sql_success": 0.10,
    "result_accuracy": 0.10,
    # Governance (10%)
    "permission": 0.04,
    "masking": 0.03,
    "audit": 0.03,
}


class ScoringEngine:
    """Engine for scoring DSL predictions against expected DSL.

    Scores across 12 dimensions grouped into 4 categories:

    Semantic:
    - intent: data_source match (0 or 1)
    - metric: metrics accuracy (func + field + alias)
    - dimension: dimensions accuracy (Jaccard similarity)
    - filter: filters accuracy (field + operator + value)

    Planning:
    - join: joins accuracy (table + on_field + join_type)
    - limit: limit accuracy (exact match)
    - order_by: order_by accuracy (sequence-aware)

    Execution:
    - sql_success: SQL execution success (0 or 1)
    - result_accuracy: query result data accuracy (0~1)

    Governance:
    - permission: permission check effectiveness (0 or 1)
    - masking: sensitive data masking (0 or 1)
    - audit: audit logging (0 or 1)
    """

    def __init__(self, weights: dict[str, float] | None = None, threshold: float = 0.8):
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.threshold = threshold

    def score(
        self,
        expected_dsl: dict[str, Any],
        actual_dsl: dict[str, Any] | None,
        sql: str | None,
        error: str | None,
        actual_data: list[dict] | None = None,
        expected_data: list[dict] | None = None,
        governance: GovernanceInfo | None = None,
    ) -> ScoreBreakdown:
        """Score a single prediction against the expected DSL.

        Args:
            expected_dsl: The ground-truth DSL dict.
            actual_dsl: The predicted DSL dict (may be None on failure).
            sql: The generated SQL string.
            error: Error message if pipeline failed.
            actual_data: Actual query result rows.
            expected_data: Expected query result rows (from executing expected DSL).
            governance: Governance metadata.

        Returns:
            ScoreBreakdown with per-dimension and overall scores.
        """
        scores = ScoreBreakdown()
        gov = governance or GovernanceInfo()

        if actual_dsl is None:
            # Complete failure -- only SQL success matters (0 if error)
            scores.sql_success = 1.0 if sql and not error else 0.0
            # Governance scores can still be evaluated
            scores.permission = self._score_permission(gov, expected_dsl)
            scores.masking = self._score_masking(gov, actual_data)
            scores.audit = self._score_audit(gov)
            scores.overall = self._compute_overall(scores)
            return scores

        # Parse DSL objects for comparison
        try:
            expected = DSL.model_validate(expected_dsl)
            actual = DSL.model_validate(actual_dsl)
        except Exception as exc:
            logger.warning("DSL validation failed during scoring: %s", exc)
            scores.sql_success = 1.0 if sql and not error else 0.0
            scores.permission = self._score_permission(gov, expected_dsl)
            scores.masking = self._score_masking(gov, actual_data)
            scores.audit = self._score_audit(gov)
            scores.overall = self._compute_overall(scores)
            return scores

        # Semantic dimensions
        scores.intent = self._score_intent(expected, actual)
        scores.metric = self._score_metrics(expected.metrics, actual.metrics)
        scores.dimension = self._score_dimensions(expected.dimensions, actual.dimensions)
        scores.filter = self._score_filters(expected.filters, actual.filters)

        # Planning dimensions
        scores.join = self._score_joins(expected.joins, actual.joins)
        scores.limit = self._score_limit(expected.limit, actual.limit)
        scores.order_by = self._score_order_by(expected.order_by, actual.order_by)

        # Execution dimensions
        scores.sql_success = 1.0 if sql and not error else 0.0
        scores.result_accuracy = self._score_result_accuracy(expected_data, actual_data)

        # Governance dimensions
        scores.permission = self._score_permission(gov, expected_dsl)
        scores.masking = self._score_masking(gov, actual_data)
        scores.audit = self._score_audit(gov)

        scores.overall = self._compute_overall(scores)
        return scores

    def is_passed(self, scores: ScoreBreakdown) -> bool:
        """Return True if the overall score meets the passing threshold."""
        return scores.overall >= self.threshold

    # ------------------------------------------------------------------
    # Semantic scorers
    # ------------------------------------------------------------------

    def _score_intent(self, expected: DSL, actual: DSL) -> float:
        """Score data_source match. Exact match = 1.0, else 0.0."""
        return 1.0 if expected.data_source == actual.data_source else 0.0

    def _score_metrics(
        self,
        expected: list[Aggregation] | None,
        actual: list[Aggregation] | None,
    ) -> float:
        """Score metric accuracy.

        Exact match requires func + field + alias to all match.
        Partial credit: correct func+field but wrong alias = 0.8.
        Extra metrics incur a 0.1 penalty each.
        """
        e_list = expected or []
        a_list = actual or []

        if not e_list and not a_list:
            return 1.0
        if not e_list or not a_list:
            return 0.0

        total = 0.0
        for em in e_list:
            best = 0.0
            for am in a_list:
                score = 0.0
                if em.func == am.func:
                    score += 0.4
                if em.field == am.field:
                    score += 0.4
                if em.alias == am.alias:
                    score += 0.2
                best = max(best, score)
            total += best

        extra = max(0, len(a_list) - len(e_list))
        denominator = max(len(e_list), len(a_list))
        return max(0.0, total / denominator - extra * 0.1)

    def _score_dimensions(
        self,
        expected: list[str] | None,
        actual: list[str] | None,
    ) -> float:
        """Score dimension accuracy using Jaccard similarity."""
        e_set = set(expected or [])
        a_set = set(actual or [])

        if not e_set and not a_set:
            return 1.0

        union = e_set | a_set
        if not union:
            return 1.0

        return len(e_set & a_set) / len(union)

    def _score_filters(
        self,
        expected: list[Filter] | Any | None,
        actual: list[Filter] | Any | None,
    ) -> float:
        """Score filter accuracy.

        Matches on field + operator + value with partial credit:
        - field match = 0.4
        - operator match = 0.3
        - value match = 0.3

        Handles both flat list and FilterTreeNode (treats tree as flat for scoring).
        """
        # Flatten FilterTreeNode to list of Filter
        e_list = self._flatten_filters(expected)
        a_list = self._flatten_filters(actual)

        if not e_list and not a_list:
            return 1.0
        if not e_list or not a_list:
            return 0.0

        total = 0.0
        for ef in e_list:
            best = 0.0
            for af in a_list:
                score = 0.0
                if ef.field == af.field:
                    score += 0.4
                if ef.operator == af.operator:
                    score += 0.3
                if self._values_equal(ef.value, af.value):
                    score += 0.3
                best = max(best, score)
            total += best

        extra = max(0, len(a_list) - len(e_list))
        denominator = max(len(e_list), len(a_list))
        return max(0.0, total / denominator - extra * 0.1)

    # ------------------------------------------------------------------
    # Planning scorers
    # ------------------------------------------------------------------

    def _score_joins(
        self,
        expected: list[Join] | None,
        actual: list[Join] | None,
    ) -> float:
        """Score join accuracy.

        Matches on table + on_field + join_type.
        Alias is optional (0.1 bonus if matched).
        """
        e_list = expected or []
        a_list = actual or []

        if not e_list and not a_list:
            return 1.0
        if not e_list or not a_list:
            return 0.0

        total = 0.0
        for ej in e_list:
            best = 0.0
            for aj in a_list:
                score = 0.0
                if ej.table == aj.table:
                    score += 0.4
                if ej.on_field == aj.on_field:
                    score += 0.3
                if ej.join_type == aj.join_type:
                    score += 0.2
                if ej.alias and aj.alias and ej.alias == aj.alias:
                    score += 0.1
                best = max(best, score)
            total += best

        extra = max(0, len(a_list) - len(e_list))
        denominator = max(len(e_list), len(a_list))
        return max(0.0, total / denominator - extra * 0.1)

    def _score_limit(self, expected: int | None, actual: int | None) -> float:
        """Score limit accuracy. Exact match = 1.0, else 0.0.

        Both expected and actual being None (or default 100) = 1.0.
        """
        # Normalize defaults: None -> 100 (DSL default)
        e_val = expected if expected is not None else 100
        a_val = actual if actual is not None else 100
        return 1.0 if e_val == a_val else 0.0

    def _score_order_by(
        self,
        expected: list[OrderBy] | None,
        actual: list[OrderBy] | None,
    ) -> float:
        """Score order_by accuracy.

        Sequence-aware: matches in order, with field + direction check.
        Missing/extra entries penalized.
        """
        e_list = expected or []
        a_list = actual or []

        if not e_list and not a_list:
            return 1.0
        if not e_list or not a_list:
            return 0.0

        total = 0.0
        max_len = max(len(e_list), len(a_list))
        for i in range(max_len):
            if i >= len(e_list) or i >= len(a_list):
                break
            eo = e_list[i]
            ao = a_list[i]
            score = 0.0
            if eo.field == ao.field:
                score += 0.6
            if eo.direction == ao.direction:
                score += 0.4
            total += score

        missing = max(0, len(e_list) - len(a_list))
        extra = max(0, len(a_list) - len(e_list))
        penalty = (missing + extra) * 0.2
        denominator = max_len
        return max(0.0, total / denominator - penalty)

    # ------------------------------------------------------------------
    # Execution scorers
    # ------------------------------------------------------------------

    def _score_result_accuracy(
        self,
        expected_data: list[dict] | None,
        actual_data: list[dict] | None,
    ) -> float:
        """Score result data accuracy by comparing expected vs actual rows.

        Returns 1.0 if data matches, 0.0 if completely different.
        If expected_data is not available, falls back to checking if actual_data
        has the expected structure (non-empty when SQL succeeded).
        """
        # If no expected data available, use heuristic:
        # SQL succeeded and returned some data = partial credit
        if expected_data is None:
            if actual_data is not None and len(actual_data) > 0:
                return 0.5  # Partial: we got data but can't verify accuracy
            if actual_data is not None and len(actual_data) == 0:
                return 0.0  # Empty result
            return 0.0  # No data at all

        # If actual data is missing but expected exists
        if actual_data is None:
            return 0.0

        # Compare row counts first
        if len(expected_data) == 0 and len(actual_data) == 0:
            return 1.0
        if len(expected_data) == 0 or len(actual_data) == 0:
            return 0.0

        # Compare column names
        expected_cols = set(expected_data[0].keys()) if expected_data else set()
        actual_cols = set(actual_data[0].keys()) if actual_data else set()
        col_jaccard = len(expected_cols & actual_cols) / len(expected_cols | actual_cols) if (expected_cols | actual_cols) else 1.0

        # Compare row-level data (allow reordering)
        # Convert rows to comparable tuples
        def _row_key(row: dict) -> tuple:
            """Create a sortable tuple from a row dict."""
            return tuple(sorted((str(k), str(v)) for k, v in row.items()))

        expected_rows = {_row_key(r) for r in expected_data}
        actual_rows = {_row_key(r) for r in actual_data}

        if not expected_rows and not actual_rows:
            row_score = 1.0
        elif not expected_rows or not actual_rows:
            row_score = 0.0
        else:
            row_score = len(expected_rows & actual_rows) / max(len(expected_rows), len(actual_rows))

        # Weight: column match 30%, row match 70%
        return col_jaccard * 0.3 + row_score * 0.7

    # ------------------------------------------------------------------
    # Governance scorers
    # ------------------------------------------------------------------

    def _score_permission(
        self,
        gov: GovernanceInfo,
        expected_dsl: dict[str, Any] | None = None,
    ) -> float:
        """Score permission check effectiveness.

        If sensitive fields are in expected DSL and query was blocked = 1.0.
        If sensitive fields are in expected DSL and query succeeded = 0.0.
        No sensitive fields involved = 1.0 (not applicable).
        """
        sensitive = gov.sensitive_fields_accessed

        if not sensitive:
            # No sensitive fields involved -- permission check not tested
            return 1.0

        # Sensitive fields were involved
        if gov.permission_error:
            # Permission check correctly blocked access
            return 1.0

        # Sensitive fields accessed but no permission error = leak
        return 0.0

    def _score_masking(
        self,
        gov: GovernanceInfo,
        actual_data: list[dict] | None,
    ) -> float:
        """Score data masking effectiveness.

        Checks if sensitive fields in the result are properly masked.
        Returns 1.0 if all sensitive fields are masked, 0.0 if any are exposed.
        """
        if not gov.sensitive_fields_accessed:
            # No sensitive fields in result
            return 1.0

        if not actual_data:
            # No data returned, masking not applicable
            return 1.0

        # Check if all sensitive fields were properly masked
        # A field is considered masked if it's in gov.masked_fields
        # or if all values for that field across rows are identical (simple heuristic)
        masked = set(gov.masked_fields.keys())
        sensitive = set(gov.sensitive_fields_accessed)

        if not sensitive:
            return 1.0

        # All sensitive fields must be in masked set
        if sensitive.issubset(masked):
            return 1.0

        # Partial masking: some fields masked, some not
        masked_count = len(sensitive & masked)
        return masked_count / len(sensitive)

    def _score_audit(self, gov: GovernanceInfo) -> float:
        """Score audit logging.

        Returns 1.0 if the query was recorded in the audit log, 0.0 otherwise.
        """
        return 1.0 if gov.audit_logged else 0.0

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------

    def _compute_overall(self, scores: ScoreBreakdown) -> float:
        """Compute weighted composite score."""
        return (
            scores.intent * self.weights.get("intent", 0.0)
            + scores.metric * self.weights.get("metric", 0.0)
            + scores.dimension * self.weights.get("dimension", 0.0)
            + scores.filter * self.weights.get("filter", 0.0)
            + scores.join * self.weights.get("join", 0.0)
            + scores.limit * self.weights.get("limit", 0.0)
            + scores.order_by * self.weights.get("order_by", 0.0)
            + scores.sql_success * self.weights.get("sql_success", 0.0)
            + scores.result_accuracy * self.weights.get("result_accuracy", 0.0)
            + scores.permission * self.weights.get("permission", 0.0)
            + scores.masking * self.weights.get("masking", 0.0)
            + scores.audit * self.weights.get("audit", 0.0)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_filters(filters: list[Filter] | Any | None) -> list[Filter]:
        """Flatten FilterTreeNode or list into a flat list of Filter."""
        if filters is None:
            return []
        if isinstance(filters, list):
            return [f for f in filters if isinstance(f, Filter)]
        # FilterTreeNode: recursively extract children
        from nl2dsl.dsl.models import FilterTreeNode

        if isinstance(filters, FilterTreeNode):
            result: list[Filter] = []
            for child in filters.children:
                if isinstance(child, Filter):
                    result.append(child)
                elif isinstance(child, FilterTreeNode):
                    result.extend(ScoringEngine._flatten_filters(child))
            return result
        return []

    @staticmethod
    def _values_equal(a: Any, b: Any) -> bool:
        """Compare two filter values, handling lists."""
        if a == b:
            return True
        # Handle list comparison regardless of order
        if isinstance(a, list) and isinstance(b, list):
            return set(str(x) for x in a) == set(str(x) for x in b)
        # Handle numeric string vs number comparison
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return False
