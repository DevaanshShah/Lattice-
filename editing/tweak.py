"""FR-19 — per-scene tweak prompts. A natural-language nudge to ONE scene.

The nudge revises that scene's SPEC (preserving object ids — a nudge, not a re-author), then
scene k is re-rendered through the failure-safe regenerate_scene path (which reuses the revised
spec, keeps the prior good clip on failure, and re-stitches). Other scenes are untouched.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from composition import regen
from composition.scene_dag import VideoProject
from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SceneSpec
from core.textutil import extract_json
from prompts.loader import load


class TweakError(RuntimeError):
    pass


def apply_tweak(spec: SceneSpec, instruction: str, *, attempts: int = 3,
                client: LLMClient | None = None) -> SceneSpec:
    """Revise a SceneSpec per a nudge. Source prompt is preserved; invalid output regenerated."""
    client = client or get_client()
    messages = [
        {"role": "system", "content": load("tweak-spec")},
        {"role": "user", "content": (
            f"Instruction: {instruction}\n\nCurrent scene spec JSON:\n"
            f"{spec.model_dump_json(indent=2)}\n\nReturn the revised scene spec JSON now."
        )},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            data = extract_json(raw)
            data["prompt"] = spec.prompt   # keep the original source prompt
            return SceneSpec.model_validate(data)
        except (ValueError, ValidationError) as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "That was invalid. Return ONLY the revised scene spec JSON."})
    raise TweakError(f"tweak produced an invalid spec after {attempts} attempts: {last}")


def tweak_scene(project: VideoProject, index: int, instruction: str, *, out_dir: str | Path,
                quality: str = "preview", client: LLMClient | None = None, log=print) -> VideoProject:
    if not (0 <= index < len(project.scenes)):
        raise IndexError(f"scene index {index} out of range (have {len(project.scenes)})")
    node = project.scene(index)
    if node.spec is None:
        raise ValueError(f"scene {index} hasn't been generated yet — build it before tweaking")

    client = client or get_client()
    say = log or (lambda _m: None)
    say(f"-> tweaking scene {index} ({node.title}): {instruction!r}")

    node.spec = apply_tweak(node.spec, instruction, client=client)   # revised spec drives the rebuild
    # regenerate_scene reuses node.spec, keeps the prior clip on failure, and re-stitches on success
    regen.regenerate_scene(project, index, out_dir=out_dir, quality=quality, client=client, log=say)
    return project
