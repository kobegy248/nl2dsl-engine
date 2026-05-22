"""示例：使用 Ollama 作为 LLM 后端的插件。"""
from nl2dsl import Engine, Plugin


class OllamaLLM:
    def __init__(self, model: str, base_url: str = "http://localhost:11434/v1"):
        from openai import OpenAI
        self._client = OpenAI(api_key="ollama", base_url=base_url)
        self._model = model

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return resp.choices[0].message.content or ""

    @property
    def model_name(self) -> str:
        return self._model


class OllamaPlugin(Plugin):
    """替换默认 LLM 为 Ollama 本地模型。"""

    def register(self, engine: Engine) -> None:
        engine.register("llm", OllamaLLM(model="qwen3:8b"))


# 使用方式：
# engine = Engine()
# engine.use(OllamaPlugin())
# app = engine.build_fastapi_app()
