from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LessonPlan
from core.textutil import extract_json
from core.visual_assets import asset_inventory
from planner.playbooks import PLAYBOOKS
from planner.product_recipe import Recipe
from prompts.loader import load


# Transport attempts for ONE planning call (timeout, 429, 5xx, blank answer). The validator's
# repair loop deals with wrong answers; this only keeps a single network blip from ending a plan.
TRANSPORT_ATTEMPTS = 3
# A plan is always one JSON object, so the provider is asked to guarantee the syntax. A small model
# otherwise returns a long plan with a missing comma three times in a row.
JSON_ONLY = {"type": "json_object"}
# A plan is written, not worked out. A reasoning model left to think spends the whole output
# budget on thought and returns nothing (measured on deepseek-v4.1-flash: 4,096 tokens of
# reasoning, empty answer, at four times the cost of the plan it writes with reasoning off).
PLAN_EXTRA = {"reasoning": {"enabled": False}}


class LessonPlanError(RuntimeError):
    pass


# Narration pace of the local voice, in words per second, and how far a lesson may be from the
# length the user asked for before it is sent back.
# 2.8 words a second measured on two rendered lessons at voice speed 1.0 (154 and 174 words, 57 s
# each); the voice now speaks at settings.kokoro_speed, and the budget follows it.
WORDS_PER_SECOND = 2.8 * settings.kokoro_speed
LENGTH_TOLERANCE = .3     # the band the model is asked to write within
# The band a lesson is refused outside of. Wider than the one asked for: a good lesson a few words
# off the band was sent back five times and the client got no video (binary search at 337 words
# for a 328 cap, a rate limiter at 168 for a 176 floor, 2026-11-21/22). Inside it, the narration
# is simply paced to its words. Longer is allowed further than shorter: a long lesson only runs a
# little over, a short one leaves a ninety-second request at under a minute.
LENGTH_SHORT, LENGTH_LONG = .35, .45
PLAYBOOK_ATTEMPTS = 5     # tries for a lesson with a playbook; each rejection carries its reason
WORDS_PER_BEAT = 17       # one spoken sentence; a lesson's size is given to the model in beats
BEATS_PER_SCENE = 3.5


def _reason(exc: Exception) -> str:
    """Why an answer is sent back, in words a model can act on: every fault with the beat or item
    it is in, and none of the validator's own boilerplate. A live lesson spent five tries going
    back and forth between two faults it could not see for eighty lines of noise."""
    if not isinstance(exc, ValidationError):
        return str(exc)
    faults = []
    for error in exc.errors():
        where = [str(part) for part in error["loc"]]
        if where[:1] == ["scenes"] and len(where) >= 4 and where[2] == "beats":
            place = f"beat s{int(where[1]) + 1}_b{int(where[3]) + 1}"
            rest = [part for part in where[4:] if part != "move"]
        elif where[:1] == ["scenes"] and len(where) >= 2:
            place, rest = f"scene {int(where[1]) + 1}", where[2:]
        elif where[:2] == ["trace", "data"] and len(where) >= 3:
            place, rest = f"item {int(where[2]) + 1} of the trace's data", where[3:]
        else:
            place, rest = ".".join(where[:1]) or "the lesson", where[1:]
        faults.append(" ".join([place, *rest]) + ": " + error["msg"].removeprefix("Value error, "))
    faults = list(dict.fromkeys(faults))
    return "; ".join(faults[:8]) + (f"; and {len(faults) - 8} more like these" if len(faults) > 8 else "")


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None, attempts: int = 3,
             schema_version: int = 1, target_seconds: float | None = None,
             max_scenes: int | None = None, on_reject=None,
             diagnostic_dir: str | Path | None = None) -> LessonPlan:
    """`on_reject(reason)` is called for every answer that is sent back, so a run can show why a
    lesson needed more than one call."""
    if schema_version not in (1, 2):
        raise ValueError(f"unsupported lesson plan schema version: {schema_version}")
    client = client or get_client()
    if schema_version == 2 and skill.planner == "staged_table":
        # Staged: a model describes the teaching, code builds every step, a model writes the
        # sentences. Measured better than one call for table lessons; when it cannot plan the
        # topic, the one-call lesson below still gives the client a video.
        from planner import lesson_recurrence
        try:
            return lesson_recurrence.generate(topic, skill, client=client)
        except (LessonPlanError, ValueError) as exc:     # a fault in the plan, not the network
            if on_reject is not None:
                on_reject(f"the staged table lesson could not be planned, so the one-call "
                          f"lesson is used: {exc}")
    if schema_version == 2 and skill.planner == "staged_graph":
        # A graph search: code runs it and builds every step (planner/lesson_graph.py).
        from planner import lesson_graph
        try:
            return lesson_graph.generate(topic, skill, client=client, target_seconds=target_seconds)
        except (LessonPlanError, ValueError) as exc:
            if on_reject is not None:
                on_reject(f"the staged graph lesson could not be planned, so the one-call "
                          f"lesson is used: {exc}")
    # The recipe decides the board, and the board its playbook: a prompt of its own, a menu of
    # moves, and the code that draws them. A board without a playbook gets the general prompt.
    playbook = PLAYBOOKS.get(skill.board) if schema_version == 2 else None
    icons = asset_inventory()["icons"] if playbook is not None and playbook.needs_icons else []
    contract = (f"Selected skill: {skill.id}\nLesson guidance: {skill.outline_guidance}"
                if playbook is None or playbook.guided else "")
    if schema_version == 1:
        contract += f"\nRequired visual roles: {', '.join(skill.required_roles)}"
    if playbook is not None and target_seconds:
        target_seconds = max(target_seconds, playbook.shortest)
    # The length the user picked reaches the lesson itself, so nothing is cut off a finished one.
    words = round(target_seconds * WORDS_PER_SECOND) if target_seconds and schema_version == 2 else None
    low, high = ((round(words * (1 - LENGTH_TOLERANCE)), round(words * (1 + LENGTH_TOLERANCE)))
                 if words else (0, 0))
    # A model follows a count of sentences far better than a count of words, so the budget is
    # also given as beats and scenes.
    beats = round(words / (playbook.beat_words if playbook is not None else WORDS_PER_BEAT)) if words else 0
    # On a map the check question and its answer are added by code: two beats the model does not write.
    own = max(3, beats - 2) if playbook is not None else beats
    length = (f"Length: the narration (all spoken_text together) is about {words} words, between "
              f"{low} and {high}"
              + (", counting the check question and its answer, which are added after your last "
                 "beat" if playbook is not None else "")
              + f". Write about {own} beats, in "
              f"{max(2, min(5, round(own / BEATS_PER_SCENE)))} scenes; do not write more."
              + "\n" if words else "")
    if max_scenes and schema_version == 2:
        length += f"Use at most {max_scenes} scene(s).\n"
    length += "\n" if length else ""
    messages = [
        {"role": "system", "content": load(
            playbook.prompt if playbook is not None
            else "lesson-plan-v2" if schema_version == 2 else "lesson-plan")},
        {"role": "user", "content": f"Topic: {topic}\n\n" + (f"{contract}\n\n" if contract else "")
                                    + (f"Icon list: {', '.join(icons)}\n\n" if icons else "")
                                    + length
                                    + "Return the lesson plan JSON now."},
    ]
    last: Exception | None = None
    # A lesson with a playbook is checked much harder (its numbers, its order, its room in the
    # frame), and every rejection says exactly what to change, so it is given more tries.
    tries = max(attempts, PLAYBOOK_ATTEMPTS) if playbook is not None else attempts
    asked = list(messages)
    before = None
    for attempt in range(tries):
        data = None
        raw = client.chat(messages, max_tokens=4096, attempts=TRANSPORT_ATTEMPTS, timeout=60.0,
                          response_format=JSON_ONLY, extra_body=PLAN_EXTRA)
        if diagnostic_dir is not None:      # what the model actually wrote, kept for diagnosis
            folder = Path(diagnostic_dir)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"lesson_attempt_{attempt + 1:02d}.txt").write_text(raw, encoding="utf-8")
        try:
            data = extract_json(raw)
            if playbook is not None and not isinstance(data.get(playbook.key), dict):
                raise ValueError(f'this lesson is taught on a {playbook.key}: return the '
                                 f'"{playbook.key}" and a "move" for every beat')
            for other in PLAYBOOKS.values():
                if schema_version == 2 and other is not playbook and data.get(other.key) is not None:
                    raise ValueError(f'this lesson is not taught on a {other.key}: leave '
                                     f'"{other.key}" out')
            if playbook is not None:
                data = playbook.fill(data)
            data["topic"] = topic
            data["skill_id"] = skill.id
            data["schema_version"] = schema_version
            plan = LessonPlan.model_validate(data)
            # a playbook's anchors come from its moves, and are checked when it is compiled
            missing_anchors = [] if playbook is not None else [
                beat.id for scene in plan.scenes for beat in scene.beats if not beat.visual_anchors]
            if missing_anchors:
                raise ValueError(f"visual_anchors required for beat(s): {missing_anchors}")
            spoken = sum(len(beat.spoken_text.split()) for scene in plan.scenes for beat in scene.beats)
            if words and not words * (1 - LENGTH_SHORT) <= spoken <= words * (1 + LENGTH_LONG):
                raise ValueError(f"the narration has {spoken} words; write between {low} and {high} "
                                 "by adding or removing beats, not by padding sentences")
            if max_scenes and schema_version == 2 and len(plan.scenes) > max_scenes:
                raise ValueError(f"{len(plan.scenes)} scenes; use at most {max_scenes}")
            if playbook is not None:
                problems = playbook.problems(plan, icons)
                if problems:
                    raise ValueError(f"the {playbook.key} lesson cannot be drawn as written: "
                                     + "; ".join(problems[:6]))
                # The picture is compiled from the moves, so a lesson that cannot be drawn is
                # found here and repaired by the one call that wrote it.
                scenes = playbook.scenes(plan, skill)
                weak = playbook.craft(plan, scenes)
                if weak:
                    raise ValueError("as teaching this falls short: " + "; ".join(weak[:4]))
            return plan
        except (ValueError, ValidationError) as exc:
            last = exc
            reason = _reason(exc)
            if on_reject is not None:
                on_reject(reason)
            repair = f"That was invalid ({reason}). Return only valid JSON."
            if playbook is not None:
                # A reviewed lesson showed what a bare reason invites: the checked number is
                # changed, a step is added so a count comes out, and the sentence is left wrong.
                facts = playbook.facts(data) if playbook.facts is not None and isinstance(data, dict) else ""
                repair += (" Change what this names and nothing else: return the whole plan with "
                           "every other beat exactly as it was. If you change a number in a move, "
                           "rewrite that beat's sentence to say the same number. Do not add a step "
                           "to make a count come out, and do not delete a move to make an error "
                           "go away." + (f" Worked out from your trace: {facts}." if facts else ""))
                if reason == before:
                    # the same fault twice: the move cannot do what the lesson wants of it
                    repair += (" This is the same fault as last time, so the change you made did "
                               "not touch it. If a move cannot do what you want, replace it with a "
                               "show move that lights the items the sentence is about, and let the "
                               "sentence carry the step.")
                before = reason
                # only the latest answer goes back: earlier ones are the faults already repaired
                messages = asked + [{"role": "assistant", "content": raw},
                                    {"role": "user", "content": repair}]
            else:
                messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": repair}]
    raise LessonPlanError(f"lesson plan invalid after {tries} attempts: {_reason(last)}")
