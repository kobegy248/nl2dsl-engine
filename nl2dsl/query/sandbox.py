"""Query sandbox for pre-execution safety checks.

Runs EXPLAIN and LIMIT 10 preview before executing production SQL
to detect expensive queries, full scans, and other risks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Engine, text


@dataclass
class SandboxResult:
    passed: bool
    risks: list[str]
    sample_rows: list[dict]
    estimated_rows: int = -1
    execution_time_ms: float = -1.0


class QuerySandbox:
    """Pre-execution safety sandbox for SQL queries.

    Checks:
    1. Runs EXPLAIN QUERY PLAN to estimate scan cost
    2. Runs LIMIT 10 preview to check execution time
    3. Detects full table scans and missing filters
    """

    def __init__(
        self,
        engine: Engine,
        max_scan_rows: int = 100_000,
        max_exec_time_ms: float = 5_000,
        preview_limit: int = 10,
    ):
        self._engine = engine
        self._max_scan_rows = max_scan_rows
        self._max_exec_time_ms = max_exec_time_ms
        self._preview_limit = preview_limit

    def check(self, sql: str) -> SandboxResult:
        """Run safety checks on SQL before production execution."""
        risks: list[str] = []

        # 1. EXPLAIN QUERY PLAN (SQLite-specific)
        estimated_rows = self._explain(sql)
        if estimated_rows > self._max_scan_rows:
            risks.append(
                f"预估扫描 {estimated_rows:,} 行，超过阈值 {self._max_scan_rows:,}"
            )

        # 2. Preview execution with LIMIT
        preview_sql = self._inject_limit(sql, self._preview_limit)
        start = time.time()
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(preview_sql))
                sample_rows = [dict(row._mapping) for row in result]
        except Exception as e:
            risks.append(f"预览执行失败: {e}")
            sample_rows = []
        elapsed_ms = (time.time() - start) * 1000

        if elapsed_ms > self._max_exec_time_ms:
            risks.append(
                f"预览执行时间 {elapsed_ms:.0f}ms，超过阈值 {self._max_exec_time_ms:.0f}ms"
            )

        # 3. Heuristic: detect full scan or missing filters (only flag if scan is large)
        if "WHERE" not in sql.upper() and estimated_rows > self._max_scan_rows:
            risks.append("SQL 缺少 WHERE 条件，可能触发全表扫描")

        return SandboxResult(
            passed=len(risks) == 0,
            risks=risks,
            sample_rows=sample_rows,
            estimated_rows=estimated_rows,
            execution_time_ms=elapsed_ms,
        )

    def _explain(self, sql: str) -> int:
        """Run EXPLAIN QUERY PLAN and estimate rows to scan."""
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT"):
            # Only allow EXPLAIN on SELECT statements
            return -1
        try:
            with self._engine.connect() as conn:
                # Use text() to ensure the SQL is treated as a single statement.
                # The SQL string here comes from SQLBuilder (SQLAlchemy compiled),
                # so it is already a valid SELECT.  The guard above prevents
                # injection of other statement types.
                result = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"))
                rows = result.fetchall()
                # Heuristic: count SCAN operations and estimate
                scan_count = sum(
                    1 for r in rows
                    if "SCAN" in str(r) or "SEARCH" in str(r)
                )
                # Return a rough estimate (real production would use actual row counts)
                return scan_count * 1000
        except Exception:
            return -1

    def _inject_limit(self, sql: str, limit: int) -> str:
        """Inject LIMIT clause into SELECT statement.

        Defensive: validates *limit* is an integer and that the SQL already
        contains a SELECT.  If LIMIT already exists, returns the SQL unchanged.
        """
        if not isinstance(limit, int):
            raise ValueError(f"LIMIT must be an integer, got {type(limit).__name__}")
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT"):
            raise ValueError("Only SELECT statements can have LIMIT injected")
        if "LIMIT" in stripped:
            return sql
        return f"{sql} LIMIT {limit}"
