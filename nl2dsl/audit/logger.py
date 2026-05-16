import json
import uuid
from sqlalchemy import Engine, text


class AuditLogger:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._ensure_table()

    def _ensure_table(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS nl2dsl_audit_log (
            query_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tenant_id TEXT DEFAULT '',
            question TEXT NOT NULL,
            dsl_json TEXT,
            sql_text TEXT,
            status TEXT NOT NULL,
            execution_time_ms INTEGER,
            rows_scanned INTEGER,
            rows_returned INTEGER,
            trace_json TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        with self._engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

    def log(self, **kwargs) -> None:
        fields = [
            "query_id", "user_id", "tenant_id", "question",
            "dsl_json", "sql_text", "status", "execution_time_ms",
            "rows_scanned", "rows_returned", "trace_json",
            "error_code", "error_message",
        ]

        data = {k: kwargs.get(k) for k in fields}
        if not data["query_id"]:
            data["query_id"] = str(uuid.uuid4())

        # JSON serialize
        for json_field in ["dsl_json", "trace_json"]:
            if data.get(json_field) is not None and not isinstance(data[json_field], str):
                data[json_field] = json.dumps(data[json_field], ensure_ascii=False)

        placeholders = ", ".join([f":{k}" for k in fields])
        columns = ", ".join(fields)
        sql = f"INSERT INTO nl2dsl_audit_log ({columns}) VALUES ({placeholders})"

        with self._engine.connect() as conn:
            conn.execute(text(sql), data)
            conn.commit()

    def query(self, sql: str) -> list[dict]:
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            return [dict(row._mapping) for row in result]
