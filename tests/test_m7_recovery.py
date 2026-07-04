"""Crash recovery — a build killed mid-run (e.g. the server is restarted while rendering) leaves
finished scene clips on disk but never saves project.json, so the good scenes look 'unbuilt' and no
final.mp4 is stitched. Engine.recover_all() reconciles project.json with what actually rendered and
finalizes a complete-but-unstitched video. Docker-free: we fake the stitch leaf and drop dummy clips."""
from pathlib import Path

import pytest

from composition.scene_dag import VideoProject
from core.schemas.outline import Outline, OutlineItem
from web.engine import Engine


def _draft(engine: Engine, pid: str, titles) -> VideoProject:
    """Persist a DRAFT project (outline listed, nothing rendered) exactly like engine.plan does."""
    outline = Outline(topic="T", items=[OutlineItem(title=t, intent="x") for t in titles])
    project = VideoProject.from_outline(outline)
    engine.workspace(pid).mkdir(parents=True, exist_ok=True)
    engine.save(pid, project)
    return project


def _drop_clip(engine: Engine, pid: str, index: int) -> None:
    """Simulate a scene that finished rendering to disk (the decoupled index-keyed layout)."""
    sdir = engine.workspace(pid) / "scenes" / f"scene_{index}"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "narrated.mp4").write_bytes(b"v")
    (sdir / "narration.txt").write_text("n", encoding="utf-8")


@pytest.mark.unit
def test_recover_fills_finished_scenes_without_restitch_when_incomplete(tmp_path):
    engine = Engine(root=tmp_path / "web", client=object())
    _draft(engine, "p1", ["A", "B"])
    _drop_clip(engine, "p1", 0)                       # only scene 0 finished before the kill

    recovered = engine.recover_all()
    assert "p1" in recovered
    proj = engine.load("p1")
    assert proj.scenes[0].mp4 and not proj.scenes[1].mp4   # scene 0 recovered, scene 1 still missing
    assert proj.final_mp4 is None                          # not all built -> no stitch attempted


@pytest.mark.unit
def test_recover_stitches_final_when_all_scenes_present(tmp_path, monkeypatch):
    stitched = {}

    def fake_stitch(mp4s, *, work_dir, out_name="final.mp4", **k):
        p = Path(work_dir) / out_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"f")
        stitched["clips"] = list(mp4s)
        return p

    monkeypatch.setattr("composition.stitch.stitch", fake_stitch)
    engine = Engine(root=tmp_path / "web", client=object())
    _draft(engine, "p2", ["A", "B"])
    _drop_clip(engine, "p2", 0)
    _drop_clip(engine, "p2", 1)                       # both scenes finished, but project never saved/stitched

    recovered = engine.recover_all()
    assert "p2" in recovered
    proj = engine.load("p2")
    assert proj.scenes[0].mp4 and proj.scenes[1].mp4
    assert proj.final_mp4 and Path(proj.final_mp4).exists()   # auto-finalized
    assert len(stitched["clips"]) == 2


@pytest.mark.unit
def test_recover_skips_already_complete_and_empty(tmp_path, monkeypatch):
    calls = {"n": 0}
    engine = Engine(root=tmp_path / "web", client=object())
    # a complete project must be a cheap no-op (never re-stitched)
    monkeypatch.setattr("composition.stitch.stitch",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    proj = _draft(engine, "done", ["A"])
    _drop_clip(engine, "done", 0)
    engine._fill_node_from_dir(proj.scenes[0], engine.workspace("done") / "scenes" / "scene_0")
    proj.final_mp4 = str(engine.workspace("done") / "final.mp4")
    (engine.workspace("done") / "final.mp4").write_bytes(b"f")
    engine.save("done", proj)

    assert engine.recover_all() == []      # nothing to do
    assert calls["n"] == 0                 # complete project was skipped, not re-stitched
