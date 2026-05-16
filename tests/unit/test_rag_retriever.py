import pytest
from unittest.mock import MagicMock
from nl2dsl.rag.retriever import RAGRetriever


@pytest.fixture
def retriever():
    store = MagicMock()
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 384

    store.search.side_effect = lambda col, vector, limit: {
        "schema": [{"text": "表: orders", "score": 0.9}],
        "metrics": [{"text": "指标: sales_amount", "score": 0.85}],
        "history": [{"text": "历史: 查询销售额", "score": 0.8}],
        "terms": [{"text": "术语: 销售额=sales_amount", "score": 0.95}],
    }.get(col, [])

    return RAGRetriever(store, embedder)


def test_retrieve_schema(retriever):
    result = retriever.retrieve("查询销售额", top_k=2)
    assert "schema" in result
    assert len(result["schema"]) == 1


def test_retrieve_metrics(retriever):
    result = retriever.retrieve("查询销售额", top_k=2)
    assert "metrics" in result
    assert result["metrics"][0]["text"] == "指标: sales_amount"


def test_build_context(retriever):
    context = retriever.build_context("查询销售额")
    assert "【表结构】" in context
    assert "【指标定义】" in context
    assert "sales_amount" in context


def test_build_prompt(retriever):
    prompt = retriever.build_prompt("查询销售额")
    assert "【上下文】" in prompt
    assert "【用户问题】" in prompt
    assert "查询销售额" in prompt
