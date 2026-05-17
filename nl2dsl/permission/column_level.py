from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import PermissionError


class ColumnLevelSecurity:
    def __init__(
        self,
        sensitive_columns: dict[str, dict] | None = None,
        masking_rules: dict[str, callable] | None = None,
    ):
        self._sensitive = sensitive_columns or {}
        self._masking = masking_rules or {}

    def check(self, dsl: DSL, user_id: str) -> None:
        if not dsl.dimensions:
            return

        for dim in dsl.dimensions:
            if dim in self._sensitive:
                raise PermissionError(f"无权访问敏感字段: {dim}")

    def mask(self, row: dict) -> dict:
        result = dict(row)
        for field, rule in self._masking.items():
            if field in result and result[field] is not None:
                result[field] = rule(result[field])
        return result