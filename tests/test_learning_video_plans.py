import json
from pathlib import Path

import pytest

from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from generation.browser_scene import page_html
from planner import browser_visual_plan, lesson_plan, product_recipe
from verification import browser_layout
from verification.browser_layout import BrowserLayoutError
from verification.visual_plan_validation import VisualPlanValidationError, validate


def _lesson() -> LessonPlan:
    return LessonPlan.model_validate({
        "topic": "Agent harness", "skill_id": "workflow_explainer",
        "learning_objective": "Explain a safe support action.",
        "scenes": [{
            "id": "ticket_flow", "title": "From ticket to action",
            "learning_goal": "Show the harness workflow.",
            "beats": [
                {"id": "receive_ticket", "spoken_text": "The customer message enters the harness.",
                 "claim_ids": ["ticket_enters"], "visual_anchors": ["Agent harness"]},
                {"id": "check_policy", "spoken_text": "A policy check permits the reset tool.",
                 "claim_ids": ["policy_checked", "tool_permitted"],
                 "visual_anchors": ["Reset allowed", "Secure reset link"]},
            ],
        }],
    })


def _visual(*, cover_policy: bool = True, pattern: str = "workflow") -> BrowserVisualPlan:
    claims = ["policy_checked", "tool_permitted"] if cover_policy else ["policy_checked"]
    return BrowserVisualPlan.model_validate({
        "topic": "Agent harness", "skill_id": "workflow_explainer",
        "scenes": [{
            "lesson_scene_id": "ticket_flow", "pattern": pattern,
            "objects": [
                {"id": "ticket", "kind": "message", "role": "input", "label": "Login fails"},
                {"id": "harness", "kind": "node", "role": "operation", "label": "Agent harness"},
                {"id": "policy", "kind": "gate", "role": "decision", "label": "Reset allowed"},
                {"id": "reset", "kind": "tool", "role": "output", "label": "Secure reset link"},
            ],
            "relationships": [
                {"source_id": "ticket", "target_id": "harness", "kind": "flows_to", "label": "routes"},
                {"source_id": "harness", "target_id": "policy", "kind": "checks"},
                {"source_id": "policy", "target_id": "reset", "kind": "branches_to"},
            ],
            "beats": [
                {"narration_beat_id": "receive_ticket",
                 "actions": [{"kind": "appear", "target_ids": ["ticket", "harness"]}],
                 "evidence": [{"claim_ids": ["ticket_enters"], "object_ids": ["ticket", "harness"],
                               "kind": "relationship"}]},
                {"narration_beat_id": "check_policy",
                 "actions": [{"kind": "activate", "target_ids": ["policy", "reset"]}],
                 "evidence": [{"claim_ids": claims, "object_ids": ["policy", "reset"],
                               "kind": "state"}]},
            ],
            "opening_visible_ids": ["ticket"],
            "closing_visible_ids": ["ticket", "harness", "policy", "reset"],
        }],
    })


@pytest.mark.unit
def test_visual_plan_covers_every_narration_claim_and_skill_role():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    validate(_lesson(), _visual(), skill)


@pytest.mark.unit
def test_visual_plan_rejects_narration_claim_without_visible_evidence():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    with pytest.raises(VisualPlanValidationError, match="tool_permitted"):
        validate(_lesson(), _visual(cover_policy=False), skill)


@pytest.mark.unit
def test_visual_plan_requires_locked_narration_anchors_to_be_visible():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    lesson = _lesson()
    first = lesson.scenes[0].beats[0].model_copy(update={"visual_anchors": ["Agent harness"]})
    passing = lesson.model_copy(update={
        "scenes": [lesson.scenes[0].model_copy(update={
            "beats": [first, lesson.scenes[0].beats[1]],
        })],
    })
    validate(passing, _visual(), skill)

    missing = first.model_copy(update={"visual_anchors": ["1000 items → ≤10 checks"]})
    failing = lesson.model_copy(update={
        "scenes": [lesson.scenes[0].model_copy(update={
            "beats": [missing, lesson.scenes[0].beats[1]],
        })],
    })
    with pytest.raises(VisualPlanValidationError, match="1000 items"):
        validate(failing, _visual(), skill)


@pytest.mark.unit
def test_visual_plan_rejects_skill_pattern_drift():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    with pytest.raises(VisualPlanValidationError, match="disallowed pattern"):
        validate(_lesson(), _visual(pattern="metric"), skill)


@pytest.mark.unit
def test_lesson_and_visual_planners_send_the_locked_contract_to_the_llm():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    lesson_data = _lesson().model_dump_json()

    class LessonClient:
        def __init__(self):
            self.messages = []

        def chat(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return lesson_data

    lesson_client = LessonClient()
    lesson = lesson_plan.generate("Agent harness", skill, client=lesson_client)
    assert "Required visual roles: input, operation, output" in lesson_client.messages[-1]["content"]
    assert "visual_anchors" in lesson_client.messages[0]["content"]
    assert lesson_client.kwargs == {"max_tokens": 4096, "attempts": 1, "timeout": 60.0}

    visual_data = _visual().scenes[0].model_dump_json()

    class VisualClient:
        def __init__(self):
            self.messages = []

        def chat(self, messages, **kwargs):
            self.messages = messages
            self.kwargs = kwargs
            return visual_data

    visual_client = VisualClient()
    plan = browser_visual_plan.generate(lesson, skill, client=visual_client)
    assert "Locked lesson scene" in visual_client.messages[-1]["content"]
    assert "Allowed patterns: workflow, transformation, decision, timeline" in visual_client.messages[-1]["content"]
    assert visual_client.kwargs == {"max_tokens": 4096, "attempts": 1, "timeout": 60.0}
    assert plan.skill_id == skill.id


@pytest.mark.unit
def test_lesson_planner_repairs_missing_visual_anchors():
    skill = product_recipe.load_recipes()["workflow_explainer"]
    valid = _lesson().model_dump()
    invalid = json.loads(json.dumps(valid))
    for scene in invalid["scenes"]:
        for beat in scene["beats"]:
            beat.pop("visual_anchors", None)

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return json.dumps(invalid if len(self.calls) == 1 else valid)

    client = Client()
    result = lesson_plan.generate("Agent harness", skill, client=client)
    assert len(client.calls) == 2
    assert "visual_anchors required" in client.calls[1][-1]["content"]
    assert result.scenes[0].beats[0].visual_anchors == ["Agent harness"]


def _two_scene_lesson() -> LessonPlan:
    return LessonPlan.model_validate({
        "topic": "Agent harness", "skill_id": "workflow_explainer",
        "learning_objective": "Explain a safe support action.",
        "scenes": [
            {"id": "receive", "title": "Receive", "learning_goal": "Show the input.",
             "beats": [{"id": "receive_beat", "spoken_text": "A ticket arrives.",
                        "claim_ids": ["ticket_arrives"]}]},
            {"id": "resolve", "title": "Resolve", "learning_goal": "Show the outcome.",
             "beats": [{"id": "resolve_beat", "spoken_text": "The harness resolves it.",
                        "claim_ids": ["ticket_resolved"]}]},
        ],
    })


def _scene_json(scene_id: str, beat_id: str, claim_id: str, *, pattern: str,
                carryover: bool, include_output: bool = False) -> str:
    objects = [{"id": "ticket", "kind": "message", "role": "input", "label": "Support ticket"},
               {"id": "harness", "kind": "node", "role": "operation", "label": "Agent harness"}]
    if include_output:
        objects.append({"id": "answer", "kind": "document", "role": "output",
                        "label": "Resolved answer"})
    targets = ["ticket", "harness"] + (["answer"] if include_output else [])
    scene = {
        "lesson_scene_id": scene_id, "pattern": pattern, "objects": objects,
        "relationships": [{"source_id": "ticket", "target_id": "harness",
                           "kind": "flows_to", "label": "routes"}],
        "beats": [{"narration_beat_id": beat_id,
                   "actions": [{"kind": "appear", "target_ids": targets}],
                   "evidence": [{"claim_ids": [claim_id], "object_ids": targets,
                                 "kind": "relationship"}]}],
        "opening_visible_ids": ["ticket", "harness"] if carryover else [],
        "closing_visible_ids": targets,
        "carryover_ids": ["ticket", "harness"] if carryover else [],
    }
    return BrowserVisualPlan.model_validate({
        "topic": "Agent harness", "skill_id": "workflow_explainer", "scenes": [scene]
    }).scenes[0].model_dump_json()


@pytest.mark.unit
def test_visual_planner_generates_scenes_sequentially_with_previous_closing_state():
    lesson = _two_scene_lesson()
    skill = product_recipe.load_recipes()["workflow_explainer"]
    replies = [
        _scene_json("receive", "receive_beat", "ticket_arrives",
                    pattern="workflow", carryover=False),
        _scene_json("resolve", "resolve_beat", "ticket_resolved",
                    pattern="transformation", carryover=True, include_output=True),
    ]

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return replies[len(self.calls) - 1]

    client = Client()
    plan = browser_visual_plan.generate(lesson, skill, client=client)
    assert len(client.calls) == 2
    assert "Previous closing objects available for exact carryover:\n[]" in client.calls[0][-1]["content"]
    assert '"id": "ticket"' in client.calls[1][-1]["content"]
    assert '"label": "Support ticket"' in client.calls[1][-1]["content"]
    assert [scene.lesson_scene_id for scene in plan.scenes] == ["receive", "resolve"]


@pytest.mark.unit
def test_visual_planner_retries_only_the_invalid_scene():
    lesson = _two_scene_lesson()
    skill = product_recipe.load_recipes()["workflow_explainer"]
    replies = [
        _scene_json("receive", "receive_beat", "ticket_arrives",
                    pattern="workflow", carryover=False),
        _scene_json("wrong_scene", "resolve_beat", "ticket_resolved",
                    pattern="transformation", carryover=True, include_output=True),
        _scene_json("resolve", "resolve_beat", "ticket_resolved",
                    pattern="transformation", carryover=True, include_output=True),
    ]

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return replies[len(self.calls) - 1]

    client = Client()
    plan = browser_visual_plan.generate(lesson, skill, client=client)
    assert len(client.calls) == 3
    assert sum("Scene 1 of 2" in call[1]["content"] for call in client.calls) == 1
    assert "Repair only this scene" in client.calls[2][-1]["content"]
    assert plan.scenes[-1].lesson_scene_id == "resolve"


@pytest.mark.unit
def test_visual_planner_repairs_missing_narration_anchor():
    lesson = _lesson()
    locked = lesson.scenes[0].beats[0].model_copy(update={"visual_anchors": ["1000 checks"]})
    lesson = lesson.model_copy(update={
        "scenes": [lesson.scenes[0].model_copy(update={
            "beats": [locked, lesson.scenes[0].beats[1]],
        })],
    })
    skill = product_recipe.load_recipes()["workflow_explainer"]
    first = _visual().scenes[0]
    fixed_objects = [obj.model_copy(update={"label": "1000 checks"}) if obj.id == "harness" else obj
                     for obj in first.objects]
    replies = [first.model_dump_json(),
               first.model_copy(update={"objects": fixed_objects}).model_dump_json()]

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return replies[len(self.calls) - 1]

    client = Client()
    plan = browser_visual_plan.generate(lesson, skill, client=client)
    assert len(client.calls) == 2
    assert "Every visual_anchor" in client.calls[1][-1]["content"]
    assert next(obj.label for obj in plan.scenes[0].objects if obj.id == "harness") == "1000 checks"


@pytest.mark.unit
def test_repeated_adjacent_pattern_requires_carryover():
    lesson = _two_scene_lesson()
    skill = product_recipe.load_recipes()["workflow_explainer"]
    first = BrowserVisualPlan.model_validate_json(
        '{"topic":"Agent harness","skill_id":"workflow_explainer","scenes":[' +
        _scene_json("receive", "receive_beat", "ticket_arrives",
                    pattern="workflow", carryover=False) + ']}').scenes[0]
    second = BrowserVisualPlan.model_validate_json(
        '{"topic":"Agent harness","skill_id":"workflow_explainer","scenes":[' +
        _scene_json("resolve", "resolve_beat", "ticket_resolved",
                    pattern="workflow", carryover=True, include_output=True) + ']}').scenes[0]
    validate(lesson, BrowserVisualPlan(topic=lesson.topic, skill_id=skill.id,
                                       scenes=[first, second]), skill)
    without_carryover = second.model_copy(update={"carryover_ids": [], "opening_visible_ids": []})
    with pytest.raises(VisualPlanValidationError, match="explicit carryover"):
        validate(lesson, BrowserVisualPlan(topic=lesson.topic, skill_id=skill.id,
                                           scenes=[first, without_carryover]), skill)


@pytest.mark.unit
def test_visual_plan_rejects_reused_closing_id_without_exact_carryover():
    lesson = _two_scene_lesson()
    skill = product_recipe.load_recipes()["workflow_explainer"]
    first = BrowserVisualPlan.model_validate_json(
        '{"topic":"Agent harness","skill_id":"workflow_explainer","scenes":[' +
        _scene_json("receive", "receive_beat", "ticket_arrives",
                    pattern="workflow", carryover=False) + ']}').scenes[0]
    second = BrowserVisualPlan.model_validate_json(
        '{"topic":"Agent harness","skill_id":"workflow_explainer","scenes":[' +
        _scene_json("resolve", "resolve_beat", "ticket_resolved",
                    pattern="transformation", carryover=True, include_output=True) + ']}').scenes[0]
    reused_without_carryover = second.model_copy(update={
        "carryover_ids": ["ticket"], "opening_visible_ids": ["ticket"],
    })
    with pytest.raises(VisualPlanValidationError, match="without carryover"):
        validate(lesson, BrowserVisualPlan(topic=lesson.topic, skill_id=skill.id,
                                           scenes=[first, reused_without_carryover]), skill)


@pytest.mark.unit
@pytest.mark.parametrize("pattern", [
    "workflow", "architecture", "decision", "comparison", "transformation", "timeline",
    "feedback_loop", "metric", "contour",
])
def test_browser_scene_compiler_owns_layout_for_every_supported_pattern(pattern):
    scene = _visual().scenes[0].model_copy(update={"pattern": pattern})
    html = page_html(scene, title="The Agent Checks Policy", active_beat_id="check_policy")
    assert f'class="frame {pattern}"' in html
    assert 'data-object-id="ticket"' in html
    assert 'kind-message role-input' in html
    assert 'data-object-id="policy"' in html
    assert 'class="connections"' in html
    assert 'is-active' in html
    assert 'edge-label' in html
    assert 'routes' in html
    if pattern == "feedback_loop":
        assert 'translateY(-10px)' in html
    if pattern == "contour":
        assert 'class="contour-path"' in html


@pytest.mark.unit
def test_browser_scene_hides_objects_until_their_visual_beat():
    html = page_html(_visual().scenes[0], title="The Agent Checks Policy", active_beat_id="receive_ticket")
    assert 'data-object-id="policy"' in html
    assert 'role-decision is-hidden' in html


@pytest.mark.unit
def test_browser_scene_uses_dense_layout_for_large_workflows():
    scene = _visual().scenes[0]
    extra = [scene.objects[0].model_copy(update={"id": f"extra_{i}"}) for i in range(3)]
    dense = scene.model_copy(update={"objects": [*scene.objects, *extra]})
    html = page_html(dense, title="Large workflow", active_beat_id="receive_ticket")
    assert 'class="frame workflow dense"' in html

    comparison = dense.model_copy(update={"pattern": "comparison", "objects": dense.objects[:6]})
    assert 'class="frame comparison dense"' in page_html(comparison, title="Comparison")
    assert 'class="frame comparison dense compact"' in page_html(
        comparison, title="Comparison", layout_mode="compact")


@pytest.mark.unit
def test_browser_layout_rejects_clipping_title_overlap_and_hidden_label_collisions():
    issues = browser_layout._issues({
        "viewport": [1280, 720], "title": [400, 40, 880, 90],
        "nodes": [{"id": "top", "rect": [450, 70, 700, 180]},
                  {"id": "offscreen", "rect": [1100, 600, 1300, 700]}],
        "labels": [{"text": "routes", "rect": [500, 100, 560, 118]},
                   {"text": "clipped", "rect": [-3, 300, 60, 318]}],
    })
    assert "title overlaps node 'top'" in issues
    assert "node 'offscreen' is clipped" in issues
    assert "edge label 'routes' overlaps node 'top'" in issues
    assert "edge label 'clipped' is clipped" in issues


@pytest.mark.unit
def test_browser_layout_error_preserves_machine_readable_evidence():
    geometry = {"viewport": [1280, 720], "nodes": [], "labels": []}
    error = BrowserLayoutError("scene one", ["node 'x' is clipped"], geometry)
    assert error.issues == ["node 'x' is clipped"]
    assert error.geometry is geometry
    assert "scene one failed browser layout QA" in str(error)


@pytest.mark.unit
def test_browser_scene_runs_geometry_qa_before_screenshot(monkeypatch, tmp_path):
    from generation import browser_scene

    seen = []
    monkeypatch.setattr(browser_scene, "audit_html", lambda document, **kwargs: seen.append(kwargs["label"]))
    monkeypatch.setattr(browser_scene, "render_html", lambda document, out_png, **kwargs: Path(out_png))
    result = browser_scene.render_scene(_visual().scenes[0], tmp_path / "frame.png",
                                        title="The Agent Checks Policy", active_beat_id="check_policy")
    assert result.name == "frame.png"
    assert seen == ["browser scene 'ticket_flow'"]


@pytest.mark.unit
def test_browser_video_uses_measured_beat_audio_and_final_scene_hold(monkeypatch, tmp_path):
    from composition import browser_video
    from narration.tts import Clip

    skill = product_recipe.load_recipes()["workflow_explainer"]
    calls = []

    def fake_synthesize(text, *, out_dir, engine):
        path = tmp_path / f"{len(calls)}.mp3"
        path.write_bytes(b"audio")
        return Clip(text, path, 2.0)

    def fake_render(scene, out_png, *, title, active_beat_id):
        path = tmp_path / Path(out_png).name
        path.write_bytes(b"png")
        return path

    def fake_norm(frame, out_mp4, *, seconds, fps, audio):
        calls.append(seconds)
        path = Path(out_mp4)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mp4")
        return path

    def fake_concat(clips, out_mp4, **kwargs):
        path = Path(out_mp4)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mp4")
        return path

    monkeypatch.setattr(browser_video, "synthesize", fake_synthesize)
    monkeypatch.setattr(browser_video, "render_scene", fake_render)
    monkeypatch.setattr(browser_video, "_norm_clip", fake_norm)
    monkeypatch.setattr(browser_video, "_concat_clips", fake_concat)

    result = browser_video.build(_lesson(), _visual(), skill, out_dir=tmp_path, transition=0,
                                 beat_transition=0)
    assert calls == [2.4, 3.0]
    assert result.mp4.exists()
    assert len(result.frames) == 2
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert any(event["stage"] == "stitch" and event["status"] == "passed"
               for event in report["events"])


@pytest.mark.unit
def test_browser_video_records_layout_failure_and_retries_compact(monkeypatch, tmp_path):
    from composition import browser_video
    from narration.tts import Clip

    skill = product_recipe.load_recipes()["workflow_explainer"]
    layouts = []

    def fake_synthesize(text, *, out_dir, engine):
        path = tmp_path / "audio.mp3"
        path.write_bytes(b"audio")
        return Clip(text, path, 1.0)

    def fake_render(scene, out_png, *, title, active_beat_id, layout_mode="auto"):
        layouts.append(layout_mode)
        if len(layouts) == 1:
            raise BrowserLayoutError("scene", ["node 'ticket' is clipped"], {"viewport": [1280, 720]})
        path = Path(out_png)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return path

    def fake_media(_inputs, out_path, **kwargs):
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mp4")
        return path

    monkeypatch.setattr(browser_video, "synthesize", fake_synthesize)
    monkeypatch.setattr(browser_video, "render_scene", fake_render)
    monkeypatch.setattr(browser_video, "_norm_clip", fake_media)
    monkeypatch.setattr(browser_video, "_concat_clips", fake_media)

    browser_video.build(_lesson(), _visual(), skill, out_dir=tmp_path,
                        transition=0, beat_transition=0)
    assert layouts[:2] == ["auto", "compact"]
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    retries = [event for event in report["events"] if event["status"] == "retry"]
    assert retries[0]["category"] == "layout"
    assert retries[0]["issues"] == ["node 'ticket' is clipped"]
    assert retries[0]["action"] == "retry_compact_layout"


@pytest.mark.unit
def test_browser_generation_locks_plans_before_rendering(monkeypatch, tmp_path):
    from composition import browser_video

    skill = product_recipe.load_recipes()["workflow_explainer"]
    seen = []
    final = tmp_path / "browser-video.mp4"
    final.write_bytes(b"mp4")

    monkeypatch.setattr(browser_video.product_recipe, "pick_recipe", lambda topic, recipe: skill)
    monkeypatch.setattr(browser_video.lesson_plan, "generate",
                        lambda topic, selected, client: (seen.append("lesson"), _lesson())[1])
    monkeypatch.setattr(browser_video.browser_visual_plan, "generate",
                        lambda lesson, selected, client: (seen.append("visual"), _visual())[1])
    monkeypatch.setattr(browser_video, "build",
                        lambda lesson, plan, selected, **kwargs: (seen.append("render"),
                            browser_video.BrowserVideoResult(final, [], []))[1])

    result = browser_video.generate("Agent harness", out_dir=tmp_path, client=object(),
                                    approve_fn=lambda lesson: (seen.append("approve"), lesson)[1])
    assert seen == ["lesson", "approve", "visual", "render"]
    assert result.render.mp4 == final
    assert (tmp_path / "lesson_plan.json").exists()
    assert (tmp_path / "browser_visual_plan.json").exists()
    assert json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))["status"] == "complete"


@pytest.mark.unit
def test_browser_generation_persists_failure_stage(monkeypatch, tmp_path):
    from composition import browser_video

    skill = product_recipe.load_recipes()["workflow_explainer"]
    monkeypatch.setattr(browser_video.product_recipe, "pick_recipe", lambda topic, recipe: skill)
    monkeypatch.setattr(browser_video.lesson_plan, "generate",
                        lambda topic, selected, client: (_ for _ in ()).throw(RuntimeError("provider down")))

    with pytest.raises(RuntimeError, match="provider down"):
        browser_video.generate("Agent harness", out_dir=tmp_path, client=object())
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["events"][-1]["stage"] == "lesson_plan"
    assert report["events"][-1]["category"] == "model_or_plan"
