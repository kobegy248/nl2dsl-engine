from sqlalchemy import Engine, text


class SQLExecutor:
    def __init__(self, engine: Engine):
        self._engine = engine

    def execute(self, sql: str) -> list[dict]:
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = [dict(row._mapping) for row in result]
            return rows
