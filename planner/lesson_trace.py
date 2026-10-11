"""An algorithm lesson's trace, turned into what the renderer draws, with no model call.

The lesson step writes the code and the data once (an array, pointers into it, a target, a
counter, or an empty table), and for every beat picks one move: show, run, look, compare,
discard, fill, count. Code here writes everything else. Two things follow from that. A compare
is decided by the values on screen, and a filled cell holds what its source cells add up to, so
the picture cannot show arithmetic the data does not support. And each beat's anchor is read off
the state the move produced, so the narration is checked against the same picture.
"""
from __future__ import annotations

from core.schemas.browser_visual_plan import BrowserScene
from core.schemas.lesson_plan import BeatMove, LessonPlan, LessonScene, LessonTrace
from core.visual_state import VisualState, closing_state
from planner.lesson_shared import (LINES, apply_brief, ask_the_question, carried, closes_on_a_takeaway,
                                   compiled_beat, line_id, line_objects, number, takeaway_id)

# The proof each move owes the viewer.
PROOF = {"show": "label", "run": "label", "look": "value", "compare": "state_change",
         "discard": "state_change", "fill": "state_change", "count": "state_change",
         "clear": "state_change", "ask": "label", "answer": "label"}
CODE = "code"           # the editor window
WORKING = "working"     # the line under a table that shows how a cell was worked out
_JOIN = {"sum": " + ", "min": ", ", "max": ", "}


def trace_objects(trace: LessonTrace, scene: LessonScene, working: bool) -> list[dict]:
    """The objects of one scene on the trace: the code, every data item, the working line if the
    lesson fills a table, and that scene's lines of text. A data item is defined the same way in
    every scene, so it can be carried over."""
    objects = []
    if trace.code is not None:
        objects.append({"id": CODE, "kind": "code", "role": "context", "label": trace.code.title,
                        "payload": {"source": trace.code.source}})
    for item in trace.data:
        if item.kind == "array":
            payload, role = {"items": list(item.items) or [None] * item.size}, "input"
        elif item.kind == "pointer":
            payload, role = {"target_id": item.on, "index": 0}, "operation"
        elif item.kind == "value":
            payload, role = {"value": item.value}, "context"
        else:
            payload, role = {"value": 0}, "metric"
        objects.append({"id": item.id, "kind": item.kind, "role": role, "label": item.label,
                        "payload": payload})
    if working:
        objects.append({"id": WORKING, "kind": "formula", "role": "operation", "label": "Working",
                        "payload": {"expression": "="}})
    return objects + line_objects(scene)


def fill_trace_lesson(data: dict) -> dict:
    """Complete a trace lesson the model wrote as narration plus one move per beat: ids, one
    claim per beat and the proof its move owes. The anchors are written by the compiler, from
    the state each move produces. A lesson without a trace is returned untouched."""
    if not isinstance(data.get("trace"), dict) or not isinstance(data.get("scenes"), list):
        return data
    brief = apply_brief(data)
    for scene_number, scene in enumerate(data["scenes"], 1):
        if not isinstance(scene, dict) or not isinstance(scene.get("beats"), list):
            continue
        scene.setdefault("id", f"s{scene_number}")
        for beat_number, beat in enumerate(scene["beats"], 1):
            if not isinstance(beat, dict):
                continue
            move = beat.get("move")
            known = isinstance(move, dict) and move.get("do") in PROOF
            beat["id"] = f"{scene['id']}_b{beat_number}"
            claim = f"{beat['id']}_c"
            beat["claim_ids"] = [claim]
            # numbered all the same when the move is wrong, so the schema can say what is wrong
            beat["claim_requirements"] = {claim: [PROOF[move["do"]] if known else "label"]}
            beat.setdefault("visual_anchors", [])
            if known:
                ask_the_question(move, brief)
    return data


def _worked_out(label: str, cell: int, move: BeatMove, values: list, result) -> str:
    """The line that shows where a filled cell's value came from: 'Ways[3] = 2 + 1 = 3'."""
    name = f"{label}[{cell}]"
    if not values:
        return f"{name} = {result}"
    joined = _JOIN[move.op].join(str(value) for value in values)
    body = joined if move.op == "sum" else f"{move.op}({joined})"
    if move.plus:
        body += f" + {number(move.plus)}" if move.plus > 0 else f" - {number(-move.plus)}"
    return f"{name} = {body} = {result}"


def compile_trace_scene(lesson: LessonPlan, scene: LessonScene,
                        previous_state: VisualState | None) -> dict:
    """One scene of a trace lesson as a full visual scene, written entirely from its moves."""
    trace = lesson.trace
    items = {item.id: item for item in trace.data}
    working = any(beat.move.do == "fill" for each in lesson.scenes for beat in each.beats)
    objects = trace_objects(trace, scene, working)
    opening, visible, payloads = carried(objects, previous_state)
    rows = trace.code.source.split("\n") if trace.code else []
    beats = []
    for position, beat in enumerate(scene.beats):
        move = beat.move
        actions: list[dict] = []
        anchors: list[str] = []
        shown: list[str] = []
        changed = False         # whether something already on screen is visibly different afterwards

        def show(ids: list[str]) -> None:
            new = [item for item in dict.fromkeys(ids) if item not in visible]
            if new:
                actions.append({"kind": "appear", "target_ids": new, "params": {}})
                visible.update(new)

        def change(obj_id: str, params: dict) -> bool:
            if all(payloads[obj_id].get(key) == value for key, value in params.items()):
                return False
            actions.append({"kind": "set_state", "target_ids": [obj_id], "params": params})
            payloads[obj_id].update(params)
            return True

        def place(pointer: str, index: int | None) -> str:
            """Put a pointer on a cell, bringing it and its array on screen. Returns the array."""
            array = items[pointer].on
            show([array])
            moved = index is not None and payloads[pointer]["index"] != index
            if moved:
                actions.append({"kind": "move", "target_ids": [pointer], "params": {"index": index}})
                payloads[pointer]["index"] = index
            show([pointer])     # a hidden pointer is placed first, so it appears where it belongs
            return array

        if move.lines:          # the lines being explained are lit before what they do is shown
            show([CODE])
            change(CODE, {"active_lines": list(move.lines)})
            anchors.append(rows[move.lines[0] - 1].strip())
            shown.append(CODE)

        if move.do in LINES:
            line = line_id(beat)
            actions.append({"kind": "appear", "target_ids": [line], "params": {}})
            visible.add(line)
            anchors, shown = [move.text], [line]
        elif move.do == "show":
            show(move.items)
            shown += move.items
            anchors += [items[name].label for name in move.items if name in items][:3]
        elif move.do == "look":
            array = place(move.pointer, move.index)
            cell = payloads[array]["items"][move.index]
            anchors.append(f"{items[move.pointer].label}: {cell}")
            shown += [move.pointer, array]
        elif move.do == "compare":
            # one cell, or several in turn: the pointer walks them and each gets its mark
            tallies = [item.id for item in trace.data if item.counts == move.pointer]
            for stop in move.cells or [move.index]:
                array = place(move.pointer, stop)
                show([move.against])
                index = payloads[move.pointer]["index"]
                cell, wanted = payloads[array]["items"][index], payloads[move.against]["value"]
                results = dict(payloads[array].get("checked_results") or {})
                outcome = "match" if cell == wanted else "miss"
                changed = changed or results.get(str(index)) != outcome
                actions.append({"kind": "compare", "target_ids": [move.pointer, move.against],
                                "params": {}})
                results[str(index)] = outcome
                payloads[array]["checked_results"] = results
                for tally in tallies:       # a counter tied to this pointer counts the check itself
                    show([tally])
                    actions.append({"kind": "increment", "target_ids": [tally], "params": {}})
                    payloads[tally]["value"] += 1
            anchors.append(f"{cell} {'✓' if outcome == 'match' else '✗'}")
            anchors += [f"{items[tally].label}: {payloads[tally]['value']}" for tally in tallies]
            shown += [move.pointer, move.against, array, *tallies]
        elif move.do == "clear":
            # wipe the marks of one attempt, so the next starts on clean data
            show([move.array])
            wipe = {key: empty for key, empty in (("checked_results", {}), ("discarded_indices", []),
                                                  ("lit_indices", []), ("new_index", None))
                    if payloads[move.array].get(key) not in (None, {}, [])}
            if wipe:
                changed = change(move.array, wipe)
            resting = [item.id for item in trace.data
                       if item.kind == "pointer" and item.on == move.array and item.id in visible]
            if resting:
                actions.append({"kind": "hide", "target_ids": resting, "params": {}})
                visible.difference_update(resting)
                changed = True
            anchors.append(items[move.array].label)
            shown += [move.array, *resting]
        elif move.do == "discard":
            show([move.array])
            gone = sorted({*(payloads[move.array].get("discarded_indices") or []), *move.cells})
            changed = change(move.array, {"discarded_indices": gone})
            cells = payloads[move.array]["items"]
            anchors.append("discard [" + ",".join(str(cells[index]) for index in gone) + "]")
            shown.append(move.array)
        elif move.do == "fill":
            # one cell, or a run of cells that each read the cells `back` steps before them
            show([move.array])
            jobs = ([(cell, [cell - step for step in move.back]) for cell in move.cells]
                    if move.cells else [(move.cell, list(move.from_cells))])
            for target, sources in jobs:
                cells = list(payloads[move.array]["items"])
                empty = [index for index in sources if cells[index] is None]
                if empty:
                    raise ValueError(f"beat {beat.id}: cell {target} of {move.array!r} is worked "
                                     f"out from cells {empty}, which are still empty; fill those first")
                values = [cells[index] for index in sources]
                if any(not isinstance(value, (int, float)) for value in values):
                    raise ValueError(f"beat {beat.id}: cells {sources} of {move.array!r} do not "
                                     "all hold numbers, so they cannot be combined")
                result = number(move.value if not values else
                                {"sum": sum, "min": min, "max": max}[move.op](values) + move.plus)
                cells[target] = result
                changed = change(move.array, {"items": cells, "lit_indices": sources,
                                              "new_index": target}) or changed
                worked = _worked_out(items[move.array].label, target, move, values, result)
                change(WORKING, {"expression": worked})
                show([WORKING])
            anchors.append(worked)
            shown += [move.array, WORKING]
        elif move.do == "count":
            show([move.counter])
            if items[move.counter].counts is None:
                actions.append({"kind": "increment", "target_ids": [move.counter], "params": {}})
                payloads[move.counter]["value"] += 1
                changed = True
            # A counter tied to a pointer has already counted every check. Bumping it here would
            # show one more than were made, so the move only points at the count.
            anchors.append(f"{items[move.counter].label}: {payloads[move.counter]['value']}")
            shown.append(move.counter)

        if closes_on_a_takeaway(scene) and position == len(scene.beats) - 1:
            actions.append({"kind": "appear", "target_ids": [takeaway_id(scene)], "params": {}})
            visible.add(takeaway_id(scene))
        if not actions:     # nothing changes: still light up what the sentence is about
            on_screen = [name for name in shown if name in visible]
            if not on_screen:
                raise ValueError(f"beat {beat.id}: the {move.do} move has nothing on screen to act on")
            actions.append({"kind": "highlight", "target_ids": on_screen, "params": {}})
        if PROOF[move.do] == "state_change" and not changed:
            # A compare already made, or cells already ruled out, changes nothing: the sentence is
            # emphasis, and what it owes the viewer is the thing itself.
            beat.claim_requirements = {claim: ["label"] for claim in beat.claim_ids}
        else:
            beat.claim_requirements = {claim: [PROOF[move.do]] for claim in beat.claim_ids}
        # the texts that must be readable while this is spoken, read off the state just produced
        beat.visual_anchors = list(dict.fromkeys(anchors))[:4]
        beats.append(compiled_beat(scene, position, actions, list(dict.fromkeys(shown))))
    # No `layout_ids`: a scene gives a place to what it shows and what it carries in, and to nothing
    # else, so the data does not sit beside an empty hole before the code has been introduced.
    return {"lesson_scene_id": scene.id, "pattern": "workflow", "render_mode": "browser",
            "objects": objects, "relationships": [],
            "layout_ids": [], "beats": beats,
            "opening_visible_ids": opening, "carryover_ids": opening,
            "closing_visible_ids": [obj["id"] for obj in objects if obj["id"] in visible]}


def plan_trace_scenes(lesson: LessonPlan, skill) -> list[BrowserScene]:
    """Every scene of a trace lesson, compiled and checked by the same validator as a
    model-written scene. A failure here is a fault in the lesson, and its message is what the
    lesson step is sent to repair."""
    from verification.visual_plan_validation import validate_scene

    scenes: list[BrowserScene] = []
    state: VisualState | None = None
    for lesson_scene in lesson.scenes:
        previous = scenes[-1] if scenes else None
        scene = BrowserScene.model_validate(compile_trace_scene(lesson, lesson_scene, state))
        validate_scene(lesson_scene, scene, skill,
                       previous_closing=set(previous.closing_visible_ids) if previous else set(),
                       previous_objects={obj.id: obj for obj in previous.objects} if previous else {},
                       previous_pattern=previous.pattern if previous else None,
                       require_v2=True, previous_state=state)
        scenes.append(scene)
        state = closing_state(scene, state)
    return scenes


def trace_problems(lesson: LessonPlan, icons: list[str]) -> list[str]:
    """Why a trace lesson cannot be drawn as written. Everything the picture needs is in the
    schema and found when the scenes are compiled, so there is nothing more to check here."""
    return []


def craft_trace(lesson: LessonPlan, scenes: list[BrowserScene]) -> list[str]:
    """Where a newly planned trace lesson falls short as teaching, in words the lesson step can
    act on. These test craft, never a plot."""
    if lesson.brief is None:
        return ['the lesson starts with a "brief": decide the teaching before the scenes']
    problems = []
    if not any(beat.move.do == "ask" for beat in lesson.scenes[0].beats):
        problems.append("the first scene never puts the learner's question on screen; give one of "
                        'its beats the move {"do":"ask"}, with the question '
                        f"({lesson.brief.question!r}) as its sentence")
    moves = [beat.move for scene in lesson.scenes for beat in scene.beats if beat.move.do not in LINES]
    used = {name for move in moves
            for name in (*move.items, move.pointer, move.against, move.array, move.counter) if name}
    used |= {item.on for item in lesson.trace.data if item.id in used and item.on}
    used |= {item.id for item in lesson.trace.data if item.counts in used}     # it counts by itself
    idle = sorted(item.id for item in lesson.trace.data if item.id not in used)
    if idle:
        problems.append(f"{idle} are in the trace but no move uses them; use them or leave them out")
    if lesson.trace.code is not None and not any(move.lines for move in moves):
        problems.append('the code is never lit; give the moves that carry it out their "lines", '
                        "or leave the code out")
    doing = sum(PROOF[move.do] != "label" for move in moves)
    if doing * 3 < len(moves):
        problems.append(f"only {doing} of {len(moves)} beats show the data being looked at or "
                        "changed; at least a third must be look, compare, discard, fill or count")
    return problems
