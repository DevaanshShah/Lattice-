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


# Duration -> scope mapping. A scene lands at ~SCENE_SECONDS on screen (measured 13-18s), so a time
# budget controls HOW MANY beats fit — never how rushed each beat is (pace has a quality floor).
SCENE_SECONDS = 15


def scenes_for_duration(target_seconds: int) -> int:
    """How many ~15s scenes fit a duration budget: 30s->2, 60s->4, 150s->8 (clamped 1..10)."""
    return max(1, min(10, round(target_seconds / SCENE_SECONDS)))


def generate(topic: str, *, max_scenes: int | None = None, target_seconds: int | None = None,
             attempts: int = 3, client: LLMClient | None = None) -> Outline:
    """target_seconds (the user's 30s/60s/2min pick) beats max_scenes: it sets the scene count AND
    tells the planner to keep only the most essential beats for that budget."""
    client = client or get_client()
    budget_line = ""
    if target_seconds:
        max_scenes = scenes_for_duration(target_seconds)
        budget_line = (f"Time budget: ~{target_seconds}s total (~{SCENE_SECONDS}s per scene) — pick "
                       f"ONLY the {max_scenes} most essential beat(s); cut everything nonessential.\n")
    max_scenes = max_scenes or settings.scene_cap
    messages = [
        {"role": "system", "content": load("outline")},
        {"role": "user", "content": f"Topic: {topic}\n{budget_line}Maximum scenes: {max_scenes}\n\n"
                                    "Return the outline JSON now."},
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
