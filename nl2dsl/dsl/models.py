from typing import Any, Literal
from pydantic import BaseModel, Field


class Filter(BaseModel):
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


class DSL(BaseModel):
    metrics: list[Aggregation] | None = None
    dimensions: list[str] | None = None
    filters: list[Filter] | None = None
    order_by: list[OrderBy] | None = None
    limit: int | None = Field(default=100, le=10000)
    offset: int | None = Field(default=0, ge=0)
    data_source: str
    time_field: str | None = None
    time_range: tuple[str, str] | None = None
