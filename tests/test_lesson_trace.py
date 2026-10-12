"""A trace lesson (an algorithm: code beside its data): the model writes narration and one move
per beat, and code compiles the visuals, works out the arithmetic and counts the checks."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan, LessonTrace
from core.visual_state import closing_state
from planner import browser_visual_plan, lesson_plan
from planner.lesson_shared import story_shape
from planner.lesson_trace import craft_trace, fill_trace_lesson, plan_trace_scenes, table_by_rule
from planner.playbooks import PLAYBOOKS, playbook_of
from planner.product_recipe import load_recipes
from verification.visual_plan_validation import validate

FIXTURES = Path(__file__).parent / "fixtures" / "video_golden"
SKILL = load_recipes()["algorithm_explainer"]


def _saved(name: str) -> LessonPlan:
    return LessonPlan.model_validate_json((FIXTURES / name / "lesson_plan.json").read_text(encoding="utf-8"))


def _as_written(name: str) -> dict:
    """A fixture's lesson as the model is asked to write it: the brief, the trace, and for each
    beat only its sentence and its move. The check question and answer are left for code to add."""
    lesson = json.loads((FIXTURES / name / "lesson_plan.json").read_text(encoding="utf-8"))
    scenes = [{"title": scene["title"], "learning_goal": scene["learning_goal"],
               **({"takeaway": scene["takeaway"]} if scene["takeaway"] else {}),
               "beats": [{"spoken_text": beat["spoken_text"],
                          "move": {key: value for key, value in beat["move"].items()
                                   if value not in (None, [], 0, 1)
                                   or key in ("index", "cell", "value", "expect", "depth") and value is not None}}
                         for beat in scene["beats"]]}
              for scene in lesson["scenes"]]
    scenes[-1]["beats"] = scenes[-1]["beats"][:-2]
    for scene in scenes:
        for beat in scene["beats"]:
            if beat["move"]["do"] in ("ask", "turn"):       # the brief's words: code puts them in
                beat["move"] = {"do": beat["move"]["do"]}
    return {"brief": lesson["brief"], "trace": json.loads(json.dumps(lesson["trace"])), "scenes": scenes}


def _lesson(answer: dict) -> LessonPlan:
    data = fill_trace_lesson(answer)
    return LessonPlan.model_validate({**data, "schema_version": 2, "topic": "t", "skill_id": SKILL.id})


class _Scripted:
    def __init__(self, answers):
        self.answers, self.asked = [json.dumps(answer) for answer in answers], []

    def chat(self, messages, **_):
        self.asked.append(list(messages))
        return self.answers.pop(0)


def _steps(scene, number):
    return [(action.kind, action.target_ids, action.params) for action in scene.beats[number].actions]


@pytest.mark.unit
def test_the_recipe_for_algorithms_uses_the_trace_playbook():
    assert SKILL.board == "trace" and PLAYBOOKS["trace"].prompt == "lesson-plan-trace"
    assert playbook_of(_saved("taught_search")).board == "trace"
    assert playbook_of(_saved("taught_map")).board == "map"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["taught_search", "taught_stairs", "taught_coins"])
def test_a_trace_fixture_is_exactly_what_the_compiler_writes(name):
    lesson = _saved(name)
    saved = BrowserVisualPlan.model_validate_json(
        (FIXTURES / name / "browser_visual_plan.json").read_text(encoding="utf-8"))
    compiled = plan_trace_scenes(lesson, SKILL)
    assert saved.scenes == compiled
    assert craft_trace(lesson, compiled) == []
    validate(lesson, saved, SKILL)
    # written as the model writes it and filled again, it is the same lesson
    again = _lesson(_as_written(name))
    plan_trace_scenes(again, SKILL)
    assert [[beat.model_dump() for beat in scene.beats] for scene in again.scenes] == [
        [beat.model_dump() for beat in scene.beats] for scene in lesson.scenes]


@pytest.mark.unit
def test_checking_one_by_one_marks_every_cell_and_the_counter_counts_by_itself():
    lesson = _saved("taught_search")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    walk = _steps(first, 1)
    assert [kind for kind, _, _ in walk].count("compare") == 6
    assert [kind for kind, _, _ in walk].count("increment") == 6
    assert walk[:3] == [("appear", ["scan"], {}), ("compare", ["scan", "target"], {}),
                        ("appear", ["slow"], {})]            # the pointer starts on cell 0
    assert ("move", ["scan"], {"index": 5}) in walk
    assert lesson.scenes[0].beats[1].visual_anchors == ["30 ✓", "One by one: 6"]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert (end.payloads["slow"]["value"], end.payloads["fast"]["value"]) == (6, 2)
    assert end.payloads["numbers"]["checked_results"] == {"3": "miss", "5": "match"}
    assert end.payloads["numbers"]["discarded_indices"] == [0, 1, 2, 3]


@pytest.mark.unit
def test_clear_wipes_the_marks_and_sends_the_pointer_away():
    answer = _as_written("taught_search")
    answer["scenes"][1]["beats"][0] = {
        "spoken_text": "Wipe the marks and start again, this time with the code on screen.",
        "move": {"do": "clear", "array": "numbers", "lines": [1]}}
    lesson = _lesson(answer)
    first, second, _ = plan_trace_scenes(lesson, SKILL)
    assert _steps(second, 0) == [
        ("appear", ["code"], {}), ("set_state", ["code"], {"active_lines": [1]}),
        ("set_state", ["numbers"], {"checked_results": {}}), ("hide", ["scan", "working"], {})]
    assert lesson.scenes[1].beats[0].claim_requirements == {"s2_b1_c": ["state_change"]}
    # the pointer of the second attempt arrives already on its cell
    assert _steps(second, 1) == [("set_state", ["code"], {"active_lines": [4]}),
                                 ("move", ["mid"], {"index": 3}), ("appear", ["mid"], {})]
    assert lesson.scenes[1].beats[1].visual_anchors == ["mid = (low + high) // 2", "mid: 17"]
    assert lesson.scenes[1].beats[3].visual_anchors == ["if items[mid] < target:", "discard [3,8,12,17]"]


@pytest.mark.unit
def test_the_turning_point_is_said_in_the_briefs_words_and_the_first_attempt_is_put_away_after_it():
    """Reviewed on 2026-10-12: in four lessons of four the idea was shown and its reason never
    said, and the brief's turning point was spoken in none. It is now a move, placed by code the
    way the question is, and the beat after it starts the better idea on a clean stage."""
    lesson = _saved("taught_search")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    turn = lesson.scenes[1].beats[0]
    assert turn.move.do == "turn" and turn.spoken_text == turn.move.text == lesson.brief.turning_point
    line = {obj.id: obj for obj in second.objects}["s2_b1_line"]
    assert (line.label, line.payload) == (lesson.brief.turning_point, {"tone": "yellow", "idea": True})
    assert _steps(second, 0) == [("appear", ["s2_b1_line"], {})]       # said over the first attempt
    assert _steps(second, 1) == [                                       # then the stage is cleared
        ("set_state", ["numbers"], {"checked_results": {}}), ("hide", ["scan", "working"], {}),
        ("appear", ["code"], {}), ("set_state", ["code"], {"active_lines": [4]}),
        ("move", ["mid"], {"index": 3}), ("appear", ["mid"], {})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert (end.payloads["slow"]["value"], end.payloads["fast"]["value"]) == (6, 2)    # both costs kept
    # a tree leaves the same way, with no remove move, and its counter keeps the calls
    tree, table, _ = plan_trace_scenes(_saved("taught_recursion"), SKILL)
    assert _steps(table, 1)[0] == ("hide", ["calls"], {})
    assert closing_state(table, closing_state(tree)).payloads["count"]["value"] == 15


@pytest.mark.unit
def test_a_lesson_that_never_says_why_is_sent_back_and_a_lesson_has_one_turning_point():
    silent = _as_written("taught_search")
    silent["scenes"][1]["beats"].pop(0)
    client = _Scripted([silent, _as_written("taught_search")])
    reasons = []
    lesson_plan.generate("Why binary search needs so few checks", SKILL, client=client,
                         schema_version=2, on_reject=reasons.append)
    assert ("the lesson never says why the better way works; at the beat where the better idea "
            'begins, use the move {"do":"turn"}' in reasons[0])
    assert "'Because the list is sorted, one look at the middle rules out half of it.'" in reasons[0]
    twice = _as_written("taught_search")
    twice["scenes"][2]["beats"].insert(0, {"move": {"do": "turn"}})
    with pytest.raises(ValidationError, match="a lesson has one turning point"):
        _lesson(twice)
    early = _as_written("taught_search")
    early["scenes"][0]["beats"].insert(1, early["scenes"][1]["beats"].pop(0))
    lesson = _lesson(early)
    assert any("the turning point comes before the question it answers" in problem
               for problem in craft_trace(lesson, plan_trace_scenes(lesson, SKILL)))


@pytest.mark.unit
def test_a_compare_says_how_the_two_numbers_compare_and_a_lit_line_goes_out_after_its_step():
    """Reviewed on 2026-10-12: a red cross sat beside a lit line that was true (12 < 23), and a
    line stayed lit through sentences that had nothing to do with it."""
    lesson = _saved("taught_search")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert ("set_state", ["working"], {"expression": "17 < 30"}) in _steps(second, 2)
    assert ("set_state", ["working"], {"expression": "30 = 30"}) in _steps(third, 0)
    said = [params["expression"] for _, target, params in _steps(first, 1)
            if target == ["working"] and "expression" in params]
    assert said == ["3 < 30", "8 < 30", "12 < 30", "17 < 30", "21 < 30", "30 = 30"]
    # the check question is asked with no line of code lit
    assert _steps(third, 2)[0] == ("set_state", ["code"], {"active_lines": []})



@pytest.mark.unit
def test_a_table_is_filled_by_code_from_its_rule():
    lesson = _saved("taught_stairs")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    table = {obj.id: obj for obj in first.objects}["ways"]
    assert table.payload["items"] == [None] * 6                           # it starts empty
    # where the number comes from is shown first; then the number lands in its cell
    assert _steps(second, 1) == [
        ("set_state", ["code"], {"active_lines": [6]}),
        ("set_state", ["ways"], {"lit_indices": [1, 0], "new_index": 2}),
        ("set_state", ["working"], {"expression": "Ways[2] = 1 + 1 = 2"}),
        ("set_state", ["ways"], {"items": [1, 1, 2, None, None, None]})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]
    assert end.payloads["working"]["expression"] == "Ways[5] = 5 + 3 = 8"
    assert [anchors[-1] for anchors in (beat.visual_anchors for beat in lesson.scenes[2].beats[:2])] == [
        "Ways[4] = 3 + 2 = 5", "Ways[5] = 5 + 3 = 8"]


@pytest.mark.unit
def test_a_rule_can_take_the_smallest_and_add_one_and_never_reads_before_the_table():
    """Fewest coins of 1, 3 and 4: an amount smaller than a coin cannot use that coin."""
    lesson = _saved("taught_coins")
    table = table_by_rule(next(item for item in lesson.trace.data if item.id == "best"))
    assert [value for value, _ in table] == [0, 1, 2, 1, 1, 2, 2]
    assert [reads for _, reads in table] == [[], [0], [1], [2, 0], [3, 1, 0], [4, 2, 1], [5, 3, 2]]
    plan_trace_scenes(lesson, SKILL)
    fills = [beat.visual_anchors[-1] for scene in lesson.scenes for beat in scene.beats
             if beat.move.do == "fill"]
    assert fills == ["Fewest[0] = 0", "Fewest[1] = 0 + 1 = 1", "Fewest[2] = 1 + 1 = 2",
                     "Fewest[3] = min(2, 0) + 1 = 1", "Fewest[5] = min(1, 2, 1) + 1 = 2",
                     "Fewest[6] = min(2, 1, 2) + 1 = 2"]


@pytest.mark.unit
def test_filling_a_cell_fills_every_empty_cell_before_it_in_order():
    """What live lessons got wrong on 2026-10-11: a cell worked out from one still empty. The
    lesson no longer orders the fills, so it cannot order them wrongly."""
    answer = _as_written("taught_stairs")
    answer["scenes"][0]["beats"][2:] = [{
        "spoken_text": "Fill the table straight to the top: eight ways.",
        "move": {"do": "fill", "array": "ways", "cell": 5, "expect": 8, "lines": [6]}}]
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    wrote = [params for _, target, params in _steps(first, 2) if target == ["ways"]]
    assert [params["new_index"] for params in wrote if "new_index" in params] == [0, 1, 2, 3, 4, 5]
    assert wrote[-2:] == [{"lit_indices": [4, 3], "new_index": 5}, {"items": [1, 1, 2, 3, 5, 8]}]
    assert lesson.scenes[0].beats[2].visual_anchors[-1] == "Ways[5] = 5 + 3 = 8"
    # the later fills name cells that are already full: they point, and write nothing
    assert _steps(second, 1) == [
        ("set_state", ["code"], {"active_lines": [6]}),
        ("set_state", ["ways"], {"lit_indices": [1, 0], "new_index": 2}),
        ("set_state", ["working"], {"expression": "Ways[2] = 1 + 1 = 2"})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]


@pytest.mark.unit
def test_a_cell_pointed_at_again_is_not_counted_twice():
    answer = _as_written("taught_stairs")
    answer["trace"]["data"].append({"id": "boxes", "kind": "counter", "label": "Boxes filled", "counts": "ways"})
    answer["scenes"][2]["beats"] += [
        {"spoken_text": "Look again at stair three: two plus one.",
         "move": {"do": "fill", "array": "ways", "cell": 3, "expect": 3, "lines": [6]}},
        {"spoken_text": "{boxes} boxes, each filled once.",
         "move": {"do": "count", "counter": "boxes", "expect": 6}}]
    lesson = _lesson(answer)
    plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].beats[3].visual_anchors[-1] == "Ways[3] = 2 + 1 = 3"
    assert lesson.scenes[2].beats[4].visual_anchors == ["Boxes filled: 6"]


@pytest.mark.unit
def test_a_check_made_twice_is_emphasis_not_a_change():
    answer = _as_written("taught_search")
    answer["scenes"][1]["beats"].insert(3, {
        "spoken_text": "Seventeen, again, is not thirty.",
        "move": {"do": "compare", "pointer": "mid", "against": "target"}})
    lesson = _lesson(answer)
    _, second, _ = plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[1].beats[3].claim_requirements == {"s2_b4_c": ["label"]}
    assert [evidence.kind for evidence in second.beats[3].evidence] == ["label"]


@pytest.mark.unit
def test_a_trace_lesson_costs_one_call_and_a_weak_one_goes_back_with_the_reason():
    good = _as_written("taught_stairs")
    weak = _as_written("taught_stairs")
    weak["scenes"][0]["beats"].pop(1)                                      # the question is never asked
    weak["scenes"][2]["beats"].pop()                                       # the run of the last line goes
    for scene in weak["scenes"]:
        for beat in scene["beats"]:
            beat["move"].pop("lines", None)                                # and the code is never lit
    weak["trace"]["data"].append({"id": "spare", "kind": "value", "label": "Spare", "value": 1})
    client = _Scripted([{"brief": good["brief"], "scenes": good["scenes"]}, weak, good])
    reasons = []
    lesson = lesson_plan.generate("Counting the ways to climb stairs", SKILL, client=client,
                                  schema_version=2, on_reject=reasons.append)
    assert len(client.asked) == 3 and lesson.trace is not None
    system, user = client.asked[0][0]["content"], client.asked[0][1]["content"]
    assert "ONE trace" in system and "Icon list" not in user
    assert "taught on a trace" in reasons[0]
    for expected in ("never puts the learner's question on screen", "the code is never lit"):
        assert expected in reasons[1]
    assert "spare" not in reasons[1]             # an item nothing uses is never drawn, so it is no fault
    # the visual step then makes no call at all
    plan = browser_visual_plan.generate(lesson, SKILL, client=_Scripted([]), schema_version=2)
    validate(lesson, plan, SKILL)
    assert story_shape(lesson) == "show ask fill fill | turn fill fill | fill fill run ask answer"


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda a: a["scenes"][1]["beats"][1]["move"].update(index=9), "there is no cell 9"),
    (lambda a: a["scenes"][1]["beats"][1]["move"].update(lines=[40]), "there is no line 40"),
    (lambda a: a["scenes"][1]["beats"][1]["move"].update(pointer="target"), "'target' is not a pointer"),
    (lambda a: a["scenes"][1]["beats"][2]["move"].update(against="ghost"), "not in the trace"),
    (lambda a: a["scenes"][1]["beats"][2]["move"].update(cells=[1, 2], index=3), "not both"),
    (lambda a: a["scenes"][1]["beats"][1].update(move={"do": "send", "path": ["numbers", "target"]}),
     "'send' is not a move of a trace lesson"),
    (lambda a: a["scenes"][1]["beats"][1].update(move={"do": "fill", "array": "numbers", "cell": 1}),
     'says what its cell comes to in "expect"'),
    (lambda a: a["scenes"][1]["beats"][1].update(
        move={"do": "fill", "array": "numbers", "cell": 1, "expect": 3}),
     "'numbers' has no rule to work a cell out from"),
])
def test_a_move_that_does_not_fit_the_trace_is_refused(change, message):
    answer = _as_written("taught_search")
    change(answer)
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda t: t["data"][0].update(size=5), "either its items, or a size"),
    (lambda t: t["data"][2].update(on="target"), "which is not an array"),
    (lambda t: t["data"][4].update(counts="target"), "not a pointer, a tree or an array"),
    (lambda t: t["data"][1].update(items=[1, 2]), "a value has no items"),
    (lambda t: t["code"].update(source="x = 1\n" * 15), "at most 14 lines"),
    (lambda t: t["data"].__setitem__(0, {"id": "target", "kind": "value", "label": "T", "value": 1}),
     "unique"),
    (lambda t: t["data"][5].update(label="one by one"), "share the label 'one by one'"),
    (lambda t: t["data"][0].update(rule={"start": [1, 1], "back": [1, 2], "op": "sum"}),
     'has a rule, so it starts empty and is filled in: give it "size", not "items"'),
    (lambda t: t["data"][2].update(rule={"start": [1], "back": [1], "op": "sum"}), "a pointer has no rule"),
    (lambda t: t["data"].append({"id": "t", "kind": "array", "label": "T", "size": 4,
                                 "rule": {"start": [0], "back": [0, 1], "op": "sum"}}),
     "whole numbers from 1, each once"),
    (lambda t: t["data"].append({"id": "t", "kind": "array", "label": "T", "size": 6,
                                 "rule": {"start": [0], "back": [3, 4], "op": "min", "plus": 1}}),
     'the first cell the rule works out is cell 1.*give "start" at least 3 values'),
    (lambda t: t["data"].append({"id": "t", "kind": "array", "label": "T", "size": 2,
                                 "rule": {"start": [1, 1, 2], "back": [1, 2], "op": "sum"}}),
     "has 2 cells and 3 start values"),
])
def test_a_malformed_trace_is_refused(change, message):
    trace = _as_written("taught_search")["trace"]
    change(trace)
    with pytest.raises(ValidationError, match=message):
        LessonTrace.model_validate(trace)


@pytest.mark.unit
def test_a_lesson_is_drawn_on_a_map_or_on_a_trace_never_both():
    answer = _as_written("taught_search")
    answer["map"] = json.loads((FIXTURES / "taught_map" / "lesson_plan.json").read_text(encoding="utf-8"))["map"]
    with pytest.raises(ValidationError, match="on a map or on a trace, not both"):
        _lesson(answer)


@pytest.mark.unit
def test_a_table_draws_empty_cells_the_cells_read_and_the_cell_written():
    from generation.browser_scene import _semantic_html

    first, second, _ = plan_trace_scenes(_saved("taught_stairs"), SKILL)
    html = _semantic_html(second, closing_state(second, closing_state(first)))
    cell = lambda index: html.split(f'data-visual-key="ways:cell:{index}"')[0].rsplit('class="', 1)[1]
    assert "is-new" in cell(3) and "is-lit" in cell(2) and "is-lit" in cell(1)
    assert "is-empty" in cell(4) and "is-empty" in cell(5)
    assert "is-empty" not in cell(0) and "None" not in html
    assert "semantic-split" in html and "Ways[3] = 2 + 1 = 3" in html     # code left, working line right


@pytest.mark.unit
def test_a_run_of_fills_finishes_a_table_in_one_beat():
    answer = _as_written("taught_stairs")
    answer["scenes"][2]["beats"][0:2] = [{
        "spoken_text": "The same rule fills the rest: five ways for stair four, eight for stair five.",
        "move": {"do": "fill", "array": "ways", "cells": [4, 5], "expect": [5, 8], "lines": [6]}}]
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    run = _steps(third, 0)
    assert [params["new_index"] for kind, _, params in run if "new_index" in params] == [4, 5]
    assert [params["expression"] for kind, _, params in run if "expression" in params] == [
        "Ways[4] = 3 + 2 = 5", "Ways[5] = 5 + 3 = 8"]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]
    assert lesson.scenes[2].beats[0].visual_anchors[-1] == "Ways[5] = 5 + 3 = 8"


@pytest.mark.unit
@pytest.mark.parametrize("move, message", [
    ({"do": "fill", "array": "ways", "cells": [4, 5], "cell": 5, "expect": [5, 8]},
     'one "cell" or several "cells", not both'),
    ({"do": "fill", "array": "ways", "cells": [4, 5]}, 'says what its cell comes to in "expect"'),
    ({"do": "fill", "array": "ways", "cells": [4, 5], "expect": 8}, "a list with one number per cell"),
    ({"do": "fill", "array": "ways", "cell": 4, "expect": [5]}, "one number for one"),
    ({"do": "fill", "array": "ways", "cell": 4, "value": 5, "expect": 5}, "has nothing to check"),
    # the working belongs to the table's rule; a move has nowhere to put its own
    ({"do": "fill", "array": "ways", "cell": 4, "from_cells": [3, 2], "op": "sum", "expect": 5},
     "from_cells"),
    ({"do": "fill", "array": "ways", "cell": 4, "value": 5},
     r"""'ways' is filled by its rule, so a fill gives no "value".*"cell":4,"expect":5\}"""),
])
def test_a_fill_names_its_cell_and_the_number_expected_and_nothing_else(move, message):
    answer = _as_written("taught_stairs")
    answer["scenes"][2]["beats"][0]["move"] = move
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


@pytest.mark.unit
def test_the_data_side_has_room_by_kind_and_a_trace_lesson_gets_more_shorter_beats():
    trace = _as_written("taught_search")["trace"]
    trace["data"] += [{"id": f"more{n}", "kind": "array", "label": f"More {n}", "items": [1, 2]} for n in (1, 2)]
    with pytest.raises(ValidationError, match="room for at most 2 arrays"):
        LessonTrace.model_validate(trace)
    # An algorithm is not asked for in under ninety seconds, whatever length was picked: 252
    # words at 15 words a beat (a sentence that carries its reason) is seventeen beats, two of
    # which code adds. The recipe's older outline is not sent with it.
    client = _Scripted([_as_written("taught_search")] * 5)
    with pytest.raises(lesson_plan.LessonPlanError, match="write between 176 and 328"):
        lesson_plan.generate("Why binary search needs so few checks", SKILL, client=client,
                             schema_version=2, target_seconds=45)
    assert "is about 252 words, between 176 and 328" in client.asked[0][1]["content"]
    assert "Write about 15 beats, in 4 scenes" in client.asked[0][1]["content"]
    assert "Lesson guidance" not in client.asked[0][1]["content"]


@pytest.mark.unit
def test_a_counter_that_counts_by_itself_is_not_bumped_by_hand():
    answer = _as_written("taught_search")
    answer["scenes"][0]["beats"].insert(2, {
        "spoken_text": "That took {slow} checks.", "move": {"do": "count", "counter": "slow", "expect": 6}})
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert _steps(first, 2) == [("highlight", ["slow"], {})]              # it points at the count
    assert lesson.scenes[0].beats[2].visual_anchors == ["One by one: 6"]
    assert lesson.scenes[0].beats[2].claim_requirements == {"s1_b3_c": ["label"]}
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["slow"]["value"] == 6                             # six checks were made, six are shown
    # a counter of its own is still counted by the move
    answer = _as_written("taught_search")
    answer["trace"]["data"][4].pop("counts")
    answer["scenes"][0]["beats"].insert(2, {
        "spoken_text": "One more.", "move": {"do": "count", "counter": "slow"}})
    first, _, _ = plan_trace_scenes(_lesson(answer), SKILL)
    assert _steps(first, 2) == [("appear", ["slow"], {}), ("increment", ["slow"], {})]


@pytest.mark.unit
def test_a_recursion_is_drawn_as_the_tree_of_calls_it_really_makes():
    from core.call_tree import call_tree, positions, repeats, shown_to_depth

    calls = call_tree(5, [1, 2], 1)
    assert [call["value"] for call in calls] == [5, 4, 3, 3, 2, 2, 1, 2, 1, 1, 0, 1, 0, 1, 0]
    assert [shown_to_depth(calls, depth) for depth in (0, 1, 2, None)] == [1, 3, 7, 15]
    assert repeats({"nodes": calls, "shown": 15, "marked": [3, 2]}) == [
        "3 is worked out 2 times", "2 is worked out 3 times"]
    assert repeats({"nodes": calls, "shown": 3, "marked": [3]}) == ["3 is worked out 1 times"]
    where, width, height = positions(calls)
    assert len(where) == 15 and where[0][1] < where[1][1]                 # the first call is at the top
    assert where[1][0] < where[0][0] < where[2][0]                        # a call sits between its two
    assert all(0 < x < width and 0 < y < height for x, y in where.values())
    assert len(call_tree(3, [1], 0)) == 4                                 # a plain countdown: 3, 2, 1, 0


@pytest.mark.unit
def test_the_tree_grows_by_level_and_its_counter_reads_the_calls_shown():
    lesson = _saved("taught_recursion")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    tree = {obj.id: obj for obj in first.objects}["calls"]
    assert len(tree.payload["nodes"]) == 15 and tree.payload["shown"] == 1
    assert _steps(first, 0) == [("appear", ["calls"], {}), ("set_state", ["calls"], {"shown": 3}),
                                ("appear", ["count"], {}), ("set_state", ["count"], {"value": 3})]
    assert _steps(first, 2) == [("set_state", ["calls"], {"shown": 15}),
                                ("set_state", ["count"], {"value": 15})]
    assert _steps(first, 3) == [("set_state", ["calls"], {"marked": [3]})]
    assert _steps(first, 4) == [("set_state", ["calls"], {"marked": [2, 3]})]
    assert [beat.visual_anchors for beat in lesson.scenes[0].beats[2:5]] == [
        ["Calls made by ways(5)", "Calls: 15"], ["3 is worked out 2 times"], ["2 is worked out 3 times"]]
    # the tree leaves after the turning point; its count stays for the comparison at the end
    assert _steps(second, 1)[0] == ("hide", ["calls"], {})
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert "calls" not in end.visible and end.payloads["count"]["value"] == 15
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]


@pytest.mark.unit
@pytest.mark.parametrize("name", ["taught_recursion"])
def test_the_recursion_fixture_is_exactly_what_the_compiler_writes(name):
    lesson = _saved(name)
    saved = BrowserVisualPlan.model_validate_json(
        (FIXTURES / name / "browser_visual_plan.json").read_text(encoding="utf-8"))
    compiled = plan_trace_scenes(lesson, SKILL)
    assert saved.scenes == compiled and craft_trace(lesson, compiled) == []
    validate(lesson, saved, SKILL)


@pytest.mark.unit
def test_a_value_called_for_once_cannot_be_spotted_as_repeated_work():
    answer = _as_written("taught_recursion")
    answer["scenes"][0]["beats"][3]["move"] = {"do": "spot", "tree": "calls", "value": 5}
    with pytest.raises(ValueError, match="5 has been called for only once"):
        plan_trace_scenes(_lesson(answer), SKILL)


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda a: a["trace"]["data"][0].update(start=12), "more than 31 calls"),
    (lambda a: a["trace"]["data"][0].pop("steps"), "how much each call steps down by"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(depth=9), "there is no level 9"),
    (lambda a: a["scenes"][0]["beats"][3]["move"].update(value=7), "never calls for 7"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(tree="ways"), "'ways' is not a tree"),
    (lambda a: a["scenes"][1]["beats"][0].update(move={"do": "remove", "pieces": ["calls"]}),
     'names "items", not pieces'),
])
def test_a_tree_and_its_moves_follow_their_rules(change, message):
    answer = _as_written("taught_recursion")
    change(answer)
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


@pytest.mark.unit
def test_the_tree_draws_every_call_in_place_and_reveals_only_what_is_shown():
    from generation.browser_scene import _semantic_html
    from core.visual_state import after_beat, opening_state

    first, _, _ = plan_trace_scenes(_saved("taught_recursion"), SKILL)
    early = _semantic_html(first, after_beat(opening_state(first), first, "s1_b1"))
    late = _semantic_html(first, closing_state(first))
    assert early.count('class="tree-node') == late.count('class="tree-node') == 15    # each call has its place
    assert early.count('class="tree-node is-waiting"') == 12                          # three are shown
    assert late.count('class="tree-node is-marked"') == 5 and "is-waiting" not in late
    assert "2 is worked out 3 times · 3 is worked out 2 times" in late


@pytest.mark.unit
def test_a_table_that_contradicts_the_lessons_own_numbers_is_sent_back():
    """What a live lesson did on 2026-10-11: it started the bottom stair at 0, so the table ended
    at 5 while its narration said eight ways."""
    wrong = _as_written("taught_stairs")
    wrong["trace"]["data"][0]["rule"]["start"] = [0, 1]                    # ways[0] = 0, not 1
    wrong["scenes"][0]["beats"][2]["move"]["expect"] = 0
    client = _Scripted([wrong, _as_written("taught_stairs")])
    reasons = []
    lesson = lesson_plan.generate("Counting the ways to climb stairs", SKILL, client=client,
                                  schema_version=2, on_reject=reasons.append)
    assert len(client.asked) == 2
    assert ("you expect cell 2 of 'ways' to hold 2, but its rule gives Ways[2] = 1 + 0 = 1. From "
            "the start values [0, 1] the table comes to [0, 1, 1, 2, 3, 5], counting cells from 0"
            in reasons[0])
    _, _, third = plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].beats[1].visual_anchors[-1] == "Ways[5] = 5 + 3 = 8"


@pytest.mark.unit
def test_a_total_the_lesson_states_is_checked_against_the_counter():
    answer = _as_written("taught_search")
    answer["scenes"][2]["beats"].append({
        "spoken_text": "Binary search needed three checks.",
        "move": {"do": "count", "counter": "fast", "expect": 3}})
    with pytest.raises(ValueError, match="you expect 'fast' to read 3, but it reads 2"):
        plan_trace_scenes(_lesson(answer), SKILL)
    silent = _as_written("taught_search")                    # the same move with no total stated
    silent["scenes"][2]["beats"].append({
        "spoken_text": "Binary search needed three checks.",
        "move": {"do": "count", "counter": "fast"}})
    with pytest.raises(ValidationError, match="counts by itself; say the total you expect"):
        _lesson(silent)


@pytest.mark.unit
def test_a_table_that_is_filled_in_must_start_empty():
    answer = _as_written("taught_search")
    answer["scenes"][2]["beats"].append({
        "spoken_text": "Write a one in the first box.",
        "move": {"do": "fill", "array": "numbers", "cell": 0, "value": 1}})
    with pytest.raises(ValueError, match='already holds 3; a table that is filled in starts empty'):
        plan_trace_scenes(_lesson(answer), SKILL)


@pytest.mark.unit
def test_a_table_with_no_rule_holds_the_numbers_it_is_given():
    answer = _as_written("taught_stairs")
    del answer["trace"]["data"][0]["rule"]
    for scene in answer["scenes"]:
        for beat in scene["beats"]:
            if beat["move"]["do"] == "fill":
                beat["move"]["value"] = beat["move"].pop("expect")
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert _steps(second, 1)[1:] == [
        ("set_state", ["ways"], {"lit_indices": [], "new_index": 2}),
        ("set_state", ["working"], {"expression": "Ways[2] = 2"}),
        ("set_state", ["ways"], {"items": [1, 1, 2, None, None, None]})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]


@pytest.mark.unit
def test_a_table_declared_one_cell_short_is_sized_to_the_cells_it_fills():
    answer = _as_written("taught_stairs")
    answer["trace"]["data"][0]["size"] = 5                                 # stairs 0 to 5 are six boxes
    lesson = _lesson(answer)                                               # accepted, not sent back
    assert lesson.trace.data[0].size == 6
    _, _, third = plan_trace_scenes(lesson, SKILL)
    answer = _as_written("taught_stairs")                                  # a cell far outside is still refused
    answer["scenes"][2]["beats"][1]["move"].update(cell=40)
    with pytest.raises(ValidationError, match="there is no cell 40"):
        _lesson(answer)


@pytest.mark.unit
def test_a_tree_and_a_table_do_not_share_the_screen():
    crowded = _as_written("taught_recursion")
    crowded["scenes"][1]["beats"].pop(0)                                   # the tree is never removed
    client = _Scripted([crowded, _as_written("taught_recursion")])
    reasons = []
    lesson_plan.generate("Why plain recursion repeats its work", SKILL, client=client,
                         schema_version=2, on_reject=reasons.append)
    assert len(client.asked) == 2
    assert ("has the tree 'calls' and the array 'ways' on screen together" in reasons[0]
            and '{"do":"remove","items":["calls"]}' in reasons[0])


@pytest.mark.unit
def test_an_item_taken_off_screen_comes_back_the_way_the_lesson_left_it():
    """A live lesson removed its call counter with the tree and pointed at it two scenes later:
    the replay had forgotten it, and the counter came back reading 0."""
    answer = _as_written("taught_recursion")
    answer["scenes"][1]["beats"].insert(1, {                                   # the counter is taken off
        "spoken_text": "Put the count of calls aside for now.", "move": {"do": "remove", "items": ["count"]}})
    answer["scenes"][2]["beats"].append({
        "spoken_text": "{count} calls, against six boxes.",
        "move": {"do": "count", "counter": "count", "expect": 15}})
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert [step for step in _steps(third, 1) if step[1] == ["count"]] == [
        ("set_state", ["count"], {"value": 15}), ("appear", ["count"], {})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["count"]["value"] == 15 and "count" in end.visible


@pytest.mark.unit
def test_a_counter_can_count_the_cells_of_a_table_as_they_are_filled():
    answer = _as_written("taught_stairs")
    answer["trace"]["data"].append({"id": "boxes", "kind": "counter", "label": "Boxes filled", "counts": "ways"})
    answer["scenes"][2]["beats"].append({
        "spoken_text": "{boxes} boxes, each filled once.",
        "move": {"do": "count", "counter": "boxes", "expect": 6}})
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["boxes"]["value"] == 6
    assert lesson.scenes[2].beats[3].visual_anchors == ["Boxes filled: 6"]


@pytest.mark.unit
def test_clearing_an_array_that_has_no_marks_yet_still_sends_its_pointer_away():
    answer = _as_written("taught_search")
    answer["scenes"][0]["beats"][1] = {                                   # the pointer only looks, no marks
        "spoken_text": "Start at the left.", "move": {"do": "look", "pointer": "scan", "index": 0}}
    lesson = _lesson(answer)
    _, second, _ = plan_trace_scenes(lesson, SKILL)                       # the validator accepts it
    assert _steps(second, 1)[0] == ("hide", ["scan"], {})                 # put away after the turning point
    answer["scenes"][1]["beats"][0] = {                                   # and by a clear move of its own
        "spoken_text": "Start again on clean data.", "move": {"do": "clear", "array": "numbers", "lines": [1]}}
    lesson = _lesson(answer)
    _, second, _ = plan_trace_scenes(lesson, SKILL)
    assert ("hide", ["scan"], {}) in _steps(second, 0)
    assert [evidence.object_ids for evidence in second.beats[0].evidence] == [["code", "numbers"]]


@pytest.mark.unit
def test_lines_written_beside_a_move_are_put_into_it():
    answer = _as_written("taught_search")
    beat = answer["scenes"][1]["beats"][1]
    beat["lines"] = beat["move"].pop("lines")
    lesson = _lesson(answer)
    assert lesson.scenes[1].beats[1].move.lines == [4]


@pytest.mark.unit
def test_a_lesson_with_a_playbook_gets_five_informed_tries():
    wrong = _as_written("taught_stairs")
    wrong["scenes"][0]["beats"][2]["move"]["expect"] = 0                   # the table will not agree
    client = _Scripted([wrong, wrong, wrong, wrong, _as_written("taught_stairs")])
    lesson = lesson_plan.generate("Counting the ways to climb stairs", SKILL, client=client, schema_version=2)
    assert len(client.asked) == 5 and lesson.trace is not None
    with pytest.raises(lesson_plan.LessonPlanError, match="invalid after 5 attempts"):
        lesson_plan.generate("Counting the ways to climb stairs", SKILL,
                             client=_Scripted([wrong] * 5), schema_version=2)


@pytest.mark.unit
def test_a_wrong_total_says_what_would_make_it_right():
    answer = _as_written("taught_recursion")
    answer["scenes"][0]["beats"][2]["move"]["depth"] = 3                   # one level short of the whole tree
    answer["scenes"][0]["beats"].insert(3, {
        "spoken_text": "Fifteen calls.", "move": {"do": "count", "counter": "count", "expect": 15}})
    with pytest.raises(ValueError, match=r"has 15 calls in all and 13 are shown: grow it fully"):
        plan_trace_scenes(_lesson(answer), SKILL)
    answer = _as_written("taught_recursion")
    answer["trace"]["data"][1].pop("counts")                               # a counter tied to nothing
    answer["scenes"][0]["beats"].insert(3, {
        "spoken_text": "Fifteen calls.", "move": {"do": "count", "counter": "count", "expect": 15}})
    with pytest.raises(ValueError, match='it counts nothing by itself: give it "counts"'):
        plan_trace_scenes(_lesson(answer), SKILL)


@pytest.mark.unit
def test_the_recursion_lesson_as_written_is_the_saved_lesson():
    lesson, again = _saved("taught_recursion"), _lesson(_as_written("taught_recursion"))
    plan_trace_scenes(again, SKILL)
    assert [[beat.model_dump() for beat in scene.beats] for scene in again.scenes] == [
        [beat.model_dump() for beat in scene.beats] for scene in lesson.scenes]


@pytest.mark.unit
def test_a_counter_belongs_to_one_attempt():
    """Live on 2026-10-11: one pointer and one counter served both attempts at a binary search,
    so the screen read "checks: 8" while the sentence said two checks, not six."""
    answer = _as_written("taught_search")
    for beat in answer["scenes"][1]["beats"] + answer["scenes"][2]["beats"]:
        if beat["move"].get("pointer") == "mid":
            beat["move"]["pointer"] = "scan"                # the second attempt reuses the first's pointer
    client = _Scripted([answer, _as_written("taught_search")])
    reasons = []
    lesson_plan.generate("Why binary search needs so few checks", SKILL, client=client,
                         schema_version=2, on_reject=reasons.append)
    assert ("'slow' counted the 6 made before 'numbers' was cleared, and would now read 7. A second "
            "attempt needs its own pointer and its own counter" in reasons[0])
    # with a pointer and a counter of its own, each attempt keeps its total
    first, second, third = plan_trace_scenes(_saved("taught_search"), SKILL)
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert (end.payloads["slow"]["value"], end.payloads["fast"]["value"]) == (6, 2)


@pytest.mark.unit
def test_a_take_takes_the_number_under_the_pointer_out_of_a_value():
    """Live on 2026-10-11: with no move for "take the biggest coin", a lesson acted it out with
    compare moves, which drew a cross on every coin, and named a coin it never took."""
    lesson = _saved("taught_coins")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert _steps(first, 1) == [                        # the sum first, then what is left
        ("move", ["take"], {"index": 2}), ("appear", ["take"], {}),
        ("set_state", ["working"], {"expression": "Left to make = 6 - 4 = 2"}),
        ("appear", ["working"], {}),
        ("set_state", ["left"], {"value": 2}),
        ("appear", ["used"], {}), ("increment", ["used"], {})]
    assert [beat.visual_anchors for beat in lesson.scenes[0].beats[1:4]] == [
        ["Left to make = 6 - 4 = 2", "Left to make: 2", "Coins used: 1"],
        ["Left to make = 2 - 1 = 1", "Left to make: 1", "Coins used: 2"],
        ["Left to make = 1 - 1 = 0", "Left to make: 0", "Coins used: 3"]]
    spent = closing_state(first)
    assert (spent.payloads["left"]["value"], spent.payloads["used"]["value"]) == (0, 3)
    assert not spent.payloads["coins"].get("checked_results")      # no ticks or crosses on the coins


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda move: move.update(expect=3),
     "you expect 'left' to read 3 after this take, but Left to make = 2 - 1 = 1"),
    (lambda move: move.update(index=1, expect=0), "3 does not fit, because only 2 is left in 'left'"),
])
def test_a_take_that_does_not_add_up_is_sent_back(change, message):
    answer = _as_written("taught_coins")
    change(answer["scenes"][0]["beats"][2]["move"])
    with pytest.raises(ValueError, match=message):
        plan_trace_scenes(_lesson(answer), SKILL)


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda move: move.pop("expect"), "a take move needs a pointer, the value its cell is taken out of"),
    (lambda move: move.update(out_of="coins"), "'coins' is not a value"),
    (lambda move: move.update(expect=[2]), "a take move expects one number, not a list"),
])
def test_a_take_follows_its_rules(change, message):
    answer = _as_written("taught_coins")
    change(answer["scenes"][0]["beats"][1]["move"])
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


def _numbered_from_one(answer: dict, array: str, pointers: tuple = ()) -> dict:
    """The same lesson with one array's cells numbered from 1, in the trace and in every move."""
    for item in answer["trace"]["data"]:
        if item["id"] == array:
            item["first"] = 1
    for scene in answer["scenes"]:
        for beat in scene["beats"]:
            move = beat["move"]
            if move.get("array") == array or move.get("pointer") in pointers:
                for key in ("cell", "index"):
                    if move.get(key) is not None:
                        move[key] += 1
                if move.get("cells"):
                    move["cells"] = [cell + 1 for cell in move["cells"]]
    return answer


@pytest.mark.unit
@pytest.mark.parametrize("name, array, pointers", [
    ("taught_search", "numbers", ("scan", "mid")), ("taught_stairs", "ways", ()),
])
def test_cells_numbered_from_one_are_the_same_picture_with_other_numbers(name, array, pointers):
    """Live on 2026-10-11: a lesson said "cell 1" to "cell 5" over a table numbered 0 to 4."""
    from generation.browser_scene import _semantic_html

    plain = plan_trace_scenes(_lesson(_as_written(name)), SKILL)
    lesson = _lesson(_numbered_from_one(_as_written(name), array, pointers))
    numbered = plan_trace_scenes(lesson, SKILL)
    assert {obj.id: obj for obj in numbered[0].objects}[array].payload["first"] == 1
    for ours, theirs in zip(numbered, plain):
        steps = lambda scene: [_steps(scene, number) for number in range(len(scene.beats))]
        if name == "taught_search":
            assert steps(ours) == steps(theirs)                 # the same cells, the same marks
    state = None
    for scene in numbered:
        state = closing_state(scene, state)
    html = _semantic_html(numbered[-1], state)
    length = lesson.trace.data[0].length
    assert f'<span class="semantic-index">{length}</span>' in html
    assert '<span class="semantic-index">0</span>' not in html
    if name == "taught_stairs":     # the working names a cell by the number shown under it
        assert lesson.scenes[2].beats[1].visual_anchors[-1] == "Ways[6] = 5 + 3 = 8"


@pytest.mark.unit
def test_a_cell_number_outside_a_numbered_array_and_a_wrong_one_say_how_it_is_numbered():
    answer = _numbered_from_one(_as_written("taught_stairs"), "ways")
    answer["scenes"][0]["beats"][2]["move"]["cell"] = 0
    with pytest.raises(ValidationError, match="'ways' has cells 1 to 6; there is no cell 0"):
        _lesson(answer)
    answer = _numbered_from_one(_as_written("taught_stairs"), "ways")
    answer["scenes"][1]["beats"][1]["move"]["expect"] = 3
    with pytest.raises(ValueError, match=r"you expect cell 3 of 'ways' to hold 3, but its rule gives "
                                         r"Ways\[3\] = 1 \+ 1 = 2.*counting cells from 1"):
        plan_trace_scenes(_lesson(answer), SKILL)
    short = _numbered_from_one(_as_written("taught_stairs"), "ways")
    short["trace"]["data"][0]["size"] = 4                   # stairs 1 to 6 are six boxes, not seven
    assert _lesson(short).trace.data[0].size == 6


@pytest.mark.unit
def test_item_ids_are_tidied_not_sent_back():
    """Live on 2026-10-11: a try was lost to an id written 'callCount'."""
    answer = _as_written("taught_recursion")
    answer["trace"]["data"][1]["id"] = "callCount"
    answer["trace"]["data"][0]["id"] = "Call-Tree"
    answer["trace"]["data"][1]["counts"] = "Call-Tree"
    for scene in answer["scenes"]:
        for beat in scene["beats"]:
            move = beat["move"]
            if move.get("tree") == "calls":
                move["tree"] = "Call-Tree"
            if move.get("items") == ["calls"]:
                move["items"] = ["Call-Tree"]
    answer["scenes"][2]["beats"].append({
        "spoken_text": "{callCount} calls, against six boxes.",
        "move": {"do": "count", "counter": "callCount", "expect": 15}})
    lesson = _lesson(answer)
    assert [item.id for item in lesson.trace.data] == ["call_tree", "callcount", "ways"]
    assert lesson.trace.data[1].counts == "call_tree"
    plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].beats[1].visual_anchors == ["Calls: 15"]


@pytest.mark.unit
def test_what_an_ask_beat_speaks_is_the_question_it_shows():
    """Live on 2026-10-11: a lesson spoke one question while the screen showed the brief's."""
    answer = _as_written("taught_stairs")
    answer["scenes"][0]["beats"][1]["spoken_text"] = "So what is the answer for five?"
    lesson = _lesson(answer)
    asked = lesson.scenes[0].beats[1]
    assert asked.spoken_text == asked.move.text == lesson.brief.question


@pytest.mark.unit
def test_a_run_of_fills_waits_until_the_rule_has_been_seen_to_work_once():
    """Live on 2026-10-11: a lesson filled a whole table in its first fill, in one sentence."""
    answer = _as_written("taught_stairs")
    answer["scenes"][0]["beats"][2:] = [{
        "spoken_text": "Fill every box from the bottom stair to the top one.",
        "move": {"do": "fill", "array": "ways", "cell": 5, "expect": 8, "lines": [6]}}]
    lesson = _lesson(answer)
    weak = craft_trace(lesson, plan_trace_scenes(lesson, SKILL))
    assert any("beat s1_b3 works out 4 cells of 'ways' in one sentence, before the viewer has seen "
               "its rule work once" in problem for problem in weak)
    answer = _as_written("taught_stairs")                   # the given cells together, then one, then a run
    answer["scenes"][0]["beats"][2:] = [{
        "spoken_text": "The bottom and the first stair each have one way.",
        "move": {"do": "fill", "array": "ways", "cells": [0, 1], "expect": [1, 1], "lines": [3, 4]}}]
    answer["scenes"][2]["beats"][0:2] = [{
        "spoken_text": "The same rule fills the rest: five ways, then eight.",
        "move": {"do": "fill", "array": "ways", "cells": [4, 5], "expect": [5, 8], "lines": [6]}}]
    lesson = _lesson(answer)
    # ... but the cell that answers the question is not one of a run
    assert craft_trace(lesson, plan_trace_scenes(lesson, SKILL)) == [
        "beat s3_b1 finishes 'ways' by filling 2 cells at once, so the cell that holds the answer is "
        "rushed; give the last cell a fill of its own, with a sentence that says which earlier cells "
        "it uses and why"]
    answer["scenes"][2]["beats"][0:1] = [
        {"spoken_text": "The same rule gives stair four: three plus two is five.",
         "move": {"do": "fill", "array": "ways", "cell": 4, "expect": 5, "lines": [6]}},
        {"spoken_text": "And the top stair uses the two below it: five plus three is eight.",
         "move": {"do": "fill", "array": "ways", "cell": 5, "expect": 8, "lines": [6]}}]
    lesson = _lesson(answer)
    assert craft_trace(lesson, plan_trace_scenes(lesson, SKILL)) == []


@pytest.mark.unit
def test_every_sentence_gets_a_breath_and_the_steps_of_a_beat_get_the_time_they_need():
    """Reviewed on 2026-10-12: sentences ran into one another at about 200 words a minute, and a
    whole table was filled in the 3.2 seconds it took to say so."""
    first, second, third = plan_trace_scenes(_saved("taught_coins"), SKILL)
    assert [beat.pause_after for beat in first.beats] == [0.4, 0.4, 0.4, 0.4, 0.9]
    assert [beat.pause_after for beat in third.beats] == [0.4, 0.4, 0.4, 4.0, 0.9]     # time to think
    # two cells worked out in one beat need twice the time of one; a line of code needs none
    assert [beat.min_seconds for beat in third.beats] == [3.6, 1.8, 0, 0, 0]
    assert [beat.min_seconds for beat in first.beats] == [0, 1.8, 1.8, 1.8, 0]         # each take
    run = third.beats[0]
    assert run.hold(2.0) == pytest.approx(1.6)      # a short sentence: the picture goes on in silence
    assert run.hold(6.0) == 0.4                     # a long one: only the breath
    search, *_ = plan_trace_scenes(_saved("taught_search"), SKILL)
    assert search.beats[1].min_seconds == pytest.approx(5.4)       # six checks, one after another


@pytest.mark.unit
def test_a_closing_scene_shows_its_takeaway_and_then_gives_way_to_the_check_question():
    """Reviewed on 2026-10-12: the last scene's takeaway was in no frame of any of four videos."""
    lesson = _saved("taught_stairs")
    *_, third = plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].takeaway == "Eight ways, and no route was listed"
    assert _steps(third, 2)[-1] == ("appear", ["takeaway_s3"], {})
    assert _steps(third, 3)[-2:] == [("hide", ["takeaway_s3"], {}), ("appear", ["s3_b4_line"], {})]
    assert "takeaway_s3" not in third.closing_visible_ids      # two lines under the picture, not three


@pytest.mark.unit
def test_what_a_finished_attempt_left_behind_goes_when_a_table_starts():
    """Reviewed on 2026-10-12: crossed-out coins, a pointer and a counter of the first attempt sat
    beside the table for thirty seconds, because the lesson never cleared them."""
    answer = _as_written("taught_coins")
    answer["scenes"][1]["beats"].pop(0)                     # no turning point and no clear move
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert all(kind != "hide" for kind, _, _ in _steps(second, 0))     # showing the table is not yet it
    assert _steps(second, 1)[0] == ("hide", ["take", "left", "working"], {})   # its first fill is
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert not {"take", "left"} & end.visible and "used" in end.visible     # the cost stays to compare
    # a lesson that comes back to the pointer keeps it
    answer = _as_written("taught_coins")
    answer["scenes"][1]["beats"].pop(0)
    answer["scenes"][2]["beats"].insert(2, {
        "spoken_text": "Look again at the three coin.", "move": {"do": "look", "pointer": "take", "index": 1}})
    _, second, _ = plan_trace_scenes(_lesson(answer), SKILL)
    assert all(kind != "hide" for beat in range(len(second.beats)) for kind, _, _ in _steps(second, beat))


@pytest.mark.unit
def test_a_count_puts_every_total_on_screen():
    """Reviewed on 2026-10-12: "five cells, not fifteen calls" was said with the fifteen gone
    from the screen twenty seconds earlier."""
    answer = _as_written("taught_recursion")
    answer["trace"]["data"].append({"id": "boxes", "kind": "counter", "label": "Boxes filled", "counts": "ways"})
    answer["scenes"][1]["beats"].insert(1, {                                   # the call counter is taken off
        "spoken_text": "Put the count of calls aside for now.", "move": {"do": "remove", "items": ["count"]}})
    answer["scenes"][2]["beats"].append({
        "spoken_text": "{boxes} boxes, where plain recursion made {count} calls.",
        "move": {"do": "count", "counter": "boxes", "expect": 6}})
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert [step for step in _steps(third, 1) if step[1] == ["count"]] == [
        ("set_state", ["count"], {"value": 15}), ("appear", ["count"], {})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert {"count", "boxes"} <= end.visible
    assert (end.payloads["count"]["value"], end.payloads["boxes"]["value"]) == (15, 6)


@pytest.mark.unit
def test_an_item_that_has_left_for_good_gives_up_its_room():
    """Reviewed on 2026-10-12: the table was drawn at about 60% size beside a hole, because the
    scene still kept room for the tree it had removed in its first beat."""
    from generation.browser_scene import animation_html

    from core.visual_state import opening_state

    first, second, _ = plan_trace_scenes(_saved("taught_recursion"), SKILL)
    state = opening_state(second, closing_state(first))
    holds_tree = lambda page: 'data-object-id=\\"calls\\"' in page
    from core.visual_state import apply_action
    for action in second.beats[0].actions:                  # the turning point, said over the tree
        apply_action(state, action)
    leaving = animation_html(second, second.beats[1], title="t", opening=state, duration=3.0)
    assert holds_tree(leaving)                              # the beat in which the tree leaves
    for action in second.beats[1].actions:
        apply_action(state, action)
    after = animation_html(second, second.beats[2], title="t", opening=state, duration=3.0)
    assert not holds_tree(after) and 'data-object-id=\\"ways\\"' in after


@pytest.mark.unit
def test_a_repair_is_sent_with_the_facts_and_told_to_change_one_thing():
    """Reviewed on 2026-10-12: in four lessons of four the worst fault was made or sealed by a
    retry. A bare reason invited the model to change the checked number, or add a step so a count
    came out, and leave the sentence wrong."""
    wrong = _as_written("taught_recursion")
    wrong["scenes"][1]["beats"][3]["move"]["expect"] = 3            # the table says 2
    client = _Scripted([wrong, wrong, _as_written("taught_recursion")])
    lesson_plan.generate("Why plain recursion repeats its work", SKILL, client=client, schema_version=2)
    repair = client.asked[1][-1]["content"]
    assert repair.startswith("That was invalid (beat s2_b4: you expect cell 2 of 'ways' to hold 3")
    assert "Do not make this pass by changing the number alone" in repair
    assert ("Change what this names and nothing else: return the whole plan with every other beat "
            "exactly as it was" in repair)
    assert ("Worked out from your trace: the tree 'calls' makes 15 calls in all, and 3 is worked out "
            "2 times, 2 is worked out 3 times, 1 is worked out 5 times, 0 is worked out 3 times; in "
            "the table 'ways' cell 0 holds 1, cell 1 holds 1, cell 2 holds 2, cell 3 holds 3, cell 4 "
            "holds 5, cell 5 holds 8." in repair)
    # only the latest answer goes back with it, not every earlier one
    assert [message["role"] for message in client.asked[2]] == ["system", "user", "assistant", "user"]


@pytest.mark.unit
def test_bookkeeping_a_model_gets_wrong_is_done_for_it_and_a_cell_holds_what_fits():
    answer = _as_written("taught_stairs")
    fill = answer["scenes"][0]["beats"][2]["move"]
    fill["index"] = fill.pop("cell")                            # the other moves say "index"
    for scene in answer["scenes"]:                              # and every beat is written flat
        scene["beats"] = [{**beat.pop("move"), **beat} for beat in scene["beats"]]
    answer["scenes"][0]["beats"][0]["why"] = "the boxes must be named before they are filled"
    lesson = _lesson(answer)
    assert lesson.scenes[0].beats[2].move.cell == 0
    assert lesson.scenes[0].beats[0].why.startswith("the boxes")       # kept, never shown or spoken
    trace = _as_written("taught_search")["trace"]
    trace["data"][0]["items"] = ["1+1+1+1", "1+1+2", "2+2"]            # a tiny case worked by hand
    LessonTrace.model_validate(trace)
    trace["data"][0]["items"] = ["one plus one", "two"]
    with pytest.raises(ValidationError, match="does not fit in a cell; an item is at most seven"):
        LessonTrace.model_validate(trace)


def _stairs_with_its_routes() -> dict:
    """The stairs lesson with every route up five stairs listed, and split after the turning
    point into the routes that end in a one-step and the routes that end in a two-step."""
    answer = _as_written("taught_stairs")
    answer["trace"]["data"].insert(0, {"id": "routes", "kind": "array", "label": "Routes up 5 stairs",
                                       "items": ["11111", "1112", "1121", "1211", "2111", "122", "212", "221"]})
    answer["scenes"][0]["beats"].insert(0, {
        "spoken_text": "Each box is one route up five stairs, written as its steps.",
        "move": {"do": "show", "items": ["routes"]}})
    answer["scenes"][1]["beats"][1:1] = [
        {"spoken_text": "Five of the routes finish with a single step, so each is a route up four stairs.",
         "move": {"do": "group", "array": "routes", "cells": [0, 2, 3, 4, 7], "text": "end in a 1-step"}},
        {"spoken_text": "The other three finish with a double step, so each is a route up three stairs.",
         "move": {"do": "group", "array": "routes", "cells": [1, 5, 6], "text": "end in a 2-step"}}]
    return answer


@pytest.mark.unit
def test_a_group_move_shows_which_cases_belong_together():
    """Reviewed on 2026-10-12: "because the last step is 1 or 2" was said and never shown, with
    the list of routes on screen the whole time. Grouping the list is how the reason is seen."""
    from generation.browser_scene import _semantic_html

    lesson = _lesson(_stairs_with_its_routes())
    first, second, third = plan_trace_scenes(lesson, SKILL)
    assert _steps(second, 1) == [("set_state", ["routes"], {
        "groups": [{"label": "end in a 1-step", "cells": [0, 2, 3, 4, 7]}]})]
    assert lesson.scenes[1].beats[1].visual_anchors == ["end in a 1-step: 5"]
    assert lesson.scenes[1].beats[2].visual_anchors == ["end in a 2-step: 3"]
    assert lesson.scenes[1].beats[1].claim_requirements == {"s2_b2_c": ["state_change"]}
    state = closing_state(second, closing_state(first))
    html = _semantic_html(second, state)
    assert "end in a 1-step: 5" in html and "end in a 2-step: 3" in html
    assert html.count("in-group group-0") == 5 and html.count("in-group group-1") == 3
    assert craft_trace(lesson, [first, second, third]) == []
    nameless = _stairs_with_its_routes()
    nameless["scenes"][1]["beats"][1]["move"].pop("text")
    with pytest.raises(ValidationError, match="a group move needs an array, the cells that belong together"):
        _lesson(nameless)


@pytest.mark.unit
def test_a_number_in_a_sentence_is_read_off_the_picture():
    """Reviewed on 2026-10-12: the screen read "checks: 8" while the voice said two. A sentence
    now names what it means, and code says the number, so the voice cannot disagree with the screen."""
    answer = _as_written("taught_search")
    answer["scenes"][2]["beats"][1]["spoken_text"] = (
        "Found in {fast} checks, where one by one took {slow}; the last cell checked held {mid}.")
    lesson = _lesson(answer)
    plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].beats[1].spoken_text == (
        "Found in 2 checks, where one by one took 6; the last cell checked held 30.")
    table = _as_written("taught_stairs")
    table["scenes"][2]["beats"][1]["spoken_text"] = "The top stair holds {ways[5]}: {ways[4]} plus {ways[3]}."
    lesson = _lesson(table)
    plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[2].beats[1].spoken_text == "The top stair holds 8: 5 plus 3."
    early = _as_written("taught_stairs")
    early["scenes"][0]["beats"][0]["spoken_text"] = "The top box will hold {ways[5]}."
    with pytest.raises(ValueError, match=r"says \{ways\[5\]\}, but that cell holds nothing yet"):
        plan_trace_scenes(_lesson(early), SKILL)
    unknown = _as_written("taught_search")
    unknown["scenes"][2]["beats"][1]["spoken_text"] = "Found in {total} checks."
    with pytest.raises(ValueError, match=r"names \{total\}, which is not an item of the trace"):
        plan_trace_scenes(_lesson(unknown), SKILL)
    silent = _as_written("taught_search")
    silent["scenes"][2]["beats"].append({
        "spoken_text": "Binary search needed far fewer checks.",
        "move": {"do": "count", "counter": "fast", "expect": 2}})
    with pytest.raises(ValueError, match=r"does not say the total it points at. Write the number as \{fast\}"):
        plan_trace_scenes(_lesson(silent), SKILL)
