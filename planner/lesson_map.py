"""A lesson's map, turned into what the renderer draws, with no model call.

The lesson step names the pieces and arrows of a system once, and for every beat picks one move
from a short menu (introduce, send, trouble, fix, measure, point, remove). Everything else is
plain code here: the objects and layout of every scene, the actions of each beat, their timing,
the claim each beat makes and the proof for it. So a system lesson costs one model call, and the
script and the picture cannot disagree, because the picture is derived from the script.
"""
from __future__ import annotations

from core.schemas.browser_visual_plan import BrowserScene
from core.schemas.lesson_plan import BeatMove, LessonMap, LessonPlan, LessonScene
from core.visual_state import VisualState, closing_state

# The proof each move owes the viewer. A move is compiled into actions that give exactly that
# proof, and the validator still replays the result as a check on this module.
PROOF = {"introduce": "label", "point": "label", "send": "relationship", "measure": "value",
         "trouble": "state_change", "fix": "state_change", "remove": "state_change"}
_ROLES = {"piece": "operation", "panel": "destination", "meter": "metric"}


def _number(value: float):
    """95.0 is drawn and matched as 95."""
    return int(value) if float(value).is_integer() else value


def takeaway_id(scene: LessonScene) -> str:
    return f"takeaway_{scene.id}"


def map_objects(lesson_map: LessonMap, scene: LessonScene) -> tuple[list[dict], list[dict]]:
    """The objects and relationships of one scene on the map: every piece, plus that scene's
    takeaway line. A piece is defined the same way in every scene, so it can be carried over."""
    objects = []
    for piece in lesson_map.pieces:
        if piece.kind == "panel":
            payload = {"tone": piece.tone,
                       "members": [other.id for other in lesson_map.pieces if other.panel == piece.id]}
            kind = "group"
        elif piece.kind == "meter":
            payload = {"value": _number(piece.value), "max": _number(piece.max), "tone": piece.tone}
            kind = "metric"
        else:
            payload = {"asset_id": piece.icon, "tone": piece.tone}
            if piece.count > 1:
                payload["count"] = piece.count
            if piece.planned:
                payload["placeholder"] = True
            kind = "icon"
        objects.append({"id": piece.id, "kind": kind, "role": _ROLES[piece.kind],
                        "label": piece.label, "payload": payload})
    if scene.takeaway:
        objects.append({"id": takeaway_id(scene), "kind": "caption", "role": "audit",
                        "label": scene.takeaway, "payload": {"tone": "teal", "tick": True}})
    relationships = [{"source_id": arrow.source, "target_id": arrow.target, "kind": "flows_to",
                      **({"label": arrow.label} if arrow.label else {})}
                     for arrow in lesson_map.arrows]
    return objects, relationships


def _involved(move: dict) -> list[str]:
    ids = [*(move.get("pieces") or []), *(move.get("path") or [])]
    if move.get("meter"):
        ids.append(move["meter"])
    return list(dict.fromkeys(item for item in ids if isinstance(item, str)))


def fill_map_lesson(data: dict) -> dict:
    """Complete a map lesson the model wrote as narration plus one move per beat.

    Ids, the claim of each beat, the proof it owes and the texts that must be readable are all
    decided by the move, so the model is not asked for them and cannot get them wrong. A lesson
    without a map is returned untouched."""
    lesson_map = data.get("map")
    if not isinstance(lesson_map, dict) or not isinstance(data.get("scenes"), list):
        return data
    routes = _one_arrow_per_pair(lesson_map)
    labels = {piece.get("id"): piece.get("label") for piece in lesson_map.get("pieces") or []
              if isinstance(piece, dict)}
    for scene_number, scene in enumerate(data["scenes"], 1):
        if not isinstance(scene, dict) or not isinstance(scene.get("beats"), list):
            continue
        scene.setdefault("id", f"s{scene_number}")
        for beat_number, beat in enumerate(scene["beats"], 1):
            move = beat.get("move") if isinstance(beat, dict) else None
            if not isinstance(move, dict) or move.get("do") not in PROOF:
                continue        # the schema reports a beat without a usable move
            if isinstance(move.get("path"), list):
                move["path"] = _along_the_arrows(move["path"], routes)
            beat["id"] = f"{scene['id']}_b{beat_number}"
            claim = f"{beat['id']}_c"
            beat["claim_ids"] = [claim]
            beat["claim_requirements"] = {claim: [PROOF[move["do"]]]}
            anchors = [labels[item] for item in _involved(move)
                       if isinstance(labels.get(item), str) and item != move.get("meter")][:3]
            if move.get("meter") in labels and isinstance(move.get("value"), (int, float)):
                anchors.append(f"{labels[move['meter']]}: {_number(move['value'])}")
            beat["visual_anchors"] = anchors
    return data


def _one_arrow_per_pair(lesson_map: dict) -> dict[str, list[str]]:
    """Keep the first arrow between two pieces and drop a second one. Models draw a request arrow
    and a reply arrow; the ball already travels back along an arrow, so the second is the same
    line drawn twice. Returns which pieces each piece is joined to."""
    kept, joined = [], {}
    for arrow in lesson_map.get("arrows") or []:
        ends = (arrow.get("source"), arrow.get("target")) if isinstance(arrow, dict) else None
        if ends and all(isinstance(end, str) for end in ends) and ends[1] in joined.get(ends[0], []):
            continue
        kept.append(arrow)
        if ends and all(isinstance(end, str) for end in ends):
            joined.setdefault(ends[0], []).append(ends[1])
            joined.setdefault(ends[1], []).append(ends[0])
    if isinstance(lesson_map.get("arrows"), list):
        lesson_map["arrows"] = kept
    return joined


def _along_the_arrows(path: list, joined: dict[str, list[str]]) -> list:
    """A path that jumps between two pieces with no arrow is routed through the pieces between
    them: "from the service back to the phone" passes the gateway. A jump with no route is left
    as written, for the schema to report."""
    if not path or not all(isinstance(item, str) for item in path):
        return path
    full = [path[0]]
    for target in path[1:]:
        start = full[-1]
        if target in joined.get(start, []) or start == target:
            full.append(target)
            continue
        came_from, queue = {start: None}, [start]
        while queue and target not in came_from:      # shortest route, breadth first
            here = queue.pop(0)
            for there in joined.get(here, []):
                if there not in came_from:
                    came_from[there] = here
                    queue.append(there)
        if target not in came_from:
            full.append(target)
            continue
        hops = [target]
        while came_from[hops[-1]] != start:
            hops.append(came_from[hops[-1]])
        full.extend(reversed(hops))
    return full


def lesson_map_problems(lesson: LessonPlan, icons: list[str]) -> list[str]:
    """Why a map lesson cannot be drawn as written, in words the lesson step can act on."""
    if lesson.map is None:
        return []
    problems = [f"map piece {piece.id!r} uses icon {piece.icon!r}, which is not in the icon list"
                for piece in lesson.map.pieces if piece.kind == "piece" and piece.icon not in icons]
    for scene in lesson.scenes[1:]:      # the first scene may simply present the pieces
        if all(PROOF[beat.move.do] == "label" for beat in scene.beats):
            problems.append(f"scene {scene.id} only names things; give at least one beat a send, "
                            "trouble, fix or measure move")
    return problems


def _actions(move: BeatMove, lesson_map: LessonMap, visible: set[str], payloads: dict) -> list[dict]:
    """The actions one move becomes, given what is on screen. `visible` and `payloads` are
    advanced as the actions are written, so the next move sees their result."""
    pieces = {piece.id: piece for piece in lesson_map.pieces}
    actions: list[dict] = []

    def show(ids: list[str]) -> None:
        # a piece inside a panel needs its panel on screen: bring the panel with it
        wanted = list(dict.fromkeys(
            [*ids, *(pieces[item].panel for item in ids if pieces[item].panel)]))
        new = [item for item in wanted if item not in visible]
        if new:
            actions.append({"kind": "appear", "target_ids": new, "params": {}})
            visible.update(new)

    def change(ids: list[str], params: dict) -> None:
        changed = [item for item in ids
                   if any(payloads[item].get(key) != value for key, value in params.items())]
        if changed:
            actions.append({"kind": "set_state", "target_ids": changed, "params": params})
            for item in changed:
                payloads[item].update(params)

    meter = [move.meter] if move.meter else []
    if move.do == "introduce":
        show(move.pieces)
    elif move.do == "point":
        show(move.pieces)
        actions.append({"kind": "highlight", "target_ids": move.pieces, "params": {}})
    elif move.do == "send":
        show(move.path)
        actions.append({"kind": "trace", "target_ids": move.path,
                        "params": {"count": move.count} if move.count > 1 else {}})
    elif move.do == "measure":
        show(meter)
        change(meter, {"value": _number(move.value)})
    elif move.do == "trouble":
        show([*move.path, *move.pieces, *meter])
        if len(move.path) > 1:      # the traffic that causes the trouble arrives first
            actions.append({"kind": "trace", "target_ids": move.path,
                            "params": {"count": move.count} if move.count > 1 else {}})
        if meter:
            change(meter, {"value": _number(move.value), "tone": "red"})
        change(move.pieces, {"tone": "red"})
    elif move.do == "fix":
        show([*move.pieces, *meter])
        change([item for item in move.pieces if payloads[item].get("placeholder")],
               {"placeholder": False})
        # the problem is solved: every piece that turned red is healthy again, named or not
        healed = [*move.pieces, *(item for item in visible if item in pieces and item not in move.pieces
                                  and pieces[item].kind == "piece"
                                  and payloads[item].get("tone") == "red")]
        for tone in dict.fromkeys(pieces[item].tone for item in healed):
            change([item for item in healed if pieces[item].tone == tone], {"tone": tone})
        if meter:
            change(meter, {"value": _number(move.value), "tone": pieces[move.meter].tone})
    elif move.do == "remove":
        gone = [item for item in move.pieces if item in visible]
        if gone:
            actions.append({"kind": "hide", "target_ids": gone, "params": {}})
            visible.difference_update(gone)
    if not actions:     # nothing left to change: still show what the sentence is about
        on_screen = [item for item in _involved(move.model_dump()) if item in visible]
        if on_screen:
            actions.append({"kind": "highlight", "target_ids": on_screen, "params": {}})
    return actions


def compile_map_scene(lesson: LessonPlan, scene: LessonScene,
                      previous_state: VisualState | None) -> dict:
    """One scene of a map lesson as a full visual scene, written entirely from its moves."""
    objects, relationships = map_objects(lesson.map, scene)
    opening = [obj["id"] for obj in objects
               if previous_state is not None and obj["id"] in previous_state.visible]
    visible = set(opening)
    payloads = {obj["id"]: dict(obj["payload"]) for obj in objects}
    if previous_state is not None:
        for obj_id in opening:
            payloads[obj_id] = dict(previous_state.payloads[obj_id])
    beats = []
    for position, beat in enumerate(scene.beats):
        actions = _actions(beat.move, lesson.map, visible, payloads)
        if scene.takeaway and position == len(scene.beats) - 1:
            actions.append({"kind": "appear", "target_ids": [takeaway_id(scene)], "params": {}})
            visible.add(takeaway_id(scene))
        if not actions:
            raise ValueError(f"beat {beat.id}: the {beat.move.do} move has nothing on screen to "
                             "act on; introduce the piece first")
        for number, action in enumerate(actions):
            # steps share the beat evenly; each plays briskly at the start of its share and holds
            action["id"] = f"{beat.id}_{number + 1}"
            action["start_fraction"] = round(.06 + .88 * number / len(actions), 4)
            action["end_fraction"] = round(.06 + .88 * (number + 1) / len(actions), 4)
        if (PROOF[beat.move.do] == "state_change"
                and not any(action["kind"] in {"set_state", "hide"} for action in actions)):
            # Trouble on a piece that is already red, or a fix with nothing left to mend, changes
            # nothing: the sentence is emphasis, and what it owes the viewer is the piece itself.
            beat.claim_requirements = {claim: ["label"] for claim in beat.claim_ids}
        shown = [item for item in _involved(beat.move.model_dump())]
        evidence = [{"claim_ids": [claim], "object_ids": shown, "kind": kind,
                     "action_ids": [action["id"] for action in actions]}
                    for claim, kinds in beat.claim_requirements.items() for kind in kinds]
        beats.append({"narration_beat_id": beat.id, "actions": actions, "evidence": evidence})
    return {"lesson_scene_id": scene.id, "pattern": "architecture", "render_mode": "browser",
            "objects": objects, "relationships": relationships,
            "layout_ids": [obj["id"] for obj in objects], "beats": beats,
            "opening_visible_ids": opening, "carryover_ids": opening,
            "closing_visible_ids": [obj["id"] for obj in objects if obj["id"] in visible]}


def plan_map_scenes(lesson: LessonPlan, skill) -> list[BrowserScene]:
    """Every scene of a map lesson, compiled and checked by the same validator as a model-written
    scene. A failure here is a fault in the lesson (for example trouble on a piece that is
    already red), and its message is what the lesson step is sent to repair."""
    from verification.visual_plan_validation import validate_scene

    scenes: list[BrowserScene] = []
    state: VisualState | None = None
    for lesson_scene in lesson.scenes:
        previous = scenes[-1] if scenes else None
        scene = BrowserScene.model_validate(compile_map_scene(lesson, lesson_scene, state))
        validate_scene(lesson_scene, scene, skill,
                       previous_closing=set(previous.closing_visible_ids) if previous else set(),
                       previous_objects={obj.id: obj for obj in previous.objects} if previous else {},
                       previous_pattern=previous.pattern if previous else None,
                       require_v2=True, previous_state=state)
        scenes.append(scene)
        state = closing_state(scene, state)
    fixed = any(beat.move.do == "fix" for lesson_scene in lesson.scenes for beat in lesson_scene.beats)
    still_red = sorted(obj_id for obj_id in state.visible
                       if state.payloads[obj_id].get("tone") == "red") if fixed and state else []
    if still_red:
        raise ValueError(f"the lesson has a fix but ends with {still_red} still red; give the fix "
                         "move the meter and the lower value it falls to, and put the fix after "
                         "the last trouble")
    return scenes
