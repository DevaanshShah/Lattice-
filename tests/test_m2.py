"""M2 unit tests — the hard gate. No Docker, no network, no model calls.

Every I/O boundary (render, model fixer, vision critic) is injected as a fake, so these
assert the *behaviour* that makes M2's DoD hold:
  - render worker builds a sandboxed, multi-frame extraction command (T-3)
  - compile-repair recovers within the cap, trims the traceback it feeds back, and fails
    gracefully (best attempt + useful error, never spins) when it can't (T-4 / FR-5, FR-7)
  - the vision critic output is STRUCTURED and the loop is capped (T-5 / FR-6)
  - the free compile check GATES the paid vision call — never conflated (the M2 invariant)
  - best-of-N keeps the highest-scoring candidate (T-5 / FR-6 fallback)
"""
from pathlib import Path

import pytest

from render.worker import WorkerResult


def _ok(frames, mp4="out.mp4"):
    return WorkerResult(True, 0, "", "", Path(mp4), [Path(f) for f in frames], [])


def _fail(stderr, code=1):
    return WorkerResult(False, code, "", stderr, None, [], [])


# --- T-3: render worker (pure command builders are unit-testable without Docker) -----------

@pytest.mark.unit
def test_extract_command_is_sandboxed_and_multiframe(tmp_path):
    from render.worker import build_extract_command
    cmd = build_extract_command(tmp_path, "media/videos/scene/480p15/GeneratedScene.mp4",
                                "frames/frame_%03d.png", vf="fps=0.5", n=3)
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in cmd                    # sandbox invariant holds for ffmpeg too
    assert "ffmpeg" in cmd
    assert "-frames:v" in cmd and "3" in cmd          # samples MULTIPLE frames, not one
    assert "frames/frame_%03d.png" in cmd


@pytest.mark.unit
def test_probe_command_is_sandboxed():
    from render.worker import build_probe_command
    cmd = build_probe_command(Path.cwd(), "x.mp4")
    assert "ffprobe" in cmd and "--network=none" in cmd


@pytest.mark.unit
def test_render_code_writes_scene_and_reports_failure(tmp_path, monkeypatch):
    """A render crash surfaces as ok=False (the free compile signal), code persisted."""
    import render.worker as w
    from render.sandbox import RenderResult
    monkeypatch.setattr(w.sandbox, "render",
                        lambda *a, **k: RenderResult(1, "", "boom", []))
    res = w.render_code("from manim import *\n# code", tmp_path)
    assert res.ok is False and res.mp4 is None
    assert (tmp_path / "scene.py").read_text(encoding="utf-8").startswith("from manim import *")


@pytest.mark.unit
def test_render_code_extracts_frames_on_success(tmp_path, monkeypatch):
    import render.worker as w
    from render.sandbox import RenderResult
    mp4 = tmp_path / "v.mp4"
    # RenderResult is (returncode, stdout, stderr, command, outputs) — mp4 goes in outputs (5th)
    monkeypatch.setattr(w.sandbox, "render",
                        lambda *a, **k: RenderResult(0, "", "", [], [mp4]))
    monkeypatch.setattr(w, "extract_frames", lambda wd, m, n=3: [tmp_path / "f0.png", tmp_path / "f1.png"])
    res = w.render_code("code", tmp_path, frames=2)
    assert res.ok and res.mp4 == mp4 and len(res.frames) == 2


# --- T-4: caps + compile-repair ------------------------------------------------------------

@pytest.mark.unit
def test_caps_default_from_settings_and_clamp():
    from core.config import settings
    from verification.caps import Caps
    c = Caps()
    assert c.max_repair_attempts == settings.max_repair_attempts
    assert Caps(max_repair_attempts=0).max_repair_attempts == 1   # never "don't try"


@pytest.mark.unit
def test_trim_traceback_keeps_error_drops_banner():
    from verification.compile_repair import trim_traceback
    banner = "\n".join(f"noise {i}" for i in range(200))
    tb = ("Traceback (most recent call last):\n"
          '  File "scene.py", line 7, in construct\n'
          "    self.play(Create(undefined_circle))\n"
          "NameError: name 'undefined_circle' is not defined")
    out = trim_traceback(banner + "\n" + tb, max_chars=2000)
    assert out.startswith("Traceback (most recent call last)")
    assert "NameError" in out and "noise 0" not in out
    assert len(out) <= 2000


@pytest.mark.unit
def test_trim_traceback_caps_chars_and_keeps_tail():
    from verification.compile_repair import trim_traceback
    huge = "Traceback (most recent call last):\n" + "x" * 5000 + "\nNameError: boom"
    out = trim_traceback(huge, max_chars=500)
    assert len(out) <= 500 and out.endswith("NameError: boom")  # the tail (error) is kept


@pytest.mark.unit
def test_trim_traceback_no_traceback_keeps_last_lines():
    from verification.compile_repair import trim_traceback
    out = trim_traceback("\n".join(f"line{i}" for i in range(100)), max_lines=10)
    assert "line99" in out and "line0\n" not in out


@pytest.mark.unit
def test_repair_recovers_within_cap_and_logs(tmp_path):
    """Broken first render, fixed second -> recovers; each attempt logged."""
    from verification.caps import Caps
    from verification.compile_repair import repair

    renders = [_fail("Traceback (most recent call last):\nNameError: x"), _ok(["f.png"])]
    seen_errors = []

    def render_fn(code, wd):
        return renders.pop(0)

    def regen_fn(code, error):
        seen_errors.append(error)
        return "fixed code"

    res = repair("bad code", tmp_path, render_fn=render_fn, regen_fn=regen_fn,
                 caps=Caps(max_repair_attempts=4))
    assert res.ok and res.code == "fixed code" and res.mp4 is not None
    assert [a.ok for a in res.attempts] == [False, True]
    assert len(seen_errors) == 1 and "NameError" in seen_errors[0]   # trimmed traceback fed back


@pytest.mark.unit
def test_repair_fails_gracefully_after_cap_never_spins(tmp_path):
    from verification.caps import Caps
    from verification.compile_repair import repair

    calls = {"render": 0, "regen": 0}

    def render_fn(code, wd):
        calls["render"] += 1
        return _fail("Traceback (most recent call last):\nValueError: nope")

    def regen_fn(code, error):
        calls["regen"] += 1
        return "still bad"

    res = repair("bad", tmp_path, render_fn=render_fn, regen_fn=regen_fn,
                 caps=Caps(max_repair_attempts=3))
    assert res.ok is False
    assert res.error and "did not compile" in res.error          # useful error, best attempt
    assert calls["render"] == 3 and calls["regen"] == 2          # bounded: never exceeds cap
    assert res.n_attempts == 3


# --- T-5: structured critique + caps + best-of-N -------------------------------------------

@pytest.mark.unit
def test_critique_report_is_structured_with_scores():
    from verification.vision_critic import CritiqueReport
    r = CritiqueReport.model_validate({
        "ok": False, "score": 55,
        "issues": [{"type": "overlap", "location": "top", "description": "labels stack",
                    "suggested_fix": "shift down"}],
    })
    assert r.ok is False and r.n_issues == 1
    i = r.issues[0]
    assert i.type == "overlap" and i.location == "top" and i.suggested_fix == "shift down"
    assert r.effective_score() == 55


@pytest.mark.unit
def test_critique_report_accepts_aliases_and_derives_score():
    from verification.vision_critic import CritiqueReport
    # tolerant of the older 'where'/'fix' field names; derives a score when none is given
    r = CritiqueReport.model_validate({"ok": False, "issues": [
        {"type": "off_screen", "where": "right edge", "fix": "to_edge(LEFT)"}]})
    assert r.issues[0].location == "right edge" and r.issues[0].suggested_fix == "to_edge(LEFT)"
    assert r.effective_score() == 80                                 # 100 - 20*1 issue
    assert CritiqueReport(ok=True).effective_score() == 100          # clean scene


@pytest.mark.unit
def test_critique_degrades_on_unparseable_reply(tmp_path):
    from verification import vision_critic
    png = tmp_path / "f.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n fake")

    class Fake:
        def chat(self, messages, **kw):
            return "I think it looks pretty good honestly"   # not JSON

    r = vision_critic.critique([png], intent="x", client=Fake())
    assert r.ok is False and r.n_issues == 1 and r.issues[0].type == "other"


@pytest.mark.unit
def test_critique_requires_frames():
    from verification.vision_critic import CritiqueError, critique
    with pytest.raises(CritiqueError):
        critique([], intent="x", client=object())


@pytest.mark.unit
def test_data_url_is_base64_png(tmp_path):
    from verification.vision_critic import _data_url
    png = tmp_path / "f.png"
    png.write_bytes(b"hello")
    assert _data_url(png).startswith("data:image/png;base64,")


@pytest.mark.unit
def test_compile_gates_vision_invariant(tmp_path):
    """THE invariant: if the scene never compiles, the paid vision critic is NEVER called."""
    from verification.caps import Caps
    from verification import vision_critic

    critic_calls = {"n": 0}

    def render_fn(code, wd):
        return _fail("Traceback (most recent call last):\nNameError: boom")

    def critic_fn(frames):
        critic_calls["n"] += 1
        from verification.vision_critic import CritiqueReport
        return CritiqueReport(ok=True)

    res = vision_critic.run("bad", tmp_path, None, render_fn=render_fn, critic_fn=critic_fn,
                            compile_regen_fn=lambda c, e: "still bad",
                            issue_regen_fn=lambda c, r: c,
                            caps=Caps(max_repair_attempts=2, max_critic_iters=2))
    assert res.compiled is False and res.critique is None
    assert critic_calls["n"] == 0            # compile gated vision — never conflated
    assert res.passed is False


@pytest.mark.unit
def test_critic_loop_converges_when_clean(tmp_path):
    from verification.caps import Caps
    from verification import vision_critic
    from verification.vision_critic import CritiqueReport

    regen_calls = {"n": 0}

    def render_fn(code, wd):
        return _ok(["f0.png", "f1.png", "f2.png"])

    def critic_fn(frames):
        assert len(frames) == 3             # samples MULTIPLE frames, not one
        return CritiqueReport(ok=True, score=95)

    res = vision_critic.run("code", tmp_path, None, render_fn=render_fn, critic_fn=critic_fn,
                            compile_regen_fn=lambda c, e: c,
                            issue_regen_fn=lambda c, r: regen_calls.__setitem__("n", regen_calls["n"] + 1) or c,
                            caps=Caps(max_critic_iters=3))
    assert res.passed and res.compiled and res.iterations == 1
    assert regen_calls["n"] == 0            # no fix needed once it's clean


@pytest.mark.unit
def test_critic_loop_returns_best_on_nonconvergence(tmp_path):
    """Always-flagged scene -> loop hits the cap and returns the highest-scoring attempt."""
    from verification.caps import Caps
    from verification import vision_critic
    from verification.vision_critic import CritiqueIssue, CritiqueReport

    scores = [40, 75, 60]      # iteration scores; best (75) must be the one returned
    seq = iter(scores)
    regen_calls = {"n": 0}

    def render_fn(code, wd):
        return _ok(["f0.png", "f1.png"])

    def critic_fn(frames):
        s = next(seq)
        return CritiqueReport(ok=False, score=s, issues=[CritiqueIssue(type="overlap")])

    def issue_regen_fn(code, report):
        regen_calls["n"] += 1
        return "revised"

    res = vision_critic.run("code", tmp_path, None, render_fn=render_fn, critic_fn=critic_fn,
                            compile_regen_fn=lambda c, e: c, issue_regen_fn=issue_regen_fn,
                            caps=Caps(max_critic_iters=3))
    assert res.compiled and res.passed is False        # never surfaced as "passed"
    assert res.score() == 75                            # best attempt kept
    assert res.iterations == 3 and regen_calls["n"] == 2   # bounded: cap respected, no spin


@pytest.mark.unit
def test_best_of_n_keeps_highest_scoring_compiled(tmp_path):
    from verification import best_of_n
    from verification.vision_critic import CritiqueReport, CritiqueResult

    def res(compiled, score):
        rep = CritiqueReport(ok=score >= 90, score=score)
        return CritiqueResult(compiled, rep if compiled else None, "code")

    # candidate 1 compiles with mediocre score; candidate 2 compiles best; candidate 0 doesn't compile
    table = {0: res(False, 99), 1: res(True, 55), 2: res(True, 88)}
    out = best_of_n.run(lambda i: f"code{i}", lambda code, i: table[i], n=3)
    assert out.best.index == 2 and out.best.score == 88     # compiled + highest score wins
    assert len(out.candidates) == 3


@pytest.mark.unit
def test_best_of_n_prefers_compiled_over_higher_uncompiled():
    from verification import best_of_n
    from verification.vision_critic import CritiqueReport, CritiqueResult

    table = {
        0: CritiqueResult(False, None, "c0"),                          # didn't compile
        1: CritiqueResult(True, CritiqueReport(ok=False, score=30), "c1"),  # compiled, low score
    }
    out = best_of_n.run(lambda i: f"c{i}", lambda code, i: table[i], n=2)
    assert out.best.index == 1 and out.best.compiled is True
