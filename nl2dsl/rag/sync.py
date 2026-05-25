"""RAG 向量库同步逻辑。

设计：
- 每个 YAML 配置文件对应一个或多个集合
- 通过状态文件记录 YAML 的 mtime，启动时检查是否过期
- 按需增量同步，无需手动运行脚本

集合映射：
- configs/metrics.yaml -> schema + metrics
- configs/terms.yaml   -> terms
- configs/history.yaml -> history
"""

from __future__ import annotations

import hashlib
import json
import yaml
from pathlib import Path
from typing import Any

from nl2dsl.rag.base import VectorStore
from nl2dsl.rag.embedder import BGEEmbedder, MockEmbedder
from nl2dsl.utils.logger import get_logger

logger = get_logger("rag.sync")


# YAML 文件 -> Milvus collection 的映射
_CONFIG_COLLECTIONS = {
    "metrics.yaml": ["schema", "metrics"],
    "terms.yaml": ["terms"],
    "history.yaml": ["history"],
}


def _hash_id(s: str) -> int:
    """Milvus needs integer IDs; hash string to int64."""
    h = hashlib.md5(s.encode()).hexdigest()
    return int(h[:15], 16)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _ensure_collections(store: VectorStore, names: list[str], dim: int) -> None:
    """Create missing collections."""
    for name in names:
        if not store.has_collection(name):
            store.create_collection(name, dimension=dim)
            logger.info("Created collection: %s (dim=%d)", name, dim)


def _build_metrics_records(metrics_yaml: dict, embedder) -> tuple[list[dict], list[dict]]:
    """Build records for schema and metrics collections."""
    schema_records = []
    metric_records = []

    for name, info in metrics_yaml.get("metrics", {}).items():
        text = f"指标: {name}, 计算: {info.get('expr', '')}, 说明: {info.get('description', '')}"
        rec = {
            "id": _hash_id(f"metric_{name}"),
            "vector": embedder.embed(text),
            "text": text,
            "type": "metric",
            "name": name,
        }
        schema_records.append(rec)
        metric_records.append(rec)

    for name, info in metrics_yaml.get("dimensions", {}).items():
        text = f"维度: {name}, 字段: {info.get('column', name)}, 说明: {info.get('description', '')}"
        schema_records.append({
            "id": _hash_id(f"dim_{name}"),
            "vector": embedder.embed(text),
            "text": text,
            "type": "dimension",
            "name": name,
        })

    return schema_records, metric_records


def _build_terms_records(terms_yaml: dict, embedder) -> list[dict]:
    """Build records for terms collection (含每个 alias 单独入库)."""
    records = []
    for name, info in terms_yaml.get("terms", {}).items():
        aliases = info.get("aliases", []) or []
        text = f"术语: {name}, 别名: {', '.join(aliases)}, 说明: {info.get('description', '')}"
        records.append({
            "id": _hash_id(f"term_{name}"),
            "vector": embedder.embed(text),
            "text": text,
            "type": "term",
            "name": name,
        })
        for i, alias in enumerate(aliases):
            records.append({
                "id": _hash_id(f"term_alias_{name}_{i}"),
                "vector": embedder.embed(alias),
                "text": f"{alias} -> {name}",
                "type": "term_alias",
                "name": alias,
            })
    return records


def _build_history_records(history_yaml: dict, embedder) -> list[dict]:
    """Build records for history collection (问题 -> DSL 示例)."""
    records = []
    for i, example in enumerate(history_yaml.get("examples", [])):
        question = example.get("question", "")
        dsl = example.get("dsl", {})
        text = f"问题: {question}\nDSL: {json.dumps(dsl, ensure_ascii=False)}"
        records.append({
            "id": _hash_id(f"history_{i}_{question}"),
            "vector": embedder.embed(question),  # 只 embed question
            "text": text,
            "type": "history",
            "name": question,
        })
    return records


def _sync_yaml(
    store: VectorStore,
    embedder,
    yaml_name: str,
    yaml_path: Path,
) -> tuple[bool, int]:
    """同步单个 YAML 文件到对应的集合。

    Returns:
        (synced, count): 是否同步、写入条数
    """
    if not yaml_path.exists():
        logger.warning("YAML not found, skip: %s", yaml_path)
        return False, 0

    data = _load_yaml(yaml_path)
    if yaml_name == "metrics.yaml":
        schema_records, metric_records = _build_metrics_records(data, embedder)
        if schema_records:
            store.upsert("schema", schema_records)
        if metric_records:
            store.upsert("metrics", metric_records)
        count = len(schema_records) + len(metric_records)
    elif yaml_name == "terms.yaml":
        records = _build_terms_records(data, embedder)
        if records:
            store.upsert("terms", records)
        count = len(records)
    elif yaml_name == "history.yaml":
        records = _build_history_records(data, embedder)
        if records:
            store.upsert("history", records)
        count = len(records)
    else:
        return False, 0

    logger.info("Synced %s -> %d records", yaml_name, count)
    return True, count


def _read_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def auto_sync(
    store: VectorStore,
    embedder=None,
    configs_dir: str | Path = "configs",
    state_file: str | Path = ".rag_sync_state.json",
    force: bool = False,
) -> dict[str, int]:
    """启动时自检：对比 YAML mtime 和上次同步状态，按需增量同步。

    Args:
        store: 向量存储后端
        embedder: 向量化器（None 则用 BGE）
        configs_dir: YAML 配置目录
        state_file: 状态文件路径
        force: 强制全量同步

    Returns:
        每个 YAML 同步的记录数字典
    """
    configs_dir = Path(configs_dir)
    state_path = Path(state_file)
    state = _read_state(state_path)
    result: dict[str, int] = {}

    embedder_instance = None  # 延迟初始化，避免无需同步时加载 BGE

    for yaml_name, collections in _CONFIG_COLLECTIONS.items():
        yaml_path = configs_dir / yaml_name
        if not yaml_path.exists():
            continue

        mtime = yaml_path.stat().st_mtime
        prev_mtime = state.get(yaml_name, {}).get("mtime", 0)

        # 检查集合是否存在
        collections_missing = any(not store.has_collection(c) for c in collections)
        needs_sync = force or collections_missing or mtime > prev_mtime

        if not needs_sync:
            logger.info("RAG sync: %s up-to-date (mtime=%s)", yaml_name, prev_mtime)
            continue

        # 延迟初始化 embedder
        if embedder_instance is None:
            embedder_instance = embedder or BGEEmbedder()
            dim = embedder_instance._dim
            _ensure_collections(store, list({c for cs in _CONFIG_COLLECTIONS.values() for c in cs}), dim)

        synced, count = _sync_yaml(store, embedder_instance, yaml_name, yaml_path)
        if synced:
            result[yaml_name] = count
            state[yaml_name] = {"mtime": mtime, "synced_records": count}

    if result:
        _write_state(state_path, state)
        logger.info("RAG sync completed: %s", result)
    else:
        logger.info("RAG sync: all up-to-date, nothing to do")

    return result
