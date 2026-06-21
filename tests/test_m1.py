"""M1 unit tests - schema strictness, guardrails, and the regenerate-on-invalid loop.

No network: the LLM is replaced with tiny fakes. These assert the *behaviour* that makes
M1's DoD hold (invalid rejected, guardrails catch CE/GL + deprecated, fences stripped).
"""
import json

import pytest
from pydantic import ValidationError

VALID = {
    "title": "Hash collision",
    "narration": "Two keys hash to the same bucket, so they chain together in a list.",
    "layout_notes": "array across the top, pointer below",
    "objects": [
        {"id": "bucket", "kind": "square", "label": None, "notes": "left of frame"},
        {"id": "key_a", "kind": "text", "label": "A", "notes": None},
    ],
    "beats": [
        {"action": "create", "targets": ["bucket"], "narration_cue": None, "notes": None},
        {"action": "write", "targets": ["key_a"], "narration_cue": None, "notes": None},
        {"action": "wait", "targets": [], "narration_cue": None, "notes": None},
    ],
}


@pytest.mark.unit
def test_valid_spec_parses():
    from core.schemas.scene_spec import SceneSpec
    s = SceneSpec.model_validate({**VALID, "prompt": "p"})
    assert s.title == "Hash collision" and len(s.objects) == 2 and len(s.beats) == 3


@pytest.mark.unit
def test_unknown_object_kind_rejected():
    from core.schemas.scene_spec import SceneSpec
    bad = {**VALID, "prompt": "p", "objects": [{"id": "x", "kind": "hologram"}]}
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(bad)


@pytest.mark.unit
def test_extra_field_rejected():
    from core.schemas.scene_spec import SceneSpec
    with pytest.raises(ValidationError):
        SceneSpec.model_validate({**VALID, "prompt": "p", "surprise": 1})


@pytest.mark.unit
def test_beat_targets_must_exist():
    from core.schemas.scene_spec import SceneSpec
    bad = {**VALID, "prompt": "p",
           "beats": [{"action": "create", "targets": ["ghost"]}]}
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(bad)


@pytest.mark.unit
def test_guardrails_flag_manimgl_and_deprecated():
    from generation.guardrails import check
    code = ("from manimlib import *\n"
            "class GeneratedScene(Scene):\n"
            "    def construct(self):\n"
            "        self.play(ShowCreation(Circle()))\n")
    rules = {i.rule for i in check(code)}
    assert "no-manimgl" in rules and "deprecated" in rules


@pytest.mark.unit
def test_guardrails_clean_on_good_code():
    from generation.guardrails import check
    code = ("from manim import *\n"
            "class GeneratedScene(Scene):\n"
            "    def construct(self):\n"
            "        self.play(Create(Circle()))\n")
    assert check(code) == []


@pytest.mark.unit
def test_guardrails_require_scene_class_name():
    from generation.guardrails import check
    code = ("from manim import *\n"
            "class Foo(Scene):\n"
            "    def construct(self):\n"
            "        pass\n")
    assert "scene-class" in {i.rule for i in check(code)}


@pytest.mark.unit
def test_scene_spec_regenerates_after_invalid():
    """First model reply is garbage, second is valid -> generate() recovers."""
    from generation import scene_spec as ss

    class Fake:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kw):
            self.calls += 1
            return "sorry, here you go" if self.calls == 1 else json.dumps(VALID)

    fake = Fake()
    spec = ss.generate("explain a hash map collision", client=fake)
    assert spec.title == "Hash collision" and fake.calls == 2


@pytest.mark.unit
def test_scene_spec_raises_after_exhausting_attempts():
    from generation import scene_spec as ss

    class AlwaysBad:
        def chat(self, messages, **kw):
            return "not json"

    with pytest.raises(ss.SceneSpecError):
        ss.generate("x", attempts=2, client=AlwaysBad())


@pytest.mark.unit
def test_codegen_strips_fences_and_passes_guardrails():
    from core.schemas.scene_spec import SceneSpec
    from generation import codegen
    spec = SceneSpec.model_validate({**VALID, "prompt": "p"})
    fenced = ("```python\n"
              "from manim import *\n"
              "class GeneratedScene(Scene):\n"
              "    def construct(self):\n"
              "        self.play(Create(Circle()))\n"
              "```")

    class Fake:
        def chat(self, messages, **kw):
            return fenced

    code = codegen.generate(spec, client=Fake())
    assert "from manim import *" in code and "```" not in code
