"""FR-9 — narration-first script generation.

Generate the spoken script as one line per animation beat, so narration DRIVES the visuals
and later syncs to them. Pure LLM (generator model); invalid output is regenerated, never
passed downstream. The TTS / sync / caption layers (T-10/T-11) consume this.
"""
from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.narration import NarrationScript
from core.schemas.scene_spec import SceneSpec
from core.textutil import extract_json
from prompts.loader import load


class NarrationError(RuntimeError):
    pass


def generate(spec: SceneSpec, *, context: str | None = None, attempts: int = 3,
             client: LLMClient | None = None) -> NarrationScript:
    """`context` (optional) is the story arc — where this scene sits in the whole video and what
    came before/after — so the narration links scenes into one continuous lesson, not isolated clips."""
    client = client or get_client()
    beats = "\n".join(
        f"{i + 1}. {b.action} {b.targets}" + (f" — {b.notes}" if b.notes else "")
        for i, b in enumerate(spec.beats)
    )
    ctx = f"{context}\n\n" if context else ""
    user = (f"{ctx}Scene title: {spec.title}\nSeed narration: {spec.narration}\n"
            f"Beats ({len(spec.beats)}):\n{beats}\n\nReturn the narration JSON now.")
    messages = [{"role": "system", "content": load("narration")},
                {"role": "user", "content": user}]

    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            return NarrationScript.model_validate(extract_json(raw))
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f'That was invalid ({type(e).__name__}). Return ONLY {{"lines": [...]}} JSON.'
            )})
    raise NarrationError(f"narration script invalid after {attempts} attempts: {last}")
