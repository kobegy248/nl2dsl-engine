import time

from openai import OpenAI

from nl2dsl.utils.logger import get_logger

logger = get_logger("llm")


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        logger.info("LLMClient initialized: model=%s base_url=%s", model, base_url)

    def generate(self, user_prompt: str, system_prompt: str) -> str:
        start = time.time()
        logger.info("LLM request: model=%s prompt_length=%d", self._model, len(user_prompt))
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info("LLM response: tokens=%s time=%dms content_length=%d",
                    response.usage, elapsed, len(content) if content else 0)
        return content
