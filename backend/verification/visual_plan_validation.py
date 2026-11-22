from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re

from core.schemas.browser_visual_plan import BrowserScene, BrowserVisualPlan, VisualObject
from core.schemas.lesson_plan import LessonPlan, LessonScene
from core.call_tree import repeats
from core.visual_state import (TONES, ActionEffect, VisualState, action_effect, apply_action,
                               closing_state, displayed_fields, opening_state)
from core.visual_assets import resolve_asset
from planner.product_recipe import Recipe


class VisualPlanValidationError(ValueError):
    pass


def _visible_labels_by_beat(scene: BrowserScene, *, require_v2: bool = False,
                            previous_state: VisualState | None = None) -> dict[str, list[str]]:
    objects = {obj.id: obj for obj in scene.objects}
    if require_v2:
        state = opening_state(scene, previous_state)
        result = {}
        for beat in scene.beats:
            # An anchor counts if it is on screen at any moment while its beat is spoken.
            state = deepcopy(state)
            state.focused.clear()
            moments = []
            for action in beat.actions:
                apply_action(state, action)
                moments.append(deepcopy(state))
            labels = []
            for view in moments:
                for obj_id in view.visible:
                    obj = objects[obj_id]
                    payload = view.payloads[obj_id]
                    if obj.kind not in {"formula", "code"}:
                        labels.append(obj.label)
                    labels.extend(f"{key}: {value}" for key, value in displayed_fields(obj.kind, payload))
                    if obj.kind == "array":
                        items = payload["items"]
                        labels.append(f"{obj.label}: {', '.join(str(item) for item in items)}")
                        discarded = set(payload.get("discarded_indices", []))
                        remaining = [item for index, item in enumerate(items)
                                     if index not in discarded]
                        labels.append(f"{obj.label}: {', '.join(str(item) for item in remaining)}")
                        if discarded:
                            labels.append("discard [" + ",".join(
                                str(items[index]) for index in sorted(discarded)) + "]")
                            labels.append(f"new subarray: {', '.join(str(item) for item in remaining)}")
                            if discarded == set(range(len(discarded))):
                                labels.append("discard left")
                            if discarded == set(range(len(items) - len(discarded), len(items))):
                                labels.append("discard right")
                        for index, outcome in payload.get("checked_results", {}).items():
                            labels.append(f"{items[int(index)]} {'✓' if outcome == 'match' else '✗'}")
                        labels.extend(f"{group['label']}: {len(group['cells'])}"
                                      for group in payload.get("groups") or [])
                    elif obj.kind == "pointer":
                        target = view.payloads[payload["target_id"]]
                        labels.append(f"{obj.label}: {target['items'][payload['index']]}")
                        labels.append(f"Index: {payload['index']}")
                        if target.get("checked_results", {}).get(str(payload["index"])) == "match":
                            labels.append(f"{obj.label}: {target['items'][payload['index']]} ✓")
                            if any(action.kind == "move" and obj.id in action.target_ids
                                   for action in beat.actions):
                                labels.append(f"New {obj.label}: {target['items'][payload['index']]} ✓")
                    elif obj.kind in {"counter", "metric", "value"} and "value" in payload:
                        labels.extend((f"{obj.label}: {payload['value']}",
                                       f"{payload['value']} {obj.label}"))
                    elif obj.kind == "formula":
                        labels.append(str(payload["expression"]))
                    elif obj.kind == "code":
                        labels.append(str(payload["source"]))
                        rows = str(payload["source"]).split("\n")
                        labels.extend(rows[line - 1].strip() for line in payload.get("active_lines") or []
                                      if isinstance(line, int) and 0 < line <= len(rows))
                    elif obj.kind == "chart":
                        labels.extend(f"{item['label']}: {item['value']}"
                                      for item in payload["series"])
                    elif obj.kind == "tree":
                        labels.extend(repeats(payload))
                    elif obj.kind == "graph":
                        from core.graph_search import frontier_line
                        labels.append(frontier_line(payload))
                        if payload.get("current"):
                            labels.append(str(payload["current"]))
                        if payload.get("path"):
                            labels.append(" -> ".join(payload["path"]))
                labels.extend(relation.label for relation in scene.relationships
                              if relation.label and relation.source_id in view.visible
                              and relation.target_id in view.visible)
            result[beat.narration_beat_id] = labels
        return result
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
    return re.sub(r"[_\s]+", " ", value).strip().casefold()


def _anchor_visible(anchor: str, labels: list[str]) -> bool:
    parts = [part.strip() for part in anchor.split("→")]
    def match(part: str, label: str) -> bool:
        target = _normalise_label(part)
        if target in label:
            return True
        # A fact matches when the value is drawn under a field name contained in the anchor's
        # name, or vice versa: "corrected order id: 42" is shown by "order id: 42".
        wanted, drawn = (re.fullmatch(r"([^:]+):\s*(.+)", text) for text in (target, label))
        if wanted and drawn and wanted.group(2).strip() == drawn.group(2).strip():
            wanted_words, drawn_words = (set(re.findall(r"\w+", pair.group(1)))
                                         for pair in (wanted, drawn))
            if drawn_words and (drawn_words <= wanted_words or wanted_words <= drawn_words):
                return True
        number = re.fullmatch(r"([^:]+):\s*(-?\d+(?:\.\d+)?)", target)
        if not number:
            return False
        name, value = number.groups()
        return bool(re.match(rf"^{re.escape(name)}(?:\b|\W)", label)
                    and re.search(rf":\s*{re.escape(value)}$", label))
    return all(any(match(part, label) for label in labels) for part in parts)


def validate_scene(lesson_scene: LessonScene, visual_scene: BrowserScene, skill: Recipe, *,
                   previous_closing: set[str],
                   previous_objects: Mapping[str, VisualObject] | None = None,
                   previous_pattern: str | None = None,
                   require_v2: bool = False,
                   previous_state: VisualState | None = None) -> None:
    if visual_scene.lesson_scene_id != lesson_scene.id:
        raise VisualPlanValidationError(
            f"visual scene must map to locked lesson scene {lesson_scene.id!r}")
    if not require_v2 and visual_scene.pattern not in skill.allowed_patterns:
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} uses disallowed pattern {visual_scene.pattern!r}")
    if not require_v2 and previous_pattern == visual_scene.pattern and not visual_scene.carryover_ids:
        raise VisualPlanValidationError(
            "adjacent scenes may repeat a visual pattern only with explicit carryover")
    if not require_v2 and visual_scene.pattern == "contour":
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
    if require_v2 and [beat.narration_beat_id for beat in visual_scene.beats] != list(expected_beats):
        raise VisualPlanValidationError("visual beats must follow the narration order")
    # Checked before the replay: replaying a scene that carries an object its predecessor never
    # left on screen (a cut or reordered outline) would fail on a missing state, not on this reason.
    missing_prior = sorted(set(visual_scene.carryover_ids) - previous_closing)
    if missing_prior:
        raise VisualPlanValidationError(
            f"scene {lesson_scene.id} carries object(s) absent from prior closing state: {missing_prior}")
    visible_labels = _visible_labels_by_beat(visual_scene, require_v2=require_v2,
                                            previous_state=previous_state)
    state_by_beat: dict[str, VisualState] = {}
    seen_by_beat: dict[str, set[str]] = {}
    effects_by_beat: dict[str, dict[str, ActionEffect]] = {}
    if require_v2:
        # Replay every action and record what it visibly did. Proof is judged from these screen
        # effects on the objects a claim names, whichever actions the plan happens to cite.
        kinds = {obj.id: obj.kind for obj in visual_scene.objects}
        state = opening_state(visual_scene, previous_state)
        for beat in visual_scene.beats:
            state = deepcopy(state)
            state.focused.clear()
            effects = effects_by_beat.setdefault(beat.narration_beat_id, {})
            seen = seen_by_beat.setdefault(beat.narration_beat_id, set())
            for action in beat.actions:
                before = deepcopy(state)
                apply_action(state, action)
                effects[action.id] = action_effect(kinds, before, state)
                seen |= state.visible
            state_by_beat[beat.narration_beat_id] = state
    prior_actions = {}
    prior_effects: dict[str, ActionEffect] = {}
    for beat_id, lesson_beat in expected_beats.items():
        covered = {claim for evidence in actual_beats[beat_id].evidence for claim in evidence.claim_ids}
        missing = sorted(set(lesson_beat.claim_ids) - covered)
        unknown = sorted(covered - set(lesson_beat.claim_ids))
        if missing or unknown:
            raise VisualPlanValidationError(
                f"beat {beat_id} has invalid visual claim coverage; missing={missing}, unknown={unknown}")
        labels = [_normalise_label(label) for label in visible_labels[beat_id]]
        missing_anchors = [anchor for anchor in lesson_beat.visual_anchors
                           if not _anchor_visible(anchor, labels)]
        if missing_anchors:
            raise VisualPlanValidationError(
                f"beat {beat_id} is missing visible narration anchor(s): {missing_anchors}")
        if require_v2:
            hidden_evidence = sorted({obj_id for evidence in actual_beats[beat_id].evidence
                                      for obj_id in evidence.object_ids
                                      if obj_id not in seen_by_beat[beat_id]})
            if hidden_evidence:
                raise VisualPlanValidationError(
                    f"beat {beat_id} cites hidden evidence objects {hidden_evidence}; "
                    "use appear before the visual demonstration")
            _validate_v2_beat(lesson_beat, actual_beats[beat_id], visual_scene, prior_actions,
                              prior_effects, effects_by_beat[beat_id], state_by_beat[beat_id],
                              seen_by_beat[beat_id])
            prior_actions.update({action.id: action for action in actual_beats[beat_id].actions})
            prior_effects.update(effects_by_beat[beat_id])
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
    if require_v2:
        new_incremented_counters = {
            target for beat in visual_scene.beats for action in beat.actions
            if action.kind == "increment" for target in action.target_ids
        } - set(visual_scene.carryover_ids)
        for obj in visual_scene.objects:
            if (obj.id in new_incremented_counters and obj.kind == "counter"
                    and obj.payload.get("value") != 0):
                raise VisualPlanValidationError(
                    f"new incremented counter {obj.id!r} must start at 0; "
                    f"it starts at {obj.payload.get('value')!r} before any increments")
        for obj in visual_scene.objects:
            tone, members = obj.payload.get("tone"), obj.payload.get("members")
            if tone is not None and tone not in TONES:
                raise VisualPlanValidationError(
                    f"object {obj.id!r} has unknown tone {tone!r}; use one of {list(TONES)}")
            if members is not None and (obj.kind != "group" or not isinstance(members, list)):
                raise VisualPlanValidationError(
                    f"object {obj.id!r}: only a group can hold members, as a list of object ids")
            if obj.kind != "icon" and obj.payload.get("icon") is not None:
                try:
                    resolve_asset("icon", str(obj.payload["icon"]))
                except ValueError as exc:
                    raise VisualPlanValidationError(str(exc)) from exc
        for obj in visual_scene.objects:
            if obj.kind in {"image", "icon"}:
                try:
                    resolve_asset(obj.kind, str(obj.payload["asset_id"]))
                except ValueError as exc:
                    raise VisualPlanValidationError(str(exc)) from exc
        if visual_scene.render_mode == "manim":
            supported = {"array", "pointer", "counter", "value", "formula", "gate"}
            unsupported = sorted({obj.kind for obj in visual_scene.objects} - supported)
            if unsupported:
                raise VisualPlanValidationError(
                    f"Manim algorithm scene has unsupported object kind(s): {unsupported}")
            arrays = [obj for obj in visual_scene.objects if obj.kind == "array"]
            if len(arrays) != 1 or len(arrays[0].payload["items"]) > 12:
                raise VisualPlanValidationError("Manim algorithm scene needs one array of at most 12 cells")
            unsupported_actions = sorted({action.kind for beat in visual_scene.beats
                                          for action in beat.actions} - {
                                              "appear", "hide", "move", "set_state",
                                              "increment", "highlight", "focus", "hold", "compare"})
            if unsupported_actions:
                raise VisualPlanValidationError(
                    f"Manim algorithm scene has unsupported action(s): {unsupported_actions}")
        if previous_state is not None and set(visual_scene.carryover_ids) - set(previous_state.visible):
            raise VisualPlanValidationError("carried object is not visible in prior closing state")
        state = closing_state(visual_scene, previous_state)
        if state.visible != set(visual_scene.closing_visible_ids):
            raise VisualPlanValidationError(
                f"scene {lesson_scene.id} closing_visible_ids disagree with executed actions")


def _validate_v2_beat(lesson_beat, visual_beat, scene: BrowserScene, prior_actions: dict,
                      prior_effects: dict[str, ActionEffect],
                      current_effects: dict[str, ActionEffect], beat_state: VisualState,
                      seen: set[str]) -> None:
    objects = {obj.id: obj for obj in scene.objects}
    current_actions = {action.id: action for action in visual_beat.actions}
    if None in current_actions or len(current_actions) != len(visual_beat.actions):
        raise VisualPlanValidationError(f"beat {lesson_beat.id} needs unique action ids")
    actions = {**prior_actions, **current_actions}
    for action in visual_beat.actions:
        if action.kind == "move":
            if any(objects[target].kind != "pointer" for target in action.target_ids):
                raise VisualPlanValidationError("move action requires a pointer")
            if not isinstance(action.params.get("index"), int) or action.params["index"] < 0:
                raise VisualPlanValidationError("move action requires nonnegative index")
            for target in action.target_ids:
                array = objects[objects[target].payload["target_id"]]
                if action.params["index"] >= len(array.payload["items"]):
                    raise VisualPlanValidationError("pointer move exceeds array bounds")
        if action.kind == "increment":
            if any(objects[target].kind != "counter" for target in action.target_ids):
                raise VisualPlanValidationError("increment action requires a counter")
            if not isinstance(action.params.get("by", 1), (int, float)):
                raise VisualPlanValidationError("increment action requires numeric by")
        if action.kind == "compare":
            if (len(action.target_ids) != 2 or objects[action.target_ids[0]].kind != "pointer"
                    or objects[action.target_ids[1]].kind != "value"):
                raise VisualPlanValidationError("compare action requires a pointer and fixed value")
        if action.kind == "trace":
            # the ball follows arrows that exist, through pieces that are on screen
            arrows = {frozenset((relation.source_id, relation.target_id))
                      for relation in scene.relationships}
            hops = list(zip(action.target_ids, action.target_ids[1:]))
            # either direction: a reply travels back along the arrow its request came by
            missing = [f"{a}->{b}" for a, b in hops if frozenset((a, b)) not in arrows]
            if not hops or missing:
                raise VisualPlanValidationError(
                    f"trace action {action.id!r} needs a path of two or more pieces joined by "
                    f"relationships; no arrow for {missing or action.target_ids}")
            unseen = sorted(set(action.target_ids) - seen)
            if unseen:
                raise VisualPlanValidationError(
                    f"trace action {action.id!r} passes through pieces not on screen: {unseen}")
            count, tone = action.params.get("count", 1), action.params.get("tone")
            if type(count) is not int or not 1 <= count <= 5 or (tone is not None and tone not in TONES):
                raise VisualPlanValidationError(
                    f"trace action {action.id!r}: count is 1 to 5 and tone one of {list(TONES)}")
        if action.kind == "set_state" and "tone" in action.params:
            # Colour carries meaning on a map: red is trouble, a piece's own colour is healthy.
            # Any other change of colour would be a change the viewer cannot read.
            for target in action.target_ids:
                own = objects[target].payload.get("tone")
                if action.params["tone"] not in {"red", own}:
                    raise VisualPlanValidationError(
                        f"action {action.id!r} recolours {target!r} to {action.params['tone']!r}; a "
                        f"piece may only turn 'red' (in trouble) or back to its own tone {own!r}")
        if action.kind == "set_state" and not action.params:
            raise VisualPlanValidationError("set_state action requires changed state")
        if action.kind == "set_state":
            for target in action.target_ids:
                if scene.render_mode == "manim":
                    allowed = {"array": {"discarded_indices"},
                               "pointer": set(), "counter": {"value"},
                               "value": set(), "formula": set(), "gate": set()}
                    if set(action.params) - allowed[objects[target].kind]:
                        raise VisualPlanValidationError(
                            f"unsupported Manim state update for {objects[target].kind}")
                if objects[target].kind == "counter" and "value" in action.params and not isinstance(
                        action.params["value"], (int, float)):
                    raise VisualPlanValidationError("counter state value must be numeric")
                if objects[target].kind == "array" and "discarded_indices" in action.params:
                    indices = action.params["discarded_indices"]
                    if (not isinstance(indices, list) or any(
                            not isinstance(index, int) or index < 0
                            or index >= len(objects[target].payload["items"])
                            for index in indices)):
                        raise VisualPlanValidationError("discarded array indices are out of bounds")
    # Arrows this beat actually shows: one it travels or connects, or one that draws itself
    # because the beat brings an end of it on screen. An arrow that merely exists proves nothing.
    shown_arrows: set[frozenset] = set()
    for action in visual_beat.actions:
        if action.kind in {"connect", "branch", "trace"}:
            shown_arrows.update(frozenset(pair) for pair in zip(action.target_ids, action.target_ids[1:]))
            if action.kind != "trace":
                shown_arrows.add(frozenset(action.target_ids))
    revealed = set().union(*(effect.revealed for effect in current_effects.values()))         if current_effects else set()
    shown_arrows.update(frozenset((relation.source_id, relation.target_id))
                        for relation in scene.relationships
                        if {relation.source_id, relation.target_id} & revealed)
    evidence_by_claim = {claim: [] for claim in lesson_beat.claim_ids}
    for evidence in visual_beat.evidence:
        allowed_actions = actions if evidence.kind == "sequence" else current_actions
        if set(evidence.action_ids) - set(allowed_actions):
            raise VisualPlanValidationError(
                f"beat {lesson_beat.id} evidence cites an unavailable action")
        for claim in evidence.claim_ids:
            evidence_by_claim[claim].append(evidence)
    for claim, requirements in lesson_beat.claim_requirements.items():
        for requirement in requirements:
            earlier = requirement == "sequence"     # only a sequence may lean on earlier beats
            if any(_proves(requirement, evidence,
                           _steps(_claimed([evidence], objects), evidence.action_ids,
                                  prior_effects, current_effects, earlier=earlier),
                           objects, scene, beat_state, seen, shown_arrows)
                   for evidence in evidence_by_claim[claim]):
                continue
            claimed = _claimed(evidence_by_claim[claim], objects)
            cited = [action_id for evidence in evidence_by_claim[claim]
                     for action_id in evidence.action_ids]
            shown = "; ".join(f"{action_id}: {effect.describe()}" for action_id, effect in _steps(
                claimed, cited, prior_effects, current_effects, earlier=earlier)) or "no actions"
            raise VisualPlanValidationError(
                f"beat {lesson_beat.id} claim {claim!r} lacks {requirement} visual proof. "
                f"What the actions did to {sorted(claimed)}: {shown}. "
                f"{_PROOF_NEEDS.get(requirement, '')}".rstrip())


_PROOF_NEEDS = {
    "state_change": "Needed: an object the claim names, already on screen, visibly changes or is removed.",
    "sequence": ("Needed: two or more visible steps in order on the objects the claim names, at "
                 "least one changing an object already on screen; appearing, highlighting, or "
                 "re-setting a value already shown is not a step that changes it."),
    "value": "Needed: a visible object that draws the value.",
    "relationship": ("Needed: the beat shows the arrow between two objects the claim names, by "
                     "connecting or tracing them or by bringing one of them on screen."),
}
# Hides the planner adds to tidy the screen. They are not the model's demonstration, so an object
# they remove must not count as "it changed".
_CLEANUP_PREFIXES = ("clear_finished_steps", "hide_final_")


def _claimed(evidence_items, objects) -> set[str]:
    """Objects a claim is about: the ones its evidence names, plus the array under a named pointer
    (a compare marks the array cell, not the pointer)."""
    ids = {obj_id for evidence in evidence_items for obj_id in evidence.object_ids}
    return ids | {objects[obj_id].payload["target_id"] for obj_id in ids
                  if objects[obj_id].kind == "pointer"}


def _steps(claimed: set[str], cited: list[str], prior_effects: dict[str, ActionEffect],
           current_effects: dict[str, ActionEffect], *, earlier: bool) -> list[tuple[str, ActionEffect]]:
    """What each action did to the claimed objects, in order: every action of this beat, cited or
    not, preceded by the earlier-beat actions the evidence cites when `earlier` allows them."""
    before = [action_id for action_id in dict.fromkeys(cited)
              if earlier and action_id in prior_effects and action_id not in current_effects]
    steps = []
    for action_id in [*before, *current_effects]:
        if action_id.startswith(_CLEANUP_PREFIXES):
            continue
        effect = (current_effects if action_id in current_effects else prior_effects)[action_id]
        steps.append((action_id, ActionEffect(effect.revealed & claimed, effect.changed & claimed,
                                              effect.removed & claimed)))
    return steps


def _proves(requirement, evidence, steps: list[tuple[str, ActionEffect]], objects,
            scene: BrowserScene, beat_state: VisualState, seen: set[str],
            shown_arrows: set[frozenset]) -> bool:
    if evidence.kind != requirement:
        return False
    if requirement == "label":
        return True
    if requirement == "value":
        return any(obj_id in seen and (
            objects[obj_id].kind in {"array", "pointer", "counter", "metric", "value", "formula", "chart"}
            or displayed_fields(objects[obj_id].kind, beat_state.payloads[obj_id]))
            for obj_id in evidence.object_ids)
    if requirement == "relationship":
        return any({relation.source_id, relation.target_id} <= set(evidence.object_ids)
                   and frozenset((relation.source_id, relation.target_id)) in shown_arrows
                   for relation in scene.relationships)
    if requirement == "state_change":
        return any(step.changed or step.removed for _, step in steps)
    if requirement == "sequence":
        visible_steps = [step for _, step in steps if step.revealed or step.changed or step.removed]
        return len(visible_steps) >= 2 and any(step.changed for step in visible_steps)
    if requirement == "comparison":
        ids = set(evidence.object_ids)
        if any(objects[obj_id].kind == "chart" and
               len(objects[obj_id].payload.get("series", [])) >= 2 for obj_id in ids):
            return True
        return len(ids) >= 2 and (
            any(relation.kind == "compares_to" and relation.source_id in ids
                and relation.target_id in ids for relation in scene.relationships)
            or any(objects[obj_id].kind == "formula" for obj_id in ids))
    if requirement == "asset":
        return any(objects[obj_id].kind in {"image", "icon"} for obj_id in evidence.object_ids)
    return False


def validate(lesson: LessonPlan, plan: BrowserVisualPlan, skill: Recipe) -> None:
    if plan.topic != lesson.topic or plan.skill_id != skill.id:
        raise VisualPlanValidationError("visual plan topic or skill does not match the locked lesson")
    if plan.schema_version != lesson.schema_version:
        raise VisualPlanValidationError("lesson and visual plan schema versions differ")
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
    previous_state: VisualState | None = None
    for lesson_scene in lesson.scenes:
        visual_scene = visual_scenes[lesson_scene.id]
        validate_scene(lesson_scene, visual_scene, skill,
                       previous_closing=previous_closing,
                       previous_objects=previous_objects,
                       previous_pattern=previous_pattern,
                       require_v2=plan.schema_version == 2,
                       previous_state=previous_state)
        roles.update(obj.role for obj in visual_scene.objects)
        previous_closing = set(visual_scene.closing_visible_ids)
        previous_objects = {obj.id: obj for obj in visual_scene.objects}
        previous_pattern = visual_scene.pattern
        if plan.schema_version == 2:
            previous_state = closing_state(visual_scene, previous_state)
    missing_roles = sorted(set(skill.required_roles) - roles) if plan.schema_version == 1 else []
    if missing_roles:
        raise VisualPlanValidationError(f"skill requires missing visual role(s): {missing_roles}")
