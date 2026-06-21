"""FR-1 — natural-language prompt -> validated SceneSpec.

Invalid model output is rejected and REGENERATED (with the validation error fed back), never
passed downstream. After `attempts` failures it raises rather than emitting a half-spec.
"""
from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SceneSpec
from core.textutil import extract_json
from prompts.loader import load


class SceneSpecError(RuntimeError):
    pass


def generate(prompt: str, *, attempts: int = 3, client: LLMClient | None = None) -> SceneSpec:
    client = client or get_client()
    messages = [
        {"role": "system", "content": load("scene-spec")},
        {"role": "user", "content": f"Prompt: {prompt}\n\nReturn the scene spec JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            data = extract_json(raw)
            data["prompt"] = prompt  # authoritative source prompt, not whatever the model echoed
            return SceneSpec.model_validate(data)
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f"That was invalid ({type(e).__name__}: {e}). Return ONLY corrected JSON that "
                "matches the schema exactly — no prose, no markdown, no extra fields."
            )})
    raise SceneSpecError(f"scene spec still invalid after {attempts} attempts: {last}")
