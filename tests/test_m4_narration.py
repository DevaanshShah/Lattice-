"""M4 unit tests — narration-first script generation (T-9). No network: LLM is faked."""
import json

import pytest

from core.schemas.scene_spec import SceneSpec

_SPEC = SceneSpec.model_validate({
    "title": "Stack", "prompt": "explain a stack", "narration": "A stack is LIFO.",
    "objects": [{"id": "box", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["box"]},
              {"action": "write", "targets": ["box"]}],
})


@pytest.mark.unit
def test_narration_script_parses_and_full_text():
    from core.schemas.narration import NarrationScript
    s = NarrationScript.model_validate({"lines": ["First.", "Second."]})
    assert s.lines == ["First.", "Second."] and s.full_text == "First. Second."


@pytest.mark.unit
def test_empty_lines_rejected():
    from core.schemas.narration import NarrationScript
    with pytest.raises(Exception):
        NarrationScript.model_validate({"lines": []})


@pytest.mark.unit
def test_generate_returns_script_from_model():
    from narration import script

    class Fake:
        def chat(self, messages, **kw):
            return json.dumps({"lines": ["A stack stores items.", "Last in, first out."]})

    s = script.generate(_SPEC, client=Fake())
    assert len(s.lines) == 2 and "stack" in s.full_text.lower()


@pytest.mark.unit
def test_generate_regenerates_after_invalid():
    from narration import script

    class Fake:
        def __init__(self):
            self.n = 0

        def chat(self, messages, **kw):
            self.n += 1
            return "oops not json" if self.n == 1 else json.dumps({"lines": ["ok line"]})

    f = Fake()
    s = script.generate(_SPEC, client=f)
    assert f.n == 2 and s.lines == ["ok line"]


@pytest.mark.unit
def test_generate_raises_after_cap():
    from narration import script

    class Bad:
        def chat(self, messages, **kw):
            return "never json"

    with pytest.raises(script.NarrationError):
        script.generate(_SPEC, attempts=2, client=Bad())
