"""M5 unit tests — scene-DAG project model (T-14). No network."""
import pytest

from core.schemas.outline import Outline

OUTLINE = Outline.model_validate({"topic": "TCP", "items": [
    {"title": "Handshake", "intent": "SYN/ACK"},
    {"title": "Data", "intent": "send bytes"},
]})


@pytest.mark.unit
def test_from_outline_builds_ordered_nodes():
    from composition.scene_dag import VideoProject
    p = VideoProject.from_outline(OUTLINE)
    assert [s.index for s in p.scenes] == [0, 1]
    assert p.scene(0).title == "Handshake" and p.scene(1).intent == "send bytes"
    assert p.all_ready() is False               # nothing rendered yet


@pytest.mark.unit
def test_ordered_mp4s_skips_unrendered():
    from composition.scene_dag import VideoProject
    p = VideoProject.from_outline(OUTLINE)
    p.scene(0).mp4 = "a.mp4"
    assert p.ordered_mp4s() == ["a.mp4"] and p.all_ready() is False
    p.scene(1).mp4 = "b.mp4"
    assert p.ordered_mp4s() == ["a.mp4", "b.mp4"] and p.all_ready() is True


@pytest.mark.unit
def test_save_load_roundtrip(tmp_path):
    from composition.scene_dag import VideoProject
    from core.schemas.style import StyleSpec
    p = VideoProject.from_outline(OUTLINE, style=StyleSpec(palette={"primary": "#111"}))
    p.scene(0).mp4 = "s0.mp4"
    p.scene(0).compiled = True
    p.scene(0).score = 80
    p.final_mp4 = "final.mp4"
    path = tmp_path / "project.json"
    p.save(path)

    p2 = VideoProject.load(path)
    assert p2.topic == "TCP" and p2.final_mp4 == "final.mp4"
    assert p2.scene(0).mp4 == "s0.mp4" and p2.scene(0).score == 80
    assert p2.style.palette["primary"] == "#111"
