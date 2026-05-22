import pytest
from nl2dsl.protocols import LLMBackend, SQLBuilder, SQLExecutor, SQLScanner, Validator
from nl2dsl.llm.client import LLMClient
from nl2dsl.sql_engine.builder import SQLBuilder as _SQLBuilder
from nl2dsl.sql_engine.executor import SQLExecutor as _SQLExecutor
from nl2dsl.sql_engine.scanner import SQLScanner as _SQLScanner
from nl2dsl.dsl.validator import DSLValidator


class TestProtocolCompliance:
    def test_llm_client(self):
        client = LLMClient(api_key="t", base_url="http://t", model="t")
        assert isinstance(client, LLMBackend)

    def test_sql_builder(self):
        from sqlalchemy import create_engine
        builder = _SQLBuilder(create_engine("sqlite:///:memory:"), {})
        assert isinstance(builder, SQLBuilder)

    def test_sql_executor(self):
        from sqlalchemy import create_engine
        executor = _SQLExecutor(create_engine("sqlite:///:memory:"))
        assert isinstance(executor, SQLExecutor)

    def test_sql_scanner(self):
        assert isinstance(_SQLScanner(), SQLScanner)

    def test_dsl_validator(self):
        assert isinstance(DSLValidator({}), Validator)
