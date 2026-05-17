"""Initialize vector store with schema, metrics, and terms.

Usage:
    python scripts/init_vector_store.py
"""

from __future__ import annotations

import argparse
import yaml
from pathlib import Path

from nl2dsl.rag.store import MilvusLiteStore
from nl2dsl.rag.embedder import MockEmbedder


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_vector_store(uri: str = "./milvus_lite.db") -> None:
    store = MilvusLiteStore(uri=uri)
    embedder = MockEmbedder()

    # Create collections
    store.create_collection("schema", dimension=384)
    store.create_collection("metrics", dimension=384)
    store.create_collection("terms", dimension=384)
    store.create_collection("history", dimension=384)

    # Load configs
    configs_dir = Path("configs")
    metrics_yaml = configs_dir / "metrics.yaml"
    terms_yaml = configs_dir / "terms.yaml"

    records = []

    # Insert metrics
    if metrics_yaml.exists():
        data = load_yaml(str(metrics_yaml))
        for name, info in data.get("metrics", {}).items():
            text = f"指标: {name}, 计算方式: {info.get('expr', '')}, 说明: {info.get('description', '')}"
            records.append({
                "id": f"metric_{name}",
                "vector": embedder.embed(text),
                "text": text,
                "type": "metric",
                "name": name,
            })

        for name, info in data.get("dimensions", {}).items():
            text = f"维度: {name}, 字段: {info.get('column', '')}, 说明: {info.get('description', '')}"
            vm = info.get("value_map")
            if vm:
                text += f", 可选值: {', '.join(f'{k}({v})' for k, v in vm.items())}"
            records.append({
                "id": f"dim_{name}",
                "vector": embedder.embed(text),
                "text": text,
                "type": "dimension",
                "name": name,
            })

    if records:
        store.upsert("schema", records)
        store.upsert("metrics", [r for r in records if r["type"] == "metric"])
        print(f"Inserted {len(records)} schema/metric records")

    # Insert terms
    term_records = []
    if terms_yaml.exists():
        data = load_yaml(str(terms_yaml))
        for name, info in data.get("terms", {}).items():
            aliases = ", ".join(info.get("aliases", []))
            text = f"术语: {name}({aliases}), 说明: {info.get('description', '')}"
            term_records.append({
                "id": f"term_{name}",
                "vector": embedder.embed(text),
                "text": text,
                "type": "term",
                "name": name,
            })

    if term_records:
        store.upsert("terms", term_records)
        print(f"Inserted {len(term_records)} term records")

    print("Vector store initialized successfully")


def main():
    parser = argparse.ArgumentParser(description="Initialize vector store")
    parser.add_argument("--uri", default="./milvus_lite.db", help="Milvus Lite URI")
    args = parser.parse_args()

    init_vector_store(uri=args.uri)


if __name__ == "__main__":
    main()
