from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LessonPlan
from core.textutil import extract_json
from core.visual_assets import asset_inventory
from planner.lesson_map import fill_map_lesson, lesson_map_problems, plan_map_scenes
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


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None, attempts: int = 3,
             schema_version: int = 1, target_seconds: float | None = None,
             max_scenes: int | None = None, on_reject=None) -> LessonPlan:
    """`on_reject(reason)` is called for every answer that is sent back, so a run can show why a
    lesson needed more than one call."""
    if schema_version not in (1, 2):
        raise ValueError(f"unsupported lesson plan schema version: {schema_version}")
    client = client or get_client()
    # The recipe decides the board. A map lesson gets the map prompt and the icon list; any
    # other lesson gets the general prompt, which never mentions maps.
    on_map = schema_version == 2 and skill.board == "map"
    icons = asset_inventory()["icons"] if on_map else []
    contract = f"Selected skill: {skill.id}\nLesson guidance: {skill.outline_guidance}"
    if schema_version == 1:
        contract += f"\nRequired visual roles: {', '.join(skill.required_roles)}"
    # The length the user picked reaches the lesson itself, so nothing is cut off a finished one.
    words = round(target_seconds * WORDS_PER_SECOND) if target_seconds and schema_version == 2 else None
    low, high = ((round(words * (1 - LENGTH_TOLERANCE)), round(words * (1 + LENGTH_TOLERANCE)))
                 if words else (0, 0))
    length = (f"Length: the narration (all spoken_text together) is about {words} words, between "
              f"{low} and {high}.\n" if words else "")
    if max_scenes and schema_version == 2:
        length += f"Use at most {max_scenes} scene(s).\n"
    length += "\n" if length else ""
    messages = [
        {"role": "system", "content": load(
            "lesson-plan-map" if on_map else "lesson-plan-v2" if schema_version == 2 else "lesson-plan")},
        {"role": "user", "content": f"Topic: {topic}\n\n{contract}\n\n"
                                    + (f"Icon list: {', '.join(icons)}\n\n" if icons else "")
                                    + length
                                    + "Return the lesson plan JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages, max_tokens=4096, attempts=TRANSPORT_ATTEMPTS, timeout=60.0,
                          response_format=JSON_ONLY, extra_body=PLAN_EXTRA)
        try:
            data = extract_json(raw)
            if on_map and not isinstance(data.get("map"), dict):
                raise ValueError('this lesson is taught on a map: return the "map" and a "move" '
                                 "for every beat")
            if schema_version == 2 and not on_map and data.get("map") is not None:
                raise ValueError('this lesson is not taught on a map: leave "map" out')
            if on_map:
                data = fill_map_lesson(data)
            data["topic"] = topic
            data["skill_id"] = skill.id
            data["schema_version"] = schema_version
            plan = LessonPlan.model_validate(data)
            missing_anchors = [beat.id for scene in plan.scenes for beat in scene.beats
                               if not beat.visual_anchors]
            if missing_anchors:
                raise ValueError(f"visual_anchors required for beat(s): {missing_anchors}")
            spoken = sum(len(beat.spoken_text.split()) for scene in plan.scenes for beat in scene.beats)
            if words and not low <= spoken <= high:
                raise ValueError(f"the narration has {spoken} words; write between {low} and {high} "
                                 "by adding or removing beats, not by padding sentences")
            if max_scenes and schema_version == 2 and len(plan.scenes) > max_scenes:
                raise ValueError(f"{len(plan.scenes)} scenes; use at most {max_scenes}")
            problems = lesson_map_problems(plan, icons)
            if problems:
                raise ValueError("the map lesson cannot be drawn as written: " + "; ".join(problems[:6]))
            if plan.map is not None:
                # The picture is compiled from the moves, so a lesson that cannot be drawn is
                # found here and repaired by the one call that wrote it.
                plan_map_scenes(plan, skill)
            return plan
        except (ValueError, ValidationError) as exc:
            last = exc
            if on_reject is not None:
                on_reject(str(exc))
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That was invalid ({exc}). Return only valid JSON."}]
    raise LessonPlanError(f"lesson plan invalid after {attempts} attempts: {last}")
