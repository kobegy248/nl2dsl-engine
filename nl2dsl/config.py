from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NL2DSL_",
    )

    # LLM 配置：单一 provider（向后兼容，等价于名为 "default" 的 provider）
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_model: str = "glm-4.5-air"

    # 多 provider 支持：可同时注册多个模型服务并随时切换
    # - llm_provider: 当前激活的 provider 名（默认 "default"）
    # - llm_providers: JSON 字符串，name -> {api_key, base_url, model}
    #   例: NL2DSL_LLM_PROVIDERS='{"deepseek":{"api_key":"sk-..","base_url":"https://api.deepseek.com","model":"deepseek-v4-pro"},"glm":{"api_key":"..","base_url":"https://open.bigmodel.cn/api/paas/v4/","model":"glm-4.5-air"}}'
    llm_provider: str = "default"
    llm_providers: str = ""

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
