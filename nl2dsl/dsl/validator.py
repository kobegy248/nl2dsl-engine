import re

from nl2dsl.dsl.models import DSL
from nl2dsl.exceptions import ValidationError


class DSLValidator:
    def __init__(self, registry: dict):
        self._metrics = set(registry.get("metrics", {}).keys())
        self._dimensions = set(registry.get("dimensions", {}).keys())
        self._data_sources = registry.get("data_sources", {})
        self._data_source_names = set(self._data_sources.keys())

    def _reachable_tables(self, ds_cfg: dict) -> set[str]:
        """Tables reachable from a data_source: its primary table plus the
        tables declared in its ``joins`` config (which may themselves chain
        further, but the declared set is what the optimizer/SQLBuilder injects).
        """
        tables = {ds_cfg.get("table", "")}
        joins = ds_cfg.get("joins", {})
        if isinstance(joins, dict):
            tables.update(joins.keys())
        elif isinstance(joins, list):
            for j in joins:
                if isinstance(j, dict) and j.get("table"):
                    tables.add(j["table"])
        tables.discard("")
        return tables

    def _dim_reachable_via_joins(self, dim: str, ds_cfg: dict) -> bool:
        """True if ``dim`` belongs to a data_source whose physical table is
        reachable from ``dsl.data_source`` via declared joins. This allows
        cross-table dimensions (e.g. customer_name via customer_dim) that the
        optimizer (P001) and SQLBuilder resolve with a JOIN.
        """
        reachable = self._reachable_tables(ds_cfg)
        for src_cfg in self._data_sources.values():
            if dim in (src_cfg.get("dimensions") or []):
                if src_cfg.get("table", "") in reachable:
                    return True
        return False

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
                    if d not in ds_dims and not self._dim_reachable_via_joins(d, ds_cfg):
                        errors.append(f"维度 '{d}' 不在数据源 '{dsl.data_source}' 的可用维度列表中")

        # Must have metrics or dimensions
        if not dsl.metrics and not dsl.dimensions:
            errors.append("必须指定 metrics 或 dimensions")

        if dsl.post_process:
            metric_aliases = {m.alias for m in (dsl.metrics or []) if m.alias}
            dimensions = set(dsl.dimensions or [])
            spec = dsl.post_process

            if spec.metric not in metric_aliases:
                errors.append(f"后处理指标 '{spec.metric}' 不在 DSL 输出指标中")

            if spec.type == "group_top_n":
                if not spec.group_by:
                    errors.append("group_top_n 必须指定 group_by")
                else:
                    missing = [field for field in spec.group_by if field not in dimensions]
                    if missing:
                        errors.append(f"group_top_n 分组维度不存在: {missing}")
                if len(dimensions) < 2:
                    errors.append("group_top_n 至少需要两个输出维度")

            if spec.type == "proportion" and not dimensions:
                errors.append("proportion 必须至少指定一个分组维度")

            if spec.output_field and not re.match(
                r"^[A-Za-z_][A-Za-z0-9_]*$", spec.output_field
            ):
                errors.append(f"后处理输出字段名不合法: '{spec.output_field}'")

        if errors:
            raise ValidationError("; ".join(errors))
