"""What every playbook's compiler shares.

A playbook (a map, a trace) turns a lesson's moves into scenes. These parts are the same whatever
the picture is: the lines of text shown under it, the brief's share of a lesson, the timing of a
beat's steps, and the record of one compiled beat.
"""
from __future__ import annotations

import re

from core.schemas.lesson_plan import LessonPlan, LessonScene
from core.visual_state import VisualState

LINES = {"ask", "answer"}       # moves that show a line of text, not a change in the picture
THINK_PAUSE = 3.0               # seconds a question is held before its answer
BREATH = 0.4                    # silence after every sentence, so one does not run into the next
SCENE_BREATH = 0.9              # and a longer one as a scene closes


def number(value: float):
    """95.0 is drawn and matched as 95."""
    return int(value) if float(value).is_integer() else value


def takeaway_id(scene: LessonScene) -> str:
    return f"takeaway_{scene.id}"


def line_id(beat) -> str:
    return f"{beat.id}_line"


def takeaway_beat(scene: LessonScene) -> int | None:
    """The beat on which a scene's takeaway appears: its last, or the one before the check question
    when the scene ends on a question and its answer. There is room for two lines under the
    picture, so the takeaway is shown first and gives way to the question."""
    if not scene.takeaway:
        return None
    moves = [beat.move.do if beat.move is not None else None for beat in scene.beats]
    if "answer" not in moves:
        return len(moves) - 1
    asked = moves.index("ask")
    return asked - 1 if asked > 0 else None


def stage_the_takeaway(scene: LessonScene, position: int, actions: list[dict], visible: set[str]) -> None:
    """Bring a scene's takeaway on at its beat, and take it off as the check question comes on."""
    mine = takeaway_id(scene)
    if scene.beats[position].move.do == "ask" and mine in visible:
        actions.insert(0, {"kind": "hide", "target_ids": [mine], "params": {}})
        visible.discard(mine)
    if takeaway_beat(scene) == position:
        actions.append({"kind": "appear", "target_ids": [mine], "params": {}})
        visible.add(mine)


def line_objects(scene: LessonScene) -> list[dict]:
    """The lines of text a scene shows under its picture: a question, an answer, a takeaway."""
    objects = []
    for beat in scene.beats:
        if beat.move is not None and beat.move.do in LINES:
            asks = beat.move.do == "ask"
            objects.append({"id": line_id(beat), "kind": "caption", "role": "audit",
                            "label": beat.move.text,
                            "payload": {"tone": "white", "ask": True} if asks
                            else {"tone": "teal", "tick": True}})
    if takeaway_beat(scene) is not None:
        objects.append({"id": takeaway_id(scene), "kind": "caption", "role": "audit",
                        "label": scene.takeaway, "payload": {"tone": "teal", "tick": True}})
    return objects


def apply_brief(data: dict) -> dict | None:
    """Let the brief supply what it already says: the objective, the audience, and the check
    question and its answer, which are added after the model's last beat. They are the brief's own
    words, so the model cannot forget them and does not spend its beats on them."""
    brief = data.get("brief")
    if not isinstance(brief, dict):
        return None
    if isinstance(brief.get("can_do"), str):
        data.setdefault("learning_objective", brief["can_do"])
    if isinstance(brief.get("learner"), str):
        data.setdefault("audience", brief["learner"])
    last = data["scenes"][-1] if data.get("scenes") and isinstance(data["scenes"][-1], dict) else {}
    closing = last.get("beats")
    check, answer = brief.get("check_question"), brief.get("check_answer")
    asked = isinstance(closing, list) and any(
        isinstance(beat, dict) and isinstance(beat.get("move"), dict)
        and beat["move"].get("do") == "ask" for beat in closing)
    if isinstance(closing, list) and isinstance(check, str) and isinstance(answer, str) and not asked:
        closing.append({"spoken_text": check, "move": {"do": "ask", "text": check}})
        closing.append({"spoken_text": answer, "move": {"do": "answer", "text": answer}})
    return brief


def ask_the_question(beat: dict, brief: dict | None) -> None:
    """An ask with no text asks the lesson's own question, and what the beat speaks is the
    question it shows: the viewer never hears one question while reading another."""
    move = beat["move"]
    if move.get("do") != "ask":
        return
    if not move.get("text") and isinstance(brief, dict) and isinstance(brief.get("question"), str):
        move["text"] = brief["question"]
    if isinstance(move.get("text"), str) and move["text"].strip():
        beat["spoken_text"] = move["text"]


def plain_id(old: str, fallback: str) -> str:
    """An id as a plain lower-case name. An id is only a handle, so 'order-service', 'DB 1' and
    'callCount' are tidied, not sent back."""
    new = re.sub(r"[^a-z0-9]+", "_", old.lower()).strip("_")[:24] or fallback
    return new if new[0].isalpha() else (fallback[0] + "_" + new)[:24]


def carried(objects: list[dict], previous_state: VisualState | None) -> tuple[list[str], set[str], dict]:
    """What a scene opens with: the objects the previous scene left on screen, in their state."""
    opening = [obj["id"] for obj in objects
               if previous_state is not None and obj["id"] in previous_state.visible]
    payloads = {obj["id"]: dict(obj["payload"]) for obj in objects}
    if previous_state is not None:
        for obj_id in opening:
            payloads[obj_id] = dict(previous_state.payloads[obj_id])
    return opening, set(opening), payloads


def compiled_beat(scene: LessonScene, position: int, actions: list[dict], shown: list[str],
                  seconds: float = 0.0) -> dict:
    """One beat of a compiled scene: its steps timed, its claim tied to what it shows, a breath
    after its sentence (longer after a question that the next beat answers, and as a scene
    closes), and the least time its steps need, in `seconds`."""
    beat = scene.beats[position]
    for count, action in enumerate(actions):
        # steps share the beat evenly; each plays briskly at the start of its share and holds
        action["id"] = f"{beat.id}_{count + 1}"
        action["start_fraction"] = round(.06 + .88 * count / len(actions), 4)
        action["end_fraction"] = round(.06 + .88 * (count + 1) / len(actions), 4)
    evidence = [{"claim_ids": [claim], "object_ids": shown, "kind": kind,
                 "action_ids": [action["id"] for action in actions]}
                for claim, kinds in beat.claim_requirements.items() for kind in kinds]
    entry = {"narration_beat_id": beat.id, "actions": actions, "evidence": evidence}
    following = scene.beats[position + 1].move.do if position + 1 < len(scene.beats) else None
    entry["pause_after"] = (THINK_PAUSE if beat.move.do == "ask" and following == "answer"
                            else SCENE_BREATH if following is None else BREATH)
    if seconds:
        entry["min_seconds"] = round(seconds, 2)
    return entry


def story_shape(lesson: LessonPlan) -> str:
    """A lesson's plot as its moves, scene by scene, for telling whether lessons on different
    topics are one template: 'introduce send send | trouble fix'."""
    if lesson.map is None and lesson.trace is None:
        return ""
    return " | ".join(" ".join(beat.move.do for beat in scene.beats) for scene in lesson.scenes)
