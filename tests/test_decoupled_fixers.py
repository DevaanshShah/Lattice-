"""The structural scaffold must SURVIVE a regen, on BOTH regen paths.

Confirmed regression: a scene generated in structural mode hit a COMPILE failure mid-run. Because
`build_scene` never wired a structural-aware `compile_regen_fn`, `compile_repair` fell back to its
generic default fixer (no scaffold awareness, no re-prepend) and the scene permanently reverted to a
plain freehand `Scene` subclass -- losing every geometry primitive (square_on_segment) for the rest of
that scene. `_make_issue_fixer` (vision/lint-driven) was already scaffold-safe; `_make_compile_fixer`
closes the same gap for compile-failure-driven regen. Pure prompt-construction tests (fake client) --
no LLM/Docker needed.
"""
from pathlib import Path

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
def test_build_scene_keeps_good_render_when_narration_fails(tmp_path, monkeypatch):
    # the web defect: a scene RENDERED fine, then a narration/TTS hiccup discarded the whole thing.
    # Now a good silent render must survive -> the scene ships SILENT, not lost.
    from composition import decoupled
    from core.schemas.outline import Outline, OutlineItem
    from core.schemas.scene_spec import SceneSpec
    from verification.compile_repair import RepairResult

    spec = SceneSpec.model_validate({
        "title": "T", "prompt": "p", "narration": "n",
        "objects": [{"id": "o", "kind": "square"}], "beats": [{"action": "create", "targets": ["o"]}]})
    outline = Outline(topic="t", items=[OutlineItem(title="T", intent="x")])
    wd = tmp_path / "scene_0"

    def fake_repair(code, work_dir, **k):   # a successful render: a silent mp4 inside the work dir
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        silent = Path(work_dir) / "silent.mp4"
        silent.write_bytes(b"good-render")
        return RepairResult(True, code, silent, [], [])

    monkeypatch.setattr("verification.compile_repair.repair", fake_repair)
    monkeypatch.setattr("composition.decoupled._probe_duration", lambda *a, **k: 5.0)
    monkeypatch.setattr("composition.decoupled._scene_narration",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("narration provider 500")))

    out = decoupled.build_scene(
        outline.items[0], outline, 0, work_dir=wd, client=object(), use_critic=False, structural=True,
        base_code="class GeneratedScene(LatticeScene):\n    pass\n", spec=spec)

    assert out == wd / "narrated.mp4" and out.exists()
    assert out.read_bytes() == b"good-render"                         # the GOOD render, preserved
    assert (wd / "narration.txt").read_text().strip() == "(narration unavailable)"


@pytest.mark.unit
def test_issue_fixer_reprepends_scaffold_after_regen():
    fixed_reply = "class GeneratedScene(LatticeScene):\n    def construct(self):\n        self.setup_scene('T')\n        self.play(Create(Circle()))\n"
    fixer = _make_issue_fixer(spec=None, style=None, use_components=False,
                              client=_FakeClient(fixed_reply), structural=True)
    report = CritiqueReport(ok=False, issues=[CritiqueIssue(type="overlap", description="x overlaps y")])
    out = fixer(STRUCTURAL_CODE, report)
    assert "class LatticeScene(Scene)" in out
    assert out.index("class LatticeScene") < out.index("class GeneratedScene")
