"""M7 follow-ups: the sound regression guard, storytelling narration context, and audio-robust
stitch. All Docker-free (subprocess/model are faked or the logic is pure)."""
from pathlib import Path

import pytest

from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec

SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})

VOICED = ("from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n"
          "        self.add_sound('audio/a.mp3')\n        self.play(Create(Circle()))\n")
SILENT = ("from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n"
          "        self.play(Create(Circle()))\n")


# --- sound guard: the visual fixer must never drop add_sound (FR-18 / regression) ----------

@pytest.mark.unit
def test_fixer_rejects_audio_dropping_rewrite():
    from narration import narrate
    from verification.vision_critic import CritiqueIssue, CritiqueReport

    class Fake:  # the "fix" silently drops the add_sound call
        def chat(self, m, **k):
            return SILENT

    fixer = narrate._narration_aware_fixer(SPEC, None, Fake())
    out = fixer(VOICED, CritiqueReport(ok=False, issues=[CritiqueIssue(type="off_frame", description="x")]))
    assert out == VOICED and "add_sound" in out  # rejected -> prior voiced code kept


@pytest.mark.unit
def test_fixer_accepts_audio_preserving_rewrite():
    from narration import narrate
    from verification.vision_critic import CritiqueIssue, CritiqueReport

    moved = VOICED.replace("Create(Circle())", "Create(Circle().shift(LEFT))")

    class Fake:
        def chat(self, m, **k):
            return moved

    fixer = narrate._narration_aware_fixer(SPEC, None, Fake())
    out = fixer(VOICED, CritiqueReport(ok=False, issues=[CritiqueIssue(type="overlap", description="y")]))
    # preserved add_sound -> the rewrite is accepted (the visual change is applied)
    assert "add_sound" in out and "shift(LEFT)" in out


# --- storytelling narration context --------------------------------------------------------

@pytest.mark.unit
def test_story_context_links_prev_and_next():
    from composition import video
    from composition.scene_dag import VideoProject

    proj = VideoProject.from_outline(Outline.model_validate({"topic": "neural networks", "items": [
        {"title": "Neuron", "intent": "a"}, {"title": "Layer", "intent": "b"}, {"title": "Stack", "intent": "c"}]}))
    ctx = video._story_context(proj, 1)
    assert "scene 2 of 3" in ctx
    assert "Neuron" in ctx          # links back to the previous scene
    assert "Stack" in ctx           # bridges into the next scene
    assert "neural networks" in ctx


@pytest.mark.unit
def test_story_context_empty_for_single_scene():
    from composition import video
    from composition.scene_dag import VideoProject

    proj = VideoProject.from_outline(Outline.model_validate(
        {"topic": "x", "items": [{"title": "A", "intent": "a"}]}))
    assert video._story_context(proj, 0) == ""


@pytest.mark.unit
def test_narration_generate_injects_context():
    from narration import script

    captured = {}

    class Fake:
        def chat(self, messages, **k):
            captured["user"] = messages[-1]["content"]
            return '{"lines": ["one"]}'

    script.generate(SPEC, context="STORY CONTEXT — this is scene 2 of 3", client=Fake())
    assert "STORY CONTEXT" in captured["user"]


# --- audio-robust stitch -------------------------------------------------------------------

@pytest.mark.unit
def test_audio_command_builders_shape():
    from composition.stitch import build_add_silent_audio_command, build_probe_audio_command

    pc = build_probe_audio_command("wd", "parts/p.mp4")
    assert "ffprobe" in pc and "--network=none" in pc and "parts/p.mp4" in pc

    ac = build_add_silent_audio_command("wd", "in.mp4", "out.mp4")
    assert "ffmpeg" in ac and "anullsrc=channel_layout=stereo:sample_rate=44100" in ac
    assert "aac" in ac and ac[-1] == "out.mp4"


@pytest.mark.unit
def test_ensure_uniform_audio_silences_only_voiceless(monkeypatch, tmp_path):
    import subprocess

    from composition import stitch as s

    parts = tmp_path / "parts"; parts.mkdir()
    (parts / "part_000.mp4").write_bytes(b"v0")
    (parts / "part_001.mp4").write_bytes(b"v1")
    rels = ["parts/part_000.mp4", "parts/part_001.mp4"]
    added = []

    def fake_run(cmd, **kw):
        if "ffprobe" in cmd:
            rel = cmd[-1]
            return subprocess.CompletedProcess(cmd, 0, "0\n" if rel.endswith("000.mp4") else "", "")
        out_rel = cmd[-1]                                  # ffmpeg add-silent: create the output
        (tmp_path / out_rel).write_bytes(b"withaudio")
        added.append(out_rel)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(s.subprocess, "run", fake_run)
    s._ensure_uniform_audio(tmp_path, rels)
    assert added == ["parts/part_001.mp4.aud.mp4"]         # only the voiceless clip got a track
    assert (parts / "part_001.mp4").read_bytes() == b"withaudio"  # swapped in
    assert (parts / "part_000.mp4").read_bytes() == b"v0"         # voiced clip untouched


@pytest.mark.unit
def test_ensure_uniform_audio_noop_when_all_voiced(monkeypatch, tmp_path):
    import subprocess

    from composition import stitch as s

    fixed = []
    def fake_run(cmd, **kw):
        if "ffprobe" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "0\n", "")   # everyone has audio
        fixed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(s.subprocess, "run", fake_run)
    s._ensure_uniform_audio(tmp_path, ["parts/a.mp4", "parts/b.mp4"])
    assert fixed == []   # uniform -> no remux


@pytest.mark.unit
def test_ensure_uniform_audio_single_clip_skips_probe(monkeypatch):
    from composition import stitch as s

    called = []
    monkeypatch.setattr(s.subprocess, "run", lambda *a, **k: called.append(1))
    s._ensure_uniform_audio("wd", ["parts/only.mp4"])
    assert called == []   # 1 clip can't be a mix -> no Docker calls at all
