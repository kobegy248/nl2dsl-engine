import pytest
from nl2dsl.evaluation.canonical.join_resolver import JoinResolver, CanonicalJoin


@pytest.fixture
def resolver():
    return JoinResolver({
        "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
        "product_dim": {"entity": "product", "on": "product_id", "type": "inner", "alias": "p"},
    })


def test_resolve_by_table_name(resolver):
    result = resolver.resolve("customer_dim", "customer_id", "left")
    assert result.entity == "customer"
    assert result.on_field == "customer_id"
    assert result.join_type == "left"


def test_resolve_by_alias(resolver):
    result = resolver.resolve("c", "customer_id", "left")
    assert result.entity == "customer"
