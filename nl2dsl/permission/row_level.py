from nl2dsl.dsl.models import DSL, Filter


class RowLevelSecurity:
    def __init__(self, permissions: dict):
        self._permissions = permissions

    def inject(self, dsl: DSL, user_id: str) -> DSL:
        user_perm = self._permissions.get(user_id)
        if not user_perm:
            return dsl

        row_filters = user_perm.get("row_filters", {})
        if not row_filters:
            return dsl

        new_filters = list(dsl.filters or [])
        for field, cfg in row_filters.items():
            new_filters.append(Filter(
                field=field,
                operator=cfg["operator"],
                value=cfg["value"],
            ))

        return dsl.model_copy(update={"filters": new_filters})