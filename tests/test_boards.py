"""The hand-made test boards: a system map shared by two scenes, and code beside its picture."""
import json
import re
from pathlib import Path

import pytest

from composition.slides import chrome_path
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.visual_state import closing_state, drawn_view, opening_state
from generation.browser_scene import CAPTURE_ARGS, _semantic_html, ball_after, page_html

FIXTURES = Path(__file__).parent / "fixtures" / "video_golden"


def _scenes(name: str):
    return BrowserVisualPlan.model_validate_json(
        (FIXTURES / name / "browser_visual_plan.json").read_text(encoding="utf-8")).scenes


def _lines(html: str, state: str) -> list[int]:
    return [int(number) for number in
            re.findall(rf'class="code-line {state}" data-visual-key="code:line:(\d+)"', html)]


@pytest.mark.unit
def test_code_sits_left_of_the_picture_it_explains():
    scene = _scenes("code_and_picture")[0]
    html = _semantic_html(scene, closing_state(scene))
    assert "semantic-split" in html
    code, rest = html.split('<div class="split-rest">')
    assert 'data-object-id="code"' in code and 'data-object-id="list"' in rest
    assert 'data-object-id="code"' not in rest


@pytest.mark.unit
def test_only_the_lines_being_explained_are_lit():
    scene = _scenes("code_and_picture")[0]
    html = _semantic_html(scene, closing_state(scene))
    assert _lines(html, "is-on") == [5, 6]
    assert _lines(html, "is-off") == [1, 2, 3, 4, 7, 8, 9, 10, 11]
    before = _semantic_html(scene, opening_state(scene))
    assert not _lines(before, "is-on") and not _lines(before, "is-off")   # nothing lit, nothing dimmed


@pytest.mark.unit
def test_moving_the_lit_line_counts_as_a_change_on_screen():
    source = "a = 1\nb = 2"
    assert (drawn_view("code", {"source": source, "active_lines": [1]})
            != drawn_view("code", {"source": source, "active_lines": [2]}))


@pytest.mark.unit
def test_map_pieces_are_toned_icons_and_a_panel_holds_its_members():
    first, second = _scenes("system_map")
    html = _semantic_html(second, closing_state(second, closing_state(first)))
    rider = re.search(r'<div class="([^"]*)" data-object-id="rider"[^>]*>(.*?)data-object-id=', html, re.S)
    assert {"semantic-piece", "tone-pink"} <= set(rider[1].split()) and "<svg" in rider[2]
    panel = html.split('data-object-id="trips"')[1]
    body = panel.split('<div class="panel-body">')[1]
    for member in ("main", "load", "copy", "archive"):
        assert f'data-object-id="{member}"' in body
    assert html.count('data-object-id="main"') == 1                # drawn in the panel, nowhere else


@pytest.mark.unit
def test_a_planned_piece_is_a_dashed_outline_until_it_is_built():
    first, second = _scenes("system_map")
    state = opening_state(second, closing_state(first))
    from core.visual_state import after_beat
    planned = _semantic_html(second, after_beat(after_beat(state, second, "b5"), second, "b6"))
    built = _semantic_html(second, closing_state(second, closing_state(first)))
    copy = r'class="([^"]*)" data-object-id="copy"'
    assert "is-placeholder" in re.search(copy, planned)[1]
    assert "is-placeholder" not in re.search(copy, built)[1]


@pytest.mark.unit
def test_the_ball_rests_on_the_last_piece_it_reached():
    first, second = _scenes("system_map")
    ball = None
    for beat in first.beats:
        ball = ball_after(first, beat, ball)
    assert ball == ["matchers", "main", "#f4f4f5"]
    assert ball_after(first, first.beats[1], None) is None         # drawing the arrows moves no ball
    assert ball_after(second, second.beats[1], ball) == ball       # no trace in that beat: it stays put


@pytest.mark.integration
def test_the_map_keeps_every_piece_in_place_across_scenes_and_arrows_stay_off_labels():
    from playwright.sync_api import sync_playwright

    first, second = _scenes("system_map")
    middle = closing_state(first)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        boxes = []
        for scene, state in ((first, opening_state(first)), (first, middle),
                             (second, closing_state(second, middle))):
            page.set_content(page_html(scene, title="Map", state=state))
            boxes.append({obj_id: page.locator(f'[data-object-id="{obj_id}"]').bounding_box()
                          for obj_id in ("rider", "gateway", "matchers", "hot", "main", "archive")})
        # matchers has two arrows out: the one to the hot list leaves from its top, not the shared gap
        route = json.loads(page.locator(
            'path.edge[data-source-id="matchers"][data-target-id="hot"]').get_attribute("data-route"))
        frame = page.locator(".diagram").bounding_box()
        label = page.locator(".edge-label", has_text="save trip").bounding_box()
        browser.close()
    assert boxes[0] == boxes[1] == boxes[2]
    assert len(route) == 3 and route[0][0] == route[1][0]
    matchers = boxes[2]["matchers"]
    assert abs(frame["x"] + route[0][0] - (matchers["x"] + matchers["width"] / 2)) < 1
    upright = frame["x"] + route[0][0]
    assert not label["x"] - 4 < upright < label["x"] + label["width"] + 4


@pytest.mark.unit
def test_a_trace_must_follow_arrows_that_exist():
    from core.schemas.lesson_plan import LessonPlan
    from planner.product_recipe import load_recipes
    from verification.visual_plan_validation import VisualPlanValidationError, validate

    folder = FIXTURES / "system_map"
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = BrowserVisualPlan.model_validate_json(
        (folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    skill = load_recipes()["workflow_explainer"]
    validate(lesson, plan, skill)
    trace = next(action for action in plan.scenes[0].beats[2].actions if action.kind == "trace")
    trace.target_ids = ["rider", "matchers"]                       # no arrow joins these two
    with pytest.raises(VisualPlanValidationError, match="no arrow for"):
        validate(lesson, plan, skill)


@pytest.mark.unit
def test_the_diagram_is_built_before_the_ball_moves():
    first, _ = _scenes("system_map")
    kinds = [action.kind for beat in first.beats for action in beat.actions]
    assert kinds.index("trace") > max(i for i, kind in enumerate(kinds) if kind in {"appear", "connect"})
