from __future__ import annotations

import json
from pathlib import Path


class FeedbackCollector:
    def __init__(self, storage_path: str = "./feedback.jsonl"):
        self._path = Path(storage_path)

    def collect(self, query_id: str, user_id: str, corrected_dsl: dict | None = None, comment: str = "") -> None:
        record = {
            "query_id": query_id,
            "user_id": user_id,
            "corrected_dsl": corrected_dsl,
            "comment": comment,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_feedback(self, limit: int = 100) -> list[dict]:
        if not self._path.exists():
            return []
        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records[-limit:]
