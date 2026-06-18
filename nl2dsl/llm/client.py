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
        self._structured_disabled = False
        self._json_object_disabled = False
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

    def generate_structured(self, user_prompt: str, system_prompt: str, json_schema: str | dict) -> str:
        """Generate with JSON Schema enforcement via OpenAI structured output.

        Uses response_format={"type": "json_schema", ...} for deterministic
        JSON output. Always uses temperature=0 for maximum determinism in
        structured output.
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

    def generate_json_object(self, user_prompt: str, system_prompt: str) -> str:
        """Generate with ``response_format: json_object`` (non-strict JSON).

        Less powerful than strict json_schema (no enum enforcement) but widely
        supported by OpenAI-compatible endpoints that reject strict mode — it
        at least guarantees the output parses as JSON, so the post-processor's
        operator-alias normalization and the validator run on well-formed input.
        """
        start = time.time()
        logger.info("[llm] json_object request: model=%s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        elapsed = int((time.time() - start) * 1000)
        logger.info(
            "[llm] json_object response: tokens=%s time=%dms content_length=%d",
            response.usage, elapsed, len(content) if content else 0,
        )
        return content

    def generate_with_schema_fallback(
        self, user_prompt: str, system_prompt: str, json_schema: str | dict
    ) -> str:
        """Generate DSL JSON with the strongest structured mode the endpoint supports.

        Fallback chain:
          1. ``response_format: json_schema`` (strict) — constrains operator/func
             enums so the model cannot emit illegal operators like ``time_range``.
          2. ``response_format: json_object`` — guarantees valid JSON; the
             post-processor then normalizes operators.
          3. plain generation — last resort; prompt + post-processor still
             validate the output.

        Each tier is sticky-disabled once an endpoint rejects it, so subsequent
        calls skip straight to the highest tier that works (no wasted round-trips).
        """
        if not self._structured_disabled:
            try:
                return self.generate_structured(user_prompt, system_prompt, json_schema)
            except Exception as exc:
                msg = str(exc).lower()
                if any(
                    s in msg
                    for s in (
                        "response_format", "json_schema", "json schema",
                        "not support", "unsupported", "invalid_request",
                        "bad request", "400", "unavailable",
                    )
                ):
                    logger.warning(
                        "[llm] Strict json_schema unsupported by endpoint, "
                        "trying json_object: %s", exc
                    )
                    self._structured_disabled = True
                else:
                    raise
        if not self._json_object_disabled:
            try:
                return self.generate_json_object(user_prompt, system_prompt)
            except Exception as exc:
                msg = str(exc).lower()
                if any(
                    s in msg
                    for s in (
                        "response_format", "json_object", "json object",
                        "not support", "unsupported", "invalid_request",
                        "bad request", "400", "unavailable",
                    )
                ):
                    logger.warning(
                        "[llm] json_object unsupported by endpoint, "
                        "falling back to plain generation: %s", exc
                    )
                    self._json_object_disabled = True
                else:
                    raise
        return self.generate(user_prompt, system_prompt)
