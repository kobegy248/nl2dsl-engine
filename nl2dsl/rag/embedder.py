from __future__ import annotations

from pathlib import Path


class MockEmbedder:
    """Placeholder for sentence-transformers embedder."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._dim = 384

    def embed(self, text: str) -> list[float]:
        import hashlib
        import random

        h = hashlib.md5(text.encode()).hexdigest()
        seed = int(h[:8], 16)
        rng = random.Random(seed)
        return [rng.random() for _ in range(self._dim)]


class BGEEmbedder:
    """Real embedding model using local BGE model."""

    def __init__(self, model_path: str | None = None):
        from sentence_transformers import SentenceTransformer

        if model_path is None:
            # Default: use D:/claude_work/model/bge-base-zh-v1.5
            model_path = str(Path("D:/claude_work/model/bge-base-zh-v1.5").resolve())

        self._model = SentenceTransformer(model_path)
        self._dim = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """Embed single text or batch of texts."""
        embeddings = self._model.encode(text, normalize_embeddings=True)
        if isinstance(text, str):
            return embeddings.tolist()
        return [e.tolist() for e in embeddings]
