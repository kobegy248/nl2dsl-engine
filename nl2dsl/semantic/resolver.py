from __future__ import annotations

from nl2dsl.dsl.models import DSL, Filter, Aggregation
from nl2dsl.exceptions import SemanticError


class SemanticResolver:
    def __init__(self, registry: dict):
        self._metrics = registry.get("metrics", {})
        self._dimensions = registry.get("dimensions", {})
        self._data_sources = registry.get("data_sources", {})

    def resolve(self, dsl: DSL) -> DSL:
        new_metrics = self._resolve_metrics(dsl.metrics)
        new_filters = self._resolve_filters(dsl.filters)
        return dsl.model_copy(update={"metrics": new_metrics, "filters": new_filters})

    def _resolve_metrics(self, metrics: list[Aggregation] | None) -> list[Aggregation] | None:
        if not metrics:
            return metrics
        result = []
        for m in metrics:
            expr = self._metrics.get(m.alias, {}).get("expr") if m.alias else None
            if m.alias and not expr:
                raise SemanticError(f"指标 '{m.alias}' 未定义")
            new_m = m.model_copy(update={"field": expr}) if expr else m
            result.append(new_m)
        return result

    def _resolve_filters(self, filters: list[Filter] | None) -> list[Filter] | None:
        if not filters:
            return filters
        result = []
        for f in filters:
            dim = self._dimensions.get(f.field)
            if dim:
                column = dim.get("column", f.field)
                value_map = dim.get("value_map")
                new_value = self._map_value(value_map, f.value) if value_map else f.value
                result.append(f.model_copy(update={"field": column, "value": new_value}))
            else:
                result.append(f)
        return result

    def _map_value(self, value_map: dict, value):
        if isinstance(value, list):
            return [value_map.get(v, v) for v in value]
        return value_map.get(value, value)

    def get_table_name(self, data_source: str) -> str:
        ds = self._data_sources.get(data_source, {})
        return ds.get("table", data_source)
