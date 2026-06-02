import pytest
from nl2dsl.evaluation.scorers.governance_scorer import GovernanceScorer


@pytest.fixture
def scorer():
    return GovernanceScorer()


def test_allow_match(scorer):
    assert scorer.score(
        {"permission": "allow"},
        {"permission": "allow"},
    ) == 1.0


def test_deny_mismatch(scorer):
    assert scorer.score(
        {"permission": "deny"},
        {"permission": "allow"},
    ) == 0.0
