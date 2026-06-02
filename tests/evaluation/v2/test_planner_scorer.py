import pytest
from nl2dsl.evaluation.scorers.planner_scorer import PlannerScorer
from nl2dsl.evaluation.canonical.resolver import CanonicalResolver


@pytest.fixture
def scorer():
    resolver = CanonicalResolver.from_config({
        "dimensions": {"region": {"column": "region_code"}},
        "data_sources": {
            "orders": {
                "joins": {
                    "customer_dim": {"entity": "customer", "on": "customer_id", "type": "left", "alias": "c"},
                }
            }
        },
    })
    return PlannerScorer(resolver)


def test_dimension_match(scorer):
    assert scorer.score(
        {"dimensions": ["region"], "order_by": None, "limit": None, "joins": None},
        {"dimensions": ["region"], "order_by": None, "limit": None, "joins": None},
    ) == 1.0


def test_limit_match(scorer):
    assert scorer.score(
        {"dimensions": [], "order_by": None, "limit": 10, "joins": None},
        {"dimensions": [], "order_by": None, "limit": 10, "joins": None},
    ) == 1.0
