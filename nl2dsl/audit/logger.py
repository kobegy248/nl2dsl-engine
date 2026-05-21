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

    def get_query(self, query_id: str) -> dict | None:
        """Return one audit record (with dsl/sql/trace decoded), or None."""
        with self._engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM nl2dsl_audit_log WHERE query_id = :qid"),
                {"qid": query_id},
            )
            row = result.first()
        if row is None:
            return None
        record = dict(row._mapping)
        record["dsl"] = json.loads(record.pop("dsl_json")) if record.get("dsl_json") else None
        record["sql"] = record.pop("sql_text")
        record["trace"] = json.loads(record.pop("trace_json")) if record.get("trace_json") else []
        return record

    _LIST_COLUMNS = (
        "query_id, user_id, tenant_id, question, status, "
        "execution_time_ms, rows_returned, error_code, created_at"
    )

    def list_queries(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        question_like: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: dict = {}

        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if start_time is not None:
            clauses.append("created_at >= :start_time")
            params["start_time"] = start_time
        if end_time is not None:
            clauses.append("created_at <= :end_time")
            params["end_time"] = end_time
        if question_like is not None:
            clauses.append("question LIKE :q_like")
            params["q_like"] = f"%{question_like}%"

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        list_sql = (
            f"SELECT {self._LIST_COLUMNS} FROM nl2dsl_audit_log {where} "
            f"ORDER BY created_at DESC, query_id DESC "
            f"LIMIT :limit OFFSET :offset"
        )
        count_sql = f"SELECT COUNT(*) FROM nl2dsl_audit_log {where}"

        with self._engine.connect() as conn:
            list_params = {**params, "limit": limit, "offset": offset}
            items = [dict(r._mapping) for r in conn.execute(text(list_sql), list_params)]
            total = conn.execute(text(count_sql), params).scalar() or 0

        return items, int(total)
