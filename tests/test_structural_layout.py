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


# --- square_on_segment orientation math (pure mirror; the real bug was a wrong-side square) ------

def _point_in_triangle(pt, t0, t1, t2):
    def sign(p1, p2, p3):
        return (p1[0]-p3[0])*(p2[1]-p3[1]) - (p2[0]-p3[0])*(p1[1]-p3[1])
    d1, d2, d3 = sign(pt, t0, t1), sign(pt, t1, t2), sign(pt, t2, t0)
    has_neg, has_pos = (d1 < 0 or d2 < 0 or d3 < 0), (d1 > 0 or d2 > 0 or d3 > 0)
    return not (has_neg and has_pos)


def _centroid(pts):
    xs, ys = zip(*pts)
    return (sum(xs) / len(pts), sum(ys) / len(pts))


@pytest.mark.unit
def test_square_lands_outside_the_exact_regressed_triangle():
    # the EXACT triangle from the regression: default outward=True put square_a's square INSIDE
    t0, t1, t2 = (0.0, 0.0), (1.6, 0.0), (0.0, 2.133)
    center = _centroid([t0, t1, t2])
    sq = lattice_scene.square_corners_away_from(t0, t1, away_from=center)
    assert not _point_in_triangle(_centroid(sq), t0, t1, t2)


@pytest.mark.unit
@pytest.mark.parametrize("t0,t1,t2", [
    ((0.0, 0.0), (1.6, 0.0), (0.0, 2.133)),      # the regressed case
    ((0.0, 2.133), (1.6, 0.0), (0.0, 0.0)),      # same triangle, reversed winding
    ((0.0, 0.0), (4.0, 0.0), (3.5, 0.5)),        # obtuse
    ((0.0, 0.0), (2.0, 0.0), (1.0, 1.732)),      # near-equilateral
    ((-1.0, -2.0), (3.0, -1.0), (0.0, 2.0)),     # scalene, negative coords
    ((1.2, 3.4), (-2.1, 0.7), (4.4, -1.5)),      # arbitrary rotation
])
def test_square_orientation_generalizes_across_triangle_shapes_and_vertex_order(t0, t1, t2):
    # every edge, BOTH directions -- away_from must win regardless of which vertex order is passed
    center = _centroid([t0, t1, t2])
    for p1, p2 in [(t0, t1), (t1, t0), (t1, t2), (t2, t1), (t2, t0), (t0, t2)]:
        sq = lattice_scene.square_corners_away_from(p1, p2, away_from=center)
        assert not _point_in_triangle(_centroid(sq), t0, t1, t2), f"square on {p1}->{p2} landed inside"


# --- the base source is valid python -------------------------------------------------------

@pytest.mark.unit
def test_lattice_scene_src_compiles():
    # compile() checks syntax without needing manim/numpy on the host
    compile(lattice_scene.LATTICE_SCENE_SRC, "<lattice_scene>", "exec")
    assert "class LatticeScene(Scene)" in lattice_scene.LATTICE_SCENE_SRC
    assert "def setup_scene" in lattice_scene.LATTICE_SCENE_SRC
    # components render math labels as MathTex (fixes the literal "$x_1$" structural-A/B bug)
    assert "def _label" in lattice_scene.LATTICE_SCENE_SRC and "MathTex" in lattice_scene.LATTICE_SCENE_SRC


@pytest.mark.unit
def test_lattice_scene_src_square_on_segment_takes_away_from():
    # the embedded (real, in-container) method must carry the away_from fix, not just the pure mirror
    assert "def square_on_segment" in lattice_scene.LATTICE_SCENE_SRC
    assert "away_from" in lattice_scene.LATTICE_SCENE_SRC


# --- icon library (self.icon) --------------------------------------------------------------

@pytest.mark.unit
def test_icon_method_in_src():
    src = lattice_scene.LATTICE_SCENE_SRC
    compile(src, "<lattice_scene>", "exec")             # the new method keeps the SRC valid
    assert "def icon" in src
    assert "/opt/icons" in src                          # reads the baked icon dir
    assert "labeled_box(name" in src                    # graceful fallback present


@pytest.mark.unit
def test_icon_names_are_safe_slugs():
    import re
    assert lattice_scene.ICON_NAMES                     # non-empty
    assert all(re.fullmatch(r"[a-z0-9_-]+", n) for n in lattice_scene.ICON_NAMES)  # traversal-safe filenames


@pytest.mark.unit
def test_icon_catalog_prompt_lists_all_names():
    block = lattice_scene.icon_catalog_prompt()
    assert all(n in block for n in lattice_scene.ICON_NAMES)


@pytest.mark.unit
def test_structural_prompt_injects_icons():
    sp = lattice_scene.structural_system_prompt()
    assert "icon" in sp.lower() and "server" in sp and "setup_scene" in sp


@pytest.mark.unit
def test_icon_names_derived_from_shipped_assets():
    # ICON_NAMES is AUTO-DERIVED from assets/icons/*.svg, so it can't drift from the shipped files.
    # This confirms the derivation resolves the right dir: populated, equals the stems, has known icons.
    from core.config import PROJECT_ROOT
    stems = {p.stem for p in (PROJECT_ROOT / "assets" / "icons").glob("*.svg")}
    assert lattice_scene.ICON_NAMES and set(lattice_scene.ICON_NAMES) == stems
    assert {"server", "cat", "laptop"} <= set(lattice_scene.ICON_NAMES)


# --- scaffold-API prompt (stops the model inventing methods like get_cell_center) ----------

@pytest.mark.unit
def test_scaffold_methods_parsed_from_source_not_hardcoded():
    methods = lattice_scene.scaffold_methods()
    joined = " ".join(methods)
    # the real public helpers are listed...
    for real in ("self.cell(", "self.place(", "self.place_in_area(", "self.node(",
                 "self.connect(", "self.icon(", "self.setup_scene("):
        assert real in joined, f"{real} missing from scaffold_methods()"
    # ...and private/dunder helpers are NOT (they aren't part of the model-facing API)
    assert not any("_label" in m or "_style_kw" in m for m in methods)


@pytest.mark.unit
def test_scaffold_api_prompt_names_cell_and_warns_off_hallucinations():
    sp = lattice_scene.scaffold_api_prompt()
    assert "self.cell(" in sp
    assert "get_cell_center" in sp          # the prompt explicitly calls out the non-existent method
    assert "ONLY methods" in sp


@pytest.mark.unit
def test_structural_prompt_includes_scaffold_api():
    # the block must reach the actual codegen/fixer system prompt, not just exist in isolation
    sp = lattice_scene.structural_system_prompt()
    assert "SCAFFOLD METHODS" in sp and "self.cell(" in sp


@pytest.mark.unit
def test_no_hallucinated_method_is_a_real_scaffold_method():
    # guard the exact bug: get_cell_center must NOT be a defined method on the scaffold source
    assert "def get_cell_center" not in lattice_scene.LATTICE_SCENE_SRC
    assert "def cell(" in lattice_scene.LATTICE_SCENE_SRC


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
