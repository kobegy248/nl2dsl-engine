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


def test_generate_structured_calls_openai_with_json_schema():
    """generate_structured passes response_format with json_schema."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"data_source": "orders", "metrics": []}'
    mock_response.usage = MagicMock()

    with patch.object(client._client.chat.completions, "create", return_value=mock_response) as mock_create:
        schema = '{"type": "object", "properties": {"data_source": {"type": "string"}}}'
        result = client.generate_structured("user prompt", "system prompt", schema)

        assert result == '{"data_source": "orders", "metrics": []}'
        call_kwargs = mock_create.call_args.kwargs
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert "json_schema" in call_kwargs["response_format"]
        assert call_kwargs["temperature"] == 0


def test_generate_structured_uses_temperature_zero():
    """Structured output always uses temperature=0 for determinism."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "{}"
    mock_response.usage = MagicMock()

    with patch.object(client._client.chat.completions, "create", return_value=mock_response) as mock_create:
        client.generate_structured("prompt", "sys", "{}")
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["temperature"] == 0


def test_generate_structured_accepts_dict_schema():
    """generate_structured accepts json_schema as dict."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "{}"
    mock_response.usage = MagicMock()

    with patch.object(client._client.chat.completions, "create", return_value=mock_response) as mock_create:
        schema_dict = {"type": "object", "properties": {"x": {"type": "string"}}}
        client.generate_structured("prompt", "sys", schema_dict)
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["response_format"]["json_schema"]["schema"] == schema_dict


def test_generate_with_schema_fallback_uses_structured_when_supported():
    """Prefers strict structured output when the endpoint supports it."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    with patch.object(client, "generate_structured", return_value='{"data_source": "orders"}') as m_struct, \
         patch.object(client, "generate_json_object") as m_json, \
         patch.object(client, "generate") as m_plain:
        result = client.generate_with_schema_fallback("p", "s", "{}")
        assert result == '{"data_source": "orders"}'
        m_struct.assert_called_once()
        m_json.assert_not_called()
        m_plain.assert_not_called()


def test_generate_with_schema_fallback_falls_through_to_json_object():
    """Strict rejected -> json_object tier; both sticky-disabled appropriately."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    def boom(*a, **k):
        raise Exception("400 response_format json_schema unavailable now")

    with patch.object(client, "generate_structured", side_effect=boom), \
         patch.object(client, "generate_json_object", return_value='{"data_source": "orders"}') as m_json, \
         patch.object(client, "generate") as m_plain:
        result = client.generate_with_schema_fallback("p", "s", "{}")
        assert result == '{"data_source": "orders"}'
        m_json.assert_called_once()
        m_plain.assert_not_called()
        # Sticky: strict disabled, second call goes straight to json_object.
        with patch.object(client, "generate_structured") as m_struct2, \
             patch.object(client, "generate_json_object", return_value='{"data_source": "orders"}') as m_json2:
            client.generate_with_schema_fallback("p", "s", "{}")
            m_struct2.assert_not_called()
            m_json2.assert_called_once()


def test_generate_with_schema_fallback_falls_through_to_plain():
    """Both structured tiers rejected -> plain generation, all sticky."""
    client = LLMClient(api_key="test-key", base_url="https://api.example.com", model="test-model")

    def boom(*a, **k):
        raise Exception("400 response_format unavailable")

    with patch.object(client, "generate_structured", side_effect=boom), \
         patch.object(client, "generate_json_object", side_effect=boom), \
         patch.object(client, "generate", return_value='{"data_source": "orders"}') as m_plain:
        result = client.generate_with_schema_fallback("p", "s", "{}")
        assert result == '{"data_source": "orders"}'
        m_plain.assert_called_once()
        # Sticky: second call skips both structured tiers straight to plain.
        with patch.object(client, "generate_structured") as m_struct2, \
             patch.object(client, "generate_json_object") as m_json2, \
             patch.object(client, "generate", return_value='{"data_source": "orders"}') as m_plain2:
            client.generate_with_schema_fallback("p", "s", "{}")
            m_struct2.assert_not_called()
            m_json2.assert_not_called()
            m_plain2.assert_called_once()
