"""Phase 2 — the LatticeScene structural-layout scaffold. Docker-free: we check the grid geometry,
that the base source is valid Python, the guardrail accepts the subclass, and that codegen prepends
the base + uses the structural prompt only when the flag is on. Real layout quality is proven by the
live eval (--structural) delta, not unit tests."""
import pytest

from generation import codegen, guardrails, lattice_scene


# --- grid geometry (pure) ------------------------------------------------------------------

@pytest.mark.unit
def test_grid_cells_count_distinct_and_in_frame():
    cells = lattice_scene.grid_cells()
    assert len(cells) == lattice_scene.GRID_COLS * len(lattice_scene.GRID_ROWS)  # 8 x 5 = 40
    # every cell within the frame safe area, and all distinct
    for name, (x, y) in cells.items():
        assert -7.0 <= x <= 7.0 and -4.0 <= y <= 3.0, f"{name} out of frame: {(x, y)}"
    assert len(set(cells.values())) == len(cells)


@pytest.mark.unit
def test_grid_corners_ordered_left_top_to_right_bottom():
    cells = lattice_scene.grid_cells()
    assert cells["A1"][0] < cells["A8"][0]      # A1 left of A8
    assert cells["A1"][1] > cells["E1"][1]      # row A above row E
    assert cells["A1"] != cells["E8"]


# --- the base source is valid python -------------------------------------------------------

@pytest.mark.unit
def test_lattice_scene_src_compiles():
    # compile() checks syntax without needing manim/numpy on the host
    compile(lattice_scene.LATTICE_SCENE_SRC, "<lattice_scene>", "exec")
    assert "class LatticeScene(Scene)" in lattice_scene.LATTICE_SCENE_SRC
    assert "def setup_scene" in lattice_scene.LATTICE_SCENE_SRC


# --- guardrail accepts the subclass --------------------------------------------------------

@pytest.mark.unit
def test_guardrail_accepts_lattice_subclass():
    code = ("from manim import *\n"
            "class GeneratedScene(LatticeScene):\n"
            "    def construct(self):\n"
            "        self.setup_scene('Title')\n")
    assert guardrails.check(code) == []   # LatticeScene matches the scene-class requirement


@pytest.mark.unit
def test_structural_guardrail_rejects_plain_scene():
    # the model ignoring the scaffold (case3 bug): plain Scene must be REJECTED in structural mode
    plain = ("from manim import *\n"
             "class GeneratedScene(Scene):\n"
             "    def construct(self):\n"
             "        self.play(Create(Circle()))\n")
    issues = guardrails.check(plain, structural=True)
    rules = {i.rule for i in issues}
    assert "structural-base" in rules and "structural-setup" in rules
    assert guardrails.check(plain, structural=False) == []   # but accepted in free-hand mode


@pytest.mark.unit
def test_structural_guardrail_accepts_proper_lattice_scene():
    good = ("from manim import *\n"
            "class GeneratedScene(LatticeScene):\n"
            "    def construct(self):\n"
            "        self.setup_scene('T')\n")
    assert guardrails.check(good, structural=True) == []


# --- codegen wiring: structural prepends the base + uses the structural prompt --------------

_VALID = ("from manim import *\n"
          "class GeneratedScene(LatticeScene):\n"
          "    def construct(self):\n"
          "        self.setup_scene('T')\n"
          "        self.play(Create(self.node('A')))\n")

SPEC_JSON = {
    "title": "T", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}],
}


class _Fake:
    def __init__(self, reply):
        self.reply = reply
        self.system = None

    def chat(self, messages, **k):
        self.system = messages[0]["content"]
        return self.reply


@pytest.mark.unit
def test_structural_off_returns_plain_code(monkeypatch):
    from core.schemas.scene_spec import SceneSpec
    monkeypatch.setattr(codegen.settings, "structural_layout", False)
    fake = _Fake(_VALID)
    out = codegen.generate(SceneSpec.model_validate(SPEC_JSON), client=fake)
    assert "class LatticeScene(Scene)" not in out      # base NOT prepended
    assert "lattice-codegen" not in (fake.system or "") # used the plain codegen prompt
    assert "GeneratedScene" in out


@pytest.mark.unit
def test_structural_on_prepends_base_and_uses_lattice_prompt(monkeypatch):
    from core.schemas.scene_spec import SceneSpec
    monkeypatch.setattr(codegen.settings, "structural_layout", True)
    fake = _Fake(_VALID)
    out = codegen.generate(SceneSpec.model_validate(SPEC_JSON), client=fake)
    assert "class LatticeScene(Scene)" in out          # base prepended -> GeneratedScene can resolve it
    assert out.index("class LatticeScene") < out.index("class GeneratedScene")  # base first
    # the structural prompt (mandatory setup_scene / grid) was used as the system prompt
    assert "setup_scene" in (fake.system or "")


_VALID_NARRATED = ("from manim import *\n"
                   "class GeneratedScene(LatticeScene):\n"
                   "    def construct(self):\n"
                   "        self.setup_scene('T')\n"
                   "        self.add_sound('audio/a.mp3')\n"
                   "        self.play(Create(self.node('A')))\n")


@pytest.mark.unit
def test_narrated_structural_prepends_base_and_keeps_audio(monkeypatch):
    from core.schemas.scene_spec import SceneSpec
    monkeypatch.setattr(codegen.settings, "structural_layout", True)
    fake = _Fake(_VALID_NARRATED)
    out = codegen.generate_narrated(SceneSpec.model_validate(SPEC_JSON),
                                    [("hi", "audio/a.mp3", 1.0)], client=fake)
    assert "class LatticeScene(Scene)" in out          # product path now gets the scaffold too
    assert "add_sound" in out                          # narration sync preserved
    assert "setup_scene" in (fake.system or "")        # the structural narrated prompt was used
