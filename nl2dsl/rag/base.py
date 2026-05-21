from abc import ABC, abstractmethod


class VectorStore(ABC):
    @abstractmethod
    def create_collection(self, name: str, dimension: int) -> None: ...

    @abstractmethod
    def has_collection(self, name: str) -> bool: ...

    @abstractmethod
    def upsert(self, collection: str, records: list[dict]) -> None: ...

    @abstractmethod
    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]: ...

    @abstractmethod
    def get_all(self, collection: str) -> list[dict]: ...
