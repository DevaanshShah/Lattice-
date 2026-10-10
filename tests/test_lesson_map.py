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


def _answer() -> dict:
    """A lesson exactly as the model is asked to write it: narration and a move per beat."""
    return {
        "learning_objective": "Follow an order and see why the database gets a copy.",
        "map": {"pieces": copy.deepcopy(PIECES), "arrows": copy.deepcopy(ARROWS)},
        "scenes": [
            {"title": "An order", "learning_goal": "Follow it.",
             "takeaway": "Every order ends in one database",
             "beats": [
                 {"spoken_text": SAY, "move": {"do": "introduce", "pieces": ["phone", "gateway", "service"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["phone", "gateway", "service"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["service", "db"]}},
                 {"spoken_text": SAY, "move": {"do": "send", "path": ["db", "service", "gateway", "phone"]}},
             ]},
            {"title": "Too many orders", "learning_goal": "See the overload and the fix.",
             "beats": [
                 {"spoken_text": SAY, "move": {"do": "trouble", "pieces": ["db"], "meter": "load",
                                               "value": 95, "path": ["phone", "gateway", "service", "db"],
                                               "count": 4}},
                 {"spoken_text": SAY, "move": {"do": "fix", "pieces": ["copy", "db"], "meter": "load",
                                               "value": 50}},
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
    assert [beat.id for beat in first.beats] == ["s1_b1", "s1_b2", "s1_b3", "s1_b4"]
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
                     "takeaway_s1": "caption"}
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
    # a reply travels back along the arrows; the takeaway closes the scene
    assert steps(first, 3) == [("trace", ["db", "service", "gateway", "phone"], {}),
                               ("appear", ["takeaway_s1"], {})]
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
                                  target_seconds=40, max_scenes=4)
    assert "is about 112 words, between 78 and 146" in client.asked[0][1]["content"]
    assert "Use at most 4 scene(s)" in client.asked[0][1]["content"]
    assert "the narration has 12 words" in client.asked[1][-1]["content"]
    assert sum(len(b.spoken_text.split()) for s in lesson.scenes for b in s.beats) == 102


@pytest.mark.unit
@pytest.mark.parametrize("change, message", [
    (lambda a: a["scenes"][0]["beats"][1]["move"].update(path=["phone", "load"]), "joined by an arrow"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(pieces=["router"]), "not on the map"),
    (lambda a: a["scenes"][1]["beats"][0]["move"].update(meter="db"), "is not a meter"),
    (lambda a: a["scenes"][0]["beats"][0].pop("move"), "needs a move"),
    (lambda a: a["scenes"][0]["beats"][0]["move"].update(do="explode"), "Input should be .introduce."),
    (lambda a: a["scenes"][0]["beats"][1]["move"].update(path=["phone"]), "two or more pieces"),
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
    answer["scenes"][0]["beats"] = copy.deepcopy(naming)   # an opening that presents the pieces is fine
    answer["scenes"].insert(1, {"title": "More names", "learning_goal": "g", "beats": naming})
    problems = lesson_map_problems(_lesson(answer), icons)
    assert len(problems) == 2 and "icon 'unicorn'" in problems[0]
    assert "scene s2 only names things" in problems[1]


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
    assert {name for name, recipe in recipes.items() if recipe.board == "map"} == {
        "architecture_explainer", "workflow_explainer", "before_after"}
    client = _Scripted([_answer()])
    lesson_plan.generate("An order's journey", SKILL, client=client, schema_version=2)
    system, user = client.asked[0][0]["content"], client.asked[0][1]["content"]
    assert system.startswith("You are the Lesson Director for a short learning video taught on ONE map")
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
    lesson_plan.generate("Search", recipes["algorithm_explainer"], client=client, schema_version=2)
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
