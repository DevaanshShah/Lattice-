import pytest

from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from planner.product_recipe import load_recipes
from scripts.video_regression import (CaseResult, cases, exit_code, parse_ssim_stats,
                                      silent_seconds, table)
from verification.visual_plan_validation import validate

EXPECTED = {"binary_search", "binary_search_manim", "binary_search_stills", "chart_compare",
            "legacy_cards", "structured_args", "tool_flow"}


@pytest.mark.unit
def test_fixed_set_covers_every_render_route():
    found = cases()
    assert set(found) == EXPECTED
    plans = {name: BrowserVisualPlan.model_validate_json(
        (folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
        for name, folder in found.items()}
    timed = {name for name, plan in plans.items()
             if all(action.start_fraction is not None
                    for scene in plan.scenes for beat in scene.beats for action in beat.actions)}
    assert {"tool_flow", "binary_search", "structured_args"} <= timed       # continuous animation
    assert "binary_search_stills" not in timed                              # still-frame route
    assert plans["binary_search_manim"].scenes[0].render_mode == "manim"    # Manim route
    assert plans["legacy_cards"].schema_version == 1                        # original card renderer


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixed_plan_still_passes_the_validator(name):
    folder = cases()[name]
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = BrowserVisualPlan.model_validate_json(
        (folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    validate(lesson, plan, load_recipes()[lesson.skill_id])


@pytest.mark.unit
def test_silent_narration_length_follows_the_word_count_with_a_floor():
    assert silent_seconds("Short line.") == 2.0
    assert silent_seconds(" ".join(["word"] * 23)) == 10.0


@pytest.mark.unit
def test_ssim_stats_are_read_per_frame():
    stats = ("n:1 Y:0.99 U:1.0 V:1.0 All:0.995000 (23.0)\n"
             "n:2 Y:0.50 U:0.9 V:0.9 All:0.633333 (4.3)\n")
    assert parse_ssim_stats(stats) == [0.995, 0.633333]
    assert parse_ssim_stats("") == []


@pytest.mark.unit
def test_exit_code_separates_failures_from_changes_that_need_a_look():
    same = CaseResult("a", changed=False, min_ssim=1.0)
    assert exit_code([same]) == 0
    assert exit_code([same, CaseResult("b", status="skipped")]) == 0
    assert exit_code([same, CaseResult("b", changed=True, min_ssim=0.8)]) == 2
    assert exit_code([same, CaseResult("b")]) == 2                    # no baseline yet
    assert exit_code([CaseResult("b", changed=True), CaseResult("c", status="fail")]) == 1


@pytest.mark.unit
def test_report_table_names_the_worst_frame_of_a_changed_case():
    text = table([CaseResult("a", changed=True, min_ssim=0.8123, worst_time=3.25, duration=9.0,
                             frames_compared=270),
                  CaseResult("b", status="fail", detail="plan no longer validates: x")])
    assert "CHANGED (lowest SSIM 0.8123 at 3.2s)" in text or "CHANGED (lowest SSIM 0.8123 at 3.3s)" in text
    assert "| b | FAIL |" in text and "plan no longer validates: x" in text


@pytest.mark.unit
def test_manim_cases_are_skipped_for_a_named_environment_reason(monkeypatch):
    import subprocess

    from core.config import settings
    from scripts import video_regression

    monkeypatch.setattr(settings, "exec_mode", "docker")
    answers = {"info": 1, "image": 0}
    monkeypatch.setattr(video_regression.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, answers[cmd[1]]))
    assert video_regression.manim_unavailable() == "Docker is not running"
    answers.update(info=0, image=1)
    assert "is missing" in video_regression.manim_unavailable()
    answers.update(image=0)
    assert video_regression.manim_unavailable() == ""


@pytest.mark.unit
def test_report_table_keeps_a_multi_line_error_in_one_cell():
    text = table([CaseResult("a", status="fail", detail="RuntimeError: first line\nsecond | line")])
    assert text.count("\n") == 2 and "first line second / line" in text
