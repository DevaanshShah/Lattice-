"""M6 unit tests — per-scene tweak prompts (T-20). No network/docker."""
import json

import pytest

from composition.scene_dag import VideoProject
from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec

OUTLINE2 = Outline.model_validate({"topic": "t", "items": [
    {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}]})
SPEC_DICT = {
    "title": "A", "prompt": "explain a stack", "narration": "n",
    "objects": [{"id": "box", "kind": "square"}, {"id": "label", "kind": "text", "label": "top"}],
    "beats": [{"action": "create", "targets": ["box"]}, {"action": "write", "targets": ["label"]}],
}


@pytest.mark.unit
def test_apply_tweak_preserves_object_ids_and_prompt():
    from editing import tweak

    def revised(spec_dict):
        d = json.loads(json.dumps(spec_dict))
        d["layout_notes"] = "box moved left"          # the nudge
        d.pop("prompt", None)                          # model may omit prompt
        return d

    class Fake:
        def chat(self, messages, **k):
            return json.dumps(revised(SPEC_DICT))

    spec = SceneSpec.model_validate(SPEC_DICT)
    out = tweak.apply_tweak(spec, "move the box left", client=Fake())
    assert [o.id for o in out.objects] == ["box", "label"]   # ids preserved (nudge, not re-author)
    assert out.prompt == "explain a stack"                   # source prompt preserved
    assert out.layout_notes == "box moved left"


@pytest.mark.unit
def test_apply_tweak_regenerates_on_invalid():
    from editing import tweak

    class Fake:
        def __init__(self):
            self.n = 0

        def chat(self, messages, **k):
            self.n += 1
            return "nonsense" if self.n == 1 else json.dumps(SPEC_DICT)

    f = Fake()
    out = tweak.apply_tweak(SceneSpec.model_validate(SPEC_DICT), "x", client=f)
    assert f.n == 2 and out.title == "A"


@pytest.mark.unit
def test_tweak_scene_revises_spec_then_regenerates(monkeypatch, tmp_path):
    from editing import tweak

    revised = SceneSpec.model_validate({**SPEC_DICT, "layout_notes": "nudged"})
    monkeypatch.setattr(tweak, "apply_tweak", lambda spec, instruction, **k: revised)

    seen = {}

    def fake_regen(project, index, **k):
        seen["index"] = index
        seen["spec_at_call"] = project.scene(index).spec
        return project

    monkeypatch.setattr(tweak.regen, "regenerate_scene", fake_regen)

    p = VideoProject.from_outline(OUTLINE2)
    p.scene(1).spec = SceneSpec.model_validate(SPEC_DICT)
    tweak.tweak_scene(p, 1, "move the box left", out_dir=tmp_path, client=object(), log=None)

    assert seen["index"] == 1
    assert seen["spec_at_call"] is revised               # revised spec is in place before regen
    assert p.scene(1).spec.layout_notes == "nudged"


@pytest.mark.unit
def test_tweak_unbuilt_scene_raises(tmp_path):
    from editing import tweak
    p = VideoProject.from_outline(OUTLINE2)   # specs None
    with pytest.raises(ValueError):
        tweak.tweak_scene(p, 0, "x", out_dir=tmp_path, client=object(), log=None)
