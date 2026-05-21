from pymilvus import MilvusClient
from nl2dsl.rag.base import VectorStore


class MilvusLiteStore(VectorStore):
    def __init__(self, uri: str = "./milvus_lite.db"):
        self.client = MilvusClient(uri=uri)

    def create_collection(self, name: str, dimension: int) -> None:
        if not self.client.has_collection(name):
            self.client.create_collection(
                collection_name=name,
                dimension=dimension,
                metric_type="COSINE",
            )

    def has_collection(self, name: str) -> bool:
        return self.client.has_collection(name)

    def upsert(self, collection: str, records: list[dict]) -> None:
        self.client.upsert(
            collection_name=collection,
            data=[
                {
                    "id": r["id"],
                    "vector": r["vector"],
                    "text": r["text"],
                    **r.get("metadata", {}),
                }
                for r in records
            ],
        )

    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        self.client.load_collection(collection)
        results = self.client.search(
            collection_name=collection,
            data=[vector],
            limit=limit,
            output_fields=["text", "type", "name"],
        )
        return results[0] if results else []

    def get_all(self, collection: str) -> list[dict]:
        self.client.load_collection(collection)
        results = self.client.query(
            collection_name=collection,
            filter="",
            output_fields=["id", "text", "type", "name"],
        )
        return results if results else []

    def close(self) -> None:
        self.client.close()
