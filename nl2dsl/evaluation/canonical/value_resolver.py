"""规范化值解析器。"""


class ValueResolver:
    """将维度值别名解析为物理值。"""

    def __init__(self, dimensions_config: dict):
        self._config = dimensions_config

    def resolve(self, dimension: str, value) -> str:
        """将值别名解析为物理值。

        参数：
            dimension: 维度别名
            value: 原始值（可以是别名或物理值）
        """
        cfg = self._config.get(dimension, {})
        value_map = cfg.get("value_map", {})
        if value_map and str(value) in value_map:
            return value_map[str(value)]
        return str(value)
