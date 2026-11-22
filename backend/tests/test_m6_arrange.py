"""M6 unit tests — arrange: reorder/add/delete (T-18). No network/docker.

Proves the DoD + reviewer fixes: reorder/delete reuse every clip (zero rebuilds), insert
builds exactly one scene (with failure-rollback), indices stay contiguous, sids stay distinct."""
import pytest

from composition.scene_dag import VideoProject
from core.schemas.outline import Outline

OUTLINE3 = Outline.model_validate({"topic": "t", "items": [
    {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}, {"title": "C", "intent": "c"}]})


def _rendered_project():
    p = VideoProject.from_outline(OUTLINE3)
    for s in p.scenes:
        s.mp4 = f"clip_{s.index}.mp4"
    return p


@pytest.mark.unit
def test_reorder_reuses_all_clips_and_reindexes(monkeypatch, tmp_path):
    from editing import arrange
    calls = {"stitch": 0, "build": 0}
    monkeypatch.setattr(arrange.stitch, "stitch",
                        lambda mp4s, **k: (calls.__setitem__("stitch", 1) or tmp_path / "final.mp4"))
    monkeypatch.setattr(arrange.video, "build_scene",
                        lambda *a, **k: calls.__setitem__("build", calls["build"] + 1))

    p = _rendered_project()
    sids = [s.sid for s in p.scenes]
    arrange.reorder(p, 0, 2, out_dir=tmp_path, log=None)

    assert calls["build"] == 0                          # reorder re-renders NOTHING
    assert [s.title for s in p.scenes] == ["B", "C", "A"]
    assert [s.index for s in p.scenes] == [0, 1, 2]     # reindexed
    assert p.scene_by_sid(sids[0]).title == "A"         # sids preserved
    assert calls["stitch"] == 1 and p.final_mp4 == str(tmp_path / "final.mp4")


@pytest.mark.unit
def test_delete_reuses_clips_and_reindexes(monkeypatch, tmp_path):
    from editing import arrange
    monkeypatch.setattr(arrange.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")
    built = []
    monkeypatch.setattr(arrange.video, "build_scene", lambda *a, **k: built.append(1))

    p = _rendered_project()
    arrange.delete(p, 1, out_dir=tmp_path, log=None)
    assert built == []                                   # no re-render
    assert [s.title for s in p.scenes] == ["A", "C"] and [s.index for s in p.scenes] == [0, 1]


@pytest.mark.unit
def test_delete_last_scene_raises(tmp_path):
    from editing import arrange
    p = VideoProject.from_outline(Outline.model_validate({"topic": "t", "items": [{"title": "A", "intent": "a"}]}))
    with pytest.raises(ValueError):
        arrange.delete(p, 0, out_dir=tmp_path, log=None)


@pytest.mark.unit
def test_insert_builds_only_new_scene(monkeypatch, tmp_path):
    from editing import arrange
    monkeypatch.setattr(arrange.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")
    built = {"n": 0}

    def fake_build(node, project, **k):
        built["n"] += 1
        node.mp4 = f"new_{node.sid}.mp4"
        return node

    monkeypatch.setattr(arrange.video, "build_scene", fake_build)
    p = _rendered_project()
    arrange.insert(p, 1, "NEW", "new intent", out_dir=tmp_path, client=object(), log=None)

    assert built["n"] == 1                               # built ONLY the inserted scene
    assert [s.title for s in p.scenes] == ["A", "NEW", "B", "C"]
    assert [s.index for s in p.scenes] == [0, 1, 2, 3]
    assert p.scene(1).mp4.startswith("new_")


@pytest.mark.unit
def test_insert_rolls_back_on_render_failure(monkeypatch, tmp_path):
    from editing import arrange
    stitched = {"n": 0}
    monkeypatch.setattr(arrange.stitch, "stitch",
                        lambda mp4s, **k: (stitched.__setitem__("n", 1) or tmp_path / "final.mp4"))

    def fail_build(node, project, **k):
        node.mp4 = None        # render failed
        return node

    monkeypatch.setattr(arrange.video, "build_scene", fail_build)
    p = _rendered_project()
    arrange.insert(p, 1, "NEW", "x", out_dir=tmp_path, client=object(), log=None)

    assert [s.title for s in p.scenes] == ["A", "B", "C"]   # insert rolled back
    assert [s.index for s in p.scenes] == [0, 1, 2]
    assert stitched["n"] == 0                              # no re-stitch on failure


@pytest.mark.unit
def test_delete_then_insert_gets_fresh_distinct_sid(monkeypatch, tmp_path):
    from editing import arrange
    monkeypatch.setattr(arrange.stitch, "stitch", lambda mp4s, **k: tmp_path / "final.mp4")
    monkeypatch.setattr(arrange.video, "build_scene",
                        lambda node, project, **k: setattr(node, "mp4", f"x_{node.sid}.mp4") or node)

    p = _rendered_project()
    deleted_sid = p.scene(1).sid
    arrange.delete(p, 1, out_dir=tmp_path, log=None)
    arrange.insert(p, 1, "NEW", "x", out_dir=tmp_path, client=object(), log=None)
    assert p.scene(1).sid != deleted_sid                  # fresh identity -> own work dir, no collision
