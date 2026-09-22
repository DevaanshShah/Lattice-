"""Apply planned visual actions to semantic objects without renderer-specific code."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.schemas.browser_visual_plan import BrowserScene, VisualAction


@dataclass
class VisualState:
    visible: set[str]
    payloads: dict[str, dict[str, Any]]
    focused: set[str]


def opening_state(scene: BrowserScene, previous: VisualState | None = None) -> VisualState:
    payloads = {obj.id: deepcopy(obj.payload) for obj in scene.objects}
    if previous:
        for obj_id in scene.carryover_ids:
            payloads[obj_id] = deepcopy(previous.payloads[obj_id])
    return VisualState(set(scene.opening_visible_ids), payloads, set())


def apply_action(state: VisualState, action: VisualAction) -> None:
    targets = action.target_ids
    if action.kind in {"appear", "connect", "expand", "branch", "activate", "transform"}:
        state.visible.update(targets)
    elif action.kind in {"deactivate", "hide"}:
        state.visible.difference_update(targets)
    if action.kind in {"highlight", "focus", "activate", "move", "set_state", "increment"}:
        state.focused = set(targets)
    if action.kind in {"move", "set_state", "transform"}:
        for target in targets:
            state.payloads[target].update(deepcopy(action.params))
    elif action.kind == "increment":
        amount = action.params.get("by", 1)
        for target in targets:
            if state.payloads[target].get("value") is None:
                raise ValueError(f"counter {target!r} must receive a value before increment")
            state.payloads[target]["value"] += amount
    elif action.kind == "compare":
        pointer_id, target_id = targets
        pointer = state.payloads[pointer_id]
        array = state.payloads[pointer["target_id"]]
        index = pointer["index"]
        result = "match" if array["items"][index] == state.payloads[target_id]["value"] else "miss"
        array.setdefault("checked_results", {})[str(index)] = result


def after_beat(state: VisualState, scene: BrowserScene, beat_id: str) -> VisualState:
    result = deepcopy(state)
    beat = next(beat for beat in scene.beats if beat.narration_beat_id == beat_id)
    result.focused.clear()
    for action in beat.actions:
        apply_action(result, action)
    return result


def closing_state(scene: BrowserScene, previous: VisualState | None = None) -> VisualState:
    state = opening_state(scene, previous)
    for beat in scene.beats:
        state = after_beat(state, scene, beat.narration_beat_id)
    return state
