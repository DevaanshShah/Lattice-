"""Deterministic error->fix fast-path: free, exact fixes for common Manim errors (invented colors,
stale API) applied before the LLM repair call. Pure + the compile_repair wiring (no Docker/model)."""
import pytest

from render.worker import WorkerResult
from verification import error_fixes
from verification.caps import Caps
from verification.compile_repair import repair


@pytest.mark.unit
def test_invented_color_fixed_from_nameerror():
    code = "from manim import *\nc = Circle(color=CYAN)\n"
    err = "NameError: name 'CYAN' is not defined"
    fixed = error_fixes.try_deterministic_fix(code, err)
    assert fixed is not None and "CYAN" not in fixed and "#00BCD4" in fixed


@pytest.mark.unit
def test_stale_api_fixed():
    code = "from manim import *\nself.play(ShowCreation(Circle()))\n"
    err = "NameError: name 'ShowCreation' is not defined"
    fixed = error_fixes.try_deterministic_fix(code, err)
    assert fixed is not None and "ShowCreation" not in fixed and "Create(" in fixed


@pytest.mark.unit
def test_no_rule_returns_none():
    code = "from manim import *\nx = undefined_thing\n"
    assert error_fixes.try_deterministic_fix(code, "NameError: name 'undefined_thing' is not defined") is None
    assert error_fixes.try_deterministic_fix(code, "") is None


@pytest.mark.unit
def test_only_substitutes_when_error_names_it():
    # CYAN appears in code but the error is about something else -> do NOT touch it
    code = "from manim import *\nc = Circle(color=CYAN)\n"
    assert error_fixes.try_deterministic_fix(code, "ValueError: something unrelated") is None


@pytest.mark.unit
def test_repair_uses_free_fix_before_llm(monkeypatch, tmp_path):
    # render fails once with an invented-color NameError, then (after the free fix) succeeds.
    state = {"n": 0}
    mp4 = tmp_path / "v.mp4"; mp4.write_bytes(b"v")

    def render_fn(code, wd):
        state["n"] += 1
        if state["n"] == 1:
            return WorkerResult(False, 1, "", "NameError: name 'CYAN' is not defined", None, [], [])
        return WorkerResult(True, 0, "", "", mp4, [], [])   # the free fix made it compile

    llm_calls = {"n": 0}

    def regen_fn(code, err):
        llm_calls["n"] += 1
        return code

    rep = repair("c = Circle(color=CYAN)", tmp_path, render_fn=render_fn, regen_fn=regen_fn,
                 caps=Caps(max_repair_attempts=4))
    assert rep.ok and llm_calls["n"] == 0   # fixed for FREE — the LLM repair was never called
