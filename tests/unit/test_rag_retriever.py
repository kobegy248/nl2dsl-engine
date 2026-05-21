import pytest
from unittest.mock import MagicMock
from nl2dsl.rag.retriever import RAGRetriever


@pytest.fixture
def retriever():
    store = MagicMock()
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 384

    # Mock has_collection for all collections used in _load_keywords
    store.has_collection.return_value = True

    # Mock get_all to return records with names for keyword extraction
    store.get_all.side_effect = lambda col: {
        "schema": [{"id": 1, "name": "order_fact", "text": "订单表"}],
        "metrics": [{"id": 2, "name": "sales_amount", "text": "销售额"}],
        "history": [{"id": 3, "name": "hist_001", "text": "历史查询"}],
        "terms": [{"id": 4, "name": "销售额", "text": "术语: 销售额"}],
    }.get(col, [])

    store.search.side_effect = lambda col, vector, limit: {
        "schema": [{"id": 1, "text": "表: orders", "score": 0.9}],
        "metrics": [{"id": 2, "text": "指标: sales_amount", "score": 0.85}],
        "history": [{"id": 3, "text": "历史: 查询销售额", "score": 0.8}],
        "terms": [{"id": 4, "text": "术语: 销售额=sales_amount", "score": 0.95}],
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
