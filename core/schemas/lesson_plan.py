from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisualRequirement = Literal[
    "label", "value", "relationship", "state_change", "sequence", "comparison", "asset",
]


# The colours a map piece may take. Kept equal to `core.visual_state.TONES` by a test.
MapTone = Literal["pink", "purple", "teal", "yellow", "blue", "green", "white", "red"]


class MapPiece(BaseModel):
    """One thing on the lesson's map: an icon piece, a panel that holds pieces, or a meter."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: str = Field(..., min_length=1, max_length=22)
    kind: Literal["piece", "panel", "meter"] = "piece"
    icon: str | None = None
    tone: MapTone = "teal"
    panel: str | None = None          # id of the panel this piece sits in
    count: int = Field(default=1, ge=1, le=3)      # a piece drawn several times: "several workers"
    planned: bool = False             # starts as a dashed outline: a piece about to be added
    value: float | None = None        # a meter's starting reading
    max: float = Field(default=100, gt=0)

    @model_validator(mode="after")
    def _shape(self) -> "MapPiece":
        if len(self.label.split()) > 3:
            raise ValueError(f"map piece {self.id!r}: a label is one to three words")
        if self.kind == "piece" and not self.icon:
            raise ValueError(f"map piece {self.id!r} needs an icon")
        if self.kind == "meter" and self.value is None:
            raise ValueError(f"map meter {self.id!r} needs a starting value")
        if self.kind == "panel" and self.panel:
            raise ValueError(f"map panel {self.id!r} cannot sit inside another panel")
        return self


class MapArrow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    label: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _short(self) -> "MapArrow":
        if self.label and len(self.label.split()) > 2:
            raise ValueError(f"map arrow label {self.label!r}: one or two words")
        return self


class LessonMap(BaseModel):
    """The one diagram a system lesson is taught on. Scenes reveal and change its pieces; they
    cannot add a piece it does not have."""
    model_config = ConfigDict(extra="forbid")
    pieces: list[MapPiece] = Field(..., min_length=3, max_length=10)
    arrows: list[MapArrow] = Field(..., min_length=1, max_length=10)

    @model_validator(mode="after")
    def _consistent(self) -> "LessonMap":
        kinds = {piece.id: piece.kind for piece in self.pieces}
        if len(kinds) != len(self.pieces):
            raise ValueError("map piece ids must be unique")
        labels = [piece.label.lower() for piece in self.pieces]
        if len(set(labels)) != len(labels):
            raise ValueError("map piece labels must be unique")
        for piece in self.pieces:
            if piece.panel is not None and kinds.get(piece.panel) != "panel":
                raise ValueError(f"map piece {piece.id!r} names panel {piece.panel!r}, "
                                 "which is not a panel on the map")
        members = [piece.panel for piece in self.pieces if piece.panel]
        for panel in (piece.id for piece in self.pieces if piece.kind == "panel"):
            if not 1 <= members.count(panel) <= 4:
                raise ValueError(f"map panel {panel!r} holds one to four pieces")
        if sum(kind == "piece" for kind in kinds.values()) < 2:
            raise ValueError("a map needs at least two icon pieces")
        seen = set()
        for arrow in self.arrows:
            ends = (arrow.source, arrow.target)
            if any(kinds.get(end) != "piece" for end in ends) or arrow.source == arrow.target:
                raise ValueError(f"map arrow {arrow.source!r} -> {arrow.target!r} must join two "
                                 "different icon pieces of the map")
            if ends in seen or ends[::-1] in seen:
                raise ValueError(f"map has two arrows between {arrow.source!r} and {arrow.target!r}")
            seen.add(ends)
        return self


# A question, an answer or a takeaway is shown as a line of text under the picture. It may wrap
# onto a second line; past this length it would take the room the picture needs.
LINE_LENGTH = 110


class BeatMove(BaseModel):
    """What happens on the map while a beat is spoken, chosen from a short menu. Code turns a
    move into the actions, the claim and the proof, so they cannot disagree with each other."""
    model_config = ConfigDict(extra="forbid")
    do: Literal["introduce", "send", "trouble", "fix", "measure", "point", "remove",
                "ask", "answer"]
    text: str | None = None                           # the line an ask or an answer shows
    pieces: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)     # pieces a request travels through, in order
    meter: str | None = None
    value: float | None = None
    count: int = Field(default=1, ge=1, le=5)         # balls sent along the path: 4 is heavy traffic

    @model_validator(mode="after")
    def _shape(self) -> "BeatMove":
        if (self.meter is None) != (self.value is None):
            raise ValueError("a move names a meter together with the value it should read")
        needs = {"introduce": bool(self.pieces), "point": bool(self.pieces),
                 "remove": bool(self.pieces), "send": len(self.path) >= 2,
                 "measure": self.meter is not None,
                 "trouble": bool(self.pieces) or self.meter is not None,
                 "fix": bool(self.pieces) or self.meter is not None,
                 "ask": bool(self.text), "answer": bool(self.text)}
        if not needs[self.do]:
            raise ValueError({
                "send": "a send move needs a path of two or more pieces",
                "measure": "a measure move needs a meter and a value",
                "ask": "an ask move needs the question it shows, as text",
                "answer": "an answer move needs the answer it shows, as text",
            }.get(self.do, f"a {self.do} move needs pieces" + (
                " or a meter" if self.do in {"trouble", "fix"} else "")))
        if self.path and self.do not in {"send", "trouble"}:
            raise ValueError(f"a {self.do} move has no path; only send and trouble do")
        if self.meter is not None and self.do not in {"trouble", "fix", "measure"}:
            raise ValueError(f"a {self.do} move has no meter; only trouble, fix and measure move one")
        if self.text is not None:
            if self.do not in {"ask", "answer"}:
                raise ValueError(f"a {self.do} move shows no text; only ask and answer do")
            if len(self.text) > LINE_LENGTH:
                raise ValueError(f"the text of an {self.do} move is shown under the picture: at "
                                 f"most {LINE_LENGTH} characters, not {len(self.text)}")
            if self.do == "ask" and not self.text.rstrip().endswith("?"):
                raise ValueError("the text of an ask move is a question, ending in '?'")
        if self.do in {"ask", "answer"} and (self.pieces or self.path):
            raise ValueError(f"an {self.do} move shows a line of text and names no pieces")
        return self


class LessonBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    spoken_text: str = Field(..., min_length=1)
    claim_ids: list[str] = Field(..., min_length=1)
    visual_anchors: list[str] = Field(default_factory=list)
    claim_requirements: dict[str, list[VisualRequirement]] = Field(default_factory=dict)
    move: BeatMove | None = None      # set on every beat of a map lesson, and only there

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
    # One line shown as the scene ends. Eighty characters is what fits the frame on one line
    # at the caption's size (checked by the layout test of a compiled map).
    takeaway: str | None = Field(default=None, max_length=80)


class LessonBrief(BaseModel):
    """What a lesson is for, decided before any scene is written. The scenes serve it, and it is
    what a teacher reads and approves."""
    model_config = ConfigDict(extra="forbid")
    learner: str = Field(..., min_length=1)           # who is watching and what they already know
    can_do: str = Field(..., min_length=1)            # the one thing they can do afterwards
    question: str = Field(..., min_length=1)          # the learner's own question
    problem: str = Field(..., min_length=1)           # a concrete situation where it matters
    naive_attempt: str = Field(..., min_length=1)     # what a beginner tries, and why it falls short
    turning_point: str = Field(..., min_length=1)     # the idea that resolves it
    check_question: str = Field(..., min_length=1)    # tests whether they understood
    check_answer: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _questions_are_questions(self) -> "LessonBrief":
        for name in ("question", "check_question"):
            if not getattr(self, name).rstrip().endswith("?"):
                raise ValueError(f"brief.{name} is written as a question, ending in '?'")
        for name in ("question", "check_question", "check_answer"):
            if len(getattr(self, name)) > LINE_LENGTH:
                raise ValueError(f"brief.{name} is shown on screen: at most {LINE_LENGTH} "
                                 f"characters, not {len(getattr(self, name))}")
        return self


class LessonPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2] = 1
    topic: str = Field(..., min_length=1)
    skill_id: str = Field(..., min_length=1)
    learning_objective: str = Field(..., min_length=1)
    audience: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    brief: LessonBrief | None = None      # required of a newly planned map lesson; old ones lack it
    map: LessonMap | None = None
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
        self._moves_fit_the_map()
        return self

    def _moves_fit_the_map(self) -> None:
        beats = [beat for scene in self.scenes for beat in scene.beats]
        if self.map is None:
            stray = [beat.id for beat in beats if beat.move is not None]
            if stray:
                raise ValueError(f"beat(s) {stray} have a move but the lesson has no map")
            return
        kinds = {piece.id: piece.kind for piece in self.map.pieces}
        joined = {frozenset((arrow.source, arrow.target)) for arrow in self.map.arrows}
        for beat in beats:
            move = beat.move
            if move is None:
                raise ValueError(f"beat {beat.id}: every beat of a map lesson needs a move")
            if len(beat.claim_ids) != 1:
                raise ValueError(f"beat {beat.id}: a map beat makes exactly one claim")
            unknown = sorted({*move.pieces, *move.path, *([move.meter] if move.meter else [])}
                             - set(kinds))
            if unknown:
                raise ValueError(f"beat {beat.id}: move names {unknown}, not on the map; the map "
                                 f"has {sorted(kinds)}")
            if move.meter and kinds[move.meter] != "meter":
                raise ValueError(f"beat {beat.id}: {move.meter!r} is not a meter")
            wrong = [item for item in move.path if kinds[item] != "piece"]
            apart = [f"{a}->{b}" for a, b in zip(move.path, move.path[1:])
                     if frozenset((a, b)) not in joined]
            if wrong or apart:
                raise ValueError(f"beat {beat.id}: a path goes through icon pieces joined by an "
                                 f"arrow, in either direction; not pieces {wrong}, no arrow for {apart}")
            if move.do in {"trouble", "fix"} and any(kinds[item] != "piece" for item in move.pieces):
                raise ValueError(f"beat {beat.id}: only icon pieces turn red or get fixed; use "
                                 "'meter' for a meter")
        for scene in self.scenes:       # the lines under the picture: room for a question and one more
            said = [beat.move.do for beat in scene.beats]
            if said.count("ask") > 1 or said.count("answer") > 1:
                raise ValueError(f"scene {scene.id}: a scene asks at most one question and gives "
                                 "at most one answer")
            if "answer" in said and ("ask" not in said or said.index("answer") < said.index("ask")):
                raise ValueError(f"scene {scene.id}: an answer move comes after an ask move in "
                                 "the same scene")
