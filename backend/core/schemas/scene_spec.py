"""The LOCKED scene-spec schema (FR-1).

This is the structured IR generated from a prompt BEFORE any code. Everything downstream
(codegen, style spec, regeneration, persistence) keys off it — changing it later is
expensive, so it is strict on purpose: unknown fields / kinds / actions are rejected, which
is exactly what makes the generator regenerate instead of passing junk downstream.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The generated Manim Scene subclass always has this name, so the renderer knows what to call.
SCENE_CLASS = "GeneratedScene"

ObjectKind = Literal[
    "text", "mathtex", "code", "circle", "square", "rectangle",
    "arrow", "line", "dot", "group", "table", "number_line", "axes",
]
BeatAction = Literal[
    "create", "write", "fade_in", "fade_out", "transform", "replace",
    "move", "shift", "highlight", "indicate", "grow", "wait",
]
# A product recipe may select one of these proven visual shapes. Optional so persisted and
# non-product SceneSpecs retain their existing contract.
VisualPattern = Literal[
    "architecture_map", "workflow_flow", "funnel", "metric_hero", "before_after",
]


class SceneObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1, description="stable snake_case handle, referenced by beats")
    kind: ObjectKind
    label: str | None = Field(None, description="text / LaTeX / code content, when applicable")
    notes: str | None = Field(None, description="rough position/style intent")


class AnimationBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: BeatAction
    targets: list[str] = Field(default_factory=list, description="SceneObject ids this beat acts on")
    narration_cue: str | None = Field(
        None, description="placeholder: words this beat lines up with (real sync arrives in M4)"
    )
    spoken_point: str | None = Field(
        None, description="the specific idea spoken during this beat; it must be visible through its targets"
    )
    notes: str | None = None


class AnchorLayout(BaseModel):
    """A stable grid position for an object that survives a recipe-scene handoff."""
    model_config = ConfigDict(extra="forbid")
    cell: str = Field(..., pattern=r"^[A-E][1-8]$", description="named Lattice grid cell")
    width: float = Field(..., ge=1.0, le=6.0, description="stable rendered width in scene units")
    height: float = Field(..., ge=0.5, le=3.0, description="stable rendered height in scene units")


class VisualContinuity(BaseModel):
    """The visual handoff from the prior scene, used only when recipe-video planning opts in."""
    model_config = ConfigDict(extra="forbid")
    carryover_ids: list[str] = Field(
        default_factory=list,
        description="object ids retained from the previous scene and visible at this scene's first frame",
    )
    opening_state: str | None = Field(None, description="what the first frame preserves from the prior scene")
    closing_state: str | None = Field(None, description="what this scene leaves visible for the next scene")
    anchor_layouts: dict[str, AnchorLayout] = Field(
        default_factory=dict,
        description="stable grid cells for outgoing anchors and incoming carryover objects",
    )


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1)
    prompt: str = Field(..., description="the source natural-language prompt (injected by the generator)")
    narration: str = Field(..., min_length=1, description="single placeholder narration line; full script in M4")
    layout_notes: str | None = Field(None, description="rough overall layout intent")
    visual_pattern: VisualPattern | None = Field(
        None, description="optional recipe-selected visual shape; absent for generic scenes"
    )
    continuity: VisualContinuity | None = Field(
        None, description="optional visual-state handoff; product recipe videos opt in"
    )
    objects: list[SceneObject] = Field(..., min_length=1)
    beats: list[AnimationBeat] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _beats_reference_known_and_visible_objects(self) -> "SceneSpec":
        ids = {o.id for o in self.objects}
        for b in self.beats:
            unknown = [t for t in b.targets if t not in ids]
            if unknown:
                raise ValueError(f"beat '{b.action}' targets unknown object id(s): {unknown}")
        carryover_ids = set(self.continuity.carryover_ids) if self.continuity else set()
        unknown_carryover = sorted(carryover_ids - ids)
        if unknown_carryover:
            raise ValueError(f"continuity carries unknown object id(s): {unknown_carryover}")
        anchor_layouts = self.continuity.anchor_layouts if self.continuity else {}
        unknown_layouts = sorted(set(anchor_layouts) - ids)
        if unknown_layouts:
            raise ValueError(f"continuity has layout for unknown object id(s): {unknown_layouts}")
        if carryover_ids:
            if not self.continuity or not self.continuity.opening_state or not self.continuity.closing_state:
                raise ValueError("continuity carryover requires both opening_state and closing_state")
            missing_layouts = sorted(carryover_ids - set(anchor_layouts))
            if missing_layouts:
                raise ValueError(f"continuity carryover requires stable layout for: {missing_layouts}")
            introduction_actions = {"create", "write", "fade_in", "grow"}
            reintroduced = sorted({target for beat in self.beats if beat.action in introduction_actions
                                   for target in beat.targets} & carryover_ids)
            if reintroduced:
                raise ValueError(
                    "carryover object id(s) must begin visible, not be introduced again: "
                    f"{reintroduced}"
                )
        # Geometry lint can prove a shape is laid out safely, but not that it ever appeared.
        # Catch that cheap, deterministic failure before code generation or Docker rendering.
        visible_actions = {
            "create", "write", "fade_in", "transform", "replace", "move", "shift",
            "highlight", "indicate", "grow",
        }
        animated = {target for beat in self.beats if beat.action in visible_actions
                    for target in beat.targets}
        missing = sorted(ids - animated)
        if missing:
            raise ValueError(f"declared object id(s) never receive a visible animation: {missing}")
        if self.visual_pattern:
            ungrounded = [str(i + 1) for i, beat in enumerate(self.beats)
                          if beat.action != "wait" and not beat.spoken_point]
            if ungrounded:
                raise ValueError("product-video beat(s) need a spoken_point grounded in their visual targets: "
                                 + ", ".join(ungrounded))
        if self.visual_pattern == "workflow_flow" and len(anchor_layouts) > 1:
            rows = {layout.cell[0] for layout in anchor_layouts.values()}
            if rows != {"C"}:
                raise ValueError("workflow continuity anchors must share the middle row C for a clear horizontal flow")
        return self
