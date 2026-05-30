import json
import time

from openai import OpenAI

from nl2dsl.utils.logger import get_logger

logger = get_logger("llm")


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._thinking = None
        if "bigmodel.cn" in base_url or "zhipu" in base_url.lower():
            self._thinking = {"type": "enabled"}
            logger.info("Detected ZhipuAI backend, thinking enabled")
        logger.info("LLMClient initialized: model=%s base_url=%s", model, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        start = time.time()
        logger.info("LLM request: model=%s prompt_length=%d", self._model, len(user_prompt))
        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        if self._thinking:
            kwargs["extra_body"] = {"thinking": self._thinking}
        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content

    def generate_structured(self, user_prompt: str, system_prompt: str, json_schema: str) -> str:
        """Generate with JSON Schema enforcement via OpenAI structured output.

        Uses response_format={"type": "json_schema", ...} for deterministic
        JSON output. Always uses temperature=0.
        """
        start = time.time()
        logger.info("LLM structured request: model=%s schema_length=%d", self._model, len(json_schema))

        schema_dict = json_schema if isinstance(json_schema, dict) else json.loads(json_schema)

        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "dsl_response",
                    "strict": True,
                    "schema": schema_dict,
                },
            },
        }

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM structured response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content
