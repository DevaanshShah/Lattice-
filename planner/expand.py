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
           client: LLMClient | None = None, recipe_guidance: str | None = None) -> SceneSpec:
    """recipe_guidance: optional extra instruction (from a product-video recipe, see
    planner/product_recipe.py) appended to the scene prompt to bias its objects/beats toward one
    of the fixed product-video shapes. None (the default) leaves this prompt unchanged."""
    others = ", ".join(f"{j + 1}) {t}" for j, t in enumerate(outline.titles()))
    prompt = (
        f"{item.intent}\n\n"
        f"(Context: this is scene {index + 1} of {len(outline.items)} in a video explaining "
        f"'{outline.topic}'. Full scene order: {others}. Keep THIS scene focused only on: "
        f"{item.title}.)"
    )
    if recipe_guidance:
        prompt += f"\n\n{recipe_guidance}"
    return scene_spec.generate(prompt, client=client)
