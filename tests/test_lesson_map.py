"""A map lesson: the model writes narration and one move per beat; code compiles the visuals."""
import copy
import json
import typing

import pytest
from pydantic import ValidationError

from core.schemas.lesson_plan import LessonMap, LessonPlan, MapTone
from core.visual_assets import asset_inventory
from core.visual_state import TONES, closing_state
from planner import browser_visual_plan, lesson_plan
from planner.lesson_map import fill_map_lesson, lesson_map_problems, plan_map_scenes
from planner.product_recipe import load_recipes
from verification.visual_plan_validation import VisualPlanValidationError, validate

PIECES = [
    {"id": "phone", "label": "Customer app", "icon": "smartphone", "tone": "pink"},
    {"id": "gateway", "label": "Gateway", "icon": "split", "tone": "purple"},
    {"id": "service", "label": "Order service", "icon": "server", "tone": "blue", "count": 2},
    {"id": "cache", "label": "Cache", "icon": "zap", "tone": "yellow"},
    {"id": "store", "label": "Order records", "kind": "panel", "tone": "teal"},
    {"id": "db", "label": "Database", "icon": "database", "tone": "teal", "panel": "store"},
    {"id": "load", "label": "Load", "kind": "meter", "value": 40, "tone": "teal", "panel": "store"},
    {"id": "copy", "label": "Copy", "icon": "database", "tone": "purple", "panel": "store",
     "planned": True},
]
ARROWS = [{"source": "phone", "target": "gateway", "label": "order"},
          {"source": "gateway", "target": "service"},
          {"source": "service", "target": "cache", "label": "check"},
          {"source": "service", "target": "db", "label": "save"},
          {"source": "db", "target": "copy"}]
SAY = "These are seventeen plain words that stand in for one sentence of narration in a test lesson."
ASK = "Why would every single order from every customer in a city end up in just one place?"
BRIEF = {
    "learner": "A new developer who has used apps but never built a backend.",
    "can_do": "Explain why one database becomes the weak point and what a copy changes.",
    "question": "Why can't every order just go straight into one database?",
    "problem": "A delivery app on a Friday night, with thousands of orders in ten minutes.",
    "naive_attempt": "Send every order to the one database; it works until they all arrive at once.",
    "turning_point": "A second copy shares the work, so no single store has to take it all.",
    "check_question": "What happens to the load on the first database once the copy exists?",
    "check_answer": "It falls, because the copy takes part of the work.",
}


def _answer() -> dict:
    """A lesson exactly as the model is asked to write it: narration and a move per beat."""
    return {
        "learning_objective": "Follow an order and see why the database gets a copy.",
        "brief": dict(BRIEF),
        "map": {"pieces": copy.deepcopy(PIECES), "arrows": copy.deepcopy(ARROWS)},
        "scenes": [
            {"title": "An order", "learning_goal": "Follow it.",
             "takeaway": "Every order ends in one database",
             "beats": [
                 {"spoken_text": ASK, "move": {"do": "introduce", "pieces": ["phone", "gateway", "service"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["phone", "gateway", "service"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["service", "db"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["db", "service", "gateway", "phone"]}},
                 {"spoken_text": BRIEF["question"], "move": {"do": "ask"}},
             ]},
            {"title": "Too many orders", "learning_goal": "See the overload and the fix.",
             "beats": [
                 {"spoken_text": SAY, "move": {"do": "trouble", "pieces": ["db"], "meter": "load",
                                               "value": 95, "path": ["phone", "gateway", "service", "db"],
                                               "count": 4}},
                 {"spoken_text": SAY, "move": {"do": "fix", "pieces": ["copy", "db"], "meter": "load",
                                               "value": 50}},
                 {"spoken_text": SAY, "move": {"do": "point", "pieces": ["cache"]}},
             ]},
        ]}


def _lesson(answer: dict | None = None) -> LessonPlan:
    data = fill_map_lesson(answer or _answer())
    return LessonPlan.model_validate({**data, "schema_version": 2, "topic": "An order's journey",
                                      "skill_id": "workflow_explainer"})


SKILL = load_recipes()["workflow_explainer"]


class _Scripted:
    """Answers the planner's calls from a list and keeps what it was asked."""

    def __init__(self, answers):
        self.answers, self.asked = [json.dumps(answer) for answer in answers], []

    def chat(self, messages, **_):
        self.asked.append(list(messages))
        return self.answers.pop(0)


@pytest.mark.unit
def test_map_tones_are_the_renderers_tones():
    assert set(typing.get_args(MapTone)) == set(TONES)


@pytest.mark.unit
def test_the_model_writes_only_narration_and_moves_and_code_fills_the_rest():
    lesson = _lesson()
    first = lesson.scenes[0]
    assert [scene.id for scene in lesson.scenes] == ["s1", "s2"]
    assert [beat.id for beat in first.beats] == ["s1_b1", "s1_b2", "s1_b3", "s1_b4", "s1_b5"]
    assert first.beats[0].claim_requirements == {"s1_b1_c": ["label"]}
    assert first.beats[1].claim_requirements == {"s1_b2_c": ["relationship"]}
    assert first.beats[0].visual_anchors == ["Customer app", "Gateway", "Order service"]
    trouble = lesson.scenes[1].beats[0]
    assert trouble.claim_requirements == {"s2_b1_c": ["state_change"]}
    assert "Load: 95" in trouble.visual_anchors


@pytest.mark.unit
def test_a_map_lesson_is_drawn_as_icon_pieces_with_no_model_call():
    client = _Scripted([])                                   # any call would fail on an empty list
    plan = browser_visual_plan.generate(_lesson(), SKILL, client=client, schema_version=2)
    assert client.asked == []
    first, second = plan.scenes
    kinds = {obj.id: obj.kind for obj in first.objects}
    assert kinds == {"phone": "icon", "gateway": "icon", "service": "icon", "cache": "icon",
                     "store": "group", "db": "icon", "load": "metric", "copy": "icon",
                     "s1_b5_line": "caption", "takeaway_s1": "caption"}
    by_id = {obj.id: obj for obj in first.objects}
    assert by_id["store"].payload["members"] == ["db", "load", "copy"]
    assert by_id["copy"].payload["placeholder"] is True and by_id["service"].payload["count"] == 2
    assert {obj.id: obj for obj in second.objects}["db"] == by_id["db"]          # same piece, carried
    assert set(first.layout_ids) >= {piece["id"] for piece in PIECES}


@pytest.mark.unit
def test_each_move_becomes_the_actions_that_show_it():
    first, second = plan_map_scenes(_lesson(), SKILL)
    steps = lambda scene, n: [(a.kind, a.target_ids, a.params) for a in scene.beats[n].actions]
    assert steps(first, 0) == [("appear", ["phone", "gateway", "service"], {})]
    assert steps(first, 1) == [("trace", ["phone", "gateway", "service"], {})]
    # a piece the path needs comes on screen first, and its panel comes with it
    assert steps(first, 2) == [("appear", ["db", "store"], {}), ("trace", ["service", "db"], {})]
    # a reply travels back along the arrows
    assert steps(first, 3) == [("trace", ["db", "service", "gateway", "phone"], {})]
    # the question goes on screen as a line, and the takeaway closes the scene under it
    assert steps(first, 4) == [("appear", ["s1_b5_line"], {}), ("appear", ["takeaway_s1"], {})]
    assert steps(second, 0) == [
        ("appear", ["load"], {}),
        ("trace", ["phone", "gateway", "service", "db"], {"count": 4}),
        ("set_state", ["load"], {"value": 95, "tone": "red"}),
        ("set_state", ["db"], {"tone": "red"})]
    assert steps(second, 1) == [
        ("appear", ["copy"], {}),
        ("set_state", ["copy"], {"placeholder": False}),
        ("set_state", ["db"], {"tone": "teal"}),
        ("set_state", ["load"], {"value": 50, "tone": "teal"})]
    end = closing_state(second, closing_state(first))
    assert end.payloads["load"]["value"] == 50 and end.payloads["copy"]["placeholder"] is False
    assert set(second.carryover_ids) == set(second.opening_visible_ids) == {
        "phone", "gateway", "service", "store", "db"}


@pytest.mark.unit
def test_steps_are_timed_by_code_and_each_beat_makes_one_claim():
    _, second = plan_map_scenes(_lesson(), SKILL)
    beat = second.beats[0]
    assert [action.id for action in beat.actions] == ["s2_b1_1", "s2_b1_2", "s2_b1_3", "s2_b1_4"]
    windows = [(action.start_fraction, action.end_fraction) for action in beat.actions]
    assert windows[0][0] == .06 and windows[-1][1] == .94
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))
    assert [(e.kind, e.claim_ids) for e in beat.evidence] == [("state_change", ["s2_b1_c"])]


@pytest.mark.unit
def test_a_lesson_costs_one_call_and_an_undrawable_move_goes_back_to_that_call():
    bad = _answer()
    fix = bad["scenes"][1]["beats"][1]["move"]             # the meter went red and is never
    del fix["meter"], fix["value"]                         # brought down again
    client = _Scripted([bad, _answer()])
    lesson = lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2)
    assert len(client.asked) == 2 and lesson.map is not None
    assert "ends with ['load'] still red" in client.asked[1][-1]["content"]
    plan = browser_visual_plan.generate(lesson, SKILL, client=_Scripted([]), schema_version=2)
    validate(lesson, plan, SKILL)


@pytest.mark.unit
def test_the_requested_length_reaches_the_lesson_and_a_short_lesson_is_sent_back():
    short = _answer()
    for scene in short["scenes"]:
        for beat in scene["beats"]:
            beat["spoken_text"] = "Too short."
    client = _Scripted([short, _answer()])
    lesson = lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2,
                                  target_seconds=50, max_scenes=4)
    assert ("is about 140 words, between 98 and 182, counting the check question and its answer, "
            "which are added after your last beat. Write about 6 beats, in 2 scenes"
            in client.asked[0][1]["content"])
    assert "Use at most 4 scene(s)" in client.asked[0][1]["content"]
    # eight two-word beats, plus the check question and answer that code adds
    assert "the narration has 39 words" in client.asked[1][-1]["content"]
    assert sum(len(b.spoken_text.split()) for s in lesson.scenes for b in s.beats) == 152


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda a: a["scenes"][0]["beats"][1]["move"].update(path=["phone", "load"]), "joined by an arrow"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(pieces=["router"]), "not on the map"),
    (lambda a: a["scenes"][1]["beats"][0]["move"].update(meter="db"), "is not a meter"),
    (lambda a: a["scenes"][0]["beats"][0].pop("move"), "needs a move"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(do="explode"), "Input should be .introduce."),
    (lambda a: a["scenes"][0]["beats"][1]["move"].update(path=["phone"]), "two or more pieces"),
    (lambda a: a["scenes"][0]["beats"][1]["move"].update(meter="load", value=42), "a send move has no meter"),
])
def test_a_move_that_does_not_fit_the_map_is_refused(change, message):
    answer = _answer()
    change(answer)
    for scene in answer["scenes"]:                # what the filler cannot complete, the schema reports
        for number, beat in enumerate(scene["beats"]):
            beat.setdefault("id", f"x{number}")
            beat.setdefault("claim_ids", [f"x{number}_{scene['title'][:2]}"])
            beat.setdefault("claim_requirements", {beat["claim_ids"][0]: ["label"]})
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


@pytest.mark.unit
def test_a_scene_that_only_names_things_and_an_unknown_icon_are_reported():
    icons = asset_inventory()["icons"]
    assert lesson_map_problems(_lesson(), icons) == []
    answer = _answer()
    answer["map"]["pieces"][0]["icon"] = "unicorn"
    naming = [
        {"spoken_text": SAY, "move": {"do": "introduce", "pieces": ["phone", "gateway", "service", "db"]}},
        {"spoken_text": SAY, "move": {"do": "point", "pieces": ["gateway"]}}]
    answer["scenes"].append({"title": "Recap", "learning_goal": "g", "beats": copy.deepcopy(naming)})
    assert len(lesson_map_problems(_lesson(answer), icons)) == 1   # a scene may only point: 5 of 9 beats act
    for _ in range(5):                                            # but a lesson that mostly names things may not
        answer["scenes"].append({"title": "More", "learning_goal": "g", "beats": copy.deepcopy(naming)})
    problems = lesson_map_problems(_lesson(answer), icons)
    assert "icon 'unicorn'" in problems[0]
    assert "only 5 of 19 beats show something travelling or changing" in problems[1]


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda m: m["pieces"].__setitem__(0, {**m["pieces"][0], "label": "The one phone app"}),
     "one to three words"),
    (lambda m: m["arrows"].append({"source": "phone", "target": "store"}), "must join two"),
    (lambda m: m["arrows"].append({"source": "gateway", "target": "phone"}), "two arrows between"),
    (lambda m: m["pieces"].append({"id": "x", "label": "Stray", "icon": "server", "panel": "phone"}),
     "not a panel"),
])
def test_a_malformed_map_is_refused(change, message):
    data = {"pieces": copy.deepcopy(PIECES), "arrows": copy.deepcopy(ARROWS)}
    change(data)
    with pytest.raises(ValidationError, match=message):
        LessonMap.model_validate(data)


@pytest.mark.unit
def test_a_lesson_without_a_map_is_untouched_and_may_not_carry_moves():
    plain = {"learning_objective": "x", "scenes": [{"id": "a", "title": "t", "learning_goal": "g", "beats": [
        {"id": "b", "spoken_text": "Words.", "claim_ids": ["c"], "visual_anchors": ["A"],
         "claim_requirements": {"c": ["label"]}}]}]}
    assert fill_map_lesson(copy.deepcopy(plain)) == plain
    plain["scenes"][0]["beats"][0]["move"] = {"do": "point", "pieces": ["a"]}
    with pytest.raises(ValidationError, match="has no map"):
        LessonPlan.model_validate({**plain, "schema_version": 2, "topic": "t", "skill_id": "s"})


@pytest.mark.unit
def test_a_piece_may_only_turn_red_or_back_to_its_own_colour():
    lesson = _lesson()
    plan = browser_visual_plan.generate(lesson, SKILL, client=_Scripted([]), schema_version=2)
    plan.scenes[1].beats[0].actions[3].params = {"tone": "purple"}             # db is teal
    with pytest.raises(VisualPlanValidationError, match="may only turn 'red'"):
        validate(lesson, plan, SKILL)


@pytest.mark.unit
def test_six_icon_pieces_fit_one_row_and_cards_still_wrap_after_four():
    from core.schemas.browser_visual_plan import BrowserScene
    from generation.browser_scene import _semantic_html

    def chain(kind, count):
        ids = [f"p{n}" for n in range(count)]
        payload = {"asset_id": "server"} if kind == "icon" else {}
        return BrowserScene.model_validate({
            "lesson_scene_id": "s", "pattern": "architecture",
            "objects": [{"id": i, "kind": kind, "role": "operation", "label": i.upper(),
                         "payload": payload} for i in ids],
            "relationships": [{"source_id": a, "target_id": b, "kind": "flows_to"}
                              for a, b in zip(ids, ids[1:])],
            "beats": [{"narration_beat_id": "b", "actions": [{"kind": "hold", "target_ids": [ids[0]]}],
                       "evidence": [{"claim_ids": ["c"], "object_ids": [ids[0]], "kind": "label"}]}],
            "opening_visible_ids": ids, "closing_visible_ids": ids})

    rows = lambda scene: _semantic_html(scene, closing_state(scene)).count('class="semantic-row"')
    assert rows(chain("icon", 6)) == 1 and rows(chain("icon", 7)) == 2
    assert rows(chain("message", 4)) == 1 and rows(chain("message", 5)) == 2


@pytest.mark.integration
def test_a_compiled_map_passes_the_layout_check_and_a_reply_travels_back():
    from playwright.sync_api import sync_playwright

    from composition.slides import chrome_path
    from core.visual_state import opening_state
    from generation.browser_scene import CAPTURE_ARGS, animation_html, page_html
    from verification.browser_layout import audit_html

    answer = _answer()
    answer["scenes"][0]["takeaway"] = "Every single order that a customer places ends up in the very same database"[:80]
    first, second = plan_map_scenes(_lesson(answer), SKILL)
    middle = closing_state(first)
    for scene, state in ((first, middle), (second, closing_state(second, middle))):
        assert len(audit_html(page_html(scene, title="An order", state=state))["nodes"]) >= 5
    with sync_playwright() as playwright:                  # the longest takeaway stays inside the frame
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(page_html(first, title="An order", state=middle))
        line = page.locator('[data-object-id="takeaway_s1"]')
        box, text = line.bounding_box(), line.evaluate(
            "e=>{const r=document.createRange();r.selectNodeContents(e);const b=r.getBoundingClientRect();"
            "return [b.left,b.right,b.height]}")
        browser.close()
    assert text[0] >= 16 and text[1] <= 1264 and text[2] < 40 and box["y"] + box["height"] <= 720
    # the reply beat: the ball runs from the database back to the phone, right to left
    state = opening_state(first)
    for beat in first.beats[:3]:
        for action in beat.actions:
            from core.visual_state import apply_action
            apply_action(state, action)
    document = animation_html(first, first.beats[3], title="An order", opening=state, duration=6)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(document)
        page.evaluate("() => window.animationReady()")
        xs = []
        for time in (.5, 1.5, 2.5):
            page.evaluate("t => window.seekAnimation(t)", time)
            xs.append(page.locator(".flow-packet").bounding_box()["x"])
        browser.close()
    assert xs[0] > xs[1] > xs[2]


@pytest.mark.unit
def test_an_arrow_that_merely_exists_does_not_prove_a_relationship():
    lesson = _lesson()
    plan = browser_visual_plan.generate(lesson, SKILL, client=_Scripted([]), schema_version=2)
    travel = plan.scenes[0].beats[1].actions[0]            # the send from phone to service
    travel.kind, travel.params = "highlight", {}           # the pieces glow, nothing travels
    with pytest.raises(VisualPlanValidationError, match="lacks relationship visual proof"):
        validate(lesson, plan, SKILL)


@pytest.mark.unit
def test_the_recipe_decides_the_board_and_only_that_prompt_is_sent():
    recipes = load_recipes()
    assert {name: recipe.board for name, recipe in recipes.items()} == {
        "architecture_explainer": "map", "workflow_explainer": "map", "before_after": "map",
        "algorithm_explainer": "trace", "funnel_explainer": "free", "metric_story": "free"}
    client = _Scripted([_answer()])
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2)
    system, user = client.asked[0][0]["content"], client.asked[0][1]["content"]
    assert "ONE map" in system and '"brief"' in system
    # the prompt gives the shape and principles, not a plot to follow or a worked lesson to copy
    for copied in ("Customer app", "Order service", "smartphone", "First introduce", "Then the fix"):
        assert copied not in system
    assert "Icon list: " in user
    # a lesson that skips the map is sent back, and the reason is reported
    plain = {"learning_objective": "x", "scenes": [{"id": "a", "title": "t", "learning_goal": "g", "beats": [
        {"id": "b", "spoken_text": "Words.", "claim_ids": ["c"], "visual_anchors": ["A"],
         "claim_requirements": {"c": ["label"]}}]}]}
    reasons = []
    client = _Scripted([plain, _answer()])
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2,
                         on_reject=reasons.append)
    assert len(reasons) == 1 and "taught on a map" in reasons[0]
    # a free-board recipe gets the general prompt, with no map and no icon list
    client = _Scripted([plain])
    lesson_plan.generate("Revenue", recipes["metric_story"], client=client, schema_version=2)
    assert "map" not in client.asked[0][0]["content"].lower()
    assert "Icon list" not in client.asked[0][1]["content"]


@pytest.mark.unit
def test_a_fix_heals_every_red_piece_and_a_lesson_may_not_end_red():
    answer = _answer()
    trouble = answer["scenes"][1]["beats"][0]["move"]
    trouble["pieces"] = ["db", "service"]                          # two pieces turn red
    answer["scenes"][1]["beats"][1]["move"]["pieces"] = ["copy"]   # the fix names neither
    _, second = plan_map_scenes(_lesson(answer), SKILL)
    healed = [(a.target_ids, a.params) for a in second.beats[1].actions if a.params.get("tone")]
    assert (["service"], {"tone": "blue"}) in healed
    assert any(targets == ["db"] and params["tone"] == "teal" for targets, params in healed)
    # a meter pushed up in red and never brought down is sent back to the lesson step
    del answer["scenes"][1]["beats"][1]["move"]["meter"], answer["scenes"][1]["beats"][1]["move"]["value"]
    with pytest.raises(ValueError, match=r"ends with \['load'\] still red"):
        plan_map_scenes(_lesson(answer), SKILL)


@pytest.mark.unit
def test_a_reply_arrow_is_folded_into_the_request_arrow():
    answer = _answer()
    answer["map"]["arrows"] += [{"source": "gateway", "target": "phone", "label": "answer"},
                                {"source": "db", "target": "service"}]
    lesson = _lesson(answer)                               # accepted, not sent back
    assert [(arrow.source, arrow.target) for arrow in lesson.map.arrows] == [
        (arrow["source"], arrow["target"]) for arrow in ARROWS]


@pytest.mark.unit
def test_a_path_that_skips_a_piece_is_routed_along_the_arrows():
    answer = _answer()
    answer["scenes"][0]["beats"][3]["move"]["path"] = ["db", "phone"]         # the reply, in one jump
    answer["scenes"][0]["beats"][1]["move"]["path"] = ["phone", "service", "cache"]
    lesson = _lesson(answer)
    assert lesson.scenes[0].beats[3].move.path == ["db", "service", "gateway", "phone"]
    assert lesson.scenes[0].beats[1].move.path == ["phone", "gateway", "service", "cache"]


@pytest.mark.unit
def test_trouble_on_a_piece_already_red_is_emphasis_and_points_at_it():
    answer = _answer()
    answer["scenes"][1]["beats"].insert(1, {"spoken_text": SAY, "move": {"do": "trouble", "pieces": ["db"]}})
    lesson = _lesson(answer)
    _, second = plan_map_scenes(lesson, SKILL)
    again = second.beats[1]
    assert [(action.kind, action.target_ids) for action in again.actions] == [("highlight", ["db"])]
    assert [evidence.kind for evidence in again.evidence] == ["label"]
    assert lesson.scenes[1].beats[1].claim_requirements == {"s2_b2_c": ["label"]}


@pytest.mark.unit
def test_a_new_map_lesson_starts_from_a_brief_and_an_old_one_without_it_still_loads():
    from planner.lesson_map import craft_problems

    lesson = _lesson()
    assert lesson.brief.question.endswith("?")
    assert craft_problems(lesson, plan_map_scenes(lesson, SKILL)) == []
    old = _answer()
    del old["brief"]
    old["scenes"][0]["beats"].pop()                        # and before questions were shown
    saved = _lesson(old)                                   # a lesson saved before briefs existed
    assert saved.brief is None and len(plan_map_scenes(saved, SKILL)) == 2
    client = _Scripted([old, _answer()])                   # but a newly planned one is sent back
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2)
    assert 'starts with a "brief"' in client.asked[1][-1]["content"]
    statement = _answer()
    statement["brief"]["question"] = "One database is a weak point."
    with pytest.raises(ValidationError, match="written as a question"):
        _lesson(statement)


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda a: a["scenes"][0]["beats"].pop(), "the first scene never puts the learner's question on screen"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(pieces=["phone", "gateway", "service", "cache"]),
     "brings 4 new pieces on screen at once"),
    (lambda a: a["scenes"][1]["beats"].pop(), "['cache'] are shown but never do anything"),
    (lambda a: a["scenes"][1]["beats"].insert(0, {"spoken_text": SAY, "move": {"do": "introduce", "pieces": ["cache"]}}) or
     a["scenes"][1]["beats"].pop(), "['cache'] are shown but never do anything"),
    (lambda a: a["scenes"][1]["beats"].__setitem__(slice(0, 2), [
        {"spoken_text": SAY, "move": {"do": "trouble", "pieces": ["db"]}},
        {"spoken_text": SAY, "move": {"do": "fix", "pieces": ["copy"]}}]), "meter(s) ['load'] never change"),
])
def test_a_lesson_that_falls_short_as_teaching_is_sent_back_with_the_reason(change, message):
    weak = _answer()
    change(weak)
    client = _Scripted([weak, _answer()])
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2)
    assert len(client.asked) == 2
    assert "as teaching this falls short" in client.asked[1][-1]["content"]
    assert message in client.asked[1][-1]["content"]


@pytest.mark.unit
def test_the_plot_of_a_lesson_can_be_read_off_and_compared():
    from eval.plan_score import PlanBatteryReport, TopicResult
    from planner.lesson_map import story_shape

    shape = story_shape(_lesson())
    assert shape == "introduce send send send ask | trouble fix point ask answer"
    other = _answer()
    other["scenes"][0]["beats"][1], other["scenes"][0]["beats"][2] = (
        other["scenes"][0]["beats"][2], other["scenes"][0]["beats"][1])
    report = PlanBatteryReport(model="m", results=[
        TopicResult("a", planned=True, shape=shape), TopicResult("b", planned=True, shape=shape),
        TopicResult("c", planned=True, shape="send point | measure")])
    assert report.sameness == "2 distinct plots and 2 distinct opening scenes in 3 map lessons"
    assert "sameness: 2 distinct plots" in report.table()
    assert PlanBatteryReport.from_dict(report.to_dict()).results[0].shape == shape


@pytest.mark.unit
def test_the_brief_supplies_the_objective_and_audience_the_model_left_out():
    answer = _answer()
    del answer["learning_objective"]
    lesson = _lesson(answer)
    assert lesson.learning_objective == BRIEF["can_do"] and lesson.audience == BRIEF["learner"]


@pytest.mark.unit
def test_removing_a_piece_that_was_never_shown_says_so_plainly(tmp_path):
    answer = _answer()
    answer["scenes"][1]["beats"][2] = {"spoken_text": SAY, "move": {"do": "remove", "pieces": ["cache"]}}
    client = _Scripted([answer, _answer()])
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2,
                         diagnostic_dir=tmp_path)
    assert "a remove move names ['cache'], which are not on screen" in client.asked[1][-1]["content"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "lesson_attempt_01.txt", "lesson_attempt_02.txt"]              # both answers are kept


@pytest.mark.unit
def test_the_question_is_shown_and_the_check_gets_a_pause_and_an_answer():
    lesson = _lesson()
    first, second = plan_map_scenes(lesson, SKILL)
    lines = {obj.id: obj for scene in (first, second) for obj in scene.objects if obj.kind == "caption"}
    # an ask with no text shows the lesson's own question
    assert lines["s1_b5_line"].label == BRIEF["question"] and lines["s1_b5_line"].payload["ask"] is True
    # the check question and its answer are the brief's words, added after the model's last beat
    asked, answered = lesson.scenes[1].beats[-2:]
    assert (asked.spoken_text, asked.move.do) == (BRIEF["check_question"], "ask")
    assert (answered.spoken_text, answered.move.do) == (BRIEF["check_answer"], "answer")
    assert lines["s2_b4_line"].label == BRIEF["check_question"]
    assert lines["s2_b5_line"].label == BRIEF["check_answer"] and lines["s2_b5_line"].payload["tick"] is True
    # the picture holds after the check question, and nowhere else
    assert [beat.pause_after for beat in second.beats] == [0, 0, 0, 1.6, 0]
    assert all(beat.pause_after == 0 for beat in first.beats)
    # a scene that ends on an answer shows no takeaway under it
    closing = _answer()
    closing["scenes"][1]["takeaway"] = "A copy shares the load"
    _, last = plan_map_scenes(_lesson(closing), SKILL)
    assert "takeaway_s2" not in {obj.id for obj in last.objects}


@pytest.mark.unit
def test_a_lesson_that_asks_its_own_check_is_left_as_written():
    own = _answer()
    own["scenes"][1]["beats"] += [
        {"spoken_text": "So what changed?", "move": {"do": "ask", "text": "So what changed?"}},
        {"spoken_text": "The copy took half the work.", "move": {"do": "answer", "text": "The copy took half the work."}}]
    lesson = _lesson(own)
    assert [beat.move.do for beat in lesson.scenes[1].beats] == ["trouble", "fix", "point", "ask", "answer"]
    assert lesson.scenes[1].beats[-1].spoken_text == "The copy took half the work."


@pytest.mark.unit
@pytest.mark.parametrize("beats, message", [
    ([{"do": "ask", "text": "One?"}, {"do": "ask", "text": "Two?"}], "asks at most one question"),
    ([{"do": "answer", "text": "Because."}, {"do": "ask", "text": "Why?"}], "comes after an ask move"),
    ([{"do": "ask", "text": "A statement."}], "is a question, ending in"),
    ([{"do": "ask", "text": "Why " + "so " * 40 + "long?"}], "at most 110 characters"),
    ([{"do": "send", "path": ["phone", "gateway"], "text": "hello"}], "a send move has no text"),
    ([{"do": "ask", "text": "Why?", "pieces": ["phone"]}], "an ask move has no pieces"),
])
def test_lines_of_text_follow_their_rules(beats, message):
    answer = _answer()
    answer["scenes"][1]["beats"] = [   # replaces the scene, so no check is added on top of an ask
        {"spoken_text": SAY, "move": {"do": "trouble", "pieces": ["db"], "meter": "load", "value": 95}},
        *({"spoken_text": SAY, "move": move} for move in beats)]
    with pytest.raises(ValidationError, match=message):
        _lesson(answer)


@pytest.mark.unit
def test_a_question_line_is_drawn_larger_with_its_own_mark():
    from generation.browser_scene import _semantic_html

    first, _ = plan_map_scenes(_lesson(), SKILL)
    html = _semantic_html(first, closing_state(first))
    assert ('semantic-caption-line is-question tone-white" data-object-id="s1_b5_line"' in html
            and '<span class="ask-mark">?</span>' + BRIEF["question"].replace("'", "&#x27;") in html)
    assert html.count("ask-mark") == 1                      # the takeaway keeps its own look


@pytest.mark.integration
def test_a_question_stays_bright_while_its_answer_appears():
    from playwright.sync_api import sync_playwright

    from composition.slides import chrome_path
    from core.visual_state import apply_action, opening_state
    from generation.browser_scene import CAPTURE_ARGS, animation_html

    first, second = plan_map_scenes(_lesson(), SKILL)
    state = opening_state(second, closing_state(first))
    for beat in second.beats[:4]:                           # up to and including the check question
        for action in beat.actions:
            apply_action(state, action)
    document = animation_html(second, second.beats[4], title="Check", opening=state, duration=3)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(document)
        page.evaluate("() => window.animationReady()")
        page.evaluate("() => window.seekAnimation(2.9)")    # the answer is on screen
        look = lambda obj_id: page.locator(f'[data-object-id="{obj_id}"]').evaluate(
            "e=>getComputedStyle(e).opacity")
        seen = {name: look(name) for name in ("s2_b4_line", "s2_b5_line", "phone")}
        browser.close()
    # the pieces not being talked about fade back; the question being answered does not
    assert seen == {"s2_b4_line": "1", "s2_b5_line": "1", "phone": "0.62"}


@pytest.mark.unit
def test_the_taught_map_fixture_is_exactly_what_the_compiler_writes():
    """The fixture's lesson is hand-written; its pictures must come from the compiler, so the
    regression set renders the compiled path and cannot drift from it."""
    from pathlib import Path

    from core.schemas.browser_visual_plan import BrowserVisualPlan
    from planner.lesson_map import craft_problems

    folder = Path(__file__).parent / "fixtures" / "video_golden" / "taught_map"
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    saved = BrowserVisualPlan.model_validate_json(
        (folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    compiled = plan_map_scenes(lesson, SKILL)
    assert saved.scenes == compiled
    assert craft_problems(lesson, compiled) == []
    assert [beat.pause_after for beat in compiled[-1].beats] == [0, 0, 0, 1.6, 0]


@pytest.mark.unit
def test_a_loosely_written_piece_id_is_tidied_everywhere_it_is_used():
    answer = _answer()
    loose = {"service": "Order-Service", "db": "DB 1", "load": "load%"}
    swap = lambda value: loose.get(value, value)
    for piece in answer["map"]["pieces"]:
        piece["id"] = swap(piece["id"])
    for arrow in answer["map"]["arrows"]:
        arrow["source"], arrow["target"] = swap(arrow["source"]), swap(arrow["target"])
    for scene in answer["scenes"]:
        for beat in scene["beats"]:
            move = beat["move"]
            for key in ("pieces", "path"):
                if key in move:
                    move[key] = [swap(item) for item in move[key]]
            if "meter" in move:
                move["meter"] = swap(move["meter"])
    lesson = _lesson(answer)                               # accepted, not sent back
    assert {"order_service", "db_1", "load"} <= {piece.id for piece in lesson.map.pieces}
    assert lesson.scenes[0].beats[2].move.path == ["order_service", "db_1"]
    assert lesson.scenes[1].beats[0].move.meter == "load"
    assert len(plan_map_scenes(lesson, SKILL)) == 2
    # two ids that would become the same name are left for the schema to refuse
    clash = _answer()
    clash["map"]["pieces"][0]["id"], clash["map"]["pieces"][1]["id"] = "a-b", "a b"
    with pytest.raises(ValidationError):
        _lesson(clash)


@pytest.mark.unit
def test_removing_a_piece_that_is_on_screen_is_shown_and_accepted():
    answer = _answer()
    answer["scenes"][1]["beats"].append(
        {"spoken_text": SAY, "move": {"do": "remove", "pieces": ["cache"]}})
    lesson = _lesson(answer)
    _, second = plan_map_scenes(lesson, SKILL)              # the validator accepts it
    gone = second.beats[3]
    assert [(action.kind, action.target_ids) for action in gone.actions] == [
        ("highlight", ["cache"]), ("hide", ["cache"])]      # lit once, then it leaves
    assert lesson.scenes[1].beats[3].claim_requirements == {"s2_b4_c": ["state_change"]}
    assert "cache" not in second.closing_visible_ids
