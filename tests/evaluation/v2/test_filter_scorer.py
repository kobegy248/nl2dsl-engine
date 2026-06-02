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
