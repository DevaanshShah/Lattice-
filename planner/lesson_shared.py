"""What every playbook's compiler shares.

A playbook (a map, a trace) turns a lesson's moves into scenes. These parts are the same whatever
the picture is: the lines of text shown under it, the brief's share of a lesson, the timing of a
beat's steps, and the record of one compiled beat.
"""
from __future__ import annotations

from core.schemas.lesson_plan import LessonPlan, LessonScene
from core.visual_state import VisualState

LINES = {"ask", "answer"}       # moves that show a line of text, not a change in the picture
THINK_PAUSE = 1.6               # seconds a question is held before its answer


def number(value: float):
    """95.0 is drawn and matched as 95."""
    return int(value) if float(value).is_integer() else value


def takeaway_id(scene: LessonScene) -> str:
    return f"takeaway_{scene.id}"


def line_id(beat) -> str:
    return f"{beat.id}_line"


def closes_on_a_takeaway(scene: LessonScene) -> bool:
    """A scene that gives an answer ends on that answer; a takeaway under it would be a third line."""
    return bool(scene.takeaway) and not any(beat.move and beat.move.do == "answer" for beat in scene.beats)


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
    if closes_on_a_takeaway(scene):
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


def ask_the_question(move: dict, brief: dict | None) -> None:
    """An ask with no text asks the lesson's own question."""
    if (move.get("do") == "ask" and not move.get("text") and isinstance(brief, dict)
            and isinstance(brief.get("question"), str)):
        move["text"] = brief["question"]


def carried(objects: list[dict], previous_state: VisualState | None) -> tuple[list[str], set[str], dict]:
    """What a scene opens with: the objects the previous scene left on screen, in their state."""
    opening = [obj["id"] for obj in objects
               if previous_state is not None and obj["id"] in previous_state.visible]
    payloads = {obj["id"]: dict(obj["payload"]) for obj in objects}
    if previous_state is not None:
        for obj_id in opening:
            payloads[obj_id] = dict(previous_state.payloads[obj_id])
    return opening, set(opening), payloads


def compiled_beat(scene: LessonScene, position: int, actions: list[dict], shown: list[str]) -> dict:
    """One beat of a compiled scene: its steps timed, its claim tied to what it shows, and a
    pause after a question that the next beat answers."""
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
    if beat.move.do == "ask" and following == "answer":
        entry["pause_after"] = THINK_PAUSE      # the viewer gets a moment before the answer
    return entry


def story_shape(lesson: LessonPlan) -> str:
    """A lesson's plot as its moves, scene by scene, for telling whether lessons on different
    topics are one template: 'introduce send send | trouble fix'."""
    if lesson.map is None and lesson.trace is None:
        return ""
    return " | ".join(" ".join(beat.move.do for beat in scene.beats) for scene in lesson.scenes)
