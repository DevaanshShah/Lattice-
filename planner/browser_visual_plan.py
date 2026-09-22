from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from core.llm import LLMClient, get_client
from core.schemas.browser_visual_plan import BrowserScene, BrowserVisualPlan, VisualObject
from core.schemas.lesson_plan import LessonPlan
from core.visual_state import VisualState, closing_state
from core.visual_assets import asset_inventory
from core.textutil import extract_json
from planner.product_recipe import Recipe
from prompts.loader import load
from verification.visual_plan_validation import VisualPlanValidationError, validate, validate_scene


class BrowserVisualPlanError(RuntimeError):
    pass


def _normalise_v2_carryover(data: dict, previous: BrowserScene | None) -> dict:
    beats = data.get("beats", [])
    if beats:
        data.setdefault("opening_visible_ids", beats[0].get("opening_visible_ids", []))
        if "closing_visible_ids" not in data and "closing_visible_ids" in beats[-1]:
            data["closing_visible_ids"] = beats[-1]["closing_visible_ids"]
        for beat in beats:
            for key in ("opening_visible_ids", "closing_visible_ids", "carryover_ids"):
                beat.pop(key, None)
            if not beat.get("actions"):
                targets = list(dict.fromkeys(obj_id for evidence in beat.get("evidence", [])
                                             for obj_id in evidence.get("object_ids", [])))
                if targets:
                    beat["actions"] = [{"id": f"hold_{beat['narration_beat_id']}",
                                        "kind": "hold", "target_ids": targets}]
    if previous is None:
        return _normalise_v2_visibility(data)
    previous_objects = {obj.id: obj for obj in previous.objects
                        if obj.id in previous.closing_visible_ids}
    declared = {obj["id"]: obj for obj in data.get("objects", [])}
    referenced = set(data.get("opening_visible_ids", [])) | set(data.get("closing_visible_ids", []))
    referenced |= set(data.get("carryover_ids", []))
    referenced |= {target for beat in data.get("beats", []) for action in beat.get("actions", [])
                   for target in action.get("target_ids", [])}
    referenced |= {target for beat in data.get("beats", []) for evidence in beat.get("evidence", [])
                   for target in evidence.get("object_ids", [])}
    referenced |= {target for relation in data.get("relationships", [])
                   for target in (relation.get("source_id"), relation.get("target_id"))}
    carryover = set(declared) | referenced
    carryover &= set(previous_objects)
    for obj_id in carryover:
        declared[obj_id] = previous_objects[obj_id].model_dump()
    data["objects"] = list(declared.values())
    data["carryover_ids"] = [obj_id for obj_id in previous.closing_visible_ids
                             if obj_id in carryover]
    data["opening_visible_ids"] = list(dict.fromkeys(
        [*data.get("opening_visible_ids", []), *data["carryover_ids"]]))
    return _normalise_v2_visibility(data)


def _normalise_v2_visibility(data: dict) -> dict:
    """Reveal evidence objects the model intended to show but only animated invisibly."""
    visible = set(data.get("opening_visible_ids", []))
    declared = {obj["id"] for obj in data.get("objects", [])}
    used_ids = {action.get("id") for beat in data.get("beats", [])
                for action in beat.get("actions", [])}
    for beat in data.get("beats", []):
        actions = beat.get("actions", [])
        ending = set(visible)
        for action in actions:
            if action.get("kind") in {"appear", "connect", "expand", "branch", "activate", "transform"}:
                ending.update(action.get("target_ids", []))
            elif action.get("kind") in {"hide", "deactivate"}:
                ending.difference_update(action.get("target_ids", []))
        hidden = {obj_id for evidence in beat.get("evidence", [])
                  for obj_id in evidence.get("object_ids", []) if obj_id in declared
                  and obj_id not in ending}
        intentionally_hidden = {obj_id for action in actions
                                if action.get("kind") in {"hide", "deactivate"}
                                for obj_id in action.get("target_ids", [])}
        for obj_id in sorted(hidden - intentionally_hidden):
            base = f"reveal_{beat['narration_beat_id']}_{obj_id}"
            action_id = base
            suffix = 2
            while action_id in used_ids:
                action_id = f"{base}_{suffix}"
                suffix += 1
            used_ids.add(action_id)
            actions.insert(0, {"id": action_id, "kind": "appear", "target_ids": [obj_id]})
            ending.add(obj_id)
        visible = ending
    if data.get("beats") and "closing_visible_ids" in data:
        last_actions = data["beats"][-1].setdefault("actions", [])
        to_hide = visible - set(data["closing_visible_ids"])
        referenced = {obj_id for action in last_actions for obj_id in action.get("target_ids", [])}
        referenced.update(obj_id for evidence in data["beats"][-1].get("evidence", [])
                          for obj_id in evidence.get("object_ids", []))
        for when, targets in (("early", sorted(to_hide - referenced)),
                              ("late", sorted(to_hide & referenced))):
            if not targets:
                continue
            base = f"hide_final_{when}"
            action_id = base
            suffix = 2
            while action_id in used_ids:
                action_id = f"{base}_{suffix}"
                suffix += 1
            used_ids.add(action_id)
            action = {"id": action_id, "kind": "hide", "target_ids": targets}
            if when == "early":
                last_actions.insert(0, action)
            else:
                last_actions.append(action)
    return data


def generate(lesson: LessonPlan, skill: Recipe, *, client: LLMClient | None = None,
             attempts: int = 3, schema_version: int = 1,
             diagnostic_dir: str | Path | None = None,
             starting_scenes: list[BrowserScene] | None = None) -> BrowserVisualPlan:
    if schema_version != lesson.schema_version:
        raise ValueError("visual planner schema version must match lesson plan")
    client = client or get_client()
    scenes: list[BrowserScene] = list(starting_scenes or [])
    if len(scenes) > len(lesson.scenes):
        raise ValueError("more saved visual scenes than lesson scenes")
    roles_used: set[str] = set()
    previous_state: VisualState | None = None
    for index, scene in enumerate(scenes):
        previous = scenes[index - 1] if index else None
        validate_scene(lesson.scenes[index], scene, skill,
                       previous_closing=set(previous.closing_visible_ids) if previous else set(),
                       previous_objects={obj.id: obj for obj in previous.objects} if previous else {},
                       previous_pattern=previous.pattern if previous else None,
                       require_v2=schema_version == 2, previous_state=previous_state)
        roles_used.update(obj.role for obj in scene.objects)
        if schema_version == 2:
            previous_state = closing_state(scene, previous_state)
    for index in range(len(scenes), len(lesson.scenes)):
        lesson_scene = lesson.scenes[index]
        previous = scenes[-1] if scenes else None
        previous_objects = {obj.id: obj for obj in previous.objects} if previous else {}
        previous_closing = set(previous.closing_visible_ids) if previous else set()
        available = [previous_objects[obj_id].model_dump()
                     for obj_id in previous.closing_visible_ids] if previous else []
        missing_roles = sorted(set(skill.required_roles) - roles_used) if schema_version == 1 else []
        final_requirement = (
            f"This is the final scene; it must include all still-missing required roles: "
            f"{', '.join(missing_roles) or 'none'}."
            if index == len(lesson.scenes) - 1 else
            f"Required roles still missing across the video: {', '.join(missing_roles) or 'none'}."
        ) if schema_version == 1 else "Choose visual forms from the claim requirements."
        pattern_guidance = (f"Allowed patterns: {', '.join(skill.allowed_patterns)}\n"
                            f"Required visual roles: {', '.join(skill.required_roles)}\n"
                            if schema_version == 1 else
                            "Pattern is a layout hint; choose the natural visual form.\n")
        inventory = asset_inventory() if schema_version == 2 else None
        messages = [
            {"role": "system", "content": load(
                "browser-visual-plan-v2" if schema_version == 2 else "browser-visual-plan")},
            {"role": "user", "content": (
                f"Topic: {lesson.topic}\nSelected skill: {skill.id}\n"
                + (f"Visual guidance: {skill.scene_guidance}\n" if schema_version == 2 else "")
                +
                f"Scene {index + 1} of {len(lesson.scenes)}.\n"
                f"Locked lesson scene:\n{lesson_scene.model_dump_json(indent=2)}\n\n"
                f"{pattern_guidance}"
                + (f"Available local assets: {json.dumps(inventory)}\n"
                   if inventory is not None else "")
                +
                f"Roles already used: {', '.join(sorted(roles_used)) or 'none'}\n"
                f"Previous pattern: {previous.pattern if previous else 'none'}\n"
                f"Previous closing objects available for exact carryover:\n"
                f"{json.dumps(available, indent=2)}\n\n"
                + (f"Previous executed object state:\n"
                   f"{json.dumps(previous_state.payloads, indent=2)}\n\n"
                   if schema_version == 2 and previous_state else "")
                + ("A reused id continues from that executed state. For a new method or fresh "
                   "count, create a new pointer or counter id.\n\n"
                   if schema_version == 2 and previous_state else "")
                +
                f"{final_requirement}\nReturn this one visual scene JSON now."
            )},
        ]
        last: Exception | None = None
        for attempt in range(attempts):
            raw = client.chat(messages, max_tokens=4096, attempts=1, timeout=60.0)
            if diagnostic_dir is not None:
                folder = Path(diagnostic_dir)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"scene_{index:02d}_attempt_{attempt + 1:02d}.txt").write_text(
                    raw, encoding="utf-8")
            try:
                data = extract_json(raw)
                if schema_version == 2:
                    data = _normalise_v2_carryover(data, previous)
                scene = BrowserScene.model_validate(data)
                validate_scene(lesson_scene, scene, skill,
                               previous_closing=previous_closing,
                               previous_objects=previous_objects,
                               previous_pattern=previous.pattern if previous else None,
                               require_v2=schema_version == 2,
                               previous_state=previous_state)
                if schema_version == 1 and index == len(lesson.scenes) - 1:
                    missing = sorted(set(skill.required_roles) - roles_used -
                                     {obj.role for obj in scene.objects})
                    if missing:
                        raise VisualPlanValidationError(
                            f"final scene must include missing visual role(s): {missing}")
                scenes.append(scene)
                roles_used.update(obj.role for obj in scene.objects)
                if schema_version == 2:
                    previous_state = closing_state(scene, previous_state)
                if diagnostic_dir is not None:
                    folder = Path(diagnostic_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"scene_{index:02d}_accepted.json").write_text(
                        scene.model_dump_json(indent=2), encoding="utf-8")
                break
            except (ValueError, ValidationError) as exc:
                last = exc
                if schema_version == 2:
                    repair = (f"This visual scene is invalid: {exc}. Repair only this scene. "
                              "Make the locked visual anchors true in the executed object state; "
                              "do not add a generic label box to claim a process happened. "
                              "Keep prior object definitions and executed state, and use a new id "
                              "for a new pointer or counter. Every claim needs its specified "
                              "evidence from actual actions or values. Use only supported object "
                              "kinds for the selected render_mode. Objects affected by move, "
                              "compare, increment, set_state, or hold stay hidden unless they "
                              "were opening-visible or explicitly appeared first. Return only "
                              "corrected JSON.")
                else:
                    repair = (
                        f"That scene was invalid ({exc}). Repair only this scene. Every referenced "
                        "id must be declared locally; carryover ids must exactly match an object in "
                        "the supplied previous closing state and be visible at opening. If you reuse "
                        "a previous closing id, it must be a carryover and its kind, role, label, "
                        "and initial payload must stay identical; add new downstream objects instead "
                        "of changing it. Use kind 'gate' with role 'decision'. For contour, never "
                        "create axis or contour-line objects because the renderer draws them; use "
                        "at most one object from each role group: input/source/context, "
                        "operation/tool, metric/destination/result, output/audit. Every "
                        "visual_anchor named in the locked lesson beat must appear verbatim in a "
                        "visible object or relationship label by that beat. Return only the "
                        "corrected scene JSON."
                    )
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": repair}]
        else:
            raise BrowserVisualPlanError(
                f"browser visual scene {lesson_scene.id!r} invalid after {attempts} attempts: {last}")
    plan = BrowserVisualPlan(schema_version=schema_version, topic=lesson.topic,
                             skill_id=skill.id, scenes=scenes)
    validate(lesson, plan, skill)
    return plan
