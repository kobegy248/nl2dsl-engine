"""规范化排序解析器。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalOrderBy:
    """规范化的排序表示。"""

    field: str
    direction: str | None  # "asc" | "desc" | None（默认）
    is_default: bool  # 如果方向非用户显式指定则为 True


class OrderResolver:
    """将排序解析为规范化的表示。"""

    def resolve(self, field: str, direction: str | None, user_expressed: bool = False) -> CanonicalOrderBy:
        """解析排序。

        参数：
            field: 排序字段
            direction: "asc"、"desc" 或 None
            user_expressed: 用户是否明确表达了排序方向
        """
        return CanonicalOrderBy(
            field=field,
            direction=direction.lower() if direction else None,
            is_default=not user_expressed,
        )
