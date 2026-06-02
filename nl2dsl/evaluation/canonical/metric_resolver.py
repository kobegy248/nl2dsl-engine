"""规范化指标解析器。"""


class MetricResolver:
    """将指标别名或字段+函数解析为规范化的 metric_id。"""

    def __init__(self, metrics_config: dict):
        """
        参数：
            metrics_config: {metric_id: {expr: "SUM(field)", canonical_id: "..."}}
        """
        self._config = metrics_config
        # 构建反向查找映射：(field, func) -> metric_id
        self._reverse: dict[tuple[str, str], str] = {}
        for mid, cfg in metrics_config.items():
            expr = cfg.get("expr", "")
            # 解析 "SUM(pay_amount)" -> ("sum", "pay_amount")
            if "(" in expr and ")" in expr:
                func = expr.split("(")[0].strip().lower()
                field = expr.split("(")[1].split(")")[0].strip()
                self._reverse[(field, func)] = cfg.get("canonical_id", mid)

    def resolve(self, alias_or_field: str, func: str | None = None) -> str:
        """解析为规范化的 metric_id。

        策略：
        1. 直接别名匹配
        2. 字段+函数反向查找
        3. 兜底返回原始值
        """
        # 1. 直接别名匹配
        if alias_or_field in self._config:
            return self._config[alias_or_field].get("canonical_id", alias_or_field)

        # 2. 字段+函数反向查找
        if func:
            key = (alias_or_field, func.lower())
            if key in self._reverse:
                return self._reverse[key]

        # 3. 兜底
        return alias_or_field
