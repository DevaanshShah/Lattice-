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
    notes: str | None = None


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1)
    prompt: str = Field(..., description="the source natural-language prompt (injected by the generator)")
    narration: str = Field(..., min_length=1, description="single placeholder narration line; full script in M4")
    layout_notes: str | None = Field(None, description="rough overall layout intent")
    objects: list[SceneObject] = Field(..., min_length=1)
    beats: list[AnimationBeat] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _beats_reference_known_objects(self) -> "SceneSpec":
        ids = {o.id for o in self.objects}
        for b in self.beats:
            unknown = [t for t in b.targets if t not in ids]
            if unknown:
                raise ValueError(f"beat '{b.action}' targets unknown object id(s): {unknown}")
        return self
