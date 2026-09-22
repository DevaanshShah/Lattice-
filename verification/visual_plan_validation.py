from __future__ import annotations

from collections.abc import Mapping
import re

from core.schemas.browser_visual_plan import BrowserScene, BrowserVisualPlan, VisualObject
from core.schemas.lesson_plan import LessonPlan, LessonScene
from planner.product_recipe import Recipe


class VisualPlanValidationError(ValueError):
    pass


def _visible_labels_by_beat(scene: BrowserScene) -> dict[str, list[str]]:
    objects = {obj.id: obj for obj in scene.objects}
    visible = set(scene.opening_visible_ids)
    result: dict[str, list[str]] = {}
    for beat in scene.beats:
        for action in beat.actions:
            if action.kind == "deactivate":
                visible.difference_update(action.target_ids)
            elif action.kind != "hold":
                visible.update(action.target_ids)
        labels = [objects[obj_id].label for obj_id in visible if obj_id in objects]
        labels.extend(relation.label for relation in scene.relationships
                      if relation.label and relation.source_id in visible and relation.target_id in visible)
        result[beat.narration_beat_id] = labels
    return result


def _normalise_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def validate_scene(lesson_scene: LessonScene, visual_scene: BrowserScene, skill: Recipe, *,
                   previous_closing: set[str],
                   previous_objects: Mapping[str, VisualObject] | None = None,
                   previous_pattern: str | None = None) -> None:
    if visual_scene.lesson_scene_id != lesson_scene.id:
        raise VisualPlanValidationError(
            f"visual scene must map to locked lesson scene {lesson_scene.id!r}")
    if visual_scene.pattern not in skill.allowed_patterns:
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} uses disallowed pattern {visual_scene.pattern!r}")
    if previous_pattern == visual_scene.pattern and not visual_scene.carryover_ids:
        raise VisualPlanValidationError(
            "adjacent scenes may repeat a visual pattern only with explicit carryover")
    if visual_scene.pattern == "contour":
        groups = [
            {"input", "source", "context"},
            {"operation", "tool"},
            {"metric", "destination", "result"},
            {"output", "audit"},
        ]
        scene_roles = [obj.role for obj in visual_scene.objects]
        allowed_roles = set().union(*groups)
        unsupported = sorted(set(scene_roles) - allowed_roles)
        if len(visual_scene.objects) > 4 or unsupported:
            raise VisualPlanValidationError(
                f"contour scene {lesson_scene.id} must use at most four positioned objects; "
                f"unsupported roles={unsupported}")
        conflicts = [sorted(role for role in scene_roles if role in group)
                     for group in groups if sum(role in group for role in scene_roles) > 1]
        if conflicts:
            raise VisualPlanValidationError(
                f"contour scene {lesson_scene.id} has overlapping role positions: {conflicts}")
    expected_beats = {beat.id: beat for beat in lesson_scene.beats}
    actual_beats = {beat.narration_beat_id: beat for beat in visual_scene.beats}
    if set(actual_beats) != set(expected_beats):
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} must map exactly to its narration beats")
    visible_labels = _visible_labels_by_beat(visual_scene)
    for beat_id, lesson_beat in expected_beats.items():
        covered = {claim for evidence in actual_beats[beat_id].evidence for claim in evidence.claim_ids}
        missing = sorted(set(lesson_beat.claim_ids) - covered)
        unknown = sorted(covered - set(lesson_beat.claim_ids))
        if missing or unknown:
            raise VisualPlanValidationError(
                f"beat {beat_id} has invalid visual claim coverage; missing={missing}, unknown={unknown}")
        labels = [_normalise_label(label) for label in visible_labels[beat_id]]
        missing_anchors = [anchor for anchor in lesson_beat.visual_anchors
                           if not any(_normalise_label(anchor) in label for label in labels)]
        if missing_anchors:
            raise VisualPlanValidationError(
                f"beat {beat_id} is missing visible narration anchor(s): {missing_anchors}")
    missing_prior = sorted(set(visual_scene.carryover_ids) - previous_closing)
    if missing_prior:
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} carries object(s) absent from prior closing state: {missing_prior}")
    current_objects = {obj.id: obj for obj in visual_scene.objects}
    reused = sorted(set(current_objects) & previous_closing - set(visual_scene.carryover_ids))
    if reused:
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} reuses prior closing object id(s) without carryover: {reused}")
    if previous_objects:
        changed = sorted(obj_id for obj_id in visual_scene.carryover_ids
                         if current_objects[obj_id] != previous_objects[obj_id])
        if changed:
            raise VisualPlanValidationError(
                f"scene {lesson_scene.id} changes carried object definition(s): {changed}")


def validate(lesson: LessonPlan, plan: BrowserVisualPlan, skill: Recipe) -> None:
    if plan.topic != lesson.topic or plan.skill_id != skill.id:
        raise VisualPlanValidationError("visual plan topic or skill does not match the locked lesson")
    lesson_scenes = {scene.id: scene for scene in lesson.scenes}
    visual_scenes = {scene.lesson_scene_id: scene for scene in plan.scenes}
    if set(visual_scenes) != set(lesson_scenes):
        raise VisualPlanValidationError("visual plan must contain exactly the locked lesson scenes")
    if [scene.lesson_scene_id for scene in plan.scenes] != [scene.id for scene in lesson.scenes]:
        raise VisualPlanValidationError("visual plan scenes must preserve the locked lesson order")
    previous_closing: set[str] = set()
    previous_objects: dict[str, VisualObject] = {}
    previous_pattern: str | None = None
    roles: set[str] = set()
    for lesson_scene in lesson.scenes:
        visual_scene = visual_scenes[lesson_scene.id]
        validate_scene(lesson_scene, visual_scene, skill,
                       previous_closing=previous_closing,
                       previous_objects=previous_objects,
                       previous_pattern=previous_pattern)
        roles.update(obj.role for obj in visual_scene.objects)
        previous_closing = set(visual_scene.closing_visible_ids)
        previous_objects = {obj.id: obj for obj in visual_scene.objects}
        previous_pattern = visual_scene.pattern
    missing_roles = sorted(set(skill.required_roles) - roles)
    if missing_roles:
        raise VisualPlanValidationError(f"skill requires missing visual role(s): {missing_roles}")
