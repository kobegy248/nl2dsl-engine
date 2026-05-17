from nl2dsl.dsl.builder import DSLBuilder


def test_builder_chain():
    dsl = (
        DSLBuilder("orders")
        .metric("sum", "order_amount", "sales_amount")
        .dimension("product_name")
        .filter("region", "=", "华东")
        .order_by("sales_amount", "desc")
        .limit(10)
        .build()
    )
    assert dsl.data_source == "orders"
    assert len(dsl.metrics) == 1
    assert dsl.metrics[0].alias == "sales_amount"
    assert dsl.dimensions == ["product_name"]
    assert dsl.filters[0].value == "华东"
    assert dsl.order_by[0].direction == "desc"
    assert dsl.limit == 10


def test_builder_minimal():
    dsl = DSLBuilder("orders").build()
    assert dsl.data_source == "orders"
    assert dsl.metrics is None
    assert dsl.dimensions is None
    assert dsl.limit == 100  # default
