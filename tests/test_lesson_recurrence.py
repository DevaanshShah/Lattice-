"""A recurrence-table lesson planned in steps: a model describes the teaching and the table, code
builds every step, and a model writes one sentence a step. No model writes a move."""
import copy
import json

import pytest
from pydantic import ValidationError

from planner import lesson_recurrence
from planner.lesson_plan import LessonPlanError
from planner.lesson_recurrence import ConceptSpec, build_run
from planner.lesson_shared import story_shape
from planner.product_recipe import load_recipes

SKILL = load_recipes()["algorithm_explainer"]
CONCEPT = {
    "brief": {
        "learner": "A beginner who knows loops and lists.",
        "can_do": "Explain why the ways to climb n stairs are the ways for the two stairs below, added.",
        "question": "How can we count every way up the stairs without listing them all?",
        "problem": "Climb 5 stairs, taking 1 or 2 stairs at a time.",
        "naive_attempt": "List every route by hand; the list soon grows too long to trust.",
        "turning_point": "Because every route ends in a 1-step or a 2-step, it extends a route to one of the two stairs below.",
        "check_question": "Stair 5 has 8 ways and stair 6 has 13. How many ways reach stair 7?",
        "check_answer": "Twenty-one: 13 plus 8.",
    },
    "spec": {
        "table": {"label": "Ways", "unit": "stairs", "first": 0, "size": 6, "start": [1, 1],
                  "back": [1, 2], "op": "sum", "plus": 0},
        "cases": {"label": "Routes up 5 stairs",
                  "items": ["1+1+1+1+1", "1+1+1+2", "1+1+2+1", "1+2+1+1", "2+1+1+1", "1+2+2", "2+1+2", "2+2+1"],
                  "groups": [{"name": "end in a 1-step", "ends": "+1"},
                             {"name": "end in a 2-step", "ends": "+2"}]},
        "name": "dynamic programming",
    },
}


class _Scripted:
    def __init__(self, answers):
        self.answers, self.asked = [json.dumps(answer) for answer in answers], []

    def chat(self, messages, **_):
        self.asked.append(list(messages))
        return self.answers.pop(0)


def _narration(count: int) -> dict:
    return {"scenes": [{"title": f"Part {n}", "takeaway": f"Point {n}"} for n in range(1, 5)],
            "sentences": [f"Sentence {n} explains its step." for n in range(1, count + 1)]}


@pytest.mark.unit
def test_code_builds_the_whole_run_and_no_model_writes_a_move():
    concept = ConceptSpec.model_validate(CONCEPT)
    lesson, shown = build_run(concept)
    assert len(shown) == 12
    client = _Scripted([CONCEPT, _narration(len(shown))])
    plan = lesson_recurrence.generate("Counting the ways to climb stairs", SKILL, client=client)
    assert len(client.asked) == 2                                   # two small calls, no repair
    assert story_shape(plan) == ("show ask reveal | turn group group | show fill fill | "
                                 "fill fill show ask answer")
    assert plan.scenes[1].beats[0].spoken_text == CONCEPT["brief"]["turning_point"]
    assert plan.scenes[1].beats[1].visual_anchors == ["end in a 1-step: 5"]
    assert plan.scenes[3].beats[1].visual_anchors[-1] == "Ways[5] = 5 + 3 = 8"
    # the narration step is shown the numbers; it is never asked to work one out
    steps = client.asked[1][1]["content"]
    assert "Ways[5] = 5 + 3 = 8" in steps and "It matches the 8 cases listed at the start" in steps


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda c: c["spec"]["cases"]["items"].pop(), "holds 8, but 7 cases are listed"),
    (lambda c: c["spec"]["table"].update(start=[1, 2]), r"holds 13, but 8 cases are listed.*fix its \"start\""),
    (lambda c: c["spec"]["cases"]["groups"][0].update(ends="2"), "must end like exactly one group"),
    (lambda c: c["spec"]["cases"]["items"].__setitem__(7, "2+1+2"),
     r"hold \[5, 3\], so the groups have \[3, 5\] cases; yours have \[4, 4\]"),
    (lambda c: c["spec"]["cases"]["items"].__setitem__(0, "one+one+one"), "does not fit in a box"),
])
def test_the_description_of_the_table_is_checked_against_itself(change, message):
    """What made single-call lessons fail was numbers a model could not check. Here the table's
    answer, the number of cases and the size of each group must agree, and code can check that."""
    concept = copy.deepcopy(CONCEPT)
    change(concept)
    with pytest.raises(ValidationError, match=message):
        ConceptSpec.model_validate(concept)


@pytest.mark.unit
def test_a_faulty_step_is_repaired_with_its_reason_and_a_hopeless_one_stops():
    wrong = copy.deepcopy(CONCEPT)
    wrong["spec"]["table"]["start"] = [1, 2]
    concept = ConceptSpec.model_validate(CONCEPT)
    steps = len(build_run(concept)[1])
    client = _Scripted([wrong, CONCEPT, _narration(steps - 1), _narration(steps)])
    lesson_recurrence.generate("Counting the ways to climb stairs", SKILL, client=client)
    assert "cell 5 holds 13" in client.asked[1][-1]["content"]          # the facts go back with the fault
    assert f"give exactly {steps} sentences" in client.asked[3][-1]["content"]
    with pytest.raises(LessonPlanError, match="failed after 3 attempts"):
        lesson_recurrence.generate("Stairs", SKILL, client=_Scripted([wrong] * 3))


@pytest.mark.unit
def test_code_decides_which_cases_are_in_a_group():
    """Reviewed on 2026-10-12: groups of the right sizes held the wrong routes ("1+1+1+2" among
    those that end in a 1-step). A model now says how a group ends, and code finds its cases."""
    concept = ConceptSpec.model_validate(CONCEPT)
    one, two = concept.spec.cases.groups
    items = concept.spec.cases.items
    assert [items[cell] for cell in one.cells] == ["1+1+1+1+1", "1+1+2+1", "1+2+1+1", "2+1+1+1", "2+2+1"]
    assert [items[cell] for cell in two.cells] == ["1+1+1+2", "1+2+2", "2+1+2"]
    given = copy.deepcopy(CONCEPT)
    given["spec"]["cases"]["groups"][0]["cells"] = [1, 5, 6]        # what a model says is overruled
    assert ConceptSpec.model_validate(given).spec.cases.groups[0].cells == one.cells


@pytest.mark.unit
def test_the_cases_are_held_back_until_the_question_has_been_asked():
    """Reviewed on 2026-10-12: in three lessons of three every case was on screen at second 0, so
    the answer was given before the question. Two examples show; the rest come after the question."""
    from core.visual_state import closing_state, opening_state
    from generation.browser_scene import _semantic_html
    from planner.lesson_trace import plan_trace_scenes

    client = _Scripted([CONCEPT, _narration(12)])
    plan = lesson_recurrence.generate("Counting the ways to climb stairs", SKILL, client=client)
    first = plan_trace_scenes(plan, SKILL)[0]
    cases = {obj.id: obj for obj in first.objects}["cases"]
    assert cases.payload["veiled"] == [2, 3, 4, 5, 6, 7]
    state = opening_state(first, None)
    from core.visual_state import apply_action
    for beat in first.beats[:2]:                    # shown, then asked: still held back
        for action in beat.actions:
            apply_action(state, action)
    html = _semantic_html(first, state)
    assert html.count("is-veiled") == 6 and "1+1+2+1" not in html
    assert (first.beats[2].actions[0].kind, first.beats[2].actions[0].params) == ("set_state", {"veiled": []})
    assert "1+1+2+1" in _semantic_html(first, closing_state(first))


class _Jev:
    """A stand-in for Jev's answers: each request is recorded and answered from a function."""
    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def __call__(self, request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        self.requests.append(body)
        answers = {name: {"noul": self.answer(name, body)} for name in body["questions"]}
        reply = json.dumps({"answers": answers}).encode("utf-8")
        return type("Reply", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False,
                                  "read": lambda s: reply})()


@pytest.fixture
def jev(monkeypatch):
    from core.config import settings
    from planner import jev_gates
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_api_key", "test")

    def install(answer):
        judge = _Jev(answer)
        monkeypatch.setattr(jev_gates, "urlopen", judge)
        return judge
    return install


@pytest.mark.unit
def test_a_sentence_judged_weak_is_rewritten_once(jev, monkeypatch):
    """Measured on 2026-10-15 against known-bad copies of real sentences, Jev caught most wrong
    numbers and removed reasons. A sentence it judges weak goes back once to be rewritten."""
    from planner import jev_gates
    steps = len(build_run(ConceptSpec.model_validate(CONCEPT))[1])
    first, second = _narration(steps), _narration(steps)
    second["sentences"][4] = "Rewritten with its reason."
    jev(lambda name, body: 0.1 if name == "supported_5" and
        not any("Rewritten" in step["sentence"] for step in body["state"]["steps"]) else 0.9)
    client = _Scripted([CONCEPT, first, second])
    plan = lesson_recurrence.generate("Counting the ways to climb stairs", SKILL, client=client)
    assert "Rewrite only these: sentence(s) [5] say something their step does not show" in client.asked[2][-1]["content"]
    assert plan.scenes[1].beats[1].spoken_text == "Rewritten with its reason."


@pytest.mark.unit
def test_the_judge_never_stops_a_lesson(jev, monkeypatch):
    from planner import jev_gates
    jev(lambda name, body: 0.1 if name.startswith("supported") else 0.9)      # every sentence weak, twice
    steps = len(build_run(ConceptSpec.model_validate(CONCEPT))[1])
    client = _Scripted([CONCEPT, _narration(steps), _narration(steps)])
    plan = lesson_recurrence.generate("Counting the ways to climb stairs", SKILL, client=client)
    assert len(client.asked) == 3 and plan.scenes[0].beats[0].spoken_text == "Sentence 1 explains its step."


@pytest.mark.unit
def test_an_instance_that_is_not_the_topics_goes_back(jev, monkeypatch):
    from planner import jev_gates
    seen = {"asked": 0}

    def answer(name, body):
        if name == "same":
            seen["asked"] += 1
            return 0.05 if seen["asked"] == 1 else 0.95
        return 0.9
    jev(answer)
    steps = len(build_run(ConceptSpec.model_validate(CONCEPT))[1])
    client = _Scripted([CONCEPT, CONCEPT, _narration(steps)])
    lesson_recurrence.generate("Counting the ways to climb 7 stairs", SKILL, client=client)
    assert "not the one the topic asks about" in client.asked[1][-1]["content"]


@pytest.mark.unit
def test_the_reason_is_shown_not_only_said():
    """Reviewed on 2026-10-15: "removing the last step leaves a route up 4 stairs" was said and
    nothing on screen did it, and the groups were never tied to the table. Now each case of a group
    is drawn with its last step struck through, and the cells the answer adds take the colours of
    the groups they stand for."""
    from core.visual_state import closing_state
    from generation.browser_scene import _semantic_html
    from planner.lesson_trace import plan_trace_scenes

    steps = len(build_run(ConceptSpec.model_validate(CONCEPT))[1])
    plan = lesson_recurrence.generate("stairs", SKILL, client=_Scripted([CONCEPT, _narration(steps)]))
    scenes = plan_trace_scenes(plan, SKILL)
    state = None
    for scene in scenes[:2]:
        state = closing_state(scene, state)
    grouped = _semantic_html(scenes[1], state)
    assert '1+1+2<s class="peel">+1</s>' in grouped and '1+2<s class="peel">+2</s>' in grouped
    assert plan.scenes[3].beats[1].move.match == ["end in a 1-step", "end in a 2-step"]
    for scene in scenes[2:]:
        state = closing_state(scene, state)
    assert state.payloads["table"]["tints"] == {"4": 0, "3": 1}      # box 4 = 5 routes, box 3 = 3 routes


@pytest.mark.unit
def test_the_cost_of_listing_is_shown_on_a_bigger_instance_and_cases_carry_no_numbers():
    """Reviewed on 2026-10-15: listing 8 routes was quick, so its cost was only claimed; and the
    routes' position numbers clashed with the table's stair numbers below them."""
    from planner.lesson_recurrence import bigger_instance

    concept = ConceptSpec.model_validate(CONCEPT)
    assert bigger_instance(concept.spec.table) == (20, 10946)      # routes up 20 stairs, worked out
    lesson, steps = build_run(concept)
    costs = {item["id"]: item for item in lesson["trace"]["data"] if item["kind"] == "value"}
    assert (costs["list_cost"]["label"], costs["list_cost"]["value"]) == ("Cases for 20 stairs", 10946)
    assert (costs["table_cost"]["label"], costs["table_cost"]["value"]) == ("Boxes for 20 stairs", 21)
    assert "10946 cases to list against 21 boxes" in steps[-1]["the sentence must"]
    cases = next(item for item in lesson["trace"]["data"] if item["id"] == "cases")
    assert cases["numbered"] is False
    fewest = concept.spec.table.model_copy(update={"op": "min", "plus": 1})
    assert bigger_instance(fewest) is None                          # not a count of cases
