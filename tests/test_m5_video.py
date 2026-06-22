"""M5 unit tests — video orchestrator + isolated regen (T-17). No network/docker: heavy
steps (expand, narrate, style, stitch) are faked. Asserts the wiring DoD: approval gate runs
before building, scenes assemble + stitch, and regen rebuilds ONLY the target scene."""
import pytest

from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec
from core.schemas.style import StyleSpec

OUTLINE2 = Outline.model_validate({"topic": "TCP", "items": [
    {"title": "A", "intent": "x"}, {"title": "B", "intent": "y"}]})
SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})


@pytest.mark.unit
def test_build_scene_updates_node(monkeypatch, tmp_path):
    from composition import video
    from composition.scene_dag import VideoProject
    from narration.narrate import NarratedResult

    project = VideoProject.from_outline(OUTLINE2)
    monkeypatch.setattr(video.planner_expand, "expand", lambda item, outline, idx, **k: SPEC)
    mp4 = tmp_path / "s0.mp4"
    mp4.write_bytes(b"v")
    monkeypatch.setattr(video.narrate, "build",
                        lambda spec, **k: NarratedResult(True, "code", mp4, tmp_path / "s.srt", [], ["n"]))

    node = video.build_scene(project.scene(0), project, scenes_dir=tmp_path,
                             quality="preview", client=object(), log=None)
    assert node.compiled and node.mp4 == str(mp4) and node.spec is SPEC


@pytest.mark.unit
def test_generate_video_assembles_and_stitches(monkeypatch, tmp_path):
    from composition import video

    monkeypatch.setattr(video.planner_outline, "generate", lambda topic, **k: OUTLINE2)
    monkeypatch.setattr(video.style_gen, "generate",
                        lambda topic, outline, **k: StyleSpec(palette={"primary": "#111"}))

    def fake_build(node, project, *, scenes_dir, quality, client, log):
        node.mp4 = str(tmp_path / f"s{node.index}.mp4")
        node.compiled = True
        return node

    monkeypatch.setattr(video, "build_scene", fake_build)
    monkeypatch.setattr(video.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    proj = video.generate_video("TCP", out_dir=tmp_path, client=object(), log=None)
    assert len(proj.scenes) == 2 and all(s.mp4 for s in proj.scenes)
    assert proj.final_mp4 == str(tmp_path / "final.mp4")
    assert proj.style.palette["primary"] == "#111"


@pytest.mark.unit
def test_generate_video_runs_approval_gate_before_building(monkeypatch, tmp_path):
    from composition import video
    from planner.approval import apply_edits

    monkeypatch.setattr(video.planner_outline, "generate", lambda topic, **k: OUTLINE2)
    monkeypatch.setattr(video.style_gen, "generate", lambda topic, outline, **k: StyleSpec())
    built = []
    monkeypatch.setattr(video, "build_scene",
                        lambda node, project, **k: (built.append(node.index), node)[1])
    monkeypatch.setattr(video.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    # gate cuts the outline down to ONE scene before any build
    proj = video.generate_video("TCP", approve_fn=lambda o: apply_edits(o, keep=[1]),
                                out_dir=tmp_path, client=object(), log=None)
    assert len(proj.scenes) == 1 and proj.scenes[0].title == "B"
    assert built == [0]            # only the single kept scene was built


@pytest.mark.unit
def test_regen_rebuilds_only_target_and_reuses_rest(monkeypatch, tmp_path):
    from composition import regen
    from composition.scene_dag import VideoProject

    project = VideoProject.from_outline(OUTLINE2)
    project.scene(0).mp4 = str(tmp_path / "old0.mp4")
    project.scene(1).mp4 = str(tmp_path / "old1.mp4")

    calls = {"n": 0, "idx": None}

    def fake_build(node, project, **k):
        calls["n"] += 1
        calls["idx"] = node.index
        node.mp4 = str(tmp_path / f"new{node.index}.mp4")
        return node

    monkeypatch.setattr(regen.video, "build_scene", fake_build)
    monkeypatch.setattr(regen.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    regen.regenerate_scene(project, 1, out_dir=tmp_path, client=object(), log=None)
    assert calls["n"] == 1 and calls["idx"] == 1               # only scene 1 rebuilt
    assert project.scene(0).mp4 == str(tmp_path / "old0.mp4")  # scene 0 untouched
    assert project.scene(1).mp4 == str(tmp_path / "new1.mp4")  # scene 1 updated
    assert project.final_mp4 == str(tmp_path / "final.mp4")    # re-stitched
