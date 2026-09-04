"""Developer-observability shim: a transparent wrapper around the LLM client that narrates every
call into the job log so the web "Dev Console" can show live hits, retries, prompt sizes, and timing.

It duck-types `LLMClient` (delegates any attribute it doesn't override), so anything downstream that
reads `client.model` / `client.base_url` keeps working; only `chat` / `chat_json` are intercepted.
Purely additive — if construction is skipped the pipeline uses the raw client and behaves identically.

The lines it emits are ordinary job events (prefixed so the frontend can colour them):
    [llm#3] codegen  · deepseek-chat  · sys 8.1k · user 0.6k
    [llm#3] ok       · 2.4k chars · 17.3s
    [llm#3] err      · APITimeoutError (will retry)
"""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Callable


def _kb(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _infer_kind(system: str, user: str) -> str:
    """Best-effort label for what this call is doing, from the prompt content."""
    s = (system or "").lower()
    u = (user or "").lower()
    if "vision critic" in u or "visual defects" in u:
        return "critic-fix"
    if "trimmed traceback" in u or "traceback" in u:
        return "compile-fix"
    if "scene planner" in s or "scene spec" in s:
        return "spec"          # the structured plan for one scene, before any code
    if "narration" in s and "manim" not in s:
        return "narration"
    if "setup_scene" in s or "lattice" in s or "manim" in s:
        return "codegen"
    if "outline" in s or "scene-by-scene" in s:
        return "outline"
    return "llm"


class TracingClient:
    """Wraps a real client; mirrors `chat`/`chat_json` while logging each call. `log` is the job's
    append-only sink (`job.log`)."""

    def __init__(self, inner: Any, log: Callable[[str], None]) -> None:
        self._inner = inner
        self._log = log or (lambda _m: None)
        self._n = 0

    def __getattr__(self, name: str) -> Any:  # model, base_url, and anything else read downstream
        return getattr(self._inner, name)

    def chat(self, messages: list[dict], **kw: Any) -> str:
        return self._traced("chat", messages, kw, as_json=False)

    def chat_json(self, messages: list[dict], **kw: Any) -> dict:
        return self._traced("chat_json", messages, kw, as_json=True)

    def _traced(self, method: str, messages: list[dict], kw: dict, *, as_json: bool):
        self._n += 1
        n = self._n
        system = _first_content(messages, "system")
        user = _first_content(messages, "user")
        kind = _infer_kind(system, user)
        model = str(getattr(self._inner, "model", "?")).split("/")[-1]
        self._log(f"[llm#{n}] {kind} · {model} · sys {_kb(len(system))} · user {_kb(len(user))}")
        t0 = perf_counter()
        try:
            out = getattr(self._inner, method)(messages, **kw)
        except Exception as e:  # noqa: BLE001 — log then re-raise so the real retry logic still runs
            self._log(f"[llm#{n}] err · {type(e).__name__}: {str(e)[:120]}")
            raise
        dt = perf_counter() - t0
        size = len(out) if isinstance(out, str) else len(json.dumps(out))
        self._log(f"[llm#{n}] ok · {_kb(size)} chars · {dt:.1f}s")
        return out


def _first_content(messages: list[dict], role: str) -> str:
    for m in messages or []:
        if m.get("role") == role:
            c = m.get("content")
            return c if isinstance(c, str) else json.dumps(c)
    return ""


def traced(client: Any, log: Callable[[str], None] | None) -> Any:
    """Wrap `client` for tracing when a real log sink is given; otherwise return it untouched."""
    if log is None or log is print:
        return client
    return TracingClient(client, log)
