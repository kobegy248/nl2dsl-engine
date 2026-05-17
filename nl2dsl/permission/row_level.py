from nl2dsl.dsl.models import DSL, Filter


class RowLevelSecurity:
    def __init__(self, permissions: dict):
        self._permissions = permissions

    def inject(self, dsl: DSL, user_id: str) -> DSL:
        user_perm = self._permissions.get(user_id)
        if not user_perm:
            return dsl

        new_filters = list(dsl.filters or [])

        # 行级过滤
        row_filters = user_perm.get("row_filters", {})
        for field, cfg in row_filters.items():
            new_filters.append(Filter(
                field=field,
                operator=cfg["operator"],
                value=cfg["value"],
            ))

        # 租户隔离
        tenant_id = user_perm.get("tenant_id")
        if tenant_id:
            new_filters.append(Filter(
                field="tenant_id",
                operator="=",
                value=tenant_id,
            ))

        if not new_filters:
            return dsl
        return dsl.model_copy(update={"filters": new_filters})