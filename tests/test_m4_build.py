"""M4 unit tests — captions, narrated codegen, and the narrate orchestrator. No net/docker."""
from pathlib import Path

import pytest

from core.schemas.scene_spec import SceneSpec

SPEC = SceneSpec.model_validate({
    "title": "Stack", "prompt": "explain a stack", "narration": "LIFO.",
    "objects": [{"id": "box", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["box"]},
              {"action": "write", "targets": ["box"]}],
})


# --- captions (FR-12) ---

@pytest.mark.unit
def test_build_srt_cumulative_timing():
    from narration.captions import build_srt
    srt = build_srt(["First.", "Second."], [1.0, 2.5])
    assert "1\n00:00:00,000 --> 00:00:01,000\nFirst." in srt
    assert "2\n00:00:01,000 --> 00:00:03,500\nSecond." in srt


@pytest.mark.unit
def test_ts_format():
    from narration.captions import _ts
    assert _ts(0) == "00:00:00,000"
    assert _ts(3661.5) == "01:01:01,500"


# --- narrated codegen (FR-11) ---

@pytest.mark.unit
def test_generate_narrated_returns_code_with_add_sound():
    from generation import codegen
    good = ("from manim import *\n"
            "class GeneratedScene(Scene):\n"
            "    def construct(self):\n"
            "        self.add_sound('audio/a.mp3')\n"
            "        self.play(Create(Circle()))\n")

    class Fake:
        def chat(self, m, **k):
            return good

    code = codegen.generate_narrated(SPEC, [("hi", "audio/a.mp3", 1.0)], client=Fake())
    assert "add_sound" in code


@pytest.mark.unit
def test_generate_narrated_retries_when_silent():
    """A reply with no add_sound is rejected and regenerated (a silent scene is a defect)."""
    from generation import codegen
    silent = ("from manim import *\nclass GeneratedScene(Scene):\n"
              "    def construct(self):\n        self.play(Create(Circle()))\n")
    voiced = silent.replace("        self.play",
                            "        self.add_sound('audio/a.mp3')\n        self.play", 1)

    class Fake:
        def __init__(self):
            self.n = 0

        def chat(self, m, **k):
            self.n += 1
            return silent if self.n == 1 else voiced

    f = Fake()
    code = codegen.generate_narrated(SPEC, [("hi", "audio/a.mp3", 1.0)], client=f)
    assert f.n == 2 and "add_sound" in code


# --- orchestrator ---

@pytest.mark.unit
def test_narrate_build_happy_path(tmp_path, monkeypatch):
    from core.schemas.narration import NarrationScript
    from narration import narrate
    from narration.tts import Clip
    from verification.compile_repair import RepairResult

    monkeypatch.setattr(narrate.narr_script, "generate",
                        lambda spec, **k: NarrationScript(lines=["alpha", "beta"]))

    def fake_synth(lines, *, out_dir, **k):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        clips = []
        for i, line in enumerate(lines):
            p = out / f"c{i}.mp3"
            p.write_bytes(b"x")
            clips.append(Clip(line, p, 1.0))
        return clips

    monkeypatch.setattr(narrate.tts, "synthesize_lines", fake_synth)
    monkeypatch.setattr(narrate.codegen, "generate_narrated",
                        lambda spec, beats, **k: "code with add_sound")
    mp4 = tmp_path / "v.mp4"
    monkeypatch.setattr(narrate.compile_repair, "repair",
                        lambda code, wd, **k: RepairResult(True, code, mp4, [], []))

    res = narrate.build(SPEC, work_dir=tmp_path, client=object(), log=None)
    assert res.compiled and res.mp4 == mp4
    assert res.srt and res.srt.exists()
    txt = res.srt.read_text(encoding="utf-8")
    assert "alpha" in txt and "beta" in txt


@pytest.mark.unit
def test_narrate_build_reports_failure(tmp_path, monkeypatch):
    from core.schemas.narration import NarrationScript
    from narration import narrate
    from narration.tts import Clip
    from verification.compile_repair import RepairResult

    monkeypatch.setattr(narrate.narr_script, "generate", lambda spec, **k: NarrationScript(lines=["x"]))
    monkeypatch.setattr(narrate.tts, "synthesize_lines",
                        lambda lines, *, out_dir, **k: [Clip("x", Path(out_dir) / "c.mp3", 1.0)]
                        if Path(out_dir).mkdir(parents=True, exist_ok=True) is None else [])
    monkeypatch.setattr(narrate.codegen, "generate_narrated", lambda spec, beats, **k: "code")
    monkeypatch.setattr(narrate.compile_repair, "repair",
                        lambda code, wd, **k: RepairResult(False, code, None, [], [], "boom"))

    res = narrate.build(SPEC, work_dir=tmp_path, client=object(), log=None)
    assert res.compiled is False and res.mp4 is None and res.srt is None
