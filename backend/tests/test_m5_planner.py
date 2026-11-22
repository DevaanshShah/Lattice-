"""M5 unit tests — planner: outline gen, cap, approval edits, expand (T-12). No network."""
import json

import pytest


@pytest.mark.unit
def test_outline_parses():
    from core.schemas.outline import Outline
    o = Outline.model_validate({"topic": "t", "items": [{"title": "A", "intent": "x"}]})
    assert o.titles() == ["A"]


@pytest.mark.unit
def test_outline_generate_enforces_cap():
    from planner import outline

    big = {"items": [{"title": f"S{i}", "intent": "x"} for i in range(20)]}

    class Fake:
        def chat(self, m, **k):
            return json.dumps(big)

    o = outline.generate("topic", max_scenes=5, client=Fake())
    assert len(o.items) == 5 and o.topic == "topic"     # capped, not silently huge


@pytest.mark.unit
def test_outline_regenerates_after_invalid():
    from planner import outline

    class Fake:
        def __init__(self):
            self.n = 0

        def chat(self, m, **k):
            self.n += 1
            return "junk" if self.n == 1 else json.dumps({"items": [{"title": "A", "intent": "x"}]})

    f = Fake()
    o = outline.generate("t", client=f)
    assert f.n == 2 and len(o.items) == 1


@pytest.mark.unit
def test_apply_edits_keep_reorders_and_cuts():
    from core.schemas.outline import Outline
    from planner.approval import apply_edits
    o = Outline.model_validate({"topic": "t", "items": [
        {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}, {"title": "C", "intent": "c"}]})
    out = apply_edits(o, keep=[2, 0])      # keep C then A, drop B
    assert out.titles() == ["C", "A"]


@pytest.mark.unit
def test_apply_edits_drop():
    from core.schemas.outline import Outline
    from planner.approval import apply_edits
    o = Outline.model_validate({"topic": "t", "items": [
        {"title": "A", "intent": "a"}, {"title": "B", "intent": "b"}]})
    assert apply_edits(o, drop=[0]).titles() == ["B"]


@pytest.mark.unit
def test_apply_edits_empty_raises():
    from core.schemas.outline import Outline
    from planner.approval import apply_edits
    o = Outline.model_validate({"topic": "t", "items": [{"title": "A", "intent": "a"}]})
    with pytest.raises(ValueError):
        apply_edits(o, keep=[])


@pytest.mark.unit
def test_expand_passes_context_to_scene_spec(monkeypatch):
    from core.schemas.outline import Outline
    from planner import expand as expand_mod

    captured = {}

    def fake_generate(prompt, *, client=None, **k):
        captured["prompt"] = prompt
        from core.schemas.scene_spec import SceneSpec
        return SceneSpec.model_validate({
            "title": "A", "prompt": prompt, "narration": "n",
            "objects": [{"id": "o", "kind": "square"}],
            "beats": [{"action": "create", "targets": ["o"]}]})

    monkeypatch.setattr(expand_mod.scene_spec, "generate", fake_generate)
    o = Outline.model_validate({"topic": "TCP", "items": [
        {"title": "Handshake", "intent": "show SYN/ACK"}, {"title": "Data", "intent": "send bytes"}]})
    spec = expand_mod.expand(o.items[0], o, 0, client=object())
    assert "TCP" in captured["prompt"] and "Handshake" in captured["prompt"]   # context threaded in
    assert spec.title == "A"
