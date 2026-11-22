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


def generate(prompt: str, *, attempts: int = 3, client: LLMClient | None = None,
             allowed_carryover_ids: set[str] | None = None,
             required_anchor_layouts: dict[str, dict] | None = None,
             fallback_anchor: dict | None = None,
             require_outgoing_anchor: bool = False) -> SceneSpec:
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
            # The model may try to carry an appealing detail (for example a highlighted keyword) that
            # the prior scene did not preserve. The prior anchor contract is authoritative: retain only
            # those ids and restore one known anchor when it chose none, rather than aborting the video.
            if required_anchor_layouts is not None:
                continuity = data.setdefault("continuity", {})
                requested = continuity.get("carryover_ids") or []
                carryover = [object_id for object_id in requested if object_id in required_anchor_layouts]
                if not carryover and fallback_anchor is not None:
                    carryover = [fallback_anchor["id"]]
                    object_ids = {obj.get("id") for obj in data.get("objects", [])}
                    if fallback_anchor["id"] not in object_ids:
                        data.setdefault("objects", []).insert(0, fallback_anchor)
                    if not any(fallback_anchor["id"] in beat.get("targets", [])
                               for beat in data.get("beats", [])):
                        data.setdefault("beats", []).insert(0, {
                            "action": "indicate", "targets": [fallback_anchor["id"]],
                            "spoken_point": f"{fallback_anchor.get('label') or 'The prior input'} remains in view",
                            "notes": "carry the prior visual state into this scene",
                        })
                continuity["carryover_ids"] = carryover
                continuity["anchor_layouts"] = {
                    object_id: required_anchor_layouts[object_id] for object_id in carryover
                }
            spec = SceneSpec.model_validate(data)
            if allowed_carryover_ids is not None:
                carryover = set(spec.continuity.carryover_ids) if spec.continuity else set()
                if not carryover:
                    raise ValueError("this scene must carry at least one object from the previous scene")
                invalid = sorted(carryover - allowed_carryover_ids)
                if invalid:
                    raise ValueError(f"continuity carries ids not present in the previous scene: {invalid}")
            if required_anchor_layouts:
                layouts = spec.continuity.anchor_layouts if spec.continuity else {}
                carryover = set(spec.continuity.carryover_ids) if spec.continuity else set()
                for object_id in carryover:
                    expected = required_anchor_layouts.get(object_id)
                    actual = layouts.get(object_id)
                    if expected is None:
                        raise ValueError(f"carryover '{object_id}' has no stable layout in the previous scene")
                    if actual is None or actual.model_dump() != expected:
                        raise ValueError(
                            f"carryover '{object_id}' must retain exact layout {expected}, not move or resize"
                        )
            if require_outgoing_anchor:
                layouts = spec.continuity.anchor_layouts if spec.continuity else {}
                if not layouts:
                    raise ValueError("this non-final product scene must define one or more outgoing anchor_layouts")
            return spec
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f"That was invalid ({type(e).__name__}: {e}). Return ONLY corrected JSON that "
                "matches the schema exactly — no prose, no markdown, no extra fields."
            )})
    raise SceneSpecError(f"scene spec still invalid after {attempts} attempts: {last}")
