from __future__ import annotations

import json

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.browser_visual_plan import BrowserScene, BrowserVisualPlan, VisualObject
from core.schemas.lesson_plan import LessonPlan
from core.textutil import extract_json
from planner.product_recipe import Recipe
from prompts.loader import load
from verification.visual_plan_validation import VisualPlanValidationError, validate, validate_scene


class BrowserVisualPlanError(RuntimeError):
    pass


def generate(lesson: LessonPlan, skill: Recipe, *, client: LLMClient | None = None,
             attempts: int = 3) -> BrowserVisualPlan:
    client = client or get_client()
    scenes: list[BrowserScene] = []
    roles_used: set[str] = set()
    for index, lesson_scene in enumerate(lesson.scenes):
        previous = scenes[-1] if scenes else None
        previous_objects = {obj.id: obj for obj in previous.objects} if previous else {}
        previous_closing = set(previous.closing_visible_ids) if previous else set()
        available = [previous_objects[obj_id].model_dump()
                     for obj_id in previous.closing_visible_ids] if previous else []
        missing_roles = sorted(set(skill.required_roles) - roles_used)
        final_requirement = (
            f"This is the final scene; it must include all still-missing required roles: "
            f"{', '.join(missing_roles) or 'none'}."
            if index == len(lesson.scenes) - 1 else
            f"Required roles still missing across the video: {', '.join(missing_roles) or 'none'}."
        )
        messages = [
            {"role": "system", "content": load("browser-visual-plan")},
            {"role": "user", "content": (
                f"Topic: {lesson.topic}\nSelected skill: {skill.id}\n"
                f"Scene {index + 1} of {len(lesson.scenes)}.\n"
                f"Locked lesson scene:\n{lesson_scene.model_dump_json(indent=2)}\n\n"
                f"Allowed patterns: {', '.join(skill.allowed_patterns)}\n"
                f"Required visual roles: {', '.join(skill.required_roles)}\n"
                f"Roles already used: {', '.join(sorted(roles_used)) or 'none'}\n"
                f"Previous pattern: {previous.pattern if previous else 'none'}\n"
                f"Previous closing objects available for exact carryover:\n"
                f"{json.dumps(available, indent=2)}\n\n"
                f"{final_requirement}\nReturn this one visual scene JSON now."
            )},
        ]
        last: Exception | None = None
        for _ in range(attempts):
            raw = client.chat(messages, max_tokens=4096, attempts=1, timeout=60.0)
            try:
                scene = BrowserScene.model_validate(extract_json(raw))
                validate_scene(lesson_scene, scene, skill,
                               previous_closing=previous_closing,
                               previous_objects=previous_objects,
                               previous_pattern=previous.pattern if previous else None)
                if index == len(lesson.scenes) - 1:
                    missing = sorted(set(skill.required_roles) - roles_used -
                                     {obj.role for obj in scene.objects})
                    if missing:
                        raise VisualPlanValidationError(
                            f"final scene must include missing visual role(s): {missing}")
                scenes.append(scene)
                roles_used.update(obj.role for obj in scene.objects)
                break
            except (ValueError, ValidationError) as exc:
                last = exc
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": (
                                 f"That scene was invalid ({exc}). Repair only this scene. Every referenced "
                                 "id must be declared locally; carryover ids must exactly match an object in "
                                 "the supplied previous closing state and be visible at opening. If you reuse "
                                 "a previous closing id, it must be a carryover and its kind, role, and label "
                                 "must stay identical; add new downstream objects instead of changing it. Use kind "
                                 "'gate' with role 'decision'. For contour, never create axis or contour-line "
                                 "objects because the renderer draws them; use at most one object from each "
                                 "role group: input/source/context, operation/tool, metric/destination/result, "
                                 "output/audit. Every visual_anchor named in the locked lesson beat must appear "
                                 "verbatim in a visible object or relationship label by that beat. Return only "
                                 "the corrected scene JSON."
                             )}]
        else:
            raise BrowserVisualPlanError(
                f"browser visual scene {lesson_scene.id!r} invalid after {attempts} attempts: {last}")
    plan = BrowserVisualPlan(topic=lesson.topic, skill_id=skill.id, scenes=scenes)
    validate(lesson, plan, skill)
    return plan
