import pytest
from unittest.mock import patch, MagicMock
from nl2dsl.llm.client import LLMClient


@pytest.fixture
def client():
    return LLMClient(api_key="test-key", base_url="https://test.example.com", model="test-model")


def test_generate_dsl_mock(client):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"data_source": "orders", "metrics": []}'))]

    with patch.object(client._client.chat.completions, 'create', return_value=mock_response):
        result = client.generate("查询销售额", system_prompt="你是一个助手")
        assert "orders" in result
