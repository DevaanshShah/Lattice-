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
from planner.lesson_trace import craft_trace, fill_trace_lesson, plan_trace_scenes
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
                                   if value not in (None, [], 0, 1) or key in ("index", "cell", "value")
                                   and value is not None}}
                         for beat in scene["beats"]]}
              for scene in lesson["scenes"]]
    scenes[-1]["beats"] = scenes[-1]["beats"][:-2]
    for scene in scenes:
        for beat in scene["beats"]:
            if beat["move"]["do"] == "ask":
                beat["move"] = {"do": "ask"}
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
@pytest.mark.parametrize("name", ["taught_search", "taught_stairs"])
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
    lesson = _saved("taught_search")
    first, second, _ = plan_trace_scenes(lesson, SKILL)
    assert _steps(second, 0) == [
        ("appear", ["code"], {}), ("set_state", ["code"], {"active_lines": [1]}),
        ("set_state", ["numbers"], {"checked_results": {}}), ("hide", ["scan"], {})]
    assert lesson.scenes[1].beats[0].claim_requirements == {"s2_b1_c": ["state_change"]}
    # the pointer of the second attempt arrives already on its cell
    assert _steps(second, 1) == [("set_state", ["code"], {"active_lines": [4]}),
                                 ("move", ["mid"], {"index": 3}), ("appear", ["mid"], {})]
    assert lesson.scenes[1].beats[1].visual_anchors == ["mid = (low + high) // 2", "mid: 17"]
    assert lesson.scenes[1].beats[3].visual_anchors == ["if items[mid] < target:", "discard [3,8,12,17]"]


@pytest.mark.unit
def test_a_table_is_filled_by_code_from_the_cells_it_names():
    lesson = _saved("taught_stairs")
    first, second, third = plan_trace_scenes(lesson, SKILL)
    table = {obj.id: obj for obj in first.objects}["ways"]
    assert table.payload["items"] == [None] * 6                           # it starts empty
    assert _steps(second, 0) == [
        ("set_state", ["code"], {"active_lines": [6]}),
        ("set_state", ["ways"], {"items": [1, 1, 2, None, None, None], "lit_indices": [1, 0],
                                 "new_index": 2}),
        ("set_state", ["working"], {"expression": "Ways[2] = 1 + 1 = 2"})]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]
    assert end.payloads["working"]["expression"] == "Ways[5] = 5 + 3 = 8"
    assert [anchors[-1] for anchors in (beat.visual_anchors for beat in lesson.scenes[2].beats[:2])] == [
        "Ways[4] = 3 + 2 = 5", "Ways[5] = 5 + 3 = 8"]


@pytest.mark.unit
def test_other_ways_of_working_out_a_cell_and_a_cell_read_too_early():
    answer = _as_written("taught_stairs")
    answer["scenes"][1]["beats"][0]["move"] = {
        "do": "fill", "array": "ways", "cell": 2, "from_cells": [0, 1], "op": "min", "plus": 1}
    lesson = _lesson(answer)
    plan_trace_scenes(lesson, SKILL)
    assert lesson.scenes[1].beats[0].visual_anchors == ["Ways[2] = min(1, 1) + 1 = 2"]
    early = _as_written("taught_stairs")
    early["scenes"][1]["beats"][0]["move"]["from_cells"] = [1, 4]
    with pytest.raises(ValueError, match=r"worked out from cells \[4\], which are still empty"):
        plan_trace_scenes(_lesson(early), SKILL)


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
    for expected in ("never puts the learner's question on screen", "['spare'] are in the trace",
                     "the code is never lit"):
        assert expected in reasons[1]
    # the visual step then makes no call at all
    plan = browser_visual_plan.generate(lesson, SKILL, client=_Scripted([]), schema_version=2)
    validate(lesson, plan, SKILL)
    assert story_shape(lesson) == "show ask fill fill | fill fill | fill fill run ask answer"


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
     "one of the two"),
    (lambda a: a["scenes"][1]["beats"][1].update(
        move={"do": "fill", "array": "numbers", "cell": 1, "from_cells": [0]}), '"op"'),
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
    (lambda t: t["data"][4].update(counts="numbers"), "which is not a pointer"),
    (lambda t: t["data"][1].update(items=[1, 2]), "a value has no items"),
    (lambda t: t["code"].update(source="x = 1\n" * 15), "at most 14 lines"),
    (lambda t: t["data"].__setitem__(0, {"id": "target", "kind": "value", "label": "T", "value": 1}),
     "unique"),
    (lambda t: t["data"][5].update(label="one by one"), "share the label 'one by one'"),
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
        "move": {"do": "fill", "array": "ways", "cells": [4, 5], "back": [1, 2], "op": "sum", "lines": [6]}}]
    lesson = _lesson(answer)
    first, second, third = plan_trace_scenes(lesson, SKILL)
    run = _steps(third, 0)
    assert [params.get("new_index") for kind, _, params in run if "items" in params] == [4, 5]
    assert [params["expression"] for kind, _, params in run if "expression" in params] == [
        "Ways[4] = 3 + 2 = 5", "Ways[5] = 5 + 3 = 8"]
    end = closing_state(third, closing_state(second, closing_state(first)))
    assert end.payloads["ways"]["items"] == [1, 1, 2, 3, 5, 8]
    assert lesson.scenes[2].beats[0].visual_anchors[-1] == "Ways[5] = 5 + 3 = 8"


@pytest.mark.unit
@pytest.mark.parametrize("move, message", [
    ({"do": "fill", "array": "ways", "cells": [4, 5], "back": [1, 2], "op": "sum", "value": 3},
     'takes "back" and "op" only'),
    ({"do": "fill", "array": "ways", "cells": [4, 5], "op": "sum"}, "how far back each one"),
    ({"do": "fill", "array": "ways", "cell": 4, "back": [1, 2], "op": "sum"}, '"back" belongs to a fill move over several'),
    ({"do": "fill", "array": "ways", "cells": [1, 2], "back": [1, 2], "op": "sum"}, "has no cell 2 before it"),
])
def test_a_run_of_fills_follows_its_rules(move, message):
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
    client = _Scripted([_as_written("taught_search")])
    lesson_plan.generate("Why binary search needs so few checks", SKILL, client=client,
                         schema_version=2, target_seconds=45)
    # 126 words at 13 words a beat is ten beats, two of which code adds
    assert "is about 126 words, between 88 and 164" in client.asked[0][1]["content"]
    assert "Write about 8 beats, in 2 scenes" in client.asked[0][1]["content"]


@pytest.mark.unit
def test_a_counter_that_counts_by_itself_is_not_bumped_by_hand():
    answer = _as_written("taught_search")
    answer["scenes"][0]["beats"].insert(2, {
        "spoken_text": "That took six checks.", "move": {"do": "count", "counter": "slow"}})
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
