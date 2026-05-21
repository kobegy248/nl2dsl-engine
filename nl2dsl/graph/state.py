"""LangGraph state definition for NL2DSL query pipeline."""

from __future__ import annotations

from typing import Annotated
from typing_extensions import TypedDict

from nl2dsl.dsl.models import DSL, ClarificationItem
from nl2dsl.query.sandbox import SandboxResult


def add_to_list(existing: list[dict] | None, new_item: dict | list[dict] | None) -> list[dict] | None:
    """Reducer: append new item to a list field, or return None if new_item is None.

    LangGraph wraps update values in a list before passing to the reducer,
    so new_item may be a list containing the actual dict(s) to append.
    We flatten one level of list wrapping to handle this.
    """
    if new_item is None:
        return existing

    # LangGraph wraps update values in a list; unwrap one level
    if isinstance(new_item, list):
        items_to_add = new_item
    else:
        items_to_add = [new_item]

    if existing is None:
        return list(items_to_add)
    return existing + list(items_to_add)


def add_to_attempts(existing: list[dict] | None, new_attempt: dict | None) -> list[dict] | None:
    """Reducer: append new DSL generation attempt to the attempts list."""
    return add_to_list(existing, new_attempt)


class QueryState(TypedDict):
    # Input fields (set once at start)
    question: str
    user_id: str
    tenant_id: str
    data_source: str | None

    # Intermediate outputs
    ambiguities: list[ClarificationItem] | None
    dsl: DSL | None
    dsl_attempts: Annotated[list[dict] | None, add_to_attempts]
    sql: str | None
    sandbox_result: SandboxResult | None
    complexity: str | None  # "simple" | "complex"

    # Final outputs
    data: list[dict] | None
    status: str  # "pending" | "success" | "clarification" | "warning" | "error" | "pending_review"
    error: str | None
    error_code: str | None
    trace: Annotated[list[dict] | None, add_to_list]

    # Metadata
    query_id: str
    started_at: float
    llm_used: bool
