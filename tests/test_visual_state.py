import re
import json
import subprocess

import pytest

from core.schemas.browser_visual_plan import BrowserScene, BrowserVisualPlan, VisualAction, VisualObject
from core.schemas.lesson_plan import LessonPlan
from core.visual_assets import asset_inventory, resolve_asset
from core.visual_state import after_beat, closing_state, opening_state
from generation.browser_scene import page_html, render_scene
from generation.manim_visual_scene import compile_scene
from planner import browser_visual_plan, lesson_plan
from planner.browser_visual_plan import _normalise_v2_carryover
from planner.product_recipe import load_recipes
from verification.visual_plan_validation import VisualPlanValidationError, validate


def _binary_search():
    lesson = LessonPlan.model_validate({
        "schema_version": 2,
        "topic": "Binary search", "skill_id": "workflow_explainer",
        "learning_objective": "Understand how the search range shrinks.",
        "scenes": [{
            "id": "search", "title": "Check the array", "learning_goal": "Show the checks.",
            "beats": [
                {"id": "scan", "spoken_text": "Check 2, then 5, then 8.",
                 "claim_ids": ["ordered_checks"],
                 "visual_anchors": ["Check: 8", "2 ✗", "8 ✓"],
                 "claim_requirements": {"ordered_checks": ["sequence"]}},
                {"id": "discard", "spoken_text": "Discard the left half.",
                 "claim_ids": ["discard_left"], "visual_anchors": ["Array: 12, 16, 23, 38"],
                 "claim_requirements": {"discard_left": ["state_change"]}},
            ],
        }],
    })
    plan = BrowserVisualPlan.model_validate({
        "schema_version": 2,
        "topic": "Binary search", "skill_id": "workflow_explainer",
        "scenes": [{
            "lesson_scene_id": "search", "pattern": "workflow",
            "objects": [
                {"id": "array", "kind": "array", "role": "input", "label": "Array",
                 "payload": {"items": [2, 5, 8, 12, 16, 23, 38]}},
                {"id": "pointer", "kind": "pointer", "role": "operation", "label": "Check",
                 "payload": {"target_id": "array", "index": 0}},
                {"id": "target", "kind": "value", "role": "context", "label": "Target",
                 "payload": {"value": 8}},
            ],
            "relationships": [],
            "beats": [
                {"narration_beat_id": "scan", "actions": [
                    {"id": "show", "kind": "appear", "target_ids": ["array", "pointer", "target"]},
                    {"id": "check_2", "kind": "move", "target_ids": ["pointer"],
                     "params": {"index": 0}},
                    {"id": "compare_2", "kind": "compare", "target_ids": ["pointer", "target"]},
                    {"id": "check_5", "kind": "move", "target_ids": ["pointer"],
                     "params": {"index": 1}},
                    {"id": "compare_5", "kind": "compare", "target_ids": ["pointer", "target"]},
                    {"id": "check_8", "kind": "move", "target_ids": ["pointer"],
                     "params": {"index": 2}},
                    {"id": "compare_8", "kind": "compare", "target_ids": ["pointer", "target"]},
                ], "evidence": [{"claim_ids": ["ordered_checks"],
                                 "object_ids": ["array", "pointer"], "kind": "sequence",
                                 "action_ids": ["check_2", "check_5", "check_8"]}]},
                {"narration_beat_id": "discard", "actions": [
                    {"id": "discard_cells", "kind": "set_state", "target_ids": ["array"],
                     "params": {"discarded_indices": [0, 1, 2]}},
                ], "evidence": [{"claim_ids": ["discard_left"], "object_ids": ["array"],
                                 "kind": "state_change", "action_ids": ["discard_cells"]}]},
            ],
            "opening_visible_ids": [], "closing_visible_ids": ["array", "pointer", "target"],
            "carryover_ids": [],
        }],
    })
    return lesson, plan


@pytest.mark.unit
def test_binary_search_plan_executes_a_sequence_and_discard():
    lesson, plan = _binary_search()
    validate(lesson, plan, load_recipes()["workflow_explainer"])
    scene = plan.scenes[0]
    state = after_beat(opening_state(scene), scene, "scan")
    assert state.payloads["pointer"]["index"] == 2
    assert state.payloads["array"]["checked_results"] == {
        "0": "miss", "1": "miss", "2": "match"}
    state = after_beat(state, scene, "discard")
    assert state.payloads["array"]["discarded_indices"] == [0, 1, 2]
    assert closing_state(scene).payloads == state.payloads


@pytest.mark.unit
def test_semantic_browser_frame_draws_cells_and_discarded_range():
    _, plan = _binary_search()
    scene = plan.scenes[0]
    state = closing_state(scene)
    html = page_html(scene, title="Binary search", state=state)
    assert len(re.findall(r'<div class="semantic-cell(?: |")', html)) == 7
    assert len(re.findall(r'<div class="semantic-cell[^"]*is-discarded', html)) == 3
    assert 'class="semantic-check is-match"' in html
    assert "Check</div>" in html
    assert "Array" in html


@pytest.mark.unit
def test_curated_icon_is_embedded_and_asset_escape_is_rejected():
    assert "user" in asset_inventory()["icons"]
    assert resolve_asset("icon", "user").name == "user.svg"
    with pytest.raises(ValueError, match="unsafe visual asset"):
        resolve_asset("image", "../private.png")
    scene = BrowserScene.model_validate({
        "lesson_scene_id": "person", "pattern": "architecture",
        "objects": [{"id": "person", "kind": "icon", "role": "source", "label": "Person",
                     "payload": {"asset_id": "user"}}],
        "beats": [{"narration_beat_id": "b", "actions": [
            {"id": "show", "kind": "appear", "target_ids": ["person"]}],
            "evidence": [{"claim_ids": ["c"], "object_ids": ["person"],
                          "action_ids": ["show"], "kind": "asset"}]}],
        "opening_visible_ids": [], "closing_visible_ids": ["person"],
    })
    html = page_html(scene, title="A person makes a request",
                     state=after_beat(opening_state(scene), scene, "b"))
    assert "data:image/svg+xml;base64," in html
    assert '<figcaption>Person</figcaption>' in html


@pytest.mark.integration
def test_semantic_browser_frame_passes_real_layout_audit(tmp_path):
    _, plan = _binary_search()
    scene = plan.scenes[0]
    frame = render_scene(scene, tmp_path / "binary.png", title="Binary search",
                         state=closing_state(scene))
    assert frame.exists()


@pytest.mark.integration
def test_saved_v2_plan_renders_action_frames_and_video(monkeypatch, tmp_path):
    from composition import browser_video
    from narration.tts import Clip

    lesson, plan = _binary_search()
    audio = tmp_path / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", "6", str(audio)], check=True, capture_output=True)
    monkeypatch.setattr(browser_video, "synthesize",
                        lambda text, out_dir, engine: Clip(text, audio, 6.0))
    result = browser_video.build(lesson, plan, load_recipes()["workflow_explainer"],
                                 out_dir=tmp_path / "render", beat_transition=0)
    assert result.mp4.exists()
    assert len(result.frames) == 8


@pytest.mark.unit
def test_label_cannot_prove_a_v2_state_change():
    lesson, plan = _binary_search()
    scene = plan.scenes[0]
    discard = scene.beats[1]
    discard.evidence[0].kind = "label"
    with pytest.raises(VisualPlanValidationError, match="lacks state_change visual proof"):
        validate(lesson, plan, load_recipes()["workflow_explainer"])


@pytest.mark.unit
def test_v2_evidence_must_actually_be_visible():
    lesson, plan = _binary_search()
    lesson.scenes[0].beats[0].visual_anchors = []
    plan.scenes[0].opening_visible_ids = []
    plan.scenes[0].beats[0].actions[0].target_ids = ["array", "target"]
    with pytest.raises(VisualPlanValidationError, match="hidden evidence objects"):
        validate(lesson, plan, load_recipes()["workflow_explainer"])


@pytest.mark.unit
def test_new_incremented_counter_must_start_at_zero():
    lesson, plan = _binary_search()
    plan.scenes[0].objects.append(VisualObject.model_validate(
        {"id": "checks", "kind": "counter", "role": "metric", "label": "Checks",
         "payload": {"value": 6}}))
    plan.scenes[0].beats[0].actions.append(VisualAction.model_validate(
        {"id": "count", "kind": "increment", "target_ids": ["checks"], "params": {}}))
    with pytest.raises((VisualPlanValidationError, ValueError), match="must start at 0"):
        validate(lesson, plan, load_recipes()["workflow_explainer"])


@pytest.mark.unit
def test_chart_can_visually_compare_two_method_counts():
    lesson = LessonPlan.model_validate({
        "schema_version": 2, "topic": "Search methods", "skill_id": "algorithm_explainer",
        "learning_objective": "Compare checks", "scenes": [{"id": "s", "title": "Compare",
        "learning_goal": "Compare checks", "beats": [{"id": "b",
        "spoken_text": "Brute takes six checks; binary takes two.",
        "claim_ids": ["difference"], "visual_anchors": ["Brute: 6", "Binary: 2"],
        "claim_requirements": {"difference": ["comparison"]}}]}]})
    plan = BrowserVisualPlan.model_validate({
        "schema_version": 2, "topic": "Search methods", "skill_id": "algorithm_explainer",
        "scenes": [{"lesson_scene_id": "s", "pattern": "comparison", "render_mode": "browser",
        "objects": [{"id": "checks", "kind": "chart", "role": "metric",
        "label": "Checks", "payload": {"series": [
            {"label": "Brute", "value": 6}, {"label": "Binary", "value": 2}]}}],
        "beats": [{"narration_beat_id": "b", "actions": [
            {"id": "show", "kind": "appear", "target_ids": ["checks"]}],
            "evidence": [{"claim_ids": ["difference"], "object_ids": ["checks"],
                          "action_ids": ["show"], "kind": "comparison"}]}],
        "opening_visible_ids": [], "closing_visible_ids": ["checks"]}]})
    validate(lesson, plan, load_recipes()["algorithm_explainer"])
    html = page_html(plan.scenes[0], title="Compare", state=closing_state(plan.scenes[0]))
    assert "Brute: 6" in html and "Binary: 2" in html


@pytest.mark.unit
def test_cli_semantic_visuals_is_explicit_opt_in(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts import generate_video

    seen = []
    monkeypatch.setattr(generate_video.settings, "out_dir", tmp_path)
    monkeypatch.setattr(generate_video.browser_video, "generate", lambda *a, **kw: (
        seen.append(kw), SimpleNamespace(render=SimpleNamespace(mp4=tmp_path / "video.mp4")))[1])
    assert generate_video.main(["Binary search", "--renderer", "browser_v2", "--yes"]) == 0
    assert "schema_version" not in seen[-1]
    assert generate_video.main(["Binary search", "--renderer", "browser_v2",
                                "--semantic-visuals", "--yes"]) == 0
    assert seen[-1]["schema_version"] == 2
    with pytest.raises(SystemExit):
        generate_video.main(["Binary search", "--semantic-visuals"])


@pytest.mark.unit
def test_old_saved_plan_shape_remains_loadable():
    assert LessonPlan.model_validate({
        "topic": "Old", "skill_id": "workflow_explainer", "learning_objective": "Old",
        "scenes": [{"id": "s", "title": "Old", "learning_goal": "Old",
                    "beats": [{"id": "b", "spoken_text": "Old", "claim_ids": ["c"]}]}],
    }).schema_version == 1
    assert BrowserVisualPlan.model_validate({
        "topic": "Old", "skill_id": "workflow_explainer", "scenes": [{
            "lesson_scene_id": "s", "pattern": "workflow",
            "objects": [{"id": "box", "kind": "card", "role": "input", "label": "Old"}],
            "beats": [{"narration_beat_id": "b", "actions": [
                {"kind": "appear", "target_ids": ["box"]}], "evidence": [
                    {"claim_ids": ["c"], "object_ids": ["box"], "kind": "label"}]}],
            "opening_visible_ids": [], "closing_visible_ids": ["box"],
        }],
    }).schema_version == 1


@pytest.mark.unit
def test_v2_planners_send_semantic_contract_and_keep_versions_aligned():
    lesson, plan = _binary_search()
    skill = load_recipes()["workflow_explainer"]

    class Client:
        def __init__(self, response):
            self.response = response
            self.messages = None

        def chat(self, messages, **kwargs):
            self.messages = messages
            return self.response

    lesson_client = Client(lesson.model_dump_json())
    generated_lesson = lesson_plan.generate("Binary search", skill, client=lesson_client,
                                            schema_version=2)
    assert generated_lesson.schema_version == 2
    assert "state_change" in lesson_client.messages[0]["content"]

    visual_client = Client(plan.scenes[0].model_dump_json())
    generated_plan = browser_visual_plan.generate(generated_lesson, skill, client=visual_client,
                                                  schema_version=2)
    assert generated_plan.schema_version == 2
    assert "array" in visual_client.messages[0]["content"]
    assert generated_plan.scenes[0].beats[1].actions[0].params["discarded_indices"] == [0, 1, 2]

    replay_client = Client("unused")
    resumed = browser_visual_plan.generate(generated_lesson, skill, client=replay_client,
                                           schema_version=2,
                                           starting_scenes=generated_plan.scenes)
    assert replay_client.messages is None
    assert resumed == generated_plan


@pytest.mark.unit
def test_v2_normalises_scene_state_misplaced_inside_beats():
    _, plan = _binary_search()
    data = plan.scenes[0].model_dump()
    data["beats"][0]["opening_visible_ids"] = data.pop("opening_visible_ids")
    data["beats"][-1]["closing_visible_ids"] = data.pop("closing_visible_ids")
    data["beats"][-1]["actions"] = []
    data["beats"][-1]["evidence"][0]["action_ids"] = []
    repaired = _normalise_v2_carryover(data, None)
    scene = BrowserScene.model_validate(repaired)
    assert scene.closing_visible_ids == ["array", "pointer", "target"]
    assert scene.beats[-1].actions[0].kind == "hold"


@pytest.mark.unit
def test_v2_normalises_invisible_evidence_object_without_a_duplicate_box():
    _, plan = _binary_search()
    data = plan.scenes[0].model_dump()
    data["beats"][0]["actions"][0]["target_ids"] = ["array", "target"]
    repaired = _normalise_v2_carryover(data, None)
    assert repaired["beats"][0]["actions"][0] == {
        "id": "reveal_scan_pointer", "kind": "appear", "target_ids": ["pointer"]}


@pytest.mark.unit
def test_manim_compiler_uses_the_same_actions_without_model_written_code():
    _, plan = _binary_search()
    scene = plan.scenes[0].model_copy(update={"render_mode": "manim"})
    source = compile_scene(scene, title="Binary search", opening=opening_state(scene),
                           audio=[("audio/beat_00.wav", 2.0), ("audio/beat_01.wav", 2.0)])
    compile(source, "scene.py", "exec")
    assert 'self.add_sound(audio["path"])' in source
    assert 'elif kind == "move"' in source
    assert 'elif kind == "set_state"' in source
    assert 'paired_increment = next_action' in source


@pytest.mark.integration
def test_v2_manim_scene_renders_with_the_existing_sandbox(monkeypatch, tmp_path):
    from composition import browser_video
    from narration.tts import Clip

    lesson, plan = _binary_search()
    plan.scenes[0].render_mode = "manim"
    audio = tmp_path / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", "2", str(audio)], check=True, capture_output=True)
    monkeypatch.setattr(browser_video, "synthesize",
                        lambda text, out_dir, engine: Clip(text, audio, 2.0))
    result = browser_video.build(lesson, plan, load_recipes()["workflow_explainer"],
                                 out_dir=tmp_path / "manim-render")
    assert result.mp4.exists()
    assert len(result.scene_mp4s) == 1
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,duration", "-of", "json", str(result.mp4)],
                           check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    assert {stream["codec_type"] for stream in streams} == {"video", "audio"}
    assert all(3.5 <= float(stream["duration"]) <= 4.5 for stream in streams)
