import pytest
from unittest.mock import MagicMock
from nl2dsl.llm.agent import QueryAgent, QueryResult


@pytest.fixture
def agent():
    llm = MagicMock()
    retriever = MagicMock()
    validator = MagicMock()
    resolver = MagicMock()
    rls = MagicMock()
    builder = MagicMock()
    scanner = MagicMock()
    executor = MagicMock()
    audit = MagicMock()

    return QueryAgent(
        llm_client=llm,
        retriever=retriever,
        validator=validator,
        resolver=resolver,
        row_level=rls,
        sql_builder=builder,
        sql_scanner=scanner,
        sql_executor=executor,
        audit_logger=audit,
    )


def test_query_mock_fallback(agent):
    # LLM fails, falls back to mock DSL
    agent._llm.generate = MagicMock(side_effect=Exception("no API key"))
    agent._retriever.build_prompt = MagicMock(return_value="mock prompt")
    agent._validator.validate = MagicMock()
    agent._resolver.resolve = MagicMock(side_effect=lambda x: x)
    agent._rls.inject = MagicMock(side_effect=lambda x, y: x)
    agent._builder.build = MagicMock(return_value="SELECT 1")
    agent._scanner.scan = MagicMock()
    agent._executor.execute = MagicMock(return_value=[{"a": 1}])

    result = agent.query("查询华东地区销售额", "u001", "t001")
    assert result.status == "success"
    assert result.data == [{"a": 1}]
    assert result.sql == "SELECT 1"


def test_query_error_handling(agent):
    agent._llm.generate = MagicMock(side_effect=Exception("fail"))
    agent._retriever.build_prompt = MagicMock(return_value="prompt")
    agent._validator.validate = MagicMock(side_effect=Exception("validation failed"))

    result = agent.query("test", "u001", "t001")
    assert result.status == "error"
