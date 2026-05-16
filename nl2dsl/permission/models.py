from pydantic import BaseModel
from typing import Any


class UserPermission(BaseModel):
    row_filters: dict[str, Any] | None = None