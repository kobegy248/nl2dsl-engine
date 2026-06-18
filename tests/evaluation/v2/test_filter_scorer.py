import pytest
from nl2dsl.evaluation.scorers.filter_scorer import FilterScorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def scorer():
    resolver = CanonicalResolver.from_config({
        "dimensions": {
            "region": {"column": "region_code", "value_map": {"华东": "HD"}},
        },
    })
    return FilterScorer(resolver)


def test_exact_match(scorer):
    """完全相同"""
    assert scorer.score(
        [{"field": "region", "operator": "=", "value": "华东"}],
        [{"field": "region", "operator": "=", "value": "华东"}],
    ) == 1.0


def test_canonical_match(scorer):
    """规范化后等价"""
    assert scorer.score(
        [{"field": "region", "operator": "=", "value": "华东"}],
        [{"field": "region_code", "operator": "=", "value": "HD"}],
    ) == 1.0


def test_between_bounds_order_independent(scorer):
    """between 的两端顺序不影响匹配"""
    assert scorer.score(
        [{"field": "price", "operator": "between", "value": [5000, 20000]}],
        [{"field": "price", "operator": "between", "value": [20000, 5000]}],
    ) == 1.0


def test_between_bounds_numeric_strings(scorer):
    """字符串数值边界同样按数值排序"""
    assert scorer.score(
        [{"field": "price", "operator": "between", "value": ["5000", "20000"]}],
        [{"field": "price", "operator": "between", "value": ["20000", "5000"]}],
    ) == 1.0


def test_between_different_bounds_mismatch(scorer):
    """不同的 between 边界不匹配"""
    assert scorer.score(
        [{"field": "price", "operator": "between", "value": [5000, 20000]}],
        [{"field": "price", "operator": "between", "value": [5000, 30000]}],
    ) == 0.0


def test_not_equal_operator(scorer):
    """!= 算子参与比较"""
    assert scorer.score(
        [{"field": "region", "operator": "!=", "value": "华东"}],
        [{"field": "region_code", "operator": "!=", "value": "HD"}],
    ) == 1.0
