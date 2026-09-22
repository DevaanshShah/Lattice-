from __future__ import annotations

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LessonPlan
from core.textutil import extract_json
from planner.product_recipe import Recipe
from prompts.loader import load


class LessonPlanError(RuntimeError):
    pass


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None, attempts: int = 3) -> LessonPlan:
    client = client or get_client()
    contract = (
        f"Selected skill: {skill.id}\n"
        f"Lesson guidance: {skill.outline_guidance}\n"
        f"Required visual roles: {', '.join(skill.required_roles)}"
    )
    messages = [
        {"role": "system", "content": load("lesson-plan")},
        {"role": "user", "content": f"Topic: {topic}\n\n{contract}\n\nReturn the lesson plan JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages, max_tokens=4096, attempts=1, timeout=60.0)
        try:
            data = extract_json(raw)
            data["topic"] = topic
            data["skill_id"] = skill.id
            return LessonPlan.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last = exc
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That was invalid ({exc}). Return only valid JSON."}]
    raise LessonPlanError(f"lesson plan invalid after {attempts} attempts: {last}")
