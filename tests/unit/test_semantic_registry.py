import pytest
from nl2dsl.semantic.registry import SemanticRegistry


@pytest.fixture
def registry(tmp_path):
    yaml_content = """
metrics:
  sales_amount:
    expr: SUM(order_amount)
    description: "销售额"
  gmv:
    expr: SUM(pay_amount)
    description: "GMV"

dimensions:
  product_name:
    column: product_name
    description: "产品名称"
  region:
    column: region
    description: "地区"
    value_map:
      "华东": "huadong"
      "华南": "huanan"

data_sources:
  orders:
    table: order_fact
    metrics: [sales_amount, gmv]
    dimensions: [product_name, region]
"""
    yaml_file = tmp_path / "metrics.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    reg = SemanticRegistry()
    reg.load(str(yaml_file))
    return reg


def test_load_metrics(registry):
    assert "sales_amount" in registry.metrics
    assert registry.metrics["sales_amount"]["expr"] == "SUM(order_amount)"


def test_load_dimensions(registry):
    assert "product_name" in registry.dimensions
    assert "region" in registry.dimensions


def test_load_data_sources(registry):
    assert "orders" in registry.data_sources
    assert registry.data_sources["orders"]["table"] == "order_fact"


def test_metric_exists(registry):
    assert registry.has_metric("sales_amount")
    assert not registry.has_metric("unknown")


def test_dimension_exists(registry):
    assert registry.has_dimension("product_name")
    assert not registry.has_dimension("unknown")


def test_value_map(registry):
    region_dim = registry.dimensions["region"]
    assert region_dim["value_map"]["华东"] == "huadong"
