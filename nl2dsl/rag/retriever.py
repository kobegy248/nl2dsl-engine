from __future__ import annotations

import re

import jieba

from nl2dsl.rag.base import VectorStore
from nl2dsl.rag.embedder import BGEEmbedder, MockEmbedder

# Chinese stopwords for filtering
_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也",
    "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "那",
    "个", "为", "之", "与", "及", "等", "从", "而", "以", "被", "把", "给", "让", "向",
    "往", "于", "但", "并", "却", "如果", "因为", "所以", "虽然", "然而", "而且", "或者",
    "还是", "并且", "查询", "查下", "查一下", "看一下", "看看", "一下", "多少", "怎么",
    "怎样", "如何", "什么", "哪些", "吗", "呢", "吧", "啊", "哦", "嗯",
}


class RAGRetriever:
    """RAG retriever with jieba-based keyword extraction.

    Strategy:
    1. At init time, load all keywords (record names + Chinese phrases from text)
       from each collection
    2. Register keywords into jieba custom dictionary for accurate segmentation
    3. At query time, segment user question with jieba, filter stopwords,
       match against keyword library
    4. Also retrieve by the full query for semantic matching
    5. Merge and deduplicate results
    """

    COLLECTIONS = ["schema", "metrics", "history", "terms"]

    def __init__(self, store: VectorStore, embedder: BGEEmbedder | MockEmbedder | None = None):
        self._store = store
        self._embedder = embedder or MockEmbedder()
        # Load keywords dynamically from vector store
        self._keywords = self._load_keywords()
        # Register keywords into jieba for accurate segmentation
        self._setup_jieba()

    @staticmethod
    def _extract_chinese_phrases(text: str) -> list[str]:
        """Extract consecutive Chinese character sequences (2-8 chars) from text."""
        return re.findall(r"[一-鿿]{2,8}", text)

    def _load_keywords(self) -> dict[str, list[str]]:
        """Load keyword names and Chinese phrases from each collection dynamically."""
        keywords: dict[str, list[str]] = {}
        for col in self.COLLECTIONS:
            if not self._store.has_collection(col):
                keywords[col] = []
                continue
            records = self._store.get_all(col)
            names: set[str] = set()
            for r in records:
                # Use record name
                name = r.get("name", "")
                if name and isinstance(name, str):
                    names.add(name)
                # Also extract Chinese phrases from text field
                text = r.get("text", "")
                if text and isinstance(text, str):
                    for phrase in self._extract_chinese_phrases(text):
                        names.add(phrase)
            keywords[col] = sorted(names, key=len, reverse=True)
        return keywords

    def _setup_jieba(self) -> None:
        """Register all keywords into jieba custom dictionary."""
        all_keywords: set[str] = set()
        for kw_list in self._keywords.values():
            all_keywords.update(kw_list)
        for kw in all_keywords:
            if len(kw) > 1:
                jieba.add_word(kw, freq=1000)

    def _extract_keywords(self, query: str, collection: str) -> list[str]:
        """Extract candidate keywords using jieba segmentation (case-insensitive)."""
        words = list(jieba.cut(query))
        # Filter stopwords and single-char tokens
        words = [w for w in words if w not in _STOPWORDS and len(w) > 1]

        # Build case-insensitive keyword map: lowercase -> original
        keyword_map: dict[str, str] = {}
        for kw in self._keywords.get(collection, []):
            keyword_map[kw.lower()] = kw

        matched = []
        for w in words:
            # Exact match (case-sensitive first)
            if w in keyword_map.values():
                matched.append(w)
            # Case-insensitive fallback for English/acronyms like GMV
            elif w.lower() in keyword_map:
                matched.append(keyword_map[w.lower()])
        return matched

    def retrieve(self, query: str, top_k: int = 5) -> dict[str, list[dict]]:
        """Retrieve by full query vector (semantic search)."""
        vector = self._embedder.embed(query)
        results = {}
        for col in self.COLLECTIONS:
            if self._store.has_collection(col):
                results[col] = self._store.search(col, vector, limit=top_k)
        return results

    def retrieve_by_keywords(self, query: str, top_k: int = 3) -> dict[str, list[dict]]:
        """Retrieve by jieba-segmented keywords from vector store names."""
        results: dict[str, list[dict]] = {col: [] for col in self.COLLECTIONS}

        for col in self.COLLECTIONS:
            if not self._store.has_collection(col):
                continue

            keywords = self._extract_keywords(query, col)
            if not keywords:
                # Fallback: use full query for this collection
                keywords = [query]

            seen_ids = set()
            for kw in keywords:
                vector = self._embedder.embed(kw)
                hits = self._store.search(col, vector, limit=top_k)
                for hit in hits:
                    hit_id = hit.get("id")
                    if hit_id not in seen_ids:
                        seen_ids.add(hit_id)
                        results[col].append(hit)

        return results

    def retrieve_hybrid(self, query: str, top_k: int = 5, keyword_top_k: int = 3) -> dict[str, list[dict]]:
        """Hybrid retrieval: full query semantic + keyword-split, then merge."""
        semantic_results = self.retrieve(query, top_k=top_k)
        keyword_results = self.retrieve_by_keywords(query, top_k=keyword_top_k)

        merged: dict[str, list[dict]] = {}
        for col in self.COLLECTIONS:
            seen_ids = set()
            merged[col] = []

            # Keyword results first (more precise)
            for hit in keyword_results.get(col, []):
                hit_id = hit.get("id")
                if hit_id not in seen_ids:
                    seen_ids.add(hit_id)
                    merged[col].append(hit)

            # Semantic results supplement
            for hit in semantic_results.get(col, []):
                hit_id = hit.get("id")
                if hit_id not in seen_ids:
                    seen_ids.add(hit_id)
                    merged[col].append(hit)

        return merged

    def build_context(self, query: str, top_k: int = 5) -> str:
        results = self.retrieve_hybrid(query, top_k=top_k)
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
        context = self.build_context(query, top_k=top_k)
        return f"""【上下文】
{context}

【用户问题】
{query}

请根据上下文将用户问题转换为 DSL JSON。"""