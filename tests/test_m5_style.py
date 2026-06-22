"""M5 unit tests — style spec + injection into codegen (T-13). No network."""
import json

import pytest

from core.schemas.scene_spec import SceneSpec

SPEC = SceneSpec.model_validate({
    "title": "S", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}],
})


@pytest.mark.unit
def test_style_as_prompt_includes_fields():
    from core.schemas.style import StyleSpec
    s = StyleSpec(palette={"primary": "#3498db"}, fonts="sans 36",
                  object_styles={"box": "rounded"}, layout_rules=["title at top"])
    p = s.as_prompt()
    assert "#3498db" in p and "rounded" in p and "title at top" in p


@pytest.mark.unit
def test_style_generate_from_model():
    from core.schemas.outline import Outline
    from generation import style

    payload = {"palette": {"primary": "#111111"}, "fonts": "sans",
               "object_styles": {"box": "x"}, "layout_rules": ["centered"]}

    class Fake:
        def chat(self, m, **k):
            return json.dumps(payload)

    o = Outline.model_validate({"topic": "t", "items": [{"title": "A", "intent": "x"}]})
    s = style.generate("t", o, client=Fake())
    assert s.palette["primary"] == "#111111"


@pytest.mark.unit
def test_codegen_injects_style_into_system_prompt():
    from core.schemas.style import StyleSpec
    from generation import codegen

    captured = {}

    class Fake:
        def chat(self, messages, **k):
            captured["system"] = messages[0]["content"]
            return ("from manim import *\nclass GeneratedScene(Scene):\n"
                    "    def construct(self):\n        self.play(Create(Circle()))\n")

    style = StyleSpec(palette={"primary": "#abcdef"}, layout_rules=["diagram centered"])
    codegen.generate(SPEC, client=Fake(), style=style)
    assert "#abcdef" in captured["system"] and "diagram centered" in captured["system"]


@pytest.mark.unit
def test_codegen_works_without_style():
    from generation import codegen

    class Fake:
        def chat(self, messages, **k):
            return ("from manim import *\nclass GeneratedScene(Scene):\n"
                    "    def construct(self):\n        self.play(Create(Circle()))\n")

    code = codegen.generate(SPEC, client=Fake())     # style is optional
    assert "GeneratedScene" in code
