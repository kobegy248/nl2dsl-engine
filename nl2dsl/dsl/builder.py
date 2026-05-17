from __future__ import annotations

from nl2dsl.dsl.models import DSL, Filter, Aggregation, OrderBy


class DSLBuilder:
    """Helper to build DSL objects programmatically."""

    def __init__(self, data_source: str):
        self._data_source = data_source
        self._metrics: list[Aggregation] = []
        self._dimensions: list[str] = []
        self._filters: list[Filter] = []
        self._order_by: list[OrderBy] = []
        self._limit: int | None = None

    def metric(self, func: str, field: str, alias: str | None = None) -> DSLBuilder:
        self._metrics.append(Aggregation(func=func, field=field, alias=alias))
        return self

    def dimension(self, name: str) -> DSLBuilder:
        self._dimensions.append(name)
        return self

    def filter(self, field: str, operator: str, value) -> DSLBuilder:
        self._filters.append(Filter(field=field, operator=operator, value=value))
        return self

    def order_by(self, field: str, direction: str = "asc") -> DSLBuilder:
        self._order_by.append(OrderBy(field=field, direction=direction))
        return self

    def limit(self, n: int) -> DSLBuilder:
        self._limit = n
        return self

    def build(self) -> DSL:
        kwargs: dict = {
            "data_source": self._data_source,
            "metrics": self._metrics or None,
            "dimensions": self._dimensions or None,
            "filters": self._filters or None,
            "order_by": self._order_by or None,
        }
        if self._limit is not None:
            kwargs["limit"] = self._limit
        return DSL(**kwargs)
