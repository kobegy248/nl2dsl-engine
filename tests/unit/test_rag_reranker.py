"""Unit tests for reranker integration."""

import pytest

from nl2dsl.rag.base import RerankerBase
from nl2dsl.rag.reranker import MockReranker
from nl2dsl.rag.retriever import RAGRetriever
from nl2dsl.rag.embedder import MockEmbedder


class FakeStore:
    """Minimal fake VectorStore for testing."""

    def __init__(self, data: dict[str, list[dict]]):
        self._data = data

    def has_collection(self, name: str) -> bool:
        return name in self._data

    def search(self, collection: str, vector, limit: int) -> list[dict]:
        return self._data.get(collection, [])[:limit]

    def get_all(self, collection: str) -> list[dict]:
        return self._data.get(collection, [])

    def create_collection(self, name: str, dimension: int) -> None:
        pass

    def upsert(self, collection: str, records: list[dict]) -> None:
        pass


@pytest.fixture
def fake_store():
    return FakeStore({
        "schema": [
            {"id": 1, "text": "维度: product_name, 字段: product_name, 说明: 产品名称", "type": "dimension", "name": "product_name"},
            {"id": 2, "text": "维度: brand, 字段: brand, 说明: 品牌", "type": "dimension", "name": "brand"},
            {"id": 3, "text": "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额", "type": "metric", "name": "sales_amount"},
        ],
        "metrics": [
            {"id": 3, "text": "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额", "type": "metric", "name": "sales_amount"},
            {"id": 4, "text": "指标: gmv, 计算: SUM(order_amount), 说明: 成交总额", "type": "metric", "name": "gmv"},
        ],
        "terms": [
            {"id": 5, "text": "流水 -> gmv", "type": "term_alias", "name": "流水"},
            {"id": 6, "text": "术语: gmv, 别名: 流水, 说明: 成交总额", "type": "term", "name": "gmv"},
        ],
        "history": [
            {"id": 7, "text": "问题: 查询销售额\nDSL: {metrics: [sales_amount]}", "type": "history", "name": "查询销售额"},
        ],
    })


@pytest.fixture
def embedder():
    return MockEmbedder()


class TestMockReranker:
    def test_scores_keyword_overlap(self):
        r = MockReranker()
        scores = r.rerank("查询销售额", [
            "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额",
            "维度: product_name, 字段: product_name, 说明: 产品名称",
        ])
        assert len(scores) == 2
        assert scores[0] > scores[1]  # 销售额相关度更高

    def test_empty_candidates(self):
        r = MockReranker()
        scores = r.rerank("查询销售额", [])
        assert scores == []


class TestRAGRetrieverWithRerank:
    def test_rerank_reorders_results(self, fake_store, embedder):
        reranker = MockReranker()
        retriever = RAGRetriever(fake_store, embedder, reranker=reranker)

        results = retriever.retrieve_hybrid("查询销售额", top_k=5, coarse_k=10)

        # schema 中 sales_amount 应该排在 brand 前面
        schema = results.get("schema", [])
        assert len(schema) > 0
        # sales_amount 包含"销售额"关键词，分数应该更高
        if len(schema) >= 2:
            assert schema[0].get("rerank_score", 0) >= schema[-1].get("rerank_score", 0)

    def test_threshold_filters_low_scores(self, fake_store, embedder):
        reranker = MockReranker()
        retriever = RAGRetriever(fake_store, embedder, reranker=reranker)

        # Use high threshold to filter out most results
        results = retriever.retrieve_hybrid(
            "完全不相关的问题", top_k=5, coarse_k=10, threshold=0.9
        )

        # All collections should either be empty or fallback to top-3
        for col in retriever.COLLECTIONS:
            assert len(results.get(col, [])) <= 3

    def test_no_reranker_degrades_gracefully(self, fake_store, embedder):
        retriever = RAGRetriever(fake_store, embedder, reranker=None)

        results = retriever.retrieve_hybrid("查询销售额", top_k=5)

        # Should still return results without rerank scores
        assert len(results.get("schema", [])) > 0
        for r in results.get("schema", []):
            assert "rerank_score" not in r

    def test_build_context_respects_budget(self, fake_store, embedder):
        reranker = MockReranker()
        retriever = RAGRetriever(fake_store, embedder, reranker=reranker)

        # Very small budget should truncate
        context = retriever.build_context("查询销售额", top_k=5, max_chars=200)
        assert len(context) <= 200

    def test_reranker_failure_fallback(self, fake_store, embedder):
        class FailingReranker(RerankerBase):
            def rerank(self, query: str, candidates: list[str]) -> list[float]:
                raise RuntimeError("boom")

        retriever = RAGRetriever(fake_store, embedder, reranker=FailingReranker())
        results = retriever.retrieve_hybrid("查询销售额", top_k=5)

        # Should still return results with neutral scores
        assert len(results.get("schema", [])) > 0
