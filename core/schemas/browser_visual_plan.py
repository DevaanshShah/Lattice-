from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisualPattern = Literal[
    "workflow", "architecture", "decision", "comparison", "transformation", "timeline",
    "feedback_loop", "metric", "contour",
]
VisualRole = Literal[
    "input", "operation", "output", "source", "destination", "context", "tool", "decision",
    "result", "audit", "before", "after", "metric",
]
ObjectKind = Literal["message", "node", "document", "card", "gate", "tool", "metric", "group"]
RelationKind = Literal[
    "flows_to", "connects_to", "checks", "branches_to", "returns_to", "compares_to",
    "transforms_to",
]
ActionKind = Literal[
    "appear", "connect", "highlight", "expand", "transform", "move", "branch", "activate",
    "deactivate", "hold",
]
EvidenceKind = Literal["label", "state", "relationship", "value"]


class VisualObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    kind: ObjectKind
    role: VisualRole
    label: str = Field(..., min_length=1)


class VisualRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    target_id: str
    kind: RelationKind
    label: str | None = None


class VisualEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_ids: list[str] = Field(..., min_length=1)
    object_ids: list[str] = Field(..., min_length=1)
    kind: EvidenceKind


class VisualAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ActionKind
    target_ids: list[str] = Field(..., min_length=1)


class VisualBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration_beat_id: str
    actions: list[VisualAction] = Field(..., min_length=1)
    evidence: list[VisualEvidence] = Field(..., min_length=1)


class BrowserScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_scene_id: str
    pattern: VisualPattern
    objects: list[VisualObject] = Field(..., min_length=1)
    relationships: list[VisualRelation] = Field(default_factory=list)
    beats: list[VisualBeat] = Field(..., min_length=1)
    opening_visible_ids: list[str]
    closing_visible_ids: list[str] = Field(..., min_length=1)
    carryover_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_known_objects(self) -> "BrowserScene":
        ids = [obj.id for obj in self.objects]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise ValueError(f"duplicate object id(s): {duplicates}")
        beat_ids = [beat.narration_beat_id for beat in self.beats]
        duplicate_beats = sorted({value for value in beat_ids if beat_ids.count(value) > 1})
        if duplicate_beats:
            raise ValueError(f"duplicate narration beat id(s): {duplicate_beats}")
        known = set(ids)
        references = set(self.opening_visible_ids) | set(self.closing_visible_ids) | set(self.carryover_ids)
        references |= {relation.source_id for relation in self.relationships}
        references |= {relation.target_id for relation in self.relationships}
        references |= {target for beat in self.beats for action in beat.actions for target in action.target_ids}
        references |= {target for beat in self.beats for evidence in beat.evidence for target in evidence.object_ids}
        unknown = sorted(references - known)
        if unknown:
            raise ValueError(f"unknown visual object id(s): {unknown}")
        missing_opening = sorted(set(self.carryover_ids) - set(self.opening_visible_ids))
        if missing_opening:
            raise ValueError(f"carryover object id(s) must be visible at opening: {missing_opening}")
        return self


class BrowserVisualPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(..., min_length=1)
    skill_id: str = Field(..., min_length=1)
    scenes: list[BrowserScene] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _scene_ids_are_unique(self) -> "BrowserVisualPlan":
        ids = [scene.lesson_scene_id for scene in self.scenes]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise ValueError(f"duplicate lesson scene id(s): {duplicates}")
        return self
