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
import time
from typing import Any

from core import cancel
from core.config import settings


def _is_transient(e: Exception) -> bool:
    """5xx / 429 / timeouts / dropped connections are safe to retry; 4xx (auth, bad request)
    are not — those are deterministic and would just burn attempts."""
    code = getattr(e, "status_code", None)
    if code is not None:
        return code == 429 or code >= 500
    return type(e).__name__ in {
        "APIConnectionError", "APITimeoutError", "InternalServerError",
        "RateLimitError", "ServiceUnavailableError",
    }

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
    # live product generator (V3-0324). Same model family as deepseek-chat, so priced the same;
    # tune to your AiCredits key's real per-token rate if it differs. Both id forms so estimate_cost
    # matches whether the model is referenced with or without the provider prefix.
    "deepseek/deepseek-chat-v3-0324": (0.28, 0.88),
    "deepseek-chat-v3-0324": (0.28, 0.88),
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
            # timeout: without it the SDK's own default (10 min) elapses before _create's retry
            # policy gets a turn, so a wedged route looks like a hung job.
            # max_retries=0: the SDK retries transient errors too, which would multiply with our
            # loop (6 x 3 = 18 hidden attempts). _create is the single retry authority.
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key or "not-set",
                                  timeout=settings.llm_timeout_s, max_retries=0)
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

    def _create(self, *, attempts: int | None = None, **kwargs: Any) -> Any:
        """API call with bounded retry on transient errors (5xx/429/timeout) AND on an empty
        message — some gateway-routed models (e.g. deepseek v3.2/v4 on AiCredits) intermittently
        500 or return blank content (AiCredits 500-streaks for ~10-20s, so retry persistently).
        4xx (auth/bad request) raise immediately (no point retrying)."""
        attempts = settings.llm_attempts if attempts is None else attempts
        # OpenRouter routes each call to some upstream host. Two competing goals:
        #  - latency: sort:throughput picks the fastest host (but scatters providers per call).
        #  - COST: a stable provider keeps that host's automatic prefix cache warm, so the big static
        #    system prompt is billed at the cached rate (~90% off) instead of full price every call.
        # Pinning a provider (llm_provider_pin) chooses cost; allow_fallbacks keeps reliability.
        # No-op for direct providers (DeepSeek/AiCredits) that ignore the `provider` field.
        if "openrouter.ai" in (self.base_url or ""):
            eb = dict(kwargs.get("extra_body") or {})
            prov = dict(eb.get("provider") or {})
            if settings.llm_provider_pin:
                prov.setdefault("order", [settings.llm_provider_pin])
                prov.setdefault("allow_fallbacks", True)   # warm cache, but don't wedge if the host is down
            elif settings.llm_provider_sort:
                prov.setdefault("sort", settings.llm_provider_sort)
            eb["provider"] = prov
            kwargs["extra_body"] = eb
        last_exc: Exception | None = None
        resp = None
        for i in range(attempts):
            cancel.check()      # stop/deadline lands here — never mid-flight, never after a retry sleep
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001 — re-raised below if not transient/last
                last_exc = e
                if _is_transient(e) and i < attempts - 1:
                    time.sleep(1.5 * (i + 1))
                    continue
                raise
            content = (resp.choices[0].message.content or "") if resp.choices else ""
            if not content.strip() and i < attempts - 1:
                time.sleep(1.0 * (i + 1))  # blank content -> treat as transient gateway glitch
                continue
            return resp
        if last_exc is not None:
            raise last_exc
        return resp

    def chat(self, messages: list[dict], *, model: str | None = None, **kw: Any) -> str:
        kw.setdefault("max_tokens", settings.max_output_tokens)  # cost + reservation cap (caller can override)
        resp = self._create(model=model or self.model, messages=self._with_cache(messages, model), **kw)
        _record_usage(model or self.model, resp)
        return resp.choices[0].message.content or ""

    def chat_json(self, messages: list[dict], *, model: str | None = None, **kw: Any) -> dict:
        kw.setdefault("max_tokens", settings.max_output_tokens)
        resp = self._create(
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
