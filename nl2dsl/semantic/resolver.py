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
            if expr:
                # Parse expr like "SUM(order_amount)" → func="sum", field="order_amount"
                parsed = self._parse_metric_expr(expr)
                if parsed:
                    func, field = parsed
                    new_m = m.model_copy(update={"func": func, "field": field})
                else:
                    new_m = m.model_copy(update={"field": expr})
            else:
                new_m = m
            result.append(new_m)
        return result

    @staticmethod
    def _parse_metric_expr(expr: str) -> tuple[str, str] | None:
        """Parse a metric expression like 'SUM(order_amount)' into (func, field)."""
        import re

        match = re.match(r"^([A-Z]+)\(\s*(?:DISTINCT\s+)?(.+?)\s*\)$", expr.strip(), re.IGNORECASE)
        if match:
            return match.group(1).lower(), match.group(2)
        return None

    def _resolve_filters(self, filters: list[Filter] | None) -> list[Filter] | None:
        if not filters:
            return filters
        result = []
        for f in filters:
            dim = self._dimensions.get(f.field)
            if dim:
                # Keep the semantic field name in DSL; SQLBuilder will map to physical column
                value_map = dim.get("value_map")
                new_value = self._map_value(value_map, f.value) if value_map else f.value
                result.append(f.model_copy(update={"value": new_value}))
            else:
                result.append(f)
        return result

    def _map_value(self, value_map: dict, value):
        """Map filter values. Preserves semantic values if they exist in the map keys.

        The test DSL expects business semantic values (e.g. "华东", "线上"),
        not internal database codes (e.g. "HD", "online").
        """
        if isinstance(value, list):
            return [self._map_single_value(value_map, v) for v in value]
        return self._map_single_value(value_map, value)

    @staticmethod
    def _map_single_value(value_map: dict, value):
        # If the value is already a semantic key in the map, keep it as-is
        if value in value_map:
            return value
        # Otherwise return the value unchanged (don't map to internal codes)
        return value

    def get_table_name(self, data_source: str) -> str:
        ds = self._data_sources.get(data_source, {})
        return ds.get("table", data_source)
