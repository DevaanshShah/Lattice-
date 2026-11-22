"""FR-3 (part 2) — expand one approved outline item into a full SceneSpec.

Gives the scene-spec generator the outline context (its position + the other scenes) so the
scenes read as one coherent video, not isolated fragments.
"""
from __future__ import annotations

from core.llm import LLMClient
from core.schemas.outline import Outline, OutlineItem
from core.schemas.scene_spec import SceneSpec, VisualPattern
from generation import scene_spec


def expand(item: OutlineItem, outline: Outline, index: int, *,
           client: LLMClient | None = None, recipe_guidance: str | None = None,
           visual_pattern: VisualPattern | None = None,
           previous_spec: SceneSpec | None = None) -> SceneSpec:
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
    if visual_pattern:
        prompt += f"\n\nRequired visual pattern for this scene: {visual_pattern}."
    allowed_carryover_ids = None
    required_anchor_layouts = None
    fallback_anchor = None
    if previous_spec is not None:
        prior_objects = [
            {"id": obj.id, "kind": obj.kind, "label": obj.label, "notes": obj.notes}
            for obj in previous_spec.objects
        ]
        prior_continuity = previous_spec.continuity
        prior_closing = (prior_continuity.closing_state
                         if previous_spec.continuity else previous_spec.layout_notes)
        prior_layouts = {object_id: layout.model_dump()
                         for object_id, layout in (prior_continuity.anchor_layouts.items()
                                                   if prior_continuity else [])}
        prompt += (
            "\n\nVISUAL HANDOFF FROM THE PREVIOUS SCENE:\n"
            f"Previous title: {previous_spec.title}\n"
            f"Previous closing state: {prior_closing or 'keep its final visual composition visible'}\n"
            f"Previous objects: {prior_objects}\n\n"
            "This is the NEXT scene in the SAME video, not a visual reset. Select one to three relevant "
            "previous object ids ONLY from the anchor_layouts map above and declare them in "
            "`continuity.carryover_ids`. Re-declare those exact ids "
            "with the same labels in this scene's objects. They MUST already be visible in the first frame; "
            "do not create/write/fade_in/grow them again. Use an indicate, move, shift, transform, replace, "
            "or highlight beat to change them. In `continuity.anchor_layouts`, copy each selected object's "
            f"exact prior layout (cell, width, height): {prior_layouts}. Do not move or resize an incoming "
            "anchor in frame one. Choose only labelled box/circle objects as anchors. "
            "Describe the inherited first frame in `opening_state` and the last frame that the next scene "
            "should inherit in `closing_state`."
        )
        allowed_carryover_ids = set(prior_layouts)
        required_anchor_layouts = prior_layouts
        for obj in previous_spec.objects:
            if obj.id in prior_layouts:
                fallback_anchor = obj.model_dump()
                break
    spec = scene_spec.generate(
        prompt, client=client, allowed_carryover_ids=allowed_carryover_ids,
        required_anchor_layouts=required_anchor_layouts,
        fallback_anchor=fallback_anchor,
        require_outgoing_anchor=bool(visual_pattern and index + 1 < len(outline.items)),
    )
    # The recipe is deterministic host-side policy, not an LLM suggestion. Stamp it after
    # schema validation so codegen receives the selected shape even if the model omitted it.
    if not visual_pattern:
        return spec
    # model_copy deliberately skips validation; go through the locked schema so a malformed
    # recipe file cannot leak an unknown pattern into code generation.
    return SceneSpec.model_validate({**spec.model_dump(), "visual_pattern": visual_pattern})
