from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import ValidationError


class DSLValidator:
    def __init__(self, registry: dict):
        self._metrics = set(registry.get("metrics", {}).keys())
        self._dimensions = set(registry.get("dimensions", {}).keys())
        self._data_sources = registry.get("data_sources", {})
        self._data_source_names = set(self._data_sources.keys())

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

        # Check dimensions (global registry)
        if dsl.dimensions:
            for d in dsl.dimensions:
                if d not in self._dimensions:
                    errors.append(f"维度 '{d}' 不存在")

        # Check metrics/dimensions belong to the current data_source
        ds_cfg = self._data_sources.get(dsl.data_source)
        if ds_cfg:
            ds_metrics = set(ds_cfg.get("metrics", []))
            ds_dims = set(ds_cfg.get("dimensions", []))

            if dsl.metrics:
                for m in dsl.metrics:
                    if m.alias and m.alias not in ds_metrics:
                        errors.append(f"指标 '{m.alias}' 不在数据源 '{dsl.data_source}' 的可用指标列表中")

            if dsl.dimensions:
                for d in dsl.dimensions:
                    if d not in ds_dims:
                        errors.append(f"维度 '{d}' 不在数据源 '{dsl.data_source}' 的可用维度列表中")

        # Must have metrics or dimensions
        if not dsl.metrics and not dsl.dimensions:
            errors.append("必须指定 metrics 或 dimensions")

        if errors:
            raise ValidationError("; ".join(errors))
