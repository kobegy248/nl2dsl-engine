import pytest
import tempfile
import os
from nl2dsl.rag.store import MilvusLiteStore
from nl2dsl.rag.embedder import MockEmbedder


@pytest.fixture
def store():
    tmpdir = tempfile.mkdtemp()
    uri = os.path.join(tmpdir, "test.db")
    store = MilvusLiteStore(uri=uri)
    yield store
    store.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_create_collection(store):
    store.create_collection("test_schema", dimension=384)
    assert store.has_collection("test_schema")


def test_upsert_and_search(store):
    store.create_collection("test_schema", dimension=3)

    records = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "text": "销售额指标",
            "metadata": {"type": "metric"},
        },
        {
            "id": 2,
            "vector": [0.0, 1.0, 0.0],
            "text": "订单表",
            "metadata": {"type": "table"},
        },
    ]
    store.upsert("test_schema", records)

    results = store.search("test_schema", vector=[1.0, 0.0, 0.0], limit=1)
    assert len(results) == 1
    assert results[0]["text"] == "销售额指标"
