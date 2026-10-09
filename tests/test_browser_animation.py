import subprocess
import json

import pytest

from composition.slides import chrome_path
from core.schemas.browser_visual_plan import BrowserScene
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from core.visual_state import apply_action, opening_state
from generation.browser_scene import animation_html, render_animated_beat


def flow():
    return BrowserScene.model_validate({
        "lesson_scene_id": "harness", "pattern": "workflow",
        "objects": [
            {"id": "request", "kind": "message", "role": "input", "label": "Validated request"},
            {"id": "tool", "kind": "tool", "role": "output", "label": "Search tool"}],
        "relationships": [{"source_id": "request", "target_id": "tool",
                           "kind": "flows_to", "label": "Tool arguments"}],
        "beats": [{"narration_beat_id": "send", "actions": [
            {"id": "send_request", "kind": "connect", "target_ids": ["request", "tool"],
             "start_fraction": .1, "end_fraction": .9}],
            "evidence": [{"claim_ids": ["call"], "object_ids": ["request", "tool"],
                          "kind": "relationship", "action_ids": ["send_request"]}]}],
        "opening_visible_ids": ["request", "tool"], "closing_visible_ids": ["request", "tool"],
    })


@pytest.mark.unit
def test_animation_document_is_renderer_owned_and_escapes_script_content():
    scene = flow()
    scene.objects[0].label = "</script><script>not_code()</script>"
    document = animation_html(scene, scene.beats[0], title="Tool call",
                              opening=opening_state(scene), duration=2)
    assert "window.seekAnimation" in document
    assert "not_code()</script>" not in document
    assert '"windows": [[0.2, 1.8]]' in document


@pytest.mark.unit
@pytest.mark.parametrize("fps", [0, 61, 2.5, True])
def test_bad_frame_rate_rejected_before_launch(tmp_path, fps):
    scene = flow()
    with pytest.raises(ValueError, match="fps"):
        render_animated_beat(scene, scene.beats[0], tmp_path / "bad.mp4",
            title="Tool call", opening=opening_state(scene), duration=2, audio="unused.wav", fps=fps)


@pytest.mark.unit
def test_late_subframe_action_is_rejected_before_capture(tmp_path):
    scene = flow()
    scene.beats[0].actions[0].start_fraction = .99
    scene.beats[0].actions[0].end_fraction = 1
    with pytest.raises(ValueError, match="too short to capture"):
        render_animated_beat(scene, scene.beats[0], tmp_path / "late.mp4",
            title="Tool call", opening=opening_state(scene), duration=2,
            audio="unused.wav", fps=30)
    assert not (tmp_path / "late.auto.html").exists()


@pytest.mark.integration
def test_flow_packet_moves_and_seeking_is_reproducible(tmp_path):
    from playwright.sync_api import sync_playwright

    scene = flow()
    scene.beats[0].actions[0].end_fraction = 1
    document = animation_html(scene, scene.beats[0], title="Tool call",
                              opening=opening_state(scene), duration=2)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(document)
        page.evaluate("() => window.animationReady()")
        boxes = []
        for time in [.6, 1.2, .6]:
            page.evaluate("t => window.seekAnimation(t)", time)
            boxes.append(page.locator(".flow-packet").bounding_box())
        assert boxes[1]["x"] > boxes[0]["x"]  # linked steps read left to right
        assert boxes[0] == boxes[2]
        label = page.locator(".edge-label").bounding_box()
        assert label["y"] + label["height"] < boxes[0]["y"]  # label sits clear of the packet
        page.evaluate("() => window.seekAnimation(2)")
        assert page.locator(".flow-packet").evaluate("e=>getComputedStyle(e).opacity") == "0"
        completed_frame = page.screenshot(animations="allow")
        browser.close()
    audio = tmp_path / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", "2", str(audio)],
                   check=True, capture_output=True)
    frames = render_animated_beat(scene, scene.beats[0], tmp_path / "preview.mp4",
        title="Tool call", opening=opening_state(scene), duration=2, audio=audio, fps=10)
    assert len(frames) == 20
    assert frames[5].read_bytes() != frames[12].read_bytes()
    assert frames[-1].read_bytes() == completed_frame
    assert (tmp_path / "preview.mp4").exists()


@pytest.mark.integration
def test_harness_request_result_and_rejected_arguments_build_as_one_video(tmp_path, monkeypatch):
    from composition import browser_video
    from narration.tts import Clip
    from planner.product_recipe import load_recipes

    tool = {"id": "lookup", "kind": "tool", "role": "tool", "label": "Order lookup"}
    definitions = [
        ("Send structured arguments", "The request asks about order 42. Send validated arguments to the lookup tool.",
         [tool, {"id": "args", "kind": "code", "role": "input", "label": "Arguments",
                 "payload": {"source": '{"tool":"lookup_order","order_id":42}'}}],
         [("appear", ["args"], .05, .25), ("connect", ["args", "lookup"], .35, .8)],
         ["args", "lookup"], []),
        ("Use the returned data", "The lookup returns shipped status and tracking AB42. This is tool data, not a guessed answer.",
         [tool, {"id": "result", "kind": "code", "role": "output", "label": "Returned data",
                 "payload": {"source": '{"status":"shipped","tracking":"AB42"}'}}],
         [("appear", ["result"], .05, .25), ("connect", ["lookup", "result"], .35, .8)],
         ["lookup", "result"], ["lookup"]),
        ("Reject missing arguments before execution", "A missing order ID is rejected. After supplying 42, one corrected attempt reaches the tool.",
         [tool, {"id": "invalid", "kind": "code", "role": "input", "label": "Invalid arguments",
                 "payload": {"source": '{"order_id":null}'}},
          {"id": "error", "kind": "code", "role": "audit", "label": "Validation error",
                 "payload": {"source": '{"error":"order_id is required"}'}},
          {"id": "corrected", "kind": "code", "role": "input", "label": "Corrected arguments",
                 "payload": {"source": '{"order_id":42}'}}],
         [("appear", ["invalid"], .02, .15), ("appear", ["error"], .2, .35),
          ("appear", ["corrected"], .4, .55), ("connect", ["corrected", "lookup"], .6, .9)],
         ["corrected", "lookup"], ["lookup"]),
    ]
    scenes, lessons = [], []
    for index, (title, speech, objects, actions, endpoints, carryover) in enumerate(definitions):
        beat_id, claim_id, scene_id = f"b{index}", f"c{index}", f"s{index}"
        scenes.append({"lesson_scene_id": scene_id, "pattern": "workflow", "objects": objects,
            "relationships": [{"source_id": endpoints[0], "target_id": endpoints[1],
                               "kind": "flows_to", "label": "Tool call" if index != 1 else "Result"}],
            "beats": [{"narration_beat_id": beat_id, "actions": [
                {"id": f"a{index}_{number}", "kind": kind, "target_ids": targets,
                 "start_fraction": start, "end_fraction": end}
                for number, (kind, targets, start, end) in enumerate(actions)],
                "evidence": [{"claim_ids": [claim_id], "object_ids": endpoints,
                              "kind": "relationship", "action_ids": [f"a{index}_{len(actions)-1}"]}]}],
            "opening_visible_ids": ["lookup"], "closing_visible_ids": [obj["id"] for obj in objects],
            "carryover_ids": carryover})
        lessons.append({"id": scene_id, "title": title, "learning_goal": title,
            "example": "Order 42", "beats": [{"id": beat_id, "spoken_text": speech,
                "claim_ids": [claim_id], "visual_anchors": ["Order lookup"],
                "claim_requirements": {claim_id: ["relationship"]}}]})
    lesson = LessonPlan(schema_version=2, topic="An order lookup harness", skill_id="workflow_explainer",
        audience="Beginner", learning_objective="Trace invocation, returned data and validation", scenes=lessons)
    plan = BrowserVisualPlan(schema_version=2, topic=lesson.topic, skill_id=lesson.skill_id, scenes=scenes)
    lesson_path, plan_path = tmp_path / "lesson_plan.json", tmp_path / "browser_visual_plan.json"
    lesson_path.write_text(lesson.model_dump_json(indent=2), encoding="utf-8")
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    audio = tmp_path / "synthetic-audio.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", "3", str(audio)],
                   check=True, capture_output=True)
    monkeypatch.setattr(browser_video, "synthesize", lambda text, **kwargs: Clip(text, audio, 3))
    result = browser_video.build(LessonPlan.model_validate_json(lesson_path.read_text()),
        BrowserVisualPlan.model_validate_json(plan_path.read_text()), load_recipes()["workflow_explainer"],
        out_dir=tmp_path / "render", fps=10)
    assert result.mp4.exists()
    assert len(result.scene_mp4s) == 3
    assert len(result.frames) == 90
    duration = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(result.mp4)],
        check=True, capture_output=True, text=True)
    assert float(duration.stdout) == pytest.approx(9, abs=.1)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content((tmp_path / "render" / "beats" / "scene_02_00.auto.html").read_text(encoding="utf-8"))
        page.evaluate("() => window.animationReady()")
        page.evaluate("() => window.seekAnimation(2.8)")
        edge = page.locator(".connections .edge").bounding_box()
        obstacle = page.locator('[data-object-id="error"]').bounding_box()
        assert (edge["x"] + edge["width"] <= obstacle["x"] or obstacle["x"] + obstacle["width"] <= edge["x"]
                or edge["y"] + edge["height"] <= obstacle["y"]
                or obstacle["y"] + obstacle["height"] <= edge["y"])  # arrow avoids the error box
        browser.close()


def _snapshots(document: str) -> list[str]:
    data = document.split('<script id="animation-plan" type="application/json">')[1]
    return json.loads(data.split("</script>")[0].replace("<\\/", "</"))["snapshots"]


@pytest.mark.unit
def test_an_array_is_never_dimmed_as_an_earlier_step():
    from scripts.video_regression import cases

    scene = BrowserVisualPlan.model_validate_json(
        (cases()["binary_search"] / "browser_visual_plan.json").read_text(encoding="utf-8")).scenes[0]
    state = opening_state(scene)
    for beat in scene.beats:    # actions name the pointer and the target far more often than the array
        document = animation_html(scene, beat, title="Search", opening=state, duration=4)
        assert not any("is-past" in snapshot for snapshot in _snapshots(document))
        for action in beat.actions:
            apply_action(state, action)


@pytest.mark.unit
def test_a_flow_still_dims_the_step_the_beat_has_not_touched():
    scene = flow()
    scene.beats[0].actions[0].kind = "highlight"
    scene.beats[0].actions[0].target_ids = ["tool"]
    last = _snapshots(animation_html(scene, scene.beats[0], title="Tool call",
                                     opening=opening_state(scene), duration=2))[-1]
    assert 'class="semantic-object is-past semantic-note" data-object-id="request"' in last
    assert 'class="semantic-object semantic-note" data-object-id="tool"' in last
