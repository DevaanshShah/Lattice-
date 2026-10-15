from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.call_tree import MAX_CALLS, call_tree


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


MAP_MOVES = ("introduce", "send", "trouble", "fix", "measure", "point", "remove")
TRACE_MOVES = ("show", "run", "look", "compare", "discard", "fill", "count", "clear",
               "grow", "spot", "take", "group", "reveal", "remove")
LINE_MOVES = ("ask", "answer", "turn")    # a line of text under the picture, in any lesson

# What each move may carry. Anything else on it is a mistake worth saying plainly.
_TAKES = {
    "introduce": {"pieces"}, "point": {"pieces"}, "remove": {"pieces", "items", "lines"},
    "grow": {"tree", "depth", "lines"}, "spot": {"tree", "value", "lines"},
    "send": {"path", "count"}, "trouble": {"pieces", "meter", "value", "path", "count"},
    "fix": {"pieces", "meter", "value"}, "measure": {"meter", "value"},
    "ask": {"text"}, "answer": {"text"}, "turn": {"text"},
    "show": {"items", "lines"}, "run": {"lines"}, "look": {"pointer", "index", "lines"},
    "compare": {"pointer", "index", "cells", "against", "lines"},
    "take": {"pointer", "index", "out_of", "expect", "lines"},
    "group": {"array", "cells", "text", "lines"},
    "reveal": {"array", "lines"},
    "discard": {"array", "cells", "lines"}, "clear": {"array", "lines"},
    "fill": {"array", "cell", "cells", "value", "expect", "lines"},
    "count": {"counter", "expect", "lines"},
}
_NEEDS = {
    "send": "a send move needs a path of two or more pieces",
    "measure": "a measure move needs a meter and a value",
    "ask": "an ask move needs the question it shows, as text",
    "turn": "a turn move needs the turning point it shows, as text",
    "answer": "an answer move needs the answer it shows, as text",
    "show": "a show move needs the items it puts on screen",
    "run": "a run move needs the lines of code it lights; for a sentence that only explains what "
           "is on screen, use a show move naming the items it is about",
    "look": "a look move needs a pointer and the index of the cell it points at",
    "compare": "a compare move needs a pointer and the value it is compared against",
    "group": 'a group move needs an array, the cells that belong together, and a name for them '
             'of at most 24 characters in "text"',
    "take": 'a take move needs a pointer, the value its cell is taken out of in "out_of", and '
            'the number that is left afterwards in "expect"',
    "discard": "a discard move needs an array and the cells it rules out",
    "fill": "a fill move needs an array and the cell it fills",
    "count": "a count move needs a counter",
    "clear": "a clear move needs the array whose marks it wipes",
    "grow": "a grow move needs the tree it reveals more of",
    "spot": "a spot move needs a tree and the value it picks out",
    "remove": "a remove move needs what it takes off the screen",
}


class BeatMove(BaseModel):
    """What the viewer sees while a beat is spoken, chosen from the short menu of the lesson's
    playbook. Code turns a move into the actions, the claim and the proof, so they cannot
    disagree with each other."""
    model_config = ConfigDict(extra="forbid")
    do: Literal["introduce", "send", "trouble", "fix", "measure", "point", "remove",
                "show", "run", "look", "compare", "discard", "fill", "count", "clear",
                "grow", "spot", "take", "group", "reveal", "ask", "answer", "turn"]
    text: str | None = None                           # the line an ask or an answer shows
    # on a map
    pieces: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)     # pieces a request travels through, in order
    meter: str | None = None
    value: float | None = None                        # a meter's reading, or the number a fill writes
    count: int = Field(default=1, ge=1, le=5)         # balls sent along the path: 4 is heavy traffic
    # on a trace: code beside the data it works on
    lines: list[int] = Field(default_factory=list)    # lines of code lit while this is spoken, from 1
    items: list[str] = Field(default_factory=list)
    pointer: str | None = None
    index: int | None = Field(default=None, ge=0)
    against: str | None = None                        # the value a pointed cell is compared with
    out_of: str | None = None                         # the value a pointed cell's number is taken out of
    array: str | None = None
    cells: list[int] = Field(default_factory=list)
    cell: int | None = Field(default=None, ge=0)
    counter: str | None = None
    tree: str | None = None
    depth: int | None = Field(default=None, ge=0)     # how many levels down a grow reveals
    # The number the lesson says something comes to: a cell of a table (one number for each cell
    # named), or a counter's total. Code works the real value out and refuses a lesson whose
    # number differs, so the narration cannot say eight over a table that shows five.
    expect: float | list[float] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "BeatMove":
        a = "an" if self.do[0] in "aeiou" else "a"
        fields = type(self).model_fields
        given = {name for name in fields if name != "do"
                 and getattr(self, name) != fields[name].get_default(call_default_factory=True)}
        stray = sorted(given - _TAKES[self.do])
        if stray:
            raise ValueError(f"{a} {self.do} move has no {stray[0]}; it takes {sorted(_TAKES[self.do])}")
        if self.do in {"trouble", "fix", "measure"} and (self.meter is None) != (self.value is None):
            raise ValueError("a move names a meter together with the value it should read")
        lacks = {
            "introduce": not self.pieces, "point": not self.pieces,
            "remove": not self.pieces and not self.items,
            "grow": self.tree is None, "spot": self.tree is None or self.value is None,
            "send": len(self.path) < 2, "measure": self.meter is None,
            "trouble": not self.pieces and self.meter is None,
            "fix": not self.pieces and self.meter is None,
            "ask": not self.text, "answer": not self.text, "turn": not self.text,
            "show": not self.items, "run": not self.lines,
            "look": self.pointer is None or self.index is None,
            "compare": self.pointer is None or self.against is None,
            "take": self.pointer is None or self.out_of is None or self.expect is None,
            "reveal": self.array is None,
            "group": (self.array is None or not self.cells or not self.text
                      or len(self.text or "") > 24),
            "discard": self.array is None or not self.cells,
            "fill": self.array is None or (self.cell is None and not self.cells),
            "count": self.counter is None, "clear": self.array is None,
        }
        if lacks[self.do]:
            raise ValueError(_NEEDS.get(self.do, f"a {self.do} move needs pieces" + (
                " or a meter" if self.do in {"trouble", "fix"} else "")))
        if self.do == "fill":
            # The move never carries the working: the table's rule does. It names the cell and
            # the number the lesson says is in it.
            many = bool(self.cells)
            if many and self.cell is not None:
                raise ValueError('a fill move names one "cell" or several "cells", not both')
            if self.value is not None and (many or self.expect is not None):
                raise ValueError('a fill move with a "value" writes that one number into one '
                                 '"cell" of a table that has no rule, and has nothing to check; '
                                 'on a table with a rule give "expect" and no "value"')
            if self.value is None and (self.expect is None or isinstance(self.expect, list) != many
                                       or (many and len(self.expect) != len(self.cells))):
                raise ValueError('a fill move says what its cell comes to in "expect": one number '
                                 'for one "cell", a list with one number per cell for several '
                                 '"cells". It is checked against the table\'s rule')
        if self.do in {"count", "take"} and isinstance(self.expect, list):
            raise ValueError(f'a {self.do} move expects one number, not a list')
        if self.do == "compare" and self.cells and self.index is not None:
            raise ValueError('a compare move checks one cell ("index") or several in turn '
                             '("cells"), not both')
        if any(line < 1 for line in self.lines):
            raise ValueError("lines of code are counted from 1")
        if self.text is not None:
            if len(self.text) > LINE_LENGTH:
                source = {"ask": "; it is the brief's question, so shorten that",
                          "turn": "; it is the brief's turning_point, so shorten that"}.get(self.do, "")
                raise ValueError(f"the text of {a} {self.do} move is shown under the picture: at "
                                 f"most {LINE_LENGTH} characters, not {len(self.text)}{source}")
            if self.do == "ask" and not self.text.rstrip().endswith("?"):
                raise ValueError("the text of an ask move is a question, ending in '?'")
        return self


class LessonBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    spoken_text: str = Field(..., min_length=1)
    claim_ids: list[str] = Field(..., min_length=1)
    visual_anchors: list[str] = Field(default_factory=list)
    claim_requirements: dict[str, list[VisualRequirement]] = Field(default_factory=dict)
    move: BeatMove | None = None      # set on every beat of a map lesson, and only there
    # The model's own reason for this step, written before the sentence and never shown or spoken.
    # With no hidden reasoning, what a model writes first is where it thinks.
    why: str | None = None

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


class TraceCode(BaseModel):
    """The code a trace lesson explains, shown in an editor window beside the data."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="code.py", min_length=1, max_length=28)
    source: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _fits_the_window(self) -> "TraceCode":
        rows = self.source.split("\n")
        if len(rows) > 14 or any(len(row) > 48 for row in rows):
            raise ValueError("the code must stay readable beside the data: at most 14 lines of at "
                             f"most 48 characters; this has {len(rows)} lines, the longest "
                             f"{max(len(row) for row in rows)} characters")
        if "\t" in self.source:
            raise ValueError("indent the code with spaces, not tabs")
        return self


class TableRule(BaseModel):
    """How a table is filled, stated once: its first cells are given, and every later cell is
    worked out from the cells a fixed number of steps before it. Code fills the table from this,
    so a lesson cannot fill a cell out of order or work one out from a cell that is still empty."""
    model_config = ConfigDict(extra="forbid")
    start: list[int | float] = Field(..., min_length=1, max_length=6)   # cells 0, 1, ... as given
    back: list[int] = Field(..., min_length=1, max_length=4)    # how many cells back a cell reads
    op: Literal["sum", "min", "max"]                            # how the cells read are combined
    plus: float = 0                                             # added after combining

    @model_validator(mode="after")
    def _reads_cells_that_exist(self) -> "TableRule":
        if any(step < 1 for step in self.back) or len(set(self.back)) != len(self.back):
            raise ValueError('a rule\'s "back" says how many cells back a cell reads: whole '
                             'numbers from 1, each once, such as [1, 2]')
        if len(self.start) < min(self.back):
            raise ValueError(f'the first cell the rule works out is cell {len(self.start)}, and the '
                             f'nearest cell it reads is {min(self.back)} back, before the table '
                             f'begins; give "start" at least {min(self.back)} values, counting '
                             'cells from 0')
        return self


class TraceItem(BaseModel):
    """One thing on the data side of a trace: an array (or an empty table to fill), a pointer
    into an array, a fixed value such as a target, or a counter."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,23}$")
    kind: Literal["array", "pointer", "value", "counter", "tree"]
    label: str = Field(..., min_length=1, max_length=22)
    items: list[int | float | str] = Field(default_factory=list, max_length=12)   # an array's values
    size: int | None = Field(default=None, ge=2, le=12)     # an array that starts empty, to be filled
    rule: TableRule | None = None                           # how an empty table's cells are worked out
    # The number an array's first cell goes by, 0 unless given: with 1, its cells are numbered
    # from 1 on screen, in the working and in the lesson's moves, for stair 1 or day 1.
    first: int | None = Field(default=None, ge=0, le=1)
    # How many of an array's first cells are on show at the start; the rest are drawn as "?"
    # until a reveal move, so the answer is not on screen before the question is asked.
    shown_at_first: int | None = Field(default=None, ge=1)
    on: str | None = None                                   # the array a pointer points into
    value: int | float | str | None = None                  # what a fixed value shows
    # a counter that goes up by itself: on every compare of this pointer, every call of this tree,
    # or every cell filled in this array
    counts: str | None = None
    start: int | None = Field(default=None, ge=1, le=12)    # a tree: the value the recursion is asked for
    steps: list[int] = Field(default_factory=list, max_length=3)   # how much each call steps down by
    stop: int = Field(default=1, ge=0)                      # the value at which a call asks no further

    @model_validator(mode="after")
    def _shape(self) -> "TraceItem":
        mine = {"array": {"items", "size", "rule", "first", "shown_at_first"}, "pointer": {"on"},
                "value": {"value"},
                "counter": {"counts"}, "tree": {"start", "steps"}}
        stray = sorted(name for name in ("items", "size", "rule", "first", "shown_at_first", "on",
                                         "value", "counts", "start", "steps")
                       if getattr(self, name) not in (None, []) and name not in mine[self.kind])
        if stray:
            raise ValueError(f"trace item {self.id!r}: a {self.kind} has no {stray[0]}")
        if self.kind == "array" and bool(self.items) == (self.size is not None):
            raise ValueError(f"trace array {self.id!r} has either its items, or a size if it "
                             "starts empty and is filled")
        if self.kind == "array" and self.items and len(self.items) < 2:
            raise ValueError(f"trace array {self.id!r} needs at least two items")
        wide = [item for item in self.items if len(str(item)) > 9]
        if wide:
            raise ValueError(f"trace array {self.id!r}: {wide[0]!r} does not fit in a cell; an "
                             "item is at most nine characters")
        if self.rule is not None and self.items:
            raise ValueError(f'trace array {self.id!r} has a rule, so it starts empty and is filled '
                             'in: give it "size", not "items"')
        if self.rule is not None and len(self.rule.start) > self.size:
            raise ValueError(f"trace array {self.id!r} has {self.size} cells and "
                             f"{len(self.rule.start)} start values")
        if self.kind == "pointer" and not self.on:
            raise ValueError(f"trace pointer {self.id!r} names the array it points into in 'on'")
        if self.kind == "value" and self.value is None:
            raise ValueError(f"trace value {self.id!r} needs its value")
        if self.kind == "tree":
            if self.start is None or not self.steps or any(step < 1 for step in self.steps):
                raise ValueError(f"trace tree {self.id!r} needs the value it starts from in "
                                 "'start' and how much each call steps down by in 'steps'")
            calls = len(call_tree(self.start, self.steps, self.stop))
            if calls > MAX_CALLS:
                raise ValueError(f"trace tree {self.id!r} would make more than {MAX_CALLS} calls, "
                                 "too many to read; start from a smaller value")
            if calls < 3:
                raise ValueError(f"trace tree {self.id!r} makes no calls below its start")
        return self

    @property
    def calls(self) -> list[dict]:
        """A tree's calls, in the order they are revealed."""
        return call_tree(self.start, self.steps, self.stop)

    @property
    def length(self) -> int:
        return len(self.items) or (self.size or 0)

    @property
    def base(self) -> int:
        """The number of an array's first cell."""
        return self.first or 0


class LessonTrace(BaseModel):
    """The one picture an algorithm lesson is taught on: code on the left, the data it works on
    on the right. Scenes light lines and change the data; they cannot add to either."""
    model_config = ConfigDict(extra="forbid")
    code: TraceCode | None = None
    data: list[TraceItem] = Field(..., min_length=1, max_length=10)

    @model_validator(mode="after")
    def _consistent(self) -> "LessonTrace":
        kinds = {item.id: item.kind for item in self.data}
        if len(kinds) != len(self.data) or "code" in kinds or "working" in kinds:
            raise ValueError("trace item ids must be unique, and 'code' and 'working' are taken")
        if not {"array", "tree"} & set(kinds.values()):
            raise ValueError("a trace needs at least one array or tree")
        labels = [item.label.casefold() for item in self.data]
        twice = sorted({label for label in labels if labels.count(label) > 1})
        if twice:
            raise ValueError(f"trace items share the label {twice[0]!r}; name each one so a viewer "
                             "can tell them apart, such as 'Checks, one by one' and 'Checks, binary'")
        # Arrays, values and counters are stacked on the data side; pointers sit on their array.
        room = {"array": 2, "value": 2, "counter": 3, "pointer": 4, "tree": 1}
        for kind, most in room.items():
            if list(kinds.values()).count(kind) > most:
                raise ValueError(f"a trace has room for at most {most} {kind}s")
        for item in self.data:
            if item.kind == "pointer" and kinds.get(item.on) != "array":
                raise ValueError(f"trace pointer {item.id!r} points into {item.on!r}, which is "
                                 "not an array of the trace")
            if item.counts is not None and kinds.get(item.counts) not in {"pointer", "tree", "array"}:
                raise ValueError(f"trace counter {item.id!r} counts {item.counts!r}, which is "
                                 "not a pointer, a tree or an array of the trace")
        return self


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
    brief: LessonBrief | None = None      # required of a newly planned lesson with a picture
    map: LessonMap | None = None          # the picture of a system lesson
    trace: LessonTrace | None = None      # the picture of an algorithm lesson
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
        self._moves_fit_the_picture()
        return self

    def _moves_fit_the_picture(self) -> None:
        beats = [beat for scene in self.scenes for beat in scene.beats]
        if self.map is not None and self.trace is not None:
            raise ValueError("a lesson is taught on a map or on a trace, not both")
        if self.map is None and self.trace is None:
            stray = [beat.id for beat in beats if beat.move is not None]
            if stray:
                raise ValueError(f"beat(s) {stray} have a move but the lesson has no map")
            return
        kind = "map" if self.map is not None else "trace"
        menu = (MAP_MOVES if self.map is not None else TRACE_MOVES) + LINE_MOVES
        for beat in beats:
            if beat.move is None:
                raise ValueError(f"beat {beat.id}: every beat of a {kind} lesson needs a move")
            if len(beat.claim_ids) != 1:
                raise ValueError(f"beat {beat.id}: a {kind} beat makes exactly one claim")
            if beat.move.do not in menu:
                raise ValueError(f"beat {beat.id}: {beat.move.do!r} is not a move of a {kind} "
                                 f"lesson; its moves are {list(menu)}")
        if self.map is not None:
            self._moves_fit_the_map(beats)
        else:
            self._moves_fit_the_trace(beats)
        turns = [beat.id for beat in beats if beat.move.do == "turn"]
        if len(turns) > 1:
            raise ValueError(f"beats {turns} are both turn moves; a lesson has one turning point")
        for scene in self.scenes:       # the lines under the picture: room for a question and one more
            said = [beat.move.do for beat in scene.beats]
            if said.count("ask") > 1 or said.count("answer") > 1:
                raise ValueError(f"scene {scene.id}: a scene asks at most one question and gives "
                                 "at most one answer")
            if "answer" in said and ("ask" not in said or said.index("answer") < said.index("ask")):
                raise ValueError(f"scene {scene.id}: an answer move comes after an ask move in "
                                 "the same scene")

    def _moves_fit_the_map(self, beats: list[LessonBeat]) -> None:
        kinds = {piece.id: piece.kind for piece in self.map.pieces}
        joined = {frozenset((arrow.source, arrow.target)) for arrow in self.map.arrows}
        for beat in beats:
            move = beat.move
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
            if move.items:
                raise ValueError(f"beat {beat.id}: a {move.do} move of a map lesson names pieces, "
                                 "not items")
            if move.do in {"trouble", "fix"} and any(kinds[item] != "piece" for item in move.pieces):
                raise ValueError(f"beat {beat.id}: only icon pieces turn red or get fixed; use "
                                 "'meter' for a meter")

    def _moves_fit_the_trace(self, beats: list[LessonBeat]) -> None:
        """Every beat is checked, and the faults of all of them are reported together: a model
        told of one fault a try mends one fault a try, and has five."""
        items = {item.id: item for item in self.trace.data}
        rows = len(self.trace.code.source.split("\n")) if self.trace.code else 0
        faults = []
        for beat in beats:
            try:
                self._move_fits_the_trace(beat, items, rows)
            except ValueError as fault:
                faults.append(str(fault))
        if faults:
            raise ValueError("; ".join(faults[:6])
                             + (f"; and {len(faults) - 6} more like these" if len(faults) > 6 else ""))

    def _move_fits_the_trace(self, beat: LessonBeat, items: dict, rows: int) -> None:
        move, where = beat.move, f"beat {beat.id}"
        named = [*move.items, *(name for name in (move.pointer, move.against, move.out_of,
                                                  move.array, move.counter, move.tree) if name)]
        if move.pieces:
            raise ValueError(f"{where}: a {move.do} move of a trace lesson names \"items\", "
                             "not pieces")
        unknown = sorted(set(named) - set(items) - ({"code"} if rows else set()))
        if unknown:
            raise ValueError(f"{where}: move names {unknown}, not in the trace; the trace has "
                             f"{sorted(items) + (['code'] if rows else [])}")
        outside = [line for line in move.lines if line > rows]
        if outside:
            raise ValueError(f"{where}: the code has lines 1 to {rows}; there is no line "
                             f"{outside[0]}" if rows else
                             f"{where}: the move lights lines of code, but the trace has no code")
        for name, wanted in ((move.pointer, "pointer"), (move.against, "value"),
                             (move.out_of, "value"), (move.array, "array"),
                             (move.counter, "counter"), (move.tree, "tree")):
            if name and items[name].kind != wanted:
                how = (f'; to count it, add a counter to the trace\'s data with "counts": '
                       f'"{name}" and name that counter here' if wanted == "counter" else "")
                raise ValueError(f"{where}: {name!r} is not {'an' if wanted == 'array' else 'a'} "
                                 f"{wanted}{how}")
        array = items[items[move.pointer].on] if move.pointer else items.get(move.array)
        cells = [*move.cells, *(cell for cell in (move.index, move.cell) if cell is not None)]
        beyond = sorted(cell for cell in cells if array is not None
                        and not array.base <= cell < array.base + array.length)
        if beyond:
            raise ValueError(f"{where}: {array.id!r} has cells {array.base} to "
                             f"{array.base + array.length - 1}; there is no cell {beyond[0]}")
        if move.do == "count" and items[move.counter].counts and move.expect is None:
            raise ValueError(f"{where}: {move.counter!r} counts by itself; say the total you "
                             'expect it to read in "expect", and it is checked')
        if move.tree:
            calls = items[move.tree].calls
            deepest = max(call["depth"] for call in calls)
            if move.depth is not None and move.depth > deepest:
                raise ValueError(f"{where}: {move.tree!r} is {deepest} levels deep; there is "
                                 f"no level {move.depth}")
            if move.do == "spot" and move.value not in {call["value"] for call in calls}:
                raise ValueError(f"{where}: {move.tree!r} never calls for {move.value:g}")
        if move.do == "fill" and array.rule is not None and move.value is not None:
            raise ValueError(
                f'{where}: {array.id!r} is filled by its rule, so a fill gives no "value". '
                "Name the cell and the number you say it holds, which is checked: "
                f'{{"do":"fill","array":"{array.id}","cell":{move.cell},'
                f'"expect":{move.value:g}}}')
        if move.do == "fill" and array.rule is None and move.value is None:
            raise ValueError(
                f"{where}: {array.id!r} has no rule to work a cell out from. State it once on "
                'the array, as "rule": {"start":[1,1],"back":[1,2],"op":"sum"}, or give the '
                'fill the "value" it writes')
