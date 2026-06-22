"""M6 foundation tests — sid identity, reindex, versioned persistence/migration, build_scene
spec-reuse, regen failure-safety. No network/docker. These lock the invariants the M6 editing
ops rely on (and prove the legacy M5 project still loads)."""
import json

import pytest

from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec

OUTLINE = Outline.model_validate({"topic": "TCP", "items": [
    {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}]})
SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})


@pytest.mark.unit
def test_sid_stable_across_reorder():
    from composition.scene_dag import VideoProject
    p = VideoProject.from_outline(OUTLINE)
    sids = [s.sid for s in p.scenes]
    assert len(set(sids)) == 2 and all(sids)          # unique, non-empty
    keep = p.scene(1).sid
    p.scenes.reverse()
    p.reindex()
    assert p.scene(0).sid == keep                     # sid unchanged by reorder
    assert [s.index for s in p.scenes] == [0, 1]      # index renumbered contiguously


@pytest.mark.unit
def test_scene_by_sid():
    from composition.scene_dag import VideoProject
    p = VideoProject.from_outline(OUTLINE)
    s = p.scene(1)
    assert p.scene_by_sid(s.sid) is s


@pytest.mark.unit
def test_save_load_roundtrip_current(tmp_path):
    from composition.scene_dag import SCHEMA_VERSION, VideoProject
    p = VideoProject.from_outline(OUTLINE)
    p.scene(0).mp4 = "a.mp4"
    p.final_mp4 = "f.mp4"
    path = tmp_path / "p.json"
    p.save(path)
    p2 = VideoProject.load(path)
    assert p2.schema_version == SCHEMA_VERSION
    assert p2.scene(0).mp4 == "a.mp4" and p2.final_mp4 == "f.mp4"
    assert p2.scene(0).sid == p.scene(0).sid          # sid persists


@pytest.mark.unit
def test_migrate_legacy_dump_dict_level():
    """A pre-M6 bare dump (no schema_version, nodes lack sid) is migrated at the dict level."""
    from composition.scene_dag import SCHEMA_VERSION, _detect_version, _migrate
    legacy = {"topic": "t", "scenes": [
        {"index": 0, "title": "A", "intent": "a", "mp4": "a.mp4"},
        {"index": 1, "title": "B", "intent": "b"}]}
    assert _detect_version(legacy) == 0
    m = _migrate(legacy)
    assert m["schema_version"] == SCHEMA_VERSION
    assert m["scenes"][0]["sid"] == "legacy00" and m["scenes"][1]["sid"] == "legacy01"
    assert m["scenes"][0]["versions"] == [] and m["scenes"][0]["script"] == []


@pytest.mark.unit
def test_load_migrates_legacy_file(tmp_path):
    from composition.scene_dag import VideoProject
    legacy = {"topic": "t", "scenes": [{"index": 0, "title": "A", "intent": "a", "mp4": "a.mp4"}]}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    p = VideoProject.load(path)
    assert p.schema_version == 1 and p.scene(0).sid == "legacy00" and p.scene(0).mp4 == "a.mp4"


@pytest.mark.unit
def test_future_schema_version_rejected():
    from composition.scene_dag import _migrate
    with pytest.raises(ValueError):
        _migrate({"schema_version": 999, "topic": "t", "scenes": []})


@pytest.mark.unit
def test_build_scene_reuses_existing_spec(monkeypatch, tmp_path):
    """When node.spec is already set, build_scene must NOT re-run the LLM expand."""
    from composition import video
    from composition.scene_dag import VideoProject
    from narration.narrate import NarratedResult

    p = VideoProject.from_outline(OUTLINE)
    node = p.scene(0)
    node.spec = SPEC
    calls = {"expand": 0}
    monkeypatch.setattr(video.planner_expand, "expand",
                        lambda *a, **k: (calls.__setitem__("expand", calls["expand"] + 1) or SPEC))
    mp4 = tmp_path / "v.mp4"
    monkeypatch.setattr(video.narrate, "build",
                        lambda spec, **k: NarratedResult(True, "code", mp4, tmp_path / "s.srt", [], ["L1"]))

    video.build_scene(node, p, scenes_dir=tmp_path, quality="preview", client=object(), log=None)
    assert calls["expand"] == 0 and node.spec is SPEC and node.script == ["L1"]


@pytest.mark.unit
def test_build_scene_expands_when_spec_missing(monkeypatch, tmp_path):
    from composition import video
    from composition.scene_dag import VideoProject
    from narration.narrate import NarratedResult

    p = VideoProject.from_outline(OUTLINE)
    node = p.scene(0)  # spec is None
    calls = {"expand": 0}
    monkeypatch.setattr(video.planner_expand, "expand",
                        lambda *a, **k: (calls.__setitem__("expand", 1) or SPEC))
    monkeypatch.setattr(video.narrate, "build",
                        lambda spec, **k: NarratedResult(True, "c", tmp_path / "v.mp4", None, [], ["L"]))
    video.build_scene(node, p, scenes_dir=tmp_path, quality="preview", client=object(), log=None)
    assert calls["expand"] == 1 and node.spec is SPEC


@pytest.mark.unit
def test_regen_keeps_prior_clip_on_failure(monkeypatch, tmp_path):
    from composition import regen
    from composition.scene_dag import VideoProject

    p = VideoProject.from_outline(OUTLINE)
    p.scene(0).mp4 = str(tmp_path / "good0.mp4")
    p.scene(1).mp4 = str(tmp_path / "good1.mp4")

    def fail_build(node, project, **k):
        node.mp4 = None
        node.compiled = False
        return node

    stitched = {"n": 0}
    monkeypatch.setattr(regen.video, "build_scene", fail_build)
    monkeypatch.setattr(regen.stitch, "stitch",
                        lambda *a, **k: (stitched.__setitem__("n", 1) or tmp_path / "final.mp4"))

    regen.regenerate_scene(p, 1, out_dir=tmp_path, client=object(), log=None)
    assert p.scene(1).mp4 == str(tmp_path / "good1.mp4")   # prior good clip kept
    assert stitched["n"] == 0                              # no regressed re-stitch
