from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NL2DSL_",
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_model: str = "glm-4.5-air"

    db_url: str = "sqlite:///./nl2dsl.db"
    max_limit: int = 10000
    query_timeout: int = 30

    vector_store_type: str = "milvus_lite"
    milvus_uri: str = "./milvus_lite.db"
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # Reranker settings
    reranker_enabled: bool = True
    reranker_model: str = "D:/claude_work/model/bge-reranker-base"
    reranker_device: str = "cpu"
    reranker_coarse_k: int = 10
    reranker_fine_n: int = 5
    reranker_threshold: float = 0.5
    reranker_max_context_chars: int = 4000


settings = Settings()
