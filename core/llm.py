"""OpenAI-compatible LLM client — swappable via base_url / api_key / model.

The generator and the vision critic are deliberately DIFFERENT models (strong coder
writes the Manim code; a cheaper vision model checks the render). Both run through this
one client with a different `model`.

Wired in M0 but NOT called — the first real call lands in M1 (scene-spec generation).
`openai` is imported lazily so importing this module never requires network or a key.
"""
from __future__ import annotations

import json
from typing import Any

from core.config import settings


class LLMClient:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None) -> None:
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self._client: Any = None  # created lazily on first call

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI  # lazy: import only when actually calling out
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key or "not-set")
        return self._client

    def _with_cache(self, messages: list[dict], model: str | None) -> list[dict]:
        """Mark the large static system prompt as a cached prefix for Anthropic models
        (cache_control => ~90% off repeated input). No-op for other providers, which rely on
        automatic prefix caching (we already keep the system prompt as a stable prefix)."""
        if not settings.prompt_cache_enabled:
            return messages
        m = (model or self.model).lower()
        if "claude" not in m and "anthropic" not in m:
            return messages
        if not messages or messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str):
            return messages
        head = messages[0]
        cached = {**head, "content": [
            {"type": "text", "text": head["content"], "cache_control": {"type": "ephemeral"}}]}
        return [cached, *messages[1:]]

    def chat(self, messages: list[dict], *, model: str | None = None, **kw: Any) -> str:
        kw.setdefault("max_tokens", settings.max_output_tokens)  # cost + reservation cap (caller can override)
        resp = self.client.chat.completions.create(
            model=model or self.model, messages=self._with_cache(messages, model), **kw
        )
        return resp.choices[0].message.content or ""

    def chat_json(self, messages: list[dict], *, model: str | None = None, **kw: Any) -> dict:
        kw.setdefault("max_tokens", settings.max_output_tokens)
        resp = self.client.chat.completions.create(
            model=model or self.model, messages=self._with_cache(messages, model),
            response_format={"type": "json_object"}, **kw,
        )
        return json.loads(resp.choices[0].message.content or "{}")


def get_client(**kw: Any) -> LLMClient:
    return LLMClient(**kw)


def get_critic_client() -> LLMClient:
    """Vision-critic client. May live on a DIFFERENT provider than the generator
    (e.g. Groq generator + Gemini vision critic). Falls back to the generator's provider."""
    return LLMClient(
        base_url=settings.critic_base_url or settings.llm_base_url,
        api_key=settings.critic_api_key or settings.llm_api_key,
        model=settings.critic_model,
    )
