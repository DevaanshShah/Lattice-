from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

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
WORDS_PER_SECOND = 2.8    # measured on two rendered lessons: 154 and 174 words, 57 s each
LENGTH_TOLERANCE = .3
PLAYBOOK_ATTEMPTS = 5     # tries for a lesson with a playbook; each rejection carries its reason
WORDS_PER_BEAT = 17       # one spoken sentence; a lesson's size is given to the model in beats
BEATS_PER_SCENE = 3.5


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None, attempts: int = 3,
             schema_version: int = 1, target_seconds: float | None = None,
             max_scenes: int | None = None, on_reject=None,
             diagnostic_dir: str | Path | None = None) -> LessonPlan:
    """`on_reject(reason)` is called for every answer that is sent back, so a run can show why a
    lesson needed more than one call."""
    if schema_version not in (1, 2):
        raise ValueError(f"unsupported lesson plan schema version: {schema_version}")
    client = client or get_client()
    # The recipe decides the board, and the board its playbook: a prompt of its own, a menu of
    # moves, and the code that draws them. A board without a playbook gets the general prompt.
    playbook = PLAYBOOKS.get(skill.board) if schema_version == 2 else None
    icons = asset_inventory()["icons"] if playbook is not None and playbook.needs_icons else []
    contract = f"Selected skill: {skill.id}\nLesson guidance: {skill.outline_guidance}"
    if schema_version == 1:
        contract += f"\nRequired visual roles: {', '.join(skill.required_roles)}"
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
        {"role": "user", "content": f"Topic: {topic}\n\n{contract}\n\n"
                                    + (f"Icon list: {', '.join(icons)}\n\n" if icons else "")
                                    + length
                                    + "Return the lesson plan JSON now."},
    ]
    last: Exception | None = None
    # A lesson with a playbook is checked much harder (its numbers, its order, its room in the
    # frame), and every rejection says exactly what to change, so it is given more tries.
    tries = max(attempts, PLAYBOOK_ATTEMPTS) if playbook is not None else attempts
    for attempt in range(tries):
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
            if words and not low <= spoken <= high:
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
            if on_reject is not None:
                on_reject(str(exc))
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That was invalid ({exc}). Return only valid JSON."}]
    raise LessonPlanError(f"lesson plan invalid after {tries} attempts: {last}")
