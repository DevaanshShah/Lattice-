from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisualRequirement = Literal[
    "label", "value", "relationship", "state_change", "sequence", "comparison", "asset",
]


class LessonBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    spoken_text: str = Field(..., min_length=1)
    claim_ids: list[str] = Field(..., min_length=1)
    visual_anchors: list[str] = Field(default_factory=list)
    claim_requirements: dict[str, list[VisualRequirement]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _requirements_reference_claims(self) -> "LessonBeat":
        unknown = set(self.claim_requirements) - set(self.claim_ids)
        if unknown:
            raise ValueError(f"visual requirements reference unknown claim(s): {sorted(unknown)}")
        if any(not requirements for requirements in self.claim_requirements.values()):
            raise ValueError("each visual claim requirement must name at least one evidence kind")
        return self


class LessonScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    learning_goal: str = Field(..., min_length=1)
    example: str | None = None
    beats: list[LessonBeat] = Field(..., min_length=1)
    bridge_to_next: str | None = None


class LessonPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2] = 1
    topic: str = Field(..., min_length=1)
    skill_id: str = Field(..., min_length=1)
    learning_objective: str = Field(..., min_length=1)
    audience: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    scenes: list[LessonScene] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "LessonPlan":
        scene_ids = [scene.id for scene in self.scenes]
        beat_ids = [beat.id for scene in self.scenes for beat in scene.beats]
        claim_ids = [claim for scene in self.scenes for beat in scene.beats for claim in beat.claim_ids]
        for label, values in (("scene", scene_ids), ("beat", beat_ids), ("claim", claim_ids)):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} id(s): {duplicates}")
        if self.schema_version == 2:
            missing = [claim for scene in self.scenes for beat in scene.beats
                       for claim in beat.claim_ids if claim not in beat.claim_requirements]
            if missing:
                raise ValueError(f"schema v2 requires visual requirements for claim(s): {missing}")
        return self
