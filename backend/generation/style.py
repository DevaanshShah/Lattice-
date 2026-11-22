"""FR-4 — generate the shared StyleSpec once per video (palette/fonts/object looks/layout).

Injected into every scene's codegen (see codegen.generate(..., style=...)) so independent
scenes are visibly consistent — the moat feature alongside the vision critic.
"""
from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.outline import Outline
from core.schemas.style import StyleSpec
from core.textutil import extract_json
from prompts.loader import load


class StyleError(RuntimeError):
    pass


def generate(topic: str, outline: Outline | None = None, *, attempts: int = 3,
             client: LLMClient | None = None) -> StyleSpec:
    client = client or get_client()
    scenes = ", ".join(outline.titles()) if outline else "(unknown)"
    messages = [
        {"role": "system", "content": load("style-spec")},
        {"role": "user", "content": f"Topic: {topic}\nScenes: {scenes}\n\nReturn the style spec JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            return StyleSpec.model_validate(extract_json(raw))
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "That was invalid. Return ONLY the style-spec JSON."})
    raise StyleError(f"style spec invalid after {attempts} attempts: {last}")
