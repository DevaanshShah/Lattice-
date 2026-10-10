import json
import re

import pytest

from composition.slides import chrome_path
from core.schemas.browser_visual_plan import BrowserScene
from core.visual_state import closing_state, opening_state
from generation.browser_scene import _label_lines, _semantic_html, animation_html, page_html
from verification.browser_layout import _issues, audit_html


def _chain(count: int, label: str = "then", *, visible_at_open: int | None = None) -> BrowserScene:
    """A linear flow of `count` message cards; the first `visible_at_open` are on screen at the start."""
    ids = [f"s{index}" for index in range(count)]
    opening = ids if visible_at_open is None else ids[:visible_at_open]
    late = [obj_id for obj_id in ids if obj_id not in opening]
    actions = ([{"id": "reveal", "kind": "appear", "target_ids": late,
                 "start_fraction": .1, "end_fraction": .5}] if late else
               [{"id": "hold", "kind": "hold", "target_ids": [ids[0]],
                 "start_fraction": .1, "end_fraction": .5}])
    return BrowserScene.model_validate({
        "lesson_scene_id": "flow", "pattern": "workflow",
        "objects": [{"id": obj_id, "kind": "message", "role": "operation", "label": f"Step {index + 1}",
                     "payload": {"status": "pending"}} for index, obj_id in enumerate(ids)],
        "relationships": [{"source_id": ids[index], "target_id": ids[index + 1], "kind": "flows_to",
                           "label": label} for index in range(count - 1)],
        "beats": [{"narration_beat_id": "b", "actions": actions,
                   "evidence": [{"claim_ids": ["c"], "object_ids": [ids[0]], "kind": "label"}]}],
        "opening_visible_ids": opening, "closing_visible_ids": ids})


def _snapshots(document: str) -> list[str]:
    data = document.split('<script id="animation-plan" type="application/json">')[1]
    return json.loads(data.split("</script>")[0].replace("<\\/", "</"))["snapshots"]


@pytest.mark.unit
def test_cards_use_the_original_card_styles_with_their_values_inside():
    scene = _chain(2)
    html = _semantic_html(scene, closing_state(scene))
    card = re.search(r'<div class="([^"]*)" data-object-id="s0">(.*?)</div></div>', html)
    assert {"semantic-card", "node", "kind-message", "role-operation", "has-fields"} <= set(card[1].split())
    assert '<div class="semantic-title">Step 1</div>' in card[2] and "status: pending" in card[2]


@pytest.mark.unit
def test_an_object_holds_its_place_before_it_appears():
    scene = _chain(3, visible_at_open=1)
    html = _semantic_html(scene, opening_state(scene))
    assert html.count('class="semantic-column"') == 3            # every step already has its column
    assert re.search(r'class="semantic-object is-hidden [^"]*" data-object-id="s2"', html)
    assert not re.search(r'class="semantic-object is-hidden [^"]*" data-object-id="s0"', html)


@pytest.mark.unit
def test_an_object_the_scene_never_shows_gets_no_place():
    scene = _chain(3, visible_at_open=3)
    scene.opening_visible_ids = ["s0", "s1"]
    scene.closing_visible_ids = ["s0", "s1"]
    html = _semantic_html(scene, opening_state(scene))
    assert 'data-object-id="s2"' not in html and html.count('class="semantic-column"') == 2


@pytest.mark.unit
def test_flows_longer_than_four_steps_wrap_to_rows():
    for count, rows in ((4, 1), (5, 2), (8, 2), (9, 3)):
        scene = _chain(count)
        assert _semantic_html(scene, closing_state(scene)).count('class="semantic-row"') == rows


@pytest.mark.unit
def test_arrow_labels_split_onto_two_lines_and_size_the_gap():
    assert _label_lines("returns to") == ["returns to"]
    assert _label_lines("send to validate") == ["send to", "validate"]
    assert _label_lines("antidisestablishment") == ["antidisestablishment"]      # nowhere to split
    short, long = _chain(2, label="then"), _chain(2, label="send the validated request")
    gap = lambda scene: int(re.search(r"--flow-gap:(\d+)px", _semantic_html(scene, closing_state(scene)))[1])
    assert gap(short) == 84 and gap(long) > gap(short)
    assert '"lines":["send the","validated request"]' in page_html(long, title="t", state=closing_state(long))


@pytest.mark.unit
def test_a_label_may_not_touch_a_card_but_pattern_nodes_keep_their_allowance():
    def issues(card: bool) -> list[str]:
        return _issues({"viewport": [1280, 720], "title": [400, 20, 880, 70], "cells": [],
                        "semantic_text": [],
                        "nodes": [{"id": "box", "rect": [100, 300, 300, 400], "card": card}],
                        "labels": [{"text": "then", "rect": [290, 340, 390, 360]}]})

    assert issues(card=True) == ["edge label 'then' overlaps node 'box'"]
    assert issues(card=False) == []         # 10% of the label: inside the original 25% allowance


@pytest.mark.unit
def test_an_object_being_cleared_away_is_never_lit():
    scene = _chain(2)
    scene.beats[0].actions[0].kind = "hide"
    scene.beats[0].actions[0].target_ids = ["s1"]
    last = _snapshots(animation_html(scene, scene.beats[0], title="t", opening=opening_state(scene),
                                     duration=2))[-1]
    assert re.search(r'class="semantic-object is-hidden [^"]*" data-object-id="s1"', last)
    assert "is-active" not in last


@pytest.mark.integration
@pytest.mark.parametrize("count", [5, 6, 8])
def test_long_flows_pass_the_normal_layout_without_the_compact_fallback(count):
    scene = _chain(count)
    data = audit_html(page_html(scene, title="A long flow", state=closing_state(scene)))
    assert len(data["nodes"]) == count and len(data["labels"]) == count - 1


@pytest.mark.integration
def test_a_box_does_not_move_when_another_box_appears():
    from playwright.sync_api import sync_playwright

    scene = _chain(3, visible_at_open=1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        boxes = []
        for state in (opening_state(scene), closing_state(scene)):
            page.set_content(page_html(scene, title="Tool call", state=state))
            boxes.append(page.locator('[data-object-id="s0"]').bounding_box())
        hidden = page.locator('[data-object-id="s2"]')
        page.set_content(page_html(scene, title="Tool call", state=opening_state(scene)))
        assert page.locator('[data-object-id="s2"]').evaluate("e=>getComputedStyle(e).opacity") == "0"
        assert page.locator(".connections line").count() == 0      # no arrow to a box not yet shown
        browser.close()
    assert boxes[0] == boxes[1]
    assert hidden is not None


@pytest.mark.integration
def test_an_arrow_label_arrives_with_its_arrow():
    from playwright.sync_api import sync_playwright

    from generation.browser_scene import CAPTURE_ARGS

    scene = _chain(2, visible_at_open=1)                    # the second box appears, so its arrow is new
    document = animation_html(scene, scene.beats[0], title="t", opening=opening_state(scene), duration=2)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(document)
        page.evaluate("() => window.animationReady()")
        seen = []
        for time in (.4, 1.5):
            page.evaluate("t => window.seekAnimation(t)", time)
            seen.append(float(page.locator(".edge-label").evaluate("e=>getComputedStyle(e).opacity")))
        browser.close()
    assert 0 < seen[0] < .5 and seen[1] == 1


@pytest.mark.unit
def test_two_arrow_labels_on_one_spot_are_a_layout_defect():
    data = {"viewport": [1280, 720], "title": [400, 20, 880, 80], "nodes": [],
            "labels": [{"text": "invoke", "rect": [700, 180, 780, 205]},
                       {"text": "reject", "rect": [720, 182, 795, 207]}]}
    assert _issues(data) == ["edge label 'invoke' overlaps edge label 'reject'"]


@pytest.mark.integration
def test_a_level_arrow_and_a_stepped_arrow_from_one_piece_keep_their_labels_apart():
    ids = ["agent", "harness", "answer", "lookup", "error"]
    scene = BrowserScene.model_validate({
        "lesson_scene_id": "s", "pattern": "architecture",
        "objects": [{"id": i, "kind": "icon", "role": "operation", "label": i.title(),
                     "payload": {"asset_id": "server"}} for i in ids],
        "relationships": [
            {"source_id": "agent", "target_id": "harness", "kind": "flows_to", "label": "call"},
            {"source_id": "agent", "target_id": "answer", "kind": "flows_to", "label": "reply"},
            {"source_id": "harness", "target_id": "lookup", "kind": "flows_to", "label": "invoke"},
            {"source_id": "harness", "target_id": "error", "kind": "flows_to", "label": "reject"}],
        "beats": [{"narration_beat_id": "b", "actions": [{"kind": "hold", "target_ids": ["agent"]}],
                   "evidence": [{"claim_ids": ["c"], "object_ids": ["agent"], "kind": "label"}]}],
        "opening_visible_ids": ids, "closing_visible_ids": ids})
    data = audit_html(page_html(scene, title="Two ways out", state=closing_state(scene)))   # raises on overlap
    assert sorted(label["text"] for label in data["labels"]) == ["call", "invoke", "reject", "reply"]
