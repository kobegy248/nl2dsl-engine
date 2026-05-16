from __future__ import annotations

from nl2dsl.rag.base import VectorStore
from nl2dsl.rag.embedder import MockEmbedder


class RAGRetriever:
    COLLECTIONS = ["schema", "metrics", "history", "terms"]

    def __init__(self, store: VectorStore, embedder: MockEmbedder | None = None):
        self._store = store
        self._embedder = embedder or MockEmbedder()

    def retrieve(self, query: str, top_k: int = 5) -> dict[str, list[dict]]:
        vector = self._embedder.embed(query)
        results = {}
        for col in self.COLLECTIONS:
            if self._store.has_collection(col):
                results[col] = self._store.search(col, vector, limit=top_k)
        return results

    def build_context(self, query: str, top_k: int = 5) -> str:
        results = self.retrieve(query, top_k)
        parts = []
        if results.get("schema"):
            parts.append("【表结构】\n" + "\n".join(f"- {r['text']}" for r in results["schema"]))
        if results.get("metrics"):
            parts.append("【指标定义】\n" + "\n".join(f"- {r['text']}" for r in results["metrics"]))
        if results.get("history"):
            parts.append("【历史查询示例】\n" + "\n".join(f"- {r['text']}" for r in results["history"]))
        if results.get("terms"):
            parts.append("【业务术语】\n" + "\n".join(f"- {r['text']}" for r in results["terms"]))
        return "\n\n".join(parts)

    def build_prompt(self, query: str, top_k: int = 5) -> str:
        context = self.build_context(query, top_k)
        return f"""【上下文】
{context}

【用户问题】
{query}

请根据上下文将用户问题转换为 DSL JSON。"""
