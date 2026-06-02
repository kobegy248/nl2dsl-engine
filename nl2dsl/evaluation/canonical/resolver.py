"""规范化语义解析器 — 主编排器。"""

from __future__ import annotations

from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver
from nl2dsl.evaluation.canonical.dimension_resolver import DimensionResolver
from nl2dsl.evaluation.canonical.value_resolver import ValueResolver
from nl2dsl.evaluation.canonical.time_resolver import TimeResolver, CanonicalTimeRange
from nl2dsl.evaluation.canonical.join_resolver import JoinResolver, CanonicalJoin
from nl2dsl.evaluation.canonical.order_resolver import OrderResolver, CanonicalOrderBy


class CanonicalResolver:
    """编排所有规范化解析器。"""

    def __init__(
        self,
        metric_resolver: MetricResolver,
        dimension_resolver: DimensionResolver,
        value_resolver: ValueResolver,
        time_resolver: TimeResolver,
        join_resolver: JoinResolver,
        order_resolver: OrderResolver,
    ):
        self.metric = metric_resolver
        self.dimension = dimension_resolver
        self.value = value_resolver
        self.time = time_resolver
        self.join = join_resolver
        self.order = order_resolver

    @classmethod
    def from_config(cls, config: dict) -> CanonicalResolver:
        """从项目配置（metrics.yaml 格式）构建解析器。"""
        return cls(
            metric_resolver=MetricResolver(config.get("metrics", {})),
            dimension_resolver=DimensionResolver(config.get("dimensions", {})),
            value_resolver=ValueResolver(config.get("dimensions", {})),
            time_resolver=TimeResolver(),
            join_resolver=JoinResolver(config.get("data_sources", {})),
            order_resolver=OrderResolver(),
        )

    def resolve_metric(self, alias_or_field: str, func: str | None = None) -> str:
        return self.metric.resolve(alias_or_field, func)

    def resolve_dimension(self, alias: str) -> str:
        return self.dimension.resolve(alias)

    def resolve_value(self, dimension: str, value) -> str:
        return self.value.resolve(dimension, value)

    def resolve_time(self, time_expr) -> CanonicalTimeRange | None:
        return self.time.resolve(time_expr)

    def resolve_join(self, table: str, on_field: str, join_type: str) -> CanonicalJoin:
        return self.join.resolve(table, on_field, join_type)

    def resolve_order(self, field: str, direction: str | None, user_expressed: bool = False) -> CanonicalOrderBy:
        return self.order.resolve(field, direction, user_expressed)
