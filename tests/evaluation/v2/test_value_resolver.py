import pytest
from nl2dsl.evaluation.canonical.value_resolver import ValueResolver


@pytest.fixture
def resolver():
    return ValueResolver({
        "region": {"value_map": {"华东": "HD", "华南": "HN"}},
        "channel": {"value_map": {"线上": "online", "线下": "offline"}},
    })


def test_resolve_mapped_value(resolver):
    assert resolver.resolve("region", "华东") == "HD"


def test_resolve_unmapped_value(resolver):
    assert resolver.resolve("brand", "Apple") == "Apple"


def test_resolve_dimension_without_map(resolver):
    assert resolver.resolve("region", "华北") == "华北"
