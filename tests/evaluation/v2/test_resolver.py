import pytest
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def resolver():
    return CanonicalResolver.from_config({
        "metrics": {
            "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
        },
        "dimensions": {
            "region": {"column": "region_code", "value_map": {"华东": "HD"}},
        },
        "data_sources": {
            "orders": {
                "joins": {
                    "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
                }
            }
        },
    })


def test_resolve_metric(resolver):
    assert resolver.resolve_metric("sales_amount") == "sales_amount"


def test_resolve_dimension(resolver):
    assert resolver.resolve_dimension("region") == "region_code"


def test_resolve_value(resolver):
    assert resolver.resolve_value("region", "华东") == "HD"


def test_resolve_time(resolver):
    result = resolver.resolve_time("2024年")
    assert result.start == "2024-01-01"
    assert result.granularity == "year"
