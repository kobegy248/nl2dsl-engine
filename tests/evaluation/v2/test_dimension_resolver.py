import pytest
from nl2dsl.evaluation.canonical.dimension_resolver import DimensionResolver


@pytest.fixture
def resolver():
    return DimensionResolver({
        "product_name": {"column": "product_name"},
        "region": {"column": "region_code", "value_map": {"华东": "HD", "华南": "HN"}},
        "brand": {"column": "brand"},
    })


def test_resolve_direct(resolver):
    assert resolver.resolve("product_name") == "product_name"


def test_resolve_mapped(resolver):
    assert resolver.resolve("region") == "region_code"
