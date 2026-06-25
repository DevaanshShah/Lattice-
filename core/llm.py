"""OpenAI-compatible LLM client — swappable via base_url / api_key / model.

The generator and the vision critic are deliberately DIFFERENT models (strong coder
writes the Manim code; a cheaper vision model checks the render). Both run through this
one client with a different `model`.

Wired in M0 but NOT called — the first real call lands in M1 (scene-spec generation).
`openai` is imported lazily so importing this module never requires network or a key.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from core.config import settings

# --- process-wide token + cost accounting (the eval cost metric) -----------------------------
# Every chat()/chat_json() call adds its `resp.usage` here, regardless of which client instance
# made it — so a whole pipeline run (spec-gen + codegen + repairs + critic, across threads) can
# be measured by reset_usage() before and usage_snapshot() after. Best-effort cost via a per-model
# price table (USD per 1M tokens, input/output); unknown models contribute 0 cost but still count tokens.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.0),
    "deepseek/deepseek-v4-pro": (0.40, 1.20),
    "deepseek/deepseek-chat": (0.28, 0.88),
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
}

_usage_lock = threading.Lock()
_usage: dict[str, float] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Best-effort USD cost from MODEL_PRICES; 0.0 for unknown models (tokens are still tracked)."""
    price = MODEL_PRICES.get((model or "").lower())
    if not price:
        return 0.0
    pin, pout = price
    return prompt_tokens / 1_000_000 * pin + completion_tokens / 1_000_000 * pout


def reset_usage() -> None:
    """Zero the accumulator (call before measuring a unit of work, e.g. one eval prompt)."""
    with _usage_lock:
        _usage.update(prompt_tokens=0, completion_tokens=0, calls=0, cost_usd=0.0)


def usage_snapshot() -> dict:
    """A copy of the current totals: {prompt_tokens, completion_tokens, calls, cost_usd}."""
    with _usage_lock:
        return dict(_usage)


def _record_usage(model: str, resp: Any) -> None:
    """Add one response's token usage to the process-wide accumulator (no-op if absent)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    pt = int(getattr(u, "prompt_tokens", 0) or 0)
    ct = int(getattr(u, "completion_tokens", 0) or 0)
    with _usage_lock:
        _usage["prompt_tokens"] += pt
        _usage["completion_tokens"] += ct
        _usage["calls"] += 1
        _usage["cost_usd"] += estimate_cost(model, pt, ct)


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
        _record_usage(model or self.model, resp)
        return resp.choices[0].message.content or ""

    def chat_json(self, messages: list[dict], *, model: str | None = None, **kw: Any) -> dict:
        kw.setdefault("max_tokens", settings.max_output_tokens)
        resp = self.client.chat.completions.create(
            model=model or self.model, messages=self._with_cache(messages, model),
            response_format={"type": "json_object"}, **kw,
        )
        _record_usage(model or self.model, resp)
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
