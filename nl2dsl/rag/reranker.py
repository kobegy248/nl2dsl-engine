"""Reranker implementations for RAG retrieval.

Uses Cross-Encoder models to re-order retrieved candidates by relevance.
"""

from __future__ import annotations

import re

from nl2dsl.rag.base import RerankerBase


class BGEReranker(RerankerBase):
    """Real reranker using BGE Cross-Encoder model.

    Model: BAAI/bge-reranker-base (278M params, ~420MB)
    Requires: sentence-transformers
    """

    def __init__(self, model_path: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_path, device=device)
        self._model_path = model_path

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        pairs = [(query, c) for c in candidates]
        scores = self._model.predict(pairs)
        # Handle both single array and list of arrays
        if hasattr(scores, "tolist"):
            return scores.tolist()
        return list(scores)


class MockReranker(RerankerBase):
    """Placeholder reranker for testing.

    Scores by keyword overlap between query and candidate text.
    Chinese text is segmented into individual characters for matching.
    """

    @staticmethod
    def _extract_tokens(text: str) -> set[str]:
        """Extract English words and individual Chinese characters."""
        text_lower = text.lower()
        # English words and numbers
        tokens = set(re.findall(r"[a-z0-9_]+", text_lower))
        # Individual Chinese characters
        tokens.update(re.findall(r"[一-鿿]", text_lower))
        return tokens

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        query_tokens = self._extract_tokens(query)
        scores = []
        for c in candidates:
            cand_tokens = self._extract_tokens(c)
            overlap = len(query_tokens & cand_tokens)
            denom = max(len(query_tokens), 1)
            scores.append(min(overlap / denom * 2.0, 1.0))
        return scores
