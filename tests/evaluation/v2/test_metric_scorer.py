import pytest
from nl2dsl.evaluation.scorers.metric_scorer import MetricScorer
from nl2dsl.evaluation.canonical.metric_resolver import MetricResolver


@pytest.fixture
def scorer():
    resolver = MetricResolver({
        "sales_amount": {"expr": "SUM(pay_amount)", "canonical_id": "sales_amount"},
    })
    return MetricScorer(resolver)


def test_alias_match(scorer):
    """别名直接匹配"""
    assert scorer.score("sales_amount", "sales_amount") == 1.0


def test_field_func_match(scorer):
    """字段+函数反查后匹配"""
    assert scorer.score("sales_amount", "pay_amount", func="sum") == 1.0


def test_mismatch(scorer):
    """完全不同的指标"""
    assert scorer.score("sales_amount", "gmv") == 0.0
