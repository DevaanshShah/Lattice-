"""An algorithm lesson's trace, turned into what the renderer draws, with no model call.

The lesson step writes the code and the data once (an array, pointers into it, a target, a
counter, or an empty table with the rule that fills it), and for every beat picks one move: show,
run, look, compare, discard, fill, count. Code here writes everything else. Two things follow
from that. A compare is decided by the values on screen, and a table is worked out from its rule,
so the picture cannot show arithmetic the data does not support, and a cell is never read before
it is filled. And each beat's anchor is read off the state the move produced, so the narration is
checked against the same picture.
"""
from __future__ import annotations

from core.call_tree import repeats, shown_to_depth
from core.schemas.browser_visual_plan import BrowserScene
from core.schemas.lesson_plan import LessonPlan, LessonScene, LessonTrace, TableRule, TraceItem
from core.visual_state import VisualState, closing_state
from planner.lesson_shared import (LINES, apply_brief, ask_the_question, carried, closes_on_a_takeaway,
                                   compiled_beat, line_id, line_objects, number, takeaway_id)

# The proof each move owes the viewer.
PROOF = {"show": "label", "run": "label", "look": "value", "compare": "state_change",
         "discard": "state_change", "fill": "state_change", "count": "state_change",
         "clear": "state_change", "grow": "state_change", "spot": "state_change",
         "remove": "state_change", "ask": "label", "answer": "label"}
CODE = "code"           # the editor window
WORKING = "working"     # the line under a table that shows how a cell was worked out
_JOIN = {"sum": " + ", "min": ", ", "max": ", "}
_COMBINE = {"sum": sum, "min": min, "max": max}


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
        elif item.kind == "tree":
            # every call is in the picture from the start; `shown` says how many are revealed
            payload, role = {"nodes": item.calls, "shown": 1, "marked": []}, "input"
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
    _size_tables_to_fit(data)
    for scene_number, scene in enumerate(data["scenes"], 1):
        if not isinstance(scene, dict) or not isinstance(scene.get("beats"), list):
            continue
        scene.setdefault("id", f"s{scene_number}")
        for beat_number, beat in enumerate(scene["beats"], 1):
            if not isinstance(beat, dict):
                continue
            move = beat.get("move")
            if isinstance(move, dict) and isinstance(beat.get("lines"), list):
                move.setdefault("lines", beat["lines"])     # written beside the move; it belongs in it
                del beat["lines"]
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


def _size_tables_to_fit(data: dict) -> None:
    """A table declared one cell too short for the cells the lesson fills is given the cells it
    needs. Counting from zero is bookkeeping: "stairs 0 to 5" is six boxes, and a model that
    writes five has made no teaching mistake worth a rejected lesson."""
    tables = {item.get("id"): item for item in data["trace"].get("data") or []
              if isinstance(item, dict) and item.get("kind") == "array" and isinstance(item.get("size"), int)}
    for scene in data["scenes"]:
        for beat in (scene.get("beats") or []) if isinstance(scene, dict) else []:
            move = beat.get("move") if isinstance(beat, dict) else None
            if not isinstance(move, dict) or move.get("do") != "fill" or move.get("array") not in tables:
                continue
            cells = [cell for cell in [move.get("cell"), *(move.get("cells") or [])] if isinstance(cell, int)]
            if cells and 0 <= max(cells) < 12:      # twelve cells is what the frame holds
                table = tables[move["array"]]
                table["size"] = max(table["size"], max(cells) + 1)


def table_by_rule(item: TraceItem) -> list[tuple]:
    """A table with a rule, worked out in full: for each cell, what it holds and the cells it was
    read from. A step that would reach back before cell 0 is left out, the way a coin larger than
    the amount is no use; the rule's start values are long enough that one step always reaches."""
    rule, table = item.rule, []
    for cell in range(item.size):
        reads = [] if cell < len(rule.start) else [cell - step for step in rule.back if step <= cell]
        value = (rule.start[cell] if not reads else
                 _COMBINE[rule.op]([table[index][0] for index in reads]) + rule.plus)
        table.append((number(value), reads))
    return table


def _worked_out(label: str, cell: int, rule: TableRule | None, values: list, result) -> str:
    """The line that shows where a filled cell's value came from: 'Ways[3] = 2 + 1 = 3'. A cell
    that is given, or copied from the one cell it reads, has no working to show."""
    name = f"{label}[{cell}]"
    if not values or (len(values) == 1 and not rule.plus):
        return f"{name} = {result}"
    joined = _JOIN[rule.op].join(str(value) for value in values)
    body = joined if rule.op == "sum" or len(values) == 1 else f"{rule.op}({joined})"
    if rule.plus:
        body += f" + {number(rule.plus)}" if rule.plus > 0 else f" - {number(-rule.plus)}"
    return f"{name} = {body} = {result}"


def compile_trace_scene(lesson: LessonPlan, scene: LessonScene,
                        previous_state: VisualState | None, memory: dict | None = None) -> dict:
    """One scene of a trace lesson as a full visual scene, written entirely from its moves.

    `memory` is what each item held when the lesson last left it, across scenes. The replay
    forgets the state of anything that is off screen when a scene ends, so an item brought back
    is first put back the way the lesson left it: a call counter that read 15 does not return
    reading 0."""
    trace = lesson.trace
    items = {item.id: item for item in trace.data}
    working = any(beat.move.do == "fill" for each in lesson.scenes for beat in each.beats)
    objects = trace_objects(trace, scene, working)
    opening, visible, drawn = carried(objects, previous_state)      # what the replay holds
    memory = memory if memory is not None else {}
    payloads = {obj_id: dict(memory.get(obj_id, held)) for obj_id, held in drawn.items()}
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
            for item in new:        # back the way the lesson left it, before it is seen again
                lost = {key: value for key, value in payloads[item].items()
                        if drawn[item].get(key) != value}
                if lost:
                    actions.append({"kind": "set_state", "target_ids": [item], "params": lost})
                    drawn[item].update(lost)
            if new:
                actions.append({"kind": "appear", "target_ids": new, "params": {}})
                visible.update(new)

        def change(obj_id: str, params: dict) -> bool:
            if all(payloads[obj_id].get(key) == value for key, value in params.items()):
                return False
            actions.append({"kind": "set_state", "target_ids": [obj_id], "params": params})
            payloads[obj_id].update(params)
            drawn[obj_id].update(params)
            return True

        def bump(counter: str) -> None:
            show([counter])
            actions.append({"kind": "increment", "target_ids": [counter], "params": {}})
            payloads[counter]["value"] += 1
            drawn[counter]["value"] = payloads[counter]["value"]

        def place(pointer: str, index: int | None) -> str:
            """Put a pointer on a cell, bringing it and its array on screen. Returns the array."""
            array = items[pointer].on
            show([array])
            moved = index is not None and payloads[pointer]["index"] != index
            if moved:
                actions.append({"kind": "move", "target_ids": [pointer], "params": {"index": index}})
                payloads[pointer]["index"] = drawn[pointer]["index"] = index
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
                drawn[array]["checked_results"] = dict(results)
                for tally in tallies:       # a counter tied to this pointer counts the check itself
                    bump(tally)
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
            if resting:     # the pointers leave; the claim is about the array, which may be unmarked
                actions.append({"kind": "hide", "target_ids": resting, "params": {}})
                visible.difference_update(resting)
            anchors.append(items[move.array].label)
            shown.append(move.array)        # the pointers have left; the array is what is shown
        elif move.do == "discard":
            show([move.array])
            gone = sorted({*(payloads[move.array].get("discarded_indices") or []), *move.cells})
            changed = change(move.array, {"discarded_indices": gone})
            cells = payloads[move.array]["items"]
            anchors.append("discard [" + ",".join(str(cells[index]) for index in gone) + "]")
            shown.append(move.array)
        elif move.do == "fill":
            show([move.array])
            table, rule = items[move.array], items[move.array].rule
            label, held = table.label, payloads[move.array]["items"]
            named = move.cells or [move.cell]
            if rule is None:        # a number the lesson gives, written where it says
                if held[move.cell] is not None:
                    raise ValueError(f"beat {beat.id}: cell {move.cell} of {move.array!r} already "
                                     f"holds {held[move.cell]}; a table that is filled in starts "
                                     'empty, so give the array "size" instead of "items"')
                jobs = [(move.cell, number(move.value), [])]
            else:
                # Code works the whole table out. What the lesson says a cell holds is checked
                # against it, and every cell still empty up to the last one named is filled in
                # order, so no cell is ever read before it holds a number.
                whole = table_by_rule(table)
                said = move.expect if isinstance(move.expect, list) else [move.expect]
                for cell, hoped in zip(named, said):
                    value, reads = whole[cell]
                    if number(hoped) != value:
                        worked = _worked_out(label, cell, rule, [whole[index][0] for index in reads], value)
                        raise ValueError(
                            f"beat {beat.id}: you expect cell {cell} of {move.array!r} to hold "
                            f"{number(hoped)}, but its rule gives {worked}. From the start values "
                            f"{[number(value) for value in rule.start]} the table comes to "
                            f"{[value for value, _ in whole]}, counting cells from 0. Change the "
                            "rule's start values, or the numbers the lesson states, so they agree")
                due = {cell for cell in range(max(named) + 1) if held[cell] is None}
                jobs = [(cell, *whole[cell]) for cell in sorted(due | set(named))]
            fills = [item.id for item in trace.data if item.counts == move.array]
            for target, value, reads in jobs:
                cells = list(payloads[move.array]["items"])
                again = cells[target] is not None       # filled before: pointed at, not written
                worked = _worked_out(label, target, rule, [cells[index] for index in reads], value)
                cells[target] = value
                changed = change(move.array, {"items": cells, "lit_indices": reads,
                                              "new_index": target}) or changed
                for tally in [] if again else fills:    # a counter tied to this table counts the cell
                    bump(tally)
                change(WORKING, {"expression": worked})
                show([WORKING])
            anchors.append(worked)
            shown += [move.array, WORKING, *fills]
        elif move.do == "grow":
            # reveal the calls down to a level (or all of them); a counter tied to the tree follows
            show([move.tree])
            reach = max(payloads[move.tree]["shown"],
                        shown_to_depth(payloads[move.tree]["nodes"], move.depth))
            changed = change(move.tree, {"shown": reach})
            tallies = [item.id for item in trace.data if item.counts == move.tree]
            for tally in tallies:
                show([tally])
                change(tally, {"value": reach})
            anchors.append(items[move.tree].label)
            anchors += [f"{items[tally].label}: {reach}" for tally in tallies]
            shown += [move.tree, *tallies]
        elif move.do == "spot":
            # pick out every call for one value: the same work, done more than once
            show([move.tree])
            value = number(move.value)
            calls = payloads[move.tree]["nodes"][:payloads[move.tree]["shown"]]
            if sum(call["value"] == value for call in calls) < 2:
                raise ValueError(f"beat {beat.id}: {value} has been called for only once in what "
                                 f"is shown of {move.tree!r}; grow the tree further first, or spot "
                                 "a value that repeats")
            changed = change(move.tree, {"marked": sorted({*payloads[move.tree]["marked"], value})})
            anchors.append(repeats({**payloads[move.tree], "marked": [value]})[0])
            shown.append(move.tree)
        elif move.do == "remove":
            unseen = [name for name in move.items if name not in visible]
            if unseen:
                raise ValueError(f"beat {beat.id}: a remove move names {unseen}, which are not on "
                                 "screen; only what has been shown can be taken away")
            # lit once, then gone: the viewer sees what is leaving
            actions.append({"kind": "highlight", "target_ids": list(move.items), "params": {}})
            actions.append({"kind": "hide", "target_ids": list(move.items), "params": {}})
            visible.difference_update(move.items)
            changed = True
            anchors += [items[name].label for name in move.items if name in items][:2]
            shown += move.items
        elif move.do == "count":
            show([move.counter])
            if items[move.counter].counts is None:
                bump(move.counter)
                changed = True
            # A counter tied to a pointer has already counted every check. Bumping it here would
            # show one more than were made, so the move only points at the count.
            total = payloads[move.counter]["value"]
            if move.expect is not None and number(move.expect) != total:
                tied = items[move.counter].counts
                why = ("it counts nothing by itself: give it \"counts\" with the id of the pointer, "
                       "tree or table it should follow" if tied is None else
                       f"the tree {tied!r} has {len(payloads[tied]['nodes'])} calls in all and "
                       f"{payloads[tied]['shown']} are shown: grow it fully (a grow move with no "
                       "\"depth\") before stating the total" if items[tied].kind == "tree" else
                       f"it has counted {total} so far")
                raise ValueError(f"beat {beat.id}: you expect {move.counter!r} to read "
                                 f"{number(move.expect)}, but it reads {total}; {why}")
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
    memory.update({item.id: dict(payloads[item.id]) for item in trace.data})
    if working:
        memory[WORKING] = dict(payloads[WORKING])
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
    memory: dict = {}
    for lesson_scene in lesson.scenes:
        previous = scenes[-1] if scenes else None
        scene = BrowserScene.model_validate(compile_trace_scene(lesson, lesson_scene, state, memory))
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


def _tree_beside_an_array(lesson: LessonPlan, scenes: list[BrowserScene]) -> tuple[str, str, str] | None:
    """The first beat that leaves a tree and an array on screen together, with their ids."""
    from core.visual_state import apply_action, opening_state

    kinds = {item.id: item.kind for item in lesson.trace.data}
    state = None
    for scene in scenes:
        state = opening_state(scene, state)
        for beat in scene.beats:
            for action in beat.actions:
                apply_action(state, action)
            trees = [name for name in state.visible if kinds.get(name) == "tree"]
            arrays = [name for name in state.visible if kinds.get(name) == "array"]
            if trees and arrays:
                return beat.narration_beat_id, sorted(trees)[0], sorted(arrays)[0]
    return None


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
    # An item no move uses is never brought on screen and takes no room, so it is no fault of the
    # lesson: a pointer declared and then not needed is simply not drawn.
    if lesson.trace.code is not None and not any(move.lines for move in moves):
        problems.append('the code is never lit; give the moves that carry it out their "lines", '
                        "or leave the code out")
    crowded = _tree_beside_an_array(lesson, scenes)
    if crowded:
        problems.append(f"beat {crowded[0]} has the tree {crowded[1]!r} and the array {crowded[2]!r} on "
                        "screen together, and the frame has room for one of them at a readable size; "
                        f'take the tree off first with {{"do":"remove","items":["{crowded[1]}"]}}')
    doing = sum(PROOF[move.do] != "label" for move in moves)
    if doing * 3 < len(moves):
        problems.append(f"only {doing} of {len(moves)} beats show the data being looked at or "
                        "changed; at least a third must be look, compare, discard, fill, count, "
                        "grow or spot")
    return problems
