"""Integration tests for RAG reranker in the query pipeline.

Verifies that:
1. RAG context (with rerank scores) is injected into LLM prompts
2. Graph pipeline correctly uses rag_retriever when available
3. Graceful degradation when rag_retriever is None
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nl2dsl.graph.builder import build_graph
from nl2dsl.graph.state import QueryState
from nl2dsl.rag.retriever import RAGRetriever
from nl2dsl.rag.reranker import MockReranker
from nl2dsl.rag.embedder import MockEmbedder
from nl2dsl.rag.base import VectorStore


class FakeStore(VectorStore):
    """Minimal fake VectorStore for integration testing."""

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
def rag_store():
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
def mock_services_with_rag(rag_store):
    """Create mock services with a real RAGRetriever (with MockReranker)."""
    embedder = MockEmbedder()
    reranker = MockReranker()
    rag_retriever = RAGRetriever(rag_store, embedder, reranker=reranker)

    # Mock LLM client that returns a valid DSL JSON
    llm_client = MagicMock()
    llm_client.generate.side_effect = [
        # generate_dsl call
        '{"metrics": [{"field": "sales_amount", "alias": "销售额"}], "dimensions": [], "filters": [], "limit": 10}',
        # verify_dsl call (if reached)
        '{"answer_match": true, "issues": []}',
    ]

    # Mock other services
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value = [
        MagicMock(_mapping={"product_name": "iPhone", "sales_amount": 1000.0})
    ]

    return {
        "clarification_detector": MagicMock(),
        "validator": MagicMock(),
        "row_security": MagicMock(),
        "col_security": MagicMock(),
        "resolver": MagicMock(),
        "sql_builder": MagicMock(return_value="SELECT product_name, SUM(order_amount) FROM order_fact GROUP BY product_name LIMIT 10"),
        "scanner": MagicMock(),
        "sandbox": MagicMock(),
        "executor": engine,
        "llm_client": llm_client,
        "rag_retriever": rag_retriever,
        "registry_dict": {},
    }


class TestRAGInPipeline:
    def test_rag_context_injected_into_llm_prompt(self, mock_services_with_rag):
        """When rag_retriever is available, generate_dsl uses build_prompt
        which includes RAG-retrieved context (schema, metrics, terms, history)."""
        mock_services_with_rag["clarification_detector"].detect.return_value = []
        mock_services_with_rag["sandbox"].check.return_value = MagicMock(passed=True, risks=[], sample_rows=[])
        mock_services_with_rag["row_security"].inject.side_effect = lambda dsl, uid: dsl
        mock_services_with_rag["resolver"].resolve.side_effect = lambda dsl: dsl

        graph = build_graph(**mock_services_with_rag)

        result = graph.invoke({
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        assert result["status"] == "success"
        llm_client = mock_services_with_rag["llm_client"]
        assert llm_client.generate.called

        # Collect all prompts passed to LLM across all calls
        all_prompts = [call[0][0] for call in llm_client.generate.call_args_list]
        combined = "\n".join(all_prompts)

        # Verify at least one prompt contains RAG context sections
        assert "【可用指标】" in combined
        assert "sales_amount" in combined

    def test_rerank_scores_attached_to_results(self, mock_services_with_rag):
        """Reranker attaches rerank_score to each candidate."""
        rag_retriever = mock_services_with_rag["rag_retriever"]
        results = rag_retriever.retrieve_hybrid("查询销售额", top_k=5)

        # At least one collection should have results with rerank_score
        has_score = any(
            "rerank_score" in r
            for col_results in results.values()
            for r in col_results
        )
        assert has_score

    def test_rerank_reorders_by_relevance(self, mock_services_with_rag):
        """MockReranker scores sales_amount higher than brand for '查询销售额'."""
        rag_retriever = mock_services_with_rag["rag_retriever"]
        results = rag_retriever.retrieve_hybrid("查询销售额", top_k=5)

        schema = results.get("schema", [])
        if len(schema) >= 2:
            # sales_amount (contains 销售额) should score higher than brand
            scores = [r.get("rerank_score", 0) for r in schema]
            assert scores[0] >= scores[-1]


class TestRerankImprovesPrecision:
    def test_rerank_filters_irrelevant_schema(self):
        """With reranker, low-relevance schema items are filtered by threshold.
        Without reranker, all coarse results appear in context (noise).
        """
        store = FakeStore({
            "schema": [
                {"id": 1, "text": "维度: product_name, 字段: product_name, 说明: 产品名称", "type": "dimension", "name": "product_name"},
                {"id": 2, "text": "维度: brand, 字段: brand, 说明: 品牌", "type": "dimension", "name": "brand"},
                {"id": 3, "text": "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额", "type": "metric", "name": "sales_amount"},
                {"id": 4, "text": "指标: order_count, 计算: COUNT(*), 说明: 订单数", "type": "metric", "name": "order_count"},
            ],
            "metrics": [
                {"id": 3, "text": "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额", "type": "metric", "name": "sales_amount"},
                {"id": 4, "text": "指标: order_count, 计算: COUNT(*), 说明: 订单数", "type": "metric", "name": "order_count"},
            ],
            "terms": [],
            "history": [],
        })

        embedder = MockEmbedder()

        # With reranker
        r_with = RAGRetriever(store, embedder, reranker=MockReranker())
        ctx_with = r_with.build_context("查询订单数", top_k=3)

        # Without reranker
        r_without = RAGRetriever(store, embedder, reranker=None)
        ctx_without = r_without.build_context("查询订单数", top_k=3)

        # With reranker: order_count should appear, product_name/brand should NOT
        assert "order_count" in ctx_with
        assert "product_name" not in ctx_with
        assert "brand" not in ctx_with

        # Without reranker: all items appear (no filtering)
        assert "product_name" in ctx_without
        assert "brand" in ctx_without

    def test_rerank_preserves_critical_terms(self):
        """Terms (business constraints) are highest priority and must survive
        rerank filtering even if keyword overlap is low.
        """
        store = FakeStore({
            "schema": [
                {"id": 1, "text": "维度: region, 字段: region_code, 说明: 地区代码", "type": "dimension", "name": "region"},
            ],
            "metrics": [
                {"id": 2, "text": "指标: sales_amount, 计算: SUM(order_amount), 说明: 销售额", "type": "metric", "name": "sales_amount"},
            ],
            "terms": [
                {"id": 3, "text": "流水 -> gmv", "type": "term_alias", "name": "流水"},
            ],
            "history": [],
        })

        retriever = RAGRetriever(store, MockEmbedder(), reranker=MockReranker())
        results = retriever.retrieve_hybrid("最近7天的销售额", top_k=3)

        # Terms must be present regardless of keyword overlap score
        terms = results.get("terms", [])
        assert len(terms) > 0
        assert any("流水" in t["text"] for t in terms)


class TestRAGGracefulDegradation:
    def test_pipeline_works_without_rag_retriever(self):
        """When rag_retriever is None, graph falls back to basic prompt."""
        llm_client = MagicMock()
        llm_client.generate.side_effect = [
            '{"metrics": [{"field": "sales_amount"}], "dimensions": [], "filters": [], "limit": 10}',
            '{"answer_match": true, "issues": []}',
        ]

        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__.return_value = conn
        conn.execute.return_value = [
            MagicMock(_mapping={"sales_amount": 1000.0})
        ]

        services = {
            "clarification_detector": MagicMock(),
            "validator": MagicMock(),
            "row_security": MagicMock(),
            "col_security": MagicMock(),
            "resolver": MagicMock(),
            "sql_builder": MagicMock(return_value="SELECT SUM(order_amount) FROM order_fact"),
            "scanner": MagicMock(),
            "sandbox": MagicMock(),
            "executor": engine,
            "llm_client": llm_client,
            "rag_retriever": None,
            "registry_dict": {},
        }

        services["clarification_detector"].detect.return_value = []
        services["sandbox"].check.return_value = MagicMock(passed=True, risks=[], sample_rows=[])
        services["row_security"].inject.side_effect = lambda dsl, uid: dsl
        services["resolver"].resolve.side_effect = lambda dsl: dsl

        graph = build_graph(**services)

        result = graph.invoke({
            "question": "查询销售额",
            "user_id": "u001",
            "tenant_id": "t001",
        })

        assert result["status"] == "success"
        assert llm_client.generate.called
