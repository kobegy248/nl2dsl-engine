from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import ValidationError


class DSLValidator:
    def __init__(self, registry: dict):
        self._metrics = set(registry.get("metrics", {}).keys())
        self._dimensions = set(registry.get("dimensions", {}).keys())
        self._data_sources = set(registry.get("data_sources", {}).keys())

    def validate(self, dsl: DSL) -> None:
        errors = []

        # Check data_source
        if dsl.data_source not in self._data_sources:
            errors.append(f"数据源 '{dsl.data_source}' 不存在")

        # Check metrics
        if dsl.metrics:
            for m in dsl.metrics:
                if m.alias and m.alias not in self._metrics:
                    errors.append(f"指标 '{m.alias}' 不存在")

        # Check dimensions
        if dsl.dimensions:
            for d in dsl.dimensions:
                if d not in self._dimensions:
                    errors.append(f"维度 '{d}' 不存在")

        # Must have metrics or dimensions
        if not dsl.metrics and not dsl.dimensions:
            errors.append("必须指定 metrics 或 dimensions")

        if errors:
            raise ValidationError("; ".join(errors))
