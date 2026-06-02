"""Pydantic models for the NL2DSL evaluation framework."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvalTestCase(BaseModel):
    """A single evaluation test case."""

    id: str
    query: str
    description: str
    domain: str
    tags: list[str] = Field(default_factory=list)
    expected_dsl: dict[str, Any]


class ScoreBreakdown(BaseModel):
    """Scores for each evaluation dimension.

    Dimensions are grouped into 4 categories:
    - Semantic: intent, metric, dimension, filter
    - Planning: join, limit, order_by
    - Execution: sql_success, result_accuracy
    - Governance: permission, masking, audit
    """

    # Semantic
    intent: float = 0.0           # data_source match
    metric: float = 0.0           # metrics accuracy
    dimension: float = 0.0        # dimensions accuracy (Jaccard)
    filter: float = 0.0           # filters accuracy

    # Planning
    join: float = 0.0             # joins accuracy
    limit: float = 0.0            # limit accuracy (NEW)
    order_by: float = 0.0         # order_by accuracy

    # Execution
    sql_success: float = 0.0      # 1.0 if SQL executes, 0.0 otherwise
    result_accuracy: float = 0.0  # data result accuracy (NEW)

    # Governance
    permission: float = 0.0       # permission check (NEW)
    masking: float = 0.0          # data masking (NEW)
    audit: float = 0.0            # audit logging (NEW)

    overall: float = 0.0          # weighted composite

    @property
    def semantic_score(self) -> float:
        """Weighted Semantic category score."""
        return (
            self.intent * 0.08
            + self.metric * 0.20
            + self.dimension * 0.12
            + self.filter * 0.16
        ) / 0.56

    @property
    def planning_score(self) -> float:
        """Weighted Planning category score."""
        total = 0.07 + 0.04 + 0.03
        if total == 0:
            return 1.0
        return (
            self.join * 0.07
            + self.limit * 0.04
            + self.order_by * 0.03
        ) / total

    @property
    def execution_score(self) -> float:
        """Weighted Execution category score."""
        total = 0.10 + 0.10
        if total == 0:
            return 1.0
        return (
            self.sql_success * 0.10
            + self.result_accuracy * 0.10
        ) / total

    @property
    def governance_score(self) -> float:
        """Weighted Governance category score."""
        total = 0.04 + 0.03 + 0.03
        if total == 0:
            return 1.0
        return (
            self.permission * 0.04
            + self.masking * 0.03
            + self.audit * 0.03
        ) / total


class GovernanceInfo(BaseModel):
    """Governance metadata collected during evaluation."""

    permission_error: bool = False          # API returned permission error
    sensitive_fields_accessed: list[str] = Field(default_factory=list)
    masked_fields: dict[str, str] = Field(default_factory=dict)  # field -> masked_value
    audit_logged: bool = False              # query was recorded in audit log
    query_id: str | None = None             # audit query_id if available


class TestResult(BaseModel):
    """Result of evaluating a single test case."""

    test_case: EvalTestCase
    passed: bool = False
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    actual_dsl: dict[str, Any] | None = None
    actual_sql: str | None = None
    actual_data: list[dict] | None = None   # actual query result data (NEW)
    expected_data: list[dict] | None = None # expected query result data (NEW)
    governance: GovernanceInfo = Field(default_factory=GovernanceInfo)
    error: str | None = None
    execution_time_ms: int = 0


class DomainSummary(BaseModel):
    """Summary statistics for a single domain."""

    domain: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0
    dimension_scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class TagSummary(BaseModel):
    """Summary statistics for a single tag."""

    tag: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0
    dimension_scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class EvaluationReport(BaseModel):
    """Complete evaluation report."""

    overall_score: float = 0.0
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    execution_time_ms: int = 0
    by_dimension: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    by_domain: dict[str, DomainSummary] = Field(default_factory=dict)
    by_tag: dict[str, TagSummary] = Field(default_factory=dict)
    failed_cases: list[TestResult] = Field(default_factory=list)
    all_results: list[TestResult] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# --- V2 Models (Semantic Understanding Benchmark) ---

from dataclasses import dataclass, field


@dataclass
class CanonicalQuery:
    """查询的规范化语义表示。"""

    intent: str = ""
    metric: str = ""
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    planner: dict = field(default_factory=dict)
    clarification_required: bool = False
    governance: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class V2TestCase:
    """V2 评测用例。"""

    id: str
    query: str
    difficulty: str = "easy"
    category: str = "basic"
    tags: list[str] = field(default_factory=list)
    expected: dict = field(default_factory=dict)


@dataclass
class V2ScoreBreakdown:
    """V2 评分明细。"""

    intent: float = 0.0
    metric: float = 0.0
    filter: float = 0.0
    planner: float = 0.0
    governance: float = 0.0
    overall: float = 0.0

    def compute_overall(self, weights: dict[str, float]) -> float:
        """计算加权总分。"""
        return (
            self.intent * weights.get("intent", 0.0)
            + self.metric * weights.get("metric", 0.0)
            + self.filter * weights.get("filter", 0.0)
            + self.planner * weights.get("planner", 0.0)
            + self.governance * weights.get("governance", 0.0)
        )
