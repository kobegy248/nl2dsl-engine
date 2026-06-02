"""规范化维度解析器。"""


class DimensionResolver:
    """将维度别名解析为物理列名。"""

    def __init__(self, dimensions_config: dict):
        self._config = dimensions_config

    def resolve(self, alias: str) -> str:
        """将维度别名解析为物理列名。"""
        cfg = self._config.get(alias, {})
        return cfg.get("column", alias)

    def get_value_map(self, alias: str) -> dict | None:
        """获取维度的值映射（如果存在）。"""
        cfg = self._config.get(alias, {})
        return cfg.get("value_map")
