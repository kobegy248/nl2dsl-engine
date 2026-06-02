import pytest
from nl2dsl.evaluation.scorers.base import Scorer


def test_scorer_is_abstract():
    """Scorer 不能直接实例化。"""
    with pytest.raises(TypeError):
        Scorer()
