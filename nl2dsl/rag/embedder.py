class MockEmbedder:
    """Placeholder for sentence-transformers embedder."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._dim = 384

    def embed(self, text: str) -> list[float]:
        # Placeholder: return deterministic pseudo-random vector
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        seed = int(h[:8], 16)
        import random
        rng = random.Random(seed)
        return [rng.random() for _ in range(self._dim)]
