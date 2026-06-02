import pytest
from nl2dsl.evaluation.canonical.order_resolver import OrderResolver, CanonicalOrderBy


@pytest.fixture
def resolver():
    return OrderResolver()


def test_explicit_direction(resolver):
    """用户明确表达了排序方向"""
    result = resolver.resolve("sales_amount", "desc", user_expressed=True)
    assert result.field == "sales_amount"
    assert result.direction == "desc"
    assert result.is_default is False


def test_default_direction(resolver):
    """用户未表达排序方向，使用系统默认"""
    result = resolver.resolve("sales_amount", None, user_expressed=False)
    assert result.field == "sales_amount"
    assert result.is_default is True
