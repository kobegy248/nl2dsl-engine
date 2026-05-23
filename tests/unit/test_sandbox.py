import pytest
from sqlalchemy import create_engine, text

from nl2dsl.query.sandbox import QuerySandbox, SandboxResult


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                amount REAL,
                region TEXT
            )
        """))
        conn.execute(text("INSERT INTO orders (amount, region) VALUES (100, '华东')"))
        conn.execute(text("INSERT INTO orders (amount, region) VALUES (200, '华南')"))
        conn.commit()
    return engine


@pytest.fixture
def sandbox(db_engine):
    return QuerySandbox(db_engine, max_scan_rows=1_000_000, max_exec_time_ms=10_000)


class TestQuerySandbox:
    def test_safe_query_passes(self, sandbox):
        result = sandbox.check("SELECT * FROM orders WHERE region = '华东'")
        assert isinstance(result, SandboxResult)
        assert result.passed is True
        assert len(result.risks) == 0
        assert len(result.sample_rows) > 0

    def test_missing_where_fails(self, sandbox):
        result = sandbox.check("SELECT * FROM orders")
        assert result.passed is False
        assert any("WHERE" in r for r in result.risks)

    def test_preview_limit_injected(self, sandbox):
        result = sandbox.check("SELECT * FROM orders WHERE region = '华东'")
        # LIMIT 10 should be injected, so we get at most 10 rows
        assert len(result.sample_rows) <= 10

    def test_existing_limit_not_double_injected(self, sandbox):
        result = sandbox.check("SELECT * FROM orders WHERE region = '华东' LIMIT 1")
        assert len(result.sample_rows) <= 1

    def test_explain_returns_estimate(self, sandbox):
        result = sandbox.check("SELECT * FROM orders WHERE region = '华东'")
        assert result.estimated_rows >= 0

    def test_risk_when_scan_too_large(self, db_engine):
        # Set very low threshold to trigger risk
        strict = QuerySandbox(db_engine, max_scan_rows=1, max_exec_time_ms=10_000)
        result = strict.check("SELECT * FROM orders WHERE region = '华东'")
        assert any("扫描" in r for r in result.risks)

    def test_invalid_sql_returns_risk(self, sandbox):
        result = sandbox.check("SELECT * FROM not_a_table")
        assert result.passed is False
        assert any("预览执行失败" in r or "WHERE" in r for r in result.risks)

    def test_sandbox_result_fields(self, sandbox):
        result = sandbox.check("SELECT * FROM orders WHERE region = '华东'")
        assert hasattr(result, "passed")
        assert hasattr(result, "risks")
        assert hasattr(result, "sample_rows")
        assert hasattr(result, "estimated_rows")
        assert hasattr(result, "execution_time_ms")
        assert result.execution_time_ms >= 0

    def test_inject_limit_appends(self, sandbox):
        sql = "SELECT * FROM orders WHERE region = '华东'"
        limited = sandbox._inject_limit(sql, 5)
        assert "LIMIT 5" in limited

    def test_inject_limit_skips_existing(self, sandbox):
        sql = "SELECT * FROM orders LIMIT 3"
        limited = sandbox._inject_limit(sql, 5)
        assert limited == sql
