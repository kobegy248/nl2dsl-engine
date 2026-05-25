from pymilvus import MilvusClient
from nl2dsl.rag.base import VectorStore


# 非保留字段（除 id/vector/text 外都视为 metadata 透传）
_RESERVED = {"id", "vector"}


def _flatten_hit(hit: dict) -> dict:
    """Normalize pymilvus search hit to a flat dict.

    pymilvus returns ``{id, distance, entity:{...}}``; tests expect
    a flat structure with all fields at top level.
    """
    flat = {k: v for k, v in hit.items() if k != "entity"}
    entity = hit.get("entity") or {}
    if isinstance(entity, dict):
        for k, v in entity.items():
            flat.setdefault(k, v)
    return flat


class MilvusLiteStore(VectorStore):
    def __init__(self, uri: str = "./milvus_lite.db"):
        self.client = MilvusClient(uri=uri)
        self._loaded: set[str] = set()

    def create_collection(self, name: str, dimension: int) -> None:
        if not self.client.has_collection(name):
            self.client.create_collection(
                collection_name=name,
                dimension=dimension,
                metric_type="COSINE",
            )

    def has_collection(self, name: str) -> bool:
        return self.client.has_collection(name)

    def _ensure_loaded(self, collection: str) -> None:
        if collection not in self._loaded:
            self.client.load_collection(collection)
            self._loaded.add(collection)

    def upsert(self, collection: str, records: list[dict]) -> None:
        # 透传除 id/vector 之外的所有顶层字段（text/type/name/...）作为动态字段写入
        data = []
        for r in records:
            row = {"id": r["id"], "vector": r["vector"]}
            for k, v in r.items():
                if k not in _RESERVED:
                    row[k] = v
            # 兼容旧调用：metadata 字段平铺
            for k, v in (r.get("metadata") or {}).items():
                row.setdefault(k, v)
            data.append(row)
        self.client.upsert(collection_name=collection, data=data)

    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        self._ensure_loaded(collection)
        results = self.client.search(
            collection_name=collection,
            data=[vector],
            limit=limit,
            output_fields=["text", "type", "name"],
        )
        if not results:
            return []
        return [_flatten_hit(h) for h in results[0]]

    def get_all(self, collection: str) -> list[dict]:
        self._ensure_loaded(collection)
        results = self.client.query(
            collection_name=collection,
            filter="",
            output_fields=["id", "text", "type", "name"],
        )
        return results if results else []

    def close(self) -> None:
        self.client.close()
