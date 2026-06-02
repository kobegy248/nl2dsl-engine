import pytest
from nl2dsl.evaluation.models import V2TestCase, V2ScoreBreakdown, CanonicalQuery


def test_v2_test_case():
    case = V2TestCase(
        id="BASIC_001",
        query="查询销售额",
        expected={
            "intent": "aggregate",
            "metric": "sales_amount",
        },
    )
    assert case.id == "BASIC_001"
    assert case.category == "basic"


def test_canonical_query():
    cq = CanonicalQuery(
        intent="aggregate",
        metric="sales_amount",
        filters=["region_code = HD"],
    )
    assert cq.intent == "aggregate"
