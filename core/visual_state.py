"""Apply planned visual actions to semantic objects without renderer-specific code."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.schemas.browser_visual_plan import BrowserScene, VisualAction


FIELD_KINDS = {"message", "node", "document", "card", "gate", "tool", "group"}
# Payload keys the renderer draws for each semantic kind; FIELD_KINDS draw their scalar fields.
_DRAWN_KEYS = {"array": ("items", "discarded_indices", "checked_results", "lit_indices", "new_index", "groups", "veiled", "tints"),
               "pointer": ("target_id", "index"), "counter": ("value",), "metric": ("value",),
               "value": ("value",), "formula": ("expression",), "code": ("source", "active_lines"),
               "chart": ("series",), "image": ("asset_id",), "icon": ("asset_id", "count"),
               "tree": ("shown", "marked")}


# Payload keys that say HOW a piece is drawn, not what it holds. They are never shown as rows.
STYLE_KEYS = {"tone", "icon", "placeholder", "members", "header", "count", "tick", "max", "ask", "unnumbered",
              "idea"}
# One colour per idea, on black. `red` is reserved for a problem.
TONES = ("pink", "purple", "teal", "yellow", "blue", "green", "white", "red")


def displayed_fields(kind: str, payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Scalar payload fields drawn as `key: value` rows on message-like objects."""
    if kind not in FIELD_KINDS:
        return []
    return [(str(key), "✓" if value is True else "✗" if value is False else str(value))
            for key, value in payload.items() if key not in STYLE_KEYS
            if isinstance(value, (str, int, float, bool)) and str(value) != ""]


def drawn_view(kind: str, payload: dict[str, Any]) -> str:
    """The part of an object's state a viewer can see; equal views look identical."""
    # the colour and the dashed "not built yet" outline are part of what a viewer sees
    look = [payload.get("tone"), bool(payload.get("placeholder"))]
    if kind in FIELD_KINDS:
        return repr([displayed_fields(kind, payload), look])
    return repr([[payload.get(key) for key in _DRAWN_KEYS.get(kind, ())], look])


@dataclass
class ActionEffect:
    revealed: set[str]
    changed: set[str]
    removed: set[str]

    def describe(self) -> str:
        parts = [f"{verb} {sorted(ids)}" for verb, ids in (
            ("revealed", self.revealed), ("changed", self.changed), ("removed", self.removed)) if ids]
        return ", ".join(parts) or "no visible change"


def action_effect(kinds: dict[str, str], before: "VisualState",
                  after: "VisualState") -> ActionEffect:
    """What one action visibly did: new objects, redrawn objects, or removed objects."""
    return ActionEffect(
        revealed=after.visible - before.visible,
        changed={obj_id for obj_id in before.visible & after.visible
                 if drawn_view(kinds[obj_id], before.payloads[obj_id])
                 != drawn_view(kinds[obj_id], after.payloads[obj_id])},
        removed=before.visible - after.visible)


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
    if action.kind in {"highlight", "focus", "activate", "move", "set_state", "increment", "trace"}:
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
