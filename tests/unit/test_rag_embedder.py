import pytest
from nl2dsl.rag.embedder import MockEmbedder


def test_mock_embedder_dimensions():
    emb = MockEmbedder()
    vec = emb.embed("测试文本")
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)


def test_mock_embedder_deterministic():
    emb = MockEmbedder()
    vec1 = emb.embed("相同文本")
    vec2 = emb.embed("相同文本")
    assert vec1 == vec2


def test_mock_embedder_different():
    emb = MockEmbedder()
    vec1 = emb.embed("文本A")
    vec2 = emb.embed("文本B")
    assert vec1 != vec2
