import pytest
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


@pytest.fixture
def resolver():
    return MetricResolver({
        "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
        "gmv": {"expr": "SUM(order_amount)", "canonical_id": "gmv"},
        "order_count": {"expr": "COUNT(id)", "canonical_id": "order_count"},
    })


def test_resolve_by_alias(resolver):
    """别名直接匹配 metric_id"""
    assert resolver.resolve("sales_amount") == "sales_amount"


def test_resolve_by_field_func(resolver):
    """通过字段+函数反查 metric_id"""
    assert resolver.resolve("pay_amount", func="sum") == "sales_amount"


def test_resolve_unknown(resolver):
    """无法解析时返回原始值"""
    assert resolver.resolve("unknown") == "unknown"
