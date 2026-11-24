from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisualPattern = Literal[
    "workflow", "architecture", "decision", "comparison", "transformation", "timeline",
    "feedback_loop", "metric", "contour",
]
VisualRole = Literal[
    "input", "operation", "output", "source", "destination", "context", "tool", "decision",
    "result", "audit", "before", "after", "metric",
]
ObjectKind = Literal[
    "message", "node", "document", "card", "gate", "tool", "metric", "group",
    "array", "pointer", "counter", "value", "formula", "code", "chart", "image", "icon",
    "caption", "tree", "graph",
]
RelationKind = Literal[
    "flows_to", "connects_to", "checks", "branches_to", "returns_to", "compares_to",
    "transforms_to",
]
ActionKind = Literal[
    "appear", "connect", "highlight", "expand", "transform", "move", "branch", "activate",
    "deactivate", "hold", "set_state", "increment", "hide", "focus", "compare", "trace",
]
EvidenceKind = Literal[
    "label", "state", "relationship", "value", "state_change", "sequence", "comparison", "asset",
]


class VisualObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    kind: ObjectKind
    role: VisualRole
    label: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _semantic_payload(self) -> "VisualObject":
        required = {
            "array": "items", "pointer": "target_id", "counter": "value", "value": "value",
            "formula": "expression", "code": "source", "chart": "series",
            "image": "asset_id", "icon": "asset_id", "tree": "nodes", "graph": "nodes",
        }
        key = required.get(self.kind)
        if key and key not in self.payload:
            raise ValueError(f"{self.kind} object requires payload.{key}")
        if self.kind == "array" and (not isinstance(self.payload["items"], list)
                                      or not self.payload["items"]):
            raise ValueError("array payload.items must be a nonempty list")
        if self.kind == "pointer" and (not isinstance(self.payload.get("index"), int)
                                        or self.payload["index"] < 0):
            raise ValueError("pointer payload.index must be a nonnegative integer")
        if self.kind == "counter" and self.payload["value"] is not None and not isinstance(
                self.payload["value"], (int, float)):
            raise ValueError("counter payload.value must be numeric or initially unknown")
        return self


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
    action_ids: list[str] = Field(default_factory=list)


class VisualAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ActionKind
    target_ids: list[str] = Field(..., min_length=1)
    id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    start_fraction: float | None = Field(default=None, ge=0, lt=1, allow_inf_nan=False)
    end_fraction: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def _cue_window(self) -> "VisualAction":
        if (self.start_fraction is None) != (self.end_fraction is None):
            raise ValueError("cue requires both start_fraction and end_fraction")
        if self.start_fraction is not None and self.end_fraction <= self.start_fraction:
            raise ValueError("cue end must follow its start")
        return self


class VisualBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration_beat_id: str
    actions: list[VisualAction] = Field(..., min_length=1)
    evidence: list[VisualEvidence] = Field(..., min_length=1)
    # Seconds the picture holds in silence after the narration: time for a viewer to think about
    # a question before its answer is shown.
    pause_after: float = Field(default=0, ge=0, le=5, allow_inf_nan=False)
    # The least time this beat's steps need to be followed. When the sentence is shorter, the
    # picture goes on in silence: six cells are not filled in the three seconds it takes to say so.
    min_seconds: float = Field(default=0, ge=0, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ordered_cues(self) -> "VisualBeat":
        timed = [action.start_fraction is not None for action in self.actions]
        if any(timed) and not all(timed):
            raise ValueError("all actions in a timed beat must have cue windows")
        if all(timed):
            for previous, current in zip(self.actions, self.actions[1:]):
                if current.start_fraction < previous.end_fraction:
                    raise ValueError("cue windows must be ordered and nonoverlapping")
        return self

    def hold(self, audio_duration: float) -> float:
        """Seconds the picture goes on after the narration of this beat has ended."""
        return max(self.pause_after, self.min_seconds - audio_duration)

    def timeline(self, audio_duration: float) -> list[tuple[float, float]]:
        from math import isfinite

        if not isfinite(audio_duration) or audio_duration <= 0:
            raise ValueError("audio duration must be positive and finite")
        return [(action.start_fraction * audio_duration, action.end_fraction * audio_duration)
                if action.start_fraction is not None else
                (index * audio_duration / len(self.actions),
                 (index + 1) * audio_duration / len(self.actions))
                for index, action in enumerate(self.actions)]


class BrowserScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_scene_id: str
    pattern: VisualPattern
    render_mode: Literal["browser", "manim"] = "browser"
    theme: Literal["dark", "whiteboard"] = "dark"
    objects: list[VisualObject] = Field(..., min_length=1)
    relationships: list[VisualRelation] = Field(default_factory=list)
    beats: list[VisualBeat] = Field(..., min_length=1)
    opening_visible_ids: list[str]
    closing_visible_ids: list[str] = Field(..., min_length=1)
    carryover_ids: list[str] = Field(default_factory=list)
    # Objects that keep a place on screen for the whole scene even if this scene never shows
    # them: scenes that share one map list the full map here, so a piece does not move between them.
    layout_ids: list[str] = Field(default_factory=list)

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
        references |= set(self.layout_ids)
        references |= {member for obj in self.objects for member in obj.payload.get("members", [])
                       if isinstance(obj.payload.get("members"), list)}
        references |= {relation.source_id for relation in self.relationships}
        references |= {relation.target_id for relation in self.relationships}
        references |= {target for beat in self.beats for action in beat.actions for target in action.target_ids}
        references |= {target for beat in self.beats for evidence in beat.evidence for target in evidence.object_ids}
        unknown = sorted(references - known)
        if unknown:
            raise ValueError(f"unknown visual object id(s): {unknown}")
        action_ids = [action.id for beat in self.beats for action in beat.actions if action.id]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("duplicate visual action id(s)")
        unknown_actions = {action_id for beat in self.beats for evidence in beat.evidence
                           for action_id in evidence.action_ids} - set(action_ids)
        if unknown_actions:
            raise ValueError(f"unknown visual action id(s): {sorted(unknown_actions)}")
        object_map = {obj.id: obj for obj in self.objects}
        bad_pointers = [obj.id for obj in self.objects if obj.kind == "pointer"
                        and (obj.payload["target_id"] not in object_map
                             or object_map[obj.payload["target_id"]].kind != "array")]
        if bad_pointers:
            raise ValueError(f"pointer targets must name array object(s): {bad_pointers}")
        missing_opening = sorted(set(self.carryover_ids) - set(self.opening_visible_ids))
        if missing_opening:
            raise ValueError(f"carryover object id(s) must be visible at opening: {missing_opening}")
        return self


class BrowserVisualPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2] = 1
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
