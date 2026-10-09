from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LessonPlan
from core.textutil import extract_json
from planner.product_recipe import Recipe
from prompts.loader import load


# Transport attempts for ONE planning call (timeout, 429, 5xx, blank answer). The validator's
# repair loop deals with wrong answers; this only keeps a single network blip from ending a plan.
TRANSPORT_ATTEMPTS = 3


class LessonPlanError(RuntimeError):
    pass


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None, attempts: int = 3,
             schema_version: int = 1) -> LessonPlan:
    if schema_version not in (1, 2):
        raise ValueError(f"unsupported lesson plan schema version: {schema_version}")
    client = client or get_client()
    contract = f"Selected skill: {skill.id}\nLesson guidance: {skill.outline_guidance}"
    if schema_version == 1:
        contract += f"\nRequired visual roles: {', '.join(skill.required_roles)}"
    messages = [
        {"role": "system", "content": load("lesson-plan-v2" if schema_version == 2 else "lesson-plan")},
        {"role": "user", "content": f"Topic: {topic}\n\n{contract}\n\nReturn the lesson plan JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages, max_tokens=4096, attempts=TRANSPORT_ATTEMPTS, timeout=60.0)
        try:
            data = extract_json(raw)
            data["topic"] = topic
            data["skill_id"] = skill.id
            data["schema_version"] = schema_version
            plan = LessonPlan.model_validate(data)
            missing_anchors = [beat.id for scene in plan.scenes for beat in scene.beats
                               if not beat.visual_anchors]
            if missing_anchors:
                raise ValueError(f"visual_anchors required for beat(s): {missing_anchors}")
            return plan
        except (ValueError, ValidationError) as exc:
            last = exc
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That was invalid ({exc}). Return only valid JSON."}]
    raise LessonPlanError(f"lesson plan invalid after {attempts} attempts: {last}")
