"""Phase A (partial) — cooperative cancellation + the named-step vocabulary.

What is proven here: a token trips on request or on a deadline; the pipeline's checkpoints observe
it; a stopped scene is given up rather than retried; a stopped build raises instead of stitching;
and no ambient token means no behaviour change at all (CLI, evals, every existing test).

NOT covered here (the job/API/UI half of Phase A is not wired yet — see PHASE_A_STATUS.md):
web.jobs step tracking, POST /api/jobs/{id}/cancel, the UI timer and Stop button.
"""
import time

import pytest

from core import cancel
from web import phases


# --- the token ---------------------------------------------------------------------------------
@pytest.mark.unit
def test_check_is_a_noop_without_a_token():
    """Every check() in the pipeline must be free for the CLI and eval paths."""
    cancel.set_current(None)
    cancel.check()          # must not raise


@pytest.mark.unit
def test_token_trips_on_request():
    tok = cancel.CancelToken()
    with cancel.scope(tok):
        cancel.check()
        tok.cancel()
        with pytest.raises(cancel.Cancelled) as e:
            cancel.check()
    assert e.value.reason == "cancelled"


@pytest.mark.unit
def test_token_trips_on_deadline():
    clock = [1000.0]
    tok = cancel.CancelToken(deadline_s=30, now=lambda: clock[0])
    with cancel.scope(tok):
        cancel.check()
        clock[0] += 31
        with pytest.raises(cancel.Cancelled) as e:
            cancel.check()
    assert e.value.reason == "deadline"          # an actionable reason, not a generic failure


@pytest.mark.unit
def test_cancelled_is_not_caught_by_except_exception():
    """The pipeline is full of `except Exception` handlers that retry or degrade. Every one of them
    would otherwise swallow a stop request and keep spending — hence BaseException."""
    try:
        raise cancel.Cancelled()
    except Exception:                            # noqa: BLE001 — that is the point of the test
        pytest.fail("Cancelled was caught by `except Exception`")
    except cancel.Cancelled:
        pass


@pytest.mark.unit
def test_scope_restores_the_previous_token():
    outer = cancel.CancelToken()
    with cancel.scope(outer):
        with cancel.scope(cancel.CancelToken()):
            pass
        assert cancel.current() is outer
    assert cancel.current() is None


@pytest.mark.unit
def test_carry_moves_the_token_onto_a_worker_thread():
    """Thread-locals do not inherit: without carry(), a scene rendering on a pool thread would
    never see its job's stop switch."""
    from concurrent.futures import ThreadPoolExecutor

    tok = cancel.CancelToken()
    with cancel.scope(tok):
        fn = cancel.carry(lambda: cancel.current())
    with ThreadPoolExecutor(max_workers=2) as ex:
        assert ex.submit(fn).result() is tok


@pytest.mark.unit
def test_step_deadline_is_per_thread_and_tighter_than_the_job():
    with cancel.deadline(0.01):
        time.sleep(0.02)
        with pytest.raises(cancel.Cancelled):
            cancel.check()
    cancel.check()                               # scope over -> the step's clock is gone


# --- the pipeline checkpoints -------------------------------------------------------------------
@pytest.mark.unit
def test_llm_create_stops_between_attempts(monkeypatch):
    from core import llm as llm_mod

    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)
            raise RuntimeError("upstream 500")

    c = llm_mod.LLMClient(model="m")
    c._client = type("C", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    tok = cancel.CancelToken()
    tok.cancel()
    with cancel.scope(tok), pytest.raises(cancel.Cancelled):
        c._create(messages=[{"role": "user", "content": "hi"}], model="m")
    assert calls == []                           # stopped BEFORE spending on another call


@pytest.mark.unit
def test_render_is_never_started_for_a_stopped_job(monkeypatch):
    """A render is the most expensive step in the pipeline; starting one for a job that is ending
    burns a container and up to render_timeout_s of wall clock for nothing."""
    from render import sandbox

    monkeypatch.setattr(sandbox, "build_command",
                        lambda *a, **k: pytest.fail("built a render command for a stopped job"))
    tok = cancel.CancelToken()
    tok.cancel()
    with cancel.scope(tok), pytest.raises(cancel.Cancelled):
        sandbox.render("wd", "scene.py", "GeneratedScene")


@pytest.mark.unit
def test_a_stopped_scene_is_given_up_not_retried(monkeypatch, tmp_path):
    """A stop must not look like a code failure: no retry, and a state of its own."""
    from composition import decoupled

    tries = []

    def boom(*a, **k):
        tries.append(1)
        cancel.check()
        return tmp_path / "x.mp4"

    monkeypatch.setattr(decoupled, "build_scene", boom)
    states = []
    tok = cancel.CancelToken()
    tok.cancel()
    with cancel.scope(tok):
        index, mp4 = decoupled._build_with_retry(
            object(), object(), 0, scenes_dir=tmp_path, client=object(), style=None,
            use_components=True, use_critic=False, structural=True, quality="preview",
            retries=3, on_scene=lambda i, s: states.append(s))

    assert (index, mp4) == (0, None)
    assert tries == []                           # the checkpoint fires before the attempt
    assert states == ["cancelled"]               # not "retry 1/3", not "failed"


@pytest.mark.unit
def test_a_stopped_build_raises_instead_of_stitching(monkeypatch, tmp_path):
    """Stitching a video nobody is waiting for is wasted work — but the scene clips that did
    finish stay on disk, so nothing already paid for is thrown away."""
    from composition import decoupled
    from core.schemas.outline import Outline, OutlineItem
    from core.schemas.style import StyleSpec

    clip = tmp_path / "scene.mp4"
    clip.write_bytes(b"v")
    tok = cancel.CancelToken()

    def one_scene(item, outline, index, **kw):
        tok.cancel()                             # the user presses Stop while scene 0 is finishing
        return (index, clip)

    monkeypatch.setattr(decoupled, "_build_with_retry", one_scene)
    monkeypatch.setattr(decoupled.stitch, "stitch",
                        lambda *a, **k: pytest.fail("stitched a cancelled build"))

    outline = Outline(topic="t", items=[OutlineItem(title="A", intent="x")])
    with cancel.scope(tok), pytest.raises(cancel.Cancelled):
        decoupled.build_video("t", outline=outline, style=StyleSpec(palette={"primary": "#111"}),
                              client=object(), out_dir=tmp_path, log=lambda _m: None)
    assert clip.exists()


# --- the step vocabulary -------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize("line, step, attempt", [
    # literal strings the pipeline emits today (composition/decoupled, verification/*, web/devtrace)
    ("-> outline for: 'binary search'", phases.PLANNING, None),
    ("-> using provided outline (3 scenes)", phases.PLANNING, None),
    ("-> building 3 scenes (workers=3, retries=3, layout=structural(grid))", phases.SCENE_SPEC, None),
    ("[llm#2] spec · deepseek-chat · sys 3.1k · user 0.2k", phases.SCENE_SPEC, None),
    ("[llm#3] codegen · deepseek-chat · sys 8.1k · user 0.6k", phases.CODEGEN, None),
    ("[llm#7] compile-fix · deepseek-chat · sys 8.1k · user 1.2k", phases.CODEGEN, None),
    ("[compile] attempt 2/4: FAILED (exit 1)", phases.RENDER, "2/4"),
    ("[critic] iter 1/3: layout-lint found 2 violation(s)", phases.LINT, "1/3"),
    ("[critic] iter 2/3: 1 defect(s)", phases.VISION, "2/3"),
    ("[llm#9] narration · deepseek-chat · sys 1.0k · user 0.3k", phases.NARRATION, None),
    ("-> synthesizing audio (host-side gTTS, render stays no-net)", phases.NARRATION, None),
    ("-> rendering (sandboxed, no network; audio mounted in)", phases.RENDER, None),
    ("-> stitching", phases.STITCH, None),
])
def test_classify_names_the_step_and_the_attempt(line, step, attempt):
    assert phases.classify(line) == (step, attempt)


@pytest.mark.unit
@pytest.mark.parametrize("line", ["   3 scenes", "[llm#3] ok · 2.4k chars · 17.3s", ""])
def test_classify_returns_none_for_detail_lines(line):
    """Most log lines are detail WITHIN a step; the caller must keep the step it had."""
    assert phases.classify(line) is None


@pytest.mark.unit
def test_classify_scene_status_reads_the_retry_counter():
    assert phases.classify_scene_status("retry 2/3: APIConnectionError") == (phases.RETRYING, "2/3")
    assert phases.classify_scene_status("cancelled") == (phases.CANCELLED, None)
    assert phases.classify_scene_status("done") is None


@pytest.mark.unit
def test_every_step_has_user_facing_wording():
    for step in (phases.PLANNING, phases.STYLE, phases.SCENE_SPEC, phases.CODEGEN, phases.RENDER,
                 phases.LINT, phases.VISION, phases.NARRATION, phases.MUX, phases.STITCH,
                 phases.RETRYING, phases.COMPLETE, phases.FAILED, phases.CANCELLED):
        assert phases.label(step) and phases.label(step) != step
