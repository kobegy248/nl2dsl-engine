import pytest
from nl2dsl.dsl.builder import DSLBuilder
from nl2dsl.dsl.models import DSL, Aggregation, Filter, OrderBy


class TestDSLBuilder:
    def test_empty_build(self):
        dsl = DSLBuilder("orders").build()
        assert isinstance(dsl, DSL)
        assert dsl.data_source == "orders"
        assert dsl.metrics is None
        assert dsl.dimensions is None

    def test_metric(self):
        dsl = DSLBuilder("orders").metric("sum", "order_amount", "sales").build()
        assert len(dsl.metrics) == 1
        assert dsl.metrics[0] == Aggregation(func="sum", field="order_amount", alias="sales")

    def test_multiple_metrics(self):
        dsl = (
            DSLBuilder("orders")
            .metric("sum", "amount", "total")
            .metric("count", "id", "cnt")
            .build()
        )
        assert len(dsl.metrics) == 2
        assert dsl.metrics[0].func == "sum"
        assert dsl.metrics[1].func == "count"

    def test_dimension(self):
        dsl = DSLBuilder("orders").dimension("region").build()
        assert dsl.dimensions == ["region"]

    def test_multiple_dimensions(self):
        dsl = DSLBuilder("orders").dimension("region").dimension("product").build()
        assert dsl.dimensions == ["region", "product"]

    def test_filter(self):
        dsl = DSLBuilder("orders").filter("region", "=", "华东").build()
        assert len(dsl.filters) == 1
        assert dsl.filters[0] == Filter(field="region", operator="=", value="华东")

    def test_order_by(self):
        dsl = DSLBuilder("orders").order_by("sales", "desc").build()
        assert len(dsl.order_by) == 1
        assert dsl.order_by[0] == OrderBy(field="sales", direction="desc")

    def test_limit(self):
        dsl = DSLBuilder("orders").limit(50).build()
        assert dsl.limit == 50

    def test_chain_all(self):
        dsl = (
            DSLBuilder("orders")
            .metric("sum", "amount", "total")
            .dimension("region")
            .filter("status", "=", "completed")
            .order_by("total", "desc")
            .limit(20)
            .build()
        )
        assert dsl.data_source == "orders"
        assert len(dsl.metrics) == 1
        assert dsl.dimensions == ["region"]
        assert len(dsl.filters) == 1
        assert len(dsl.order_by) == 1
        assert dsl.limit == 20

    def test_builder_returns_self(self):
        builder = DSLBuilder("orders")
        assert builder.metric("sum", "a", "b") is builder
        assert builder.dimension("x") is builder
        assert builder.filter("f", "=", "v") is builder
        assert builder.order_by("o", "asc") is builder
        assert builder.limit(10) is builder

    def test_no_limit_uses_default(self):
        dsl = DSLBuilder("orders").build()
        assert dsl.limit == 100  # default from model
