from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NL2DSL_",
    )

    llm_api_key: str = "ollama"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen3:8b"

    db_url: str = "sqlite:///./nl2dsl.db"
    max_limit: int = 10000
    query_timeout: int = 30

    vector_store_type: str = "milvus_lite"
    milvus_uri: str = "./milvus_lite.db"
    milvus_host: str = "localhost"
    milvus_port: int = 19530


settings = Settings()
