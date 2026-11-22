"""M6 unit tests — per-scene version history + rollback (T-22). No network/docker."""
from pathlib import Path

import pytest

from composition.scene_dag import SceneNode, SceneVersion, VideoProject
from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec

OUTLINE2 = Outline.model_validate({"topic": "t", "items": [
    {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}]})
SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "n", "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})


def _deep_mp4(tmp_path, content=b"v1"):
    """The REAL render layout: scenes/.../media/videos/scene/<RES>/GeneratedScene.mp4."""
    p = tmp_path / "media" / "videos" / "scene" / "480p15" / "GeneratedScene.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.mark.unit
def test_snapshot_freezes_deep_clip_with_metadata(tmp_path):
    from editing import history
    node = SceneNode(index=0, title="A", intent="a", spec=SPEC, code="c", script=["L"], score=70)
    node.mp4 = str(_deep_mp4(tmp_path, content=b"original"))
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n", encoding="utf-8")
    node.srt = str(srt)

    ver = history.snapshot(node, out_dir=tmp_path, label="x")
    assert ver is not None and len(node.versions) == 1 and ver.version == 0
    frozen = Path(ver.mp4)
    assert frozen.exists() and frozen.read_bytes() == b"original"
    assert node.sid in str(frozen) and "versions" in str(frozen)
    assert ver.score == 70 and ver.script == ["L"] and ver.spec is SPEC and ver.srt


@pytest.mark.unit
def test_snapshot_noop_when_unrendered(tmp_path):
    from editing import history
    node = SceneNode(index=0, title="A", intent="a")    # mp4 None
    assert history.snapshot(node, out_dir=tmp_path) is None and node.versions == []


@pytest.mark.unit
def test_frozen_version_survives_live_overwrite(tmp_path):
    """Linchpin: a later rebuild overwrites the live deep mp4 in place; the frozen copy is immutable."""
    from editing import history
    node = SceneNode(index=0, title="A", intent="a", spec=SPEC)
    live = _deep_mp4(tmp_path, content=b"v1")
    node.mp4 = str(live)
    ver = history.snapshot(node, out_dir=tmp_path)
    live.write_bytes(b"v2-rebuilt")                      # simulate a rebuild overwriting in place
    assert Path(ver.mp4).read_bytes() == b"v1"           # frozen bytes unchanged


@pytest.mark.unit
def test_rollback_restores_frozen_and_restitches(monkeypatch, tmp_path):
    from editing import history
    p = VideoProject.from_outline(OUTLINE2)
    n = p.scene(1)
    n.spec, n.code, n.script, n.score = SPEC, "c0", ["v0 line"], 60
    live = _deep_mp4(tmp_path, content=b"v0")
    n.mp4 = str(live)
    history.snapshot(n, out_dir=tmp_path, label="v0")    # version 0 = the good one

    # simulate a bad edit that overwrote the live clip + metadata
    live.write_bytes(b"v1-bad")
    n.code, n.script, n.score = "c1", ["v1 line"], 20

    stitched = {"n": 0}
    monkeypatch.setattr("composition.stitch.stitch",
                        lambda mp4s, **k: (stitched.__setitem__("n", 1) or tmp_path / "final.mp4"))

    history.rollback(p, 1, 0, out_dir=tmp_path, log=None)
    assert Path(n.mp4).read_bytes() == b"v0"             # restored to the frozen good clip
    assert n.script == ["v0 line"] and n.score == 60
    assert stitched["n"] == 1                            # re-stitched (no re-render)
    assert len(n.versions) >= 2                          # snapshotted current first -> reversible


@pytest.mark.unit
def test_rollback_unknown_version_raises(tmp_path):
    from editing import history
    p = VideoProject.from_outline(OUTLINE2)
    with pytest.raises(IndexError):
        history.rollback(p, 1, 0, out_dir=tmp_path, log=None)   # no versions yet


@pytest.mark.unit
def test_rollback_missing_frozen_file_raises(tmp_path):
    from editing import history
    p = VideoProject.from_outline(OUTLINE2)
    n = p.scene(0)
    n.versions.append(SceneVersion(version=0, mp4=str(tmp_path / "gone.mp4")))
    with pytest.raises(FileNotFoundError):
        history.rollback(p, 0, 0, out_dir=tmp_path, log=None)


@pytest.mark.unit
def test_history_is_per_scene(tmp_path):
    from editing import history
    p = VideoProject.from_outline(OUTLINE2)
    n0 = p.scene(0)
    n0.spec = SPEC
    n0.mp4 = str(_deep_mp4(tmp_path, content=b"x"))
    history.snapshot(n0, out_dir=tmp_path)
    assert len(n0.versions) == 1 and len(p.scene(1).versions) == 0   # per-scene, not global
