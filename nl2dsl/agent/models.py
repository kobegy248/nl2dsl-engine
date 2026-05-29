"""Data models for the Agent orchestration layer."""

from __future__ import annotations

from pydantic import BaseModel
from typing_extensions import TypedDict


class SubQuery(BaseModel):
    """A single sub-query within a Plan."""

    id: str
    dsl: dict | None = None
    depends_on: list[str] = []
    description: str


class Plan(BaseModel):
    """Execution plan produced by the planner node."""

    intent: str
    sub_queries: list[SubQuery]
    reasoning: str
    requires_approval: bool = False


class QueryResult(BaseModel):
    """Result of executing a single sub-query."""

    sub_query_id: str
    data: list[dict]
    status: str = "success"
    error: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.data)


class AgentResult(BaseModel):
    """Final result returned by AgentOrchestrator."""

    status: str
    data: list[dict] | None = None
    explanation: str | None = None
    confidence: float | None = None
    plan: Plan | None = None
    error: str | None = None


class AgentState(TypedDict):
    """Internal state for Agent orchestration (used by AgentOrchestrator)."""

    question: str
    user_id: str
    tenant_id: str
    domain: str

    plan: Plan | None
    sub_results: dict[str, QueryResult]
    final_result: dict | None

    confidence: float
    explanation: str | None
    status: str  # "planning" | "executing" | "aggregating" | "done" | "error"
    trace: list[dict]
