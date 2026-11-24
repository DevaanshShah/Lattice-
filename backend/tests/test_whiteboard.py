"""The whiteboard style (owner's Lamina-style reference, 2026-11-24): colour icons from a shortlist,
a white hand-lettered page, and pieces that are drawn on, not faded in."""
import json
from pathlib import Path

import pytest

from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.visual_assets import fluent_index, icon_choices, resolve_asset
from core.visual_state import closing_state

SAVED = Path(__file__).parent / "fixtures" / "video_golden" / "taught_map" / "browser_visual_plan.json"


def _whiteboard_scene():
    scene = BrowserVisualPlan.model_validate_json(SAVED.read_text(encoding="utf-8")).scenes[0]
    scene = scene.model_copy(deep=True, update={"theme": "whiteboard"})
    for obj in scene.objects:
        if obj.kind == "icon":
            obj.payload["asset_id"] = {"students": "fluent/student", "door": "fluent/telephone-receiver",
                                       "server": "fluent/television"}.get(obj.id, obj.payload["asset_id"])
    return scene


@pytest.mark.unit
def test_the_colour_icon_set_is_present_and_every_listed_icon_resolves():
    index = fluent_index()
    assert len(index) > 1400
    for name in ("skull", "bone", "brain", "woman-technologist", "telephone-receiver", "credit-card"):
        assert resolve_asset("icon", f"fluent/{name}").is_file()


@pytest.mark.unit
def test_a_topics_words_shortlist_its_icons_beside_the_universal_set():
    picks = icon_choices("How the skull and brain are protected by bone")
    assert {"fluent/skull", "fluent/brain", "fluent/bone"} <= set(picks[:10])
    assert "fluent/woman-technologist" in picks and "fluent/check-mark-button" in picks   # the universal set
    colours = {"red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white", "grey"}
    kinds = [" ".join(w for w in name.split("/")[1].split("-") if w not in colours) for name in icon_choices("heart")]
    assert len(kinds) == len(set(kinds))       # one heart of each kind, not one in every colour
    assert all(name.startswith("fluent/") and resolve_asset("icon", name) for name in picks)


@pytest.mark.unit
def test_the_whiteboard_style_changes_the_page_and_the_dark_one_does_not():
    from generation.browser_scene import page_html

    scene = _whiteboard_scene()
    state = closing_state(scene)
    white = page_html(scene, title="Check one", state=state)
    dark = page_html(scene.model_copy(update={"theme": "dark"}), title="Check one", state=state)
    assert 'data-theme="whiteboard"' in white and "font-family:'Board'" in white
    assert "data-theme" not in dark and "'Board'" not in dark


@pytest.mark.unit
def test_a_lesson_planned_in_the_whiteboard_style_offers_the_colour_icons():
    from planner import lesson_plan
    from planner.product_recipe import load_recipes
    from tests.test_lesson_map import _Scripted, _answer

    skill = load_recipes()["workflow_explainer"]
    client = _Scripted([_answer()])
    try:
        lesson_plan.generate("t", skill, client=client, schema_version=2, style="whiteboard")
    except Exception:
        pass                                   # the fixture's icons are not Fluent ones; the prompt is what is checked
    asked = client.asked[0][-1]["content"]
    assert "Icon list:" in asked and "fluent/" in asked


@pytest.mark.integration
def test_a_new_piece_traces_its_outline_then_fills_then_writes_its_label():
    from playwright.sync_api import sync_playwright

    from composition.slides import chrome_path
    from core.visual_state import opening_state
    from generation.browser_scene import CAPTURE_ARGS, animation_html

    scene = _whiteboard_scene()
    beat = scene.beats[0]                      # introduces the students and the front door
    appear = next(i for i, action in enumerate(beat.actions) if action.kind == "appear")
    start, end = beat.timeline(6.0)[appear]
    html = animation_html(scene, beat, title="t", opening=opening_state(scene), duration=6.0)
    probe = """() => { const piece = document.querySelector('[data-object-id="students"]');
        const shape = piece.querySelector('svg path'); const label = piece.querySelector('.piece-label');
        const style = getComputedStyle(shape);
        return {dash: parseFloat(style.strokeDashoffset), fill: parseFloat(style.fillOpacity),
                clip: getComputedStyle(label).clipPath}; }"""
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chrome_path(), args=CAPTURE_ARGS)
        seen = []
        for t in (start + .15, start + .9, end + .4):
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html)
            page.evaluate("window.animationReady()")
            page.evaluate(f"window.seekAnimation({t})")
            seen.append(page.evaluate(probe))
        browser.close()
    early, middle, late = seen
    assert early["dash"] > .5 and early["fill"] < .2          # the outline has barely started, no colour yet
    assert middle["dash"] < early["dash"]                     # the line is being drawn
    assert late["dash"] == 0 and late["fill"] == 1            # finished: fully drawn and coloured
    assert "100%" in early["clip"] and "100%" not in late["clip"]   # the label is written last
