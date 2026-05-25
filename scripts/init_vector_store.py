"""Initialize / re-sync vector store.

通常情况下不需要手动运行，后端启动会自动同步 YAML 到向量库。
仅在以下场景使用：
1. 首次部署
2. 需要强制重建（--rebuild）

Usage:
    python scripts/init_vector_store.py          # 增量同步（同启动自检）
    python scripts/init_vector_store.py --force  # 强制全量同步
"""

from __future__ import annotations

import argparse
from pathlib import Path

from nl2dsl.rag.store import MilvusLiteStore
from nl2dsl.rag.embedder import BGEEmbedder
from nl2dsl.rag.sync import auto_sync


def main():
    parser = argparse.ArgumentParser(description="Initialize vector store")
    parser.add_argument("--uri", default="./milvus_lite.db", help="Milvus Lite URI")
    parser.add_argument("--configs", default="configs", help="Configs directory")
    parser.add_argument("--state", default=".rag_sync_state.json", help="Sync state file")
    parser.add_argument("--force", action="store_true", help="Force full re-sync")
    args = parser.parse_args()

    store = MilvusLiteStore(uri=args.uri)
    embedder = BGEEmbedder()

    result = auto_sync(
        store=store,
        embedder=embedder,
        configs_dir=args.configs,
        state_file=args.state,
        force=args.force,
    )

    if result:
        print("Synced:", result)
    else:
        print("Already up-to-date.")


if __name__ == "__main__":
    main()
