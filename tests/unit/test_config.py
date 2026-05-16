import os
from nl2dsl.config import Settings


def test_settings_loads_from_env():
    os.environ["NL2DSL_LLM_API_KEY"] = "test-key"
    os.environ["NL2DSL_LLM_BASE_URL"] = "https://test.example.com"
    os.environ["NL2DSL_LLM_MODEL"] = "test-model"
    os.environ["NL2DSL_DB_URL"] = "sqlite:///./test.db"

    settings = Settings()
    assert settings.llm_api_key == "test-key"
    assert settings.llm_base_url == "https://test.example.com"
    assert settings.llm_model == "test-model"
    assert settings.db_url == "sqlite:///./test.db"
