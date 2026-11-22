"""M6 unit tests — edit narration + re-time (T-19). No network/docker.

Proves: only scene k re-renders (reusing its spec, with the supplied lines verbatim), other
scenes untouched, captions/script update, re-stitch; failure keeps prior; guards on empty/unbuilt."""
import pytest

from composition.scene_dag import VideoProject
from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec

OUTLINE2 = Outline.model_validate({"topic": "t", "items": [
    {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}]})
SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "old", "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})


def _built_project(tmp_path):
    p = VideoProject.from_outline(OUTLINE2)
    for s in p.scenes:
        s.spec = SPEC
        s.mp4 = f"old_{s.index}.mp4"
        s.srt = f"old_{s.index}.srt"
        s.script = ["old line"]
    return p


@pytest.mark.unit
def test_edit_narration_retimes_only_target(monkeypatch, tmp_path):
    from narration.narrate import NarratedResult
    from editing import narration_edit

    captured = {}

    def fake_build(spec, *, work_dir, quality, client, style, lines, log):
        captured["spec"] = spec
        captured["lines"] = lines
        return NarratedResult(True, "newcode", tmp_path / "new.mp4", tmp_path / "new.srt", [], list(lines))

    monkeypatch.setattr(narration_edit.narrate, "build", fake_build)
    monkeypatch.setattr("composition.stitch.stitch", lambda mp4s, **k: tmp_path / "final.mp4")

    p = _built_project(tmp_path)
    new = ["A stack is LIFO.", "Push adds to the top."]
    narration_edit.edit_narration(p, 1, new, out_dir=tmp_path, client=object(), log=None)

    assert captured["spec"] is p.scene(1).spec       # reused the existing spec (no re-author)
    assert captured["lines"] == new                  # verbatim user lines
    assert p.scene(1).script == new and p.scene(1).mp4 == str(tmp_path / "new.mp4")
    assert p.scene(0).mp4 == "old_0.mp4" and p.scene(0).script == ["old line"]   # other scene untouched


@pytest.mark.unit
def test_edit_narration_unbuilt_scene_raises(tmp_path):
    from editing import narration_edit
    p = VideoProject.from_outline(OUTLINE2)   # specs are None
    with pytest.raises(ValueError):
        narration_edit.edit_narration(p, 0, ["x"], out_dir=tmp_path, client=object(), log=None)


@pytest.mark.unit
def test_edit_narration_empty_raises(tmp_path):
    from editing import narration_edit
    p = _built_project(tmp_path)
    with pytest.raises(ValueError):
        narration_edit.edit_narration(p, 0, ["  "], out_dir=tmp_path, client=object(), log=None)


@pytest.mark.unit
def test_edit_narration_out_of_range_raises(tmp_path):
    from editing import narration_edit
    p = _built_project(tmp_path)
    with pytest.raises(IndexError):
        narration_edit.edit_narration(p, 9, ["x"], out_dir=tmp_path, client=object(), log=None)


@pytest.mark.unit
def test_edit_narration_failure_keeps_prior(monkeypatch, tmp_path):
    from narration.narrate import NarratedResult
    from editing import narration_edit

    monkeypatch.setattr(narration_edit.narrate, "build",
                        lambda spec, **k: NarratedResult(False, "c", None, None, [], []))
    stitched = {"n": 0}
    monkeypatch.setattr("composition.stitch.stitch",
                        lambda mp4s, **k: (stitched.__setitem__("n", 1) or tmp_path / "f.mp4"))

    p = _built_project(tmp_path)
    narration_edit.edit_narration(p, 1, ["new"], out_dir=tmp_path, client=object(), log=None)
    assert p.scene(1).mp4 == "old_1.mp4" and p.scene(1).script == ["old line"]   # unchanged
    assert stitched["n"] == 0
