"""FR-3 (part 2) — expand one approved outline item into a full SceneSpec.

Gives the scene-spec generator the outline context (its position + the other scenes) so the
scenes read as one coherent video, not isolated fragments.
"""
from __future__ import annotations

from core.llm import LLMClient
from core.schemas.outline import Outline, OutlineItem
from core.schemas.scene_spec import SceneSpec
from generation import scene_spec


def expand(item: OutlineItem, outline: Outline, index: int, *,
           client: LLMClient | None = None) -> SceneSpec:
    others = ", ".join(f"{j + 1}) {t}" for j, t in enumerate(outline.titles()))
    prompt = (
        f"{item.intent}\n\n"
        f"(Context: this is scene {index + 1} of {len(outline.items)} in a video explaining "
        f"'{outline.topic}'. Full scene order: {others}. Keep THIS scene focused only on: "
        f"{item.title}.)"
    )
    return scene_spec.generate(prompt, client=client)
