import pytest
from nl2dsl.evaluation.scorers.intent_scorer import IntentScorer


@pytest.fixture
def scorer():
    return IntentScorer()


def test_match(scorer):
    assert scorer.score("aggregate", "aggregate") == 1.0


def test_mismatch(scorer):
    assert scorer.score("aggregate", "rank") == 0.0
