"""Integration test fixtures for real LLM tests."""

from __future__ import annotations

import pytest

from nl2dsl.config import settings
from nl2dsl.llm.client import LLMClient


@pytest.fixture(scope="session")
def llm_client():
    """Create a real LLM client if API key is configured.

    Tests that need a real LLM should depend on this fixture.
    If no API key is available, the test is skipped.
    """
    if not settings.llm_api_key:
        pytest.skip("NL2DSL_LLM_API_KEY not set — skipping real LLM test")

    client = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    # Quick connectivity check
    try:
        _ = client.generate("Say hi", "You are a helpful assistant.")
    except Exception as exc:
        pytest.skip(f"LLM not reachable ({type(exc).__name__}: {exc}) — skipping real LLM test")

    return client


@pytest.fixture(scope="session")
def rag_retriever(llm_client):
    """Create a RAG retriever with real embedder if available."""
    try:
        from nl2dsl.rag.embedder import BGEEmbedder
        from nl2dsl.rag.retriever import RAGRetriever

        embedder = BGEEmbedder("D:/claude_work/model/bge-base-zh-v1.5")
        # Build a minimal in-memory store
        from nl2dsl.rag.store import MilvusLiteStore
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            store = MilvusLiteStore(uri=f"{tmpdir}/test.db")
            store.create_collection("schema", dimension=768)
            store.create_collection("metrics", dimension=768)
            store.create_collection("terms", dimension=768)
            store.create_collection("history", dimension=768)
            return RAGRetriever(store=store, embedder=embedder, reranker=None)
    except Exception:
        return None
