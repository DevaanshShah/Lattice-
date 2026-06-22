"""FR-3 (part 1) — topic -> ordered outline of scene intents.

The outline is the single biggest quality lever (a wrong outline = polished garbage), so it's
an inspectable artifact the user approves/edits BEFORE any scene renders (see approval.py).
"""
from __future__ import annotations

from pydantic import ValidationError

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline
from core.textutil import extract_json
from prompts.loader import load


class OutlineError(RuntimeError):
    pass


def generate(topic: str, *, max_scenes: int | None = None, attempts: int = 3,
             client: LLMClient | None = None) -> Outline:
    client = client or get_client()
    max_scenes = max_scenes or settings.scene_cap
    messages = [
        {"role": "system", "content": load("outline")},
        {"role": "user", "content": f"Topic: {topic}\nMaximum scenes: {max_scenes}\n\nReturn the outline JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            data = extract_json(raw)
            data["topic"] = topic
            outline = Outline.model_validate(data)
            if len(outline.items) > max_scenes:
                # cap is documented, never a silent truncation
                outline = Outline(topic=topic, items=outline.items[:max_scenes])
            return outline
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f'That was invalid ({type(e).__name__}). Return ONLY '
                '{"items":[{"title":...,"intent":...}]} JSON.'
            )})
    raise OutlineError(f"outline invalid after {attempts} attempts: {last}")
