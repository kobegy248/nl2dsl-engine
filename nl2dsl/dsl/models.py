from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class Filter(BaseModel):
    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class FilterLeaf(BaseModel):
    """A leaf node in a condition tree -- a single filter condition."""

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class FilterTreeNode(BaseModel):
    """A node in a condition tree (and / or / not)."""

    op: Literal["and", "or", "not"]
    children: list["FilterLeaf | FilterTreeNode"]

    @field_validator("children", mode="before")
    @classmethod
    def _coerce_children(cls, v):
        if v is None:
            return []
        return v


FilterTreeNode.model_rebuild()


class Having(BaseModel):
    """HAVING clause condition -- references a metric alias."""

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class OrderBy(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class Aggregation(BaseModel):
    func: Literal["sum", "avg", "count", "min", "max"]
    field: str
    alias: str | None = None


class Join(BaseModel):
    table: str
    on_field: str
    join_type: Literal["inner", "left", "right"] = "inner"
    alias: str | None = None


class DSL(BaseModel):
    metrics: list[Aggregation] | None = None
    dimensions: list[str] | None = None
    filters: list[Filter] | FilterTreeNode | None = None
    having: list[Having] | None = None
    order_by: list[OrderBy] | None = None
    limit: int | None = Field(default=100, le=10000)
    offset: int | None = Field(default=0, ge=0)
    data_source: str
    time_field: str | None = None
    time_range: tuple[str, str] | None = None
    joins: list[Join] | None = None

    @field_validator("filters", mode="before")
    @classmethod
    def _coerce_filters(cls, v):
        """Accept both old flat list and new tree dict."""
        if v is None:
            return None
        if isinstance(v, dict):
            # Tree format: {"op": "and", "children": [...]}
            return FilterTreeNode.model_validate(v)
        if isinstance(v, list):
            # Old flat list format
            return [
                Filter.model_validate(item) if isinstance(item, dict) else item
                for item in v
            ]
        return v

    @field_validator("time_range", mode="before")
    @classmethod
    def _coerce_time_range(cls, v):
        """Accept list or tuple for time_range."""
        if v is None:
            return None
        if isinstance(v, list) and len(v) == 2:
            return tuple(v)
        return v

    @field_validator("having", mode="before")
    @classmethod
    def _coerce_having(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return [
                Having.model_validate(item) if isinstance(item, dict) else item
                for item in v
            ]
        return v


class ClarificationItem(BaseModel):
    type: str
    question: str
    options: list[str]


class ClarificationResponse(BaseModel):
    status: Literal["clarification"] = "clarification"
    message: str
    items: list[ClarificationItem]
