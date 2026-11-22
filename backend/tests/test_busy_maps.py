"""Maps as the AI planned them live on 2026-11-21, busier than the hand-written fixtures: every
state of every beat must pass the layout check. Before the fixes, 4 of 7 system-design lessons
failed it (a recap scene's map pushed into the title) and an eighth failed with two arrow labels
on one spot (a health check in the same column as a load balancer)."""
from pathlib import Path

import pytest

from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from core.visual_state import apply_action, closing_state, opening_state
from generation.browser_scene import page_html
from verification.browser_layout import audit_html

FIXTURES = Path(__file__).parent / "fixtures" / "busy_maps"


@pytest.mark.integration
@pytest.mark.parametrize("name", ["health_check", "sharding_recap"])
def test_a_busy_map_passes_the_layout_check_at_every_step(name):
    folder = FIXTURES / name
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = BrowserVisualPlan.model_validate_json((folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    previous = None
    for index, scene in enumerate(plan.scenes):
        state = opening_state(scene, previous)
        for beat in scene.beats:
            for action in beat.actions:
                apply_action(state, action)
                audit_html(page_html(scene, title=lesson.scenes[index].title, state=state),
                           label=f"{name} scene {index + 1} {beat.narration_beat_id}")
        previous = closing_state(scene, previous)



@pytest.mark.integration
def test_a_piece_not_yet_built_shows_a_question_mark():
    """Reviewed on 2026-11-22: the dashed box a load balancer later fills read as a broken box,
    with requests already flowing through it. It now holds a '?': something is missing here."""
    from playwright.sync_api import sync_playwright

    from composition.slides import chrome_path

    folder = FIXTURES / "health_check"
    plan = BrowserVisualPlan.model_validate_json((folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    scene = plan.scenes[0]
    html = page_html(scene, title="The crash", state=closing_state(scene))
    assert "is-placeholder" in html
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(html)
        mark = page.evaluate("getComputedStyle(document.querySelector("
                             "'.semantic-piece.is-placeholder .piece-icons'), '::after').content")
        browser.close()
    assert mark == '"?"'


@pytest.mark.integration
def test_each_scene_is_framed_on_the_pieces_it_shows():
    """Reviewed on 2026-11-22 (a client's load-balancer video): the first scene showed two of the
    lesson's seven pieces, but the stage was sized for all seven, so the two sat small in an empty
    frame. Each scene is now framed on its own pieces, and the lines of text stay inside the frame."""
    from playwright.sync_api import sync_playwright

    from composition.slides import chrome_path

    folder = FIXTURES / "flash_sale"
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = BrowserVisualPlan.model_validate_json((folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    scene = plan.scenes[0]
    html = page_html(scene, title=lesson.scenes[0].title, state=closing_state(scene))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(html)
        width, lowest = page.evaluate("""() => {
            const shown = [...document.querySelectorAll('.semantic-object:not(.is-hidden)')]
                .filter(e => !e.classList.contains('semantic-caption-line')).map(e => e.getBoundingClientRect());
            const lines = [...document.querySelectorAll('.semantic-caption-line')].map(e => e.getBoundingClientRect());
            return [Math.max(...shown.map(r => r.right)) - Math.min(...shown.map(r => r.left)),
                    Math.max(...lines.map(r => r.bottom))];
        }""")
        browser.close()
    assert width >= 1280 * 0.3, width          # two pieces were about 200 px wide before
    assert lowest <= 720, lowest               # the question is not pushed out of the frame
