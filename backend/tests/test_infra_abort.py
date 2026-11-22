"""Infra-failure abort: a render failing because the SANDBOX is down (Docker unreachable) must
NOT trigger the repair loop's LLM fix calls — repairing the code can't fix a dead daemon. This is
what stopped the eval burning ~$0.16 thrashing against a stopped Docker. Pure (no Docker)."""
import pytest

from render.worker import WorkerResult
from verification.caps import Caps
from verification.compile_repair import _is_infra_failure, repair


def _wr(returncode, stderr):
    return WorkerResult(False, returncode, "", stderr, None, [], [])


@pytest.mark.unit
def test_is_infra_failure_distinguishes_docker_down_from_code_error():
    docker_down = _wr(127, "docker: error during connect: ... dockerDesktopLinuxEngine: The system "
                            "cannot find the file specified.")
    assert _is_infra_failure(docker_down)
    code_error = _wr(1, "NameError: name 'Circl' is not defined")
    assert not _is_infra_failure(code_error)


@pytest.mark.unit
def test_repair_aborts_on_infra_without_any_llm_fix():
    calls = {"render": 0, "fix": 0}

    def render_fn(code, wd):
        calls["render"] += 1
        return _wr(127, "docker: error during connect ... is the docker daemon running?")

    def regen_fn(code, err):
        calls["fix"] += 1
        return code

    rep = repair("code", "wd", render_fn=render_fn, regen_fn=regen_fn, caps=Caps(max_repair_attempts=4))
    assert rep.ok is False
    assert calls["render"] == 1 and calls["fix"] == 0   # one render, ZERO LLM fix calls (was 4+3 before)
    assert "Docker" in (rep.error or "")


@pytest.mark.unit
def test_repair_still_retries_real_code_errors():
    # a genuine code error must STILL drive the repair loop (don't over-abort)
    calls = {"render": 0, "fix": 0}

    def render_fn(code, wd):
        calls["render"] += 1
        return _wr(1, "NameError: name 'Squareee' is not defined")

    def regen_fn(code, err):
        calls["fix"] += 1
        return code

    repair("code", "wd", render_fn=render_fn, regen_fn=regen_fn, caps=Caps(max_repair_attempts=3))
    assert calls["render"] == 3 and calls["fix"] == 2   # full loop on a real code defect
