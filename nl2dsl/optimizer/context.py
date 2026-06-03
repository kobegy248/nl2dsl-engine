"""Rule execution context and semantic configuration wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SemanticConfig:
    """Typed wrapper around the semantic layer configuration.

    Loaded from metrics.yaml / dimensions.yaml. Provides lookup
    methods for rules to query without touching raw dicts.
    """

    metrics: dict = field(default_factory=dict)
    """{metric_id: {expr, description, canonical_id, data_source, ...}}"""

    dimensions: dict = field(default_factory=dict)
    """{dimension_id: {column, description, value_map, data_source, type, ...}}"""

    data_sources: dict = field(default_factory=dict)
    """{source_name: {table, metrics: [...], dimensions: [...], joins: [...]}}"""

    @classmethod
    def from_registry_dict(cls, registry: dict) -> SemanticConfig:
        """Build from the raw dict returned by SemanticRegistry.load()."""
        return cls(
            metrics=registry.get("metrics", {}),
            dimensions=registry.get("dimensions", {}),
            data_sources=registry.get("data_sources", {}),
        )

    def has_metric(self, name: str) -> bool:
        return name in self.metrics

    def has_dimension(self, name: str) -> bool:
        return name in self.dimensions

    def has_data_source(self, name: str) -> bool:
        return name in self.data_sources

    def get_metric_field(self, name: str) -> str | None:
        """Get the physical field name for a metric from its expr."""
        m = self.metrics.get(name, {})
        expr = m.get("expr", "")
        if "(" in expr and ")" in expr:
            return expr.split("(")[1].split(")")[0].strip()
        return None

    def get_metric_func(self, name: str) -> str | None:
        """Get the aggregation function for a metric from its expr."""
        m = self.metrics.get(name, {})
        expr = m.get("expr", "")
        if "(" in expr:
            return expr.split("(")[0].strip().lower()
        return None

    def get_dimension_column(self, name: str) -> str | None:
        """Get the physical column for a dimension."""
        d = self.dimensions.get(name, {})
        return d.get("column")

    def get_dimension_type(self, name: str) -> str:
        """Get the data type of a dimension (string, integer, boolean, date)."""
        d = self.dimensions.get(name, {})
        return d.get("type", "string")

    def get_value_map(self, dimension: str) -> dict | None:
        """Get the value_map for a dimension if it exists."""
        d = self.dimensions.get(dimension, {})
        return d.get("value_map")

    def get_values(self, dimension: str) -> list | None:
        """Get the allowed values list for a dimension."""
        d = self.dimensions.get(dimension, {})
        return d.get("values")

    def get_table_for_source(self, data_source: str) -> str:
        """Get the physical table name for a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("table", data_source)

    def get_metrics_for_source(self, data_source: str) -> list[str]:
        """Get metric IDs that belong to a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("metrics", [])

    def get_dimensions_for_source(self, data_source: str) -> list[str]:
        """Get dimension IDs that belong to a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("dimensions", [])

    def get_joins_for_source(self, data_source: str) -> list[dict]:
        """Get available JOIN paths from a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("joins", [])

    def find_data_source_for_metric(self, metric_name: str) -> str | None:
        """Find which data source contains a given metric."""
        for src_name, src_cfg in self.data_sources.items():
            if metric_name in src_cfg.get("metrics", []):
                return src_name
        return None

    def find_data_source_for_dimension(self, dimension_name: str) -> str | None:
        """Find which data source contains a given dimension."""
        for src_name, src_cfg in self.data_sources.items():
            if dimension_name in src_cfg.get("dimensions", []):
                return src_name
        return None


@dataclass
class RuleContext:
    """Read-only context passed to every rule during execution."""

    semantic_config: SemanticConfig
    user_id: str | None = None
    user_role: str | None = None
    permission_config: dict | None = None
    original_question: str | None = None
    max_limit: int = 10000
