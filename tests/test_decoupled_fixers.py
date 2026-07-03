"""The structural scaffold must SURVIVE a regen, on BOTH regen paths.

Confirmed regression: a scene generated in structural mode hit a COMPILE failure mid-run. Because
`build_scene` never wired a structural-aware `compile_regen_fn`, `compile_repair` fell back to its
generic default fixer (no scaffold awareness, no re-prepend) and the scene permanently reverted to a
plain freehand `Scene` subclass -- losing every geometry primitive (square_on_segment) for the rest of
that scene. `_make_issue_fixer` (vision/lint-driven) was already scaffold-safe; `_make_compile_fixer`
closes the same gap for compile-failure-driven regen. Pure prompt-construction tests (fake client) --
no LLM/Docker needed.
"""
import pytest

from composition.decoupled import _make_compile_fixer, _make_issue_fixer
from generation.lattice_scene import LATTICE_SCENE_SRC
from verification.vision_critic import CritiqueIssue, CritiqueReport

STRUCTURAL_CODE = (
    LATTICE_SCENE_SRC + "\n\n"
    "class GeneratedScene(LatticeScene):\n"
    "    def construct(self):\n"
    "        self.setup_scene('T')\n"
)


class _FakeClient:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, **kw):
        return self.reply


@pytest.mark.unit
def test_compile_fixer_reprepends_scaffold_after_regen():
    # the model's fix reply is a bare scene (as it would write when only shown "just the scene")
    fixed_reply = "class GeneratedScene(LatticeScene):\n    def construct(self):\n        self.setup_scene('T')\n        self.play(Create(Circle()))\n"
    fixer = _make_compile_fixer(spec=None, style=None, use_components=False,
                                client=_FakeClient(fixed_reply), structural=True)
    out = fixer(STRUCTURAL_CODE, "NameError: x is not defined")
    assert "class LatticeScene(Scene)" in out          # base re-prepended, not dropped
    assert out.index("class LatticeScene") < out.index("class GeneratedScene")


@pytest.mark.unit
def test_compile_fixer_freehand_mode_reenforces_background():
    fixed_reply = "class GeneratedScene(Scene):\n    def construct(self):\n        self.play(Create(Circle()))\n"
    fixer = _make_compile_fixer(spec=None, style=None, use_components=False,
                                client=_FakeClient(fixed_reply), structural=False)
    out = fixer("class GeneratedScene(Scene):\n    def construct(self):\n        pass\n",
               "SyntaxError: bad")
    assert "background_color" in out                   # freehand path re-pins the background


@pytest.mark.unit
def test_issue_fixer_reprepends_scaffold_after_regen():
    fixed_reply = "class GeneratedScene(LatticeScene):\n    def construct(self):\n        self.setup_scene('T')\n        self.play(Create(Circle()))\n"
    fixer = _make_issue_fixer(spec=None, style=None, use_components=False,
                              client=_FakeClient(fixed_reply), structural=True)
    report = CritiqueReport(ok=False, issues=[CritiqueIssue(type="overlap", description="x overlaps y")])
    out = fixer(STRUCTURAL_CODE, report)
    assert "class LatticeScene(Scene)" in out
    assert out.index("class LatticeScene") < out.index("class GeneratedScene")
