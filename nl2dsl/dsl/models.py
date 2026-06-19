from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class Filter(BaseModel):
    """A filter condition for the WHERE clause (flat list format)."""

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    value: Any = None


class FilterLeaf(Filter):
    """A leaf node in a condition tree -- a single filter condition."""

    pass


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


# Resolve forward references (FilterTreeNode.children references FilterLeaf)
FilterTreeNode.model_rebuild()


class Having(Filter):
    """HAVING clause condition -- references a metric alias."""

    pass


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


class PostProcess(BaseModel):
    """A governed result transformation applied after SQL execution."""

    type: Literal["group_top_n", "proportion"]
    metric: str
    group_by: list[str] | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    direction: Literal["asc", "desc"] = "desc"
    output_field: str | None = None


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
    post_process: PostProcess | None = None

    @staticmethod
    def _coerce_model_list(v, model_class):
        """Coerce a list of dicts to a list of model instances."""
        if v is None:
            return None
        if isinstance(v, list):
            return [
                model_class.model_validate(item) if isinstance(item, dict) else item
                for item in v
            ]
        return v

    @field_validator("filters", mode="before")
    @classmethod
    def _coerce_filters(cls, v):
        """Accept both old flat list and new tree dict."""
        if isinstance(v, dict):
            # Tree format: {"op": "and", "children": [...]}
            return FilterTreeNode.model_validate(v)
        return cls._coerce_model_list(v, Filter)

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
        return cls._coerce_model_list(v, Having)


class ClarificationItem(BaseModel):
    type: str
    question: str
    options: list[str]


class ClarificationResponse(BaseModel):
    status: Literal["clarification"] = "clarification"
    message: str
    items: list[ClarificationItem]
