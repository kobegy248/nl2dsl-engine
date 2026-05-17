from __future__ import annotations

from pydantic import BaseModel
from typing import Any


class RowFilter(BaseModel):
    field: str
    operator: str
    value: list | str | int | None = None


class UserPermission(BaseModel):
    user_id: str
    row_filters: dict[str, RowFilter] | None = None
    allowed_dimensions: list[str] | None = None
    blocked_columns: list[str] | None = None
    tenant_id: str | None = None