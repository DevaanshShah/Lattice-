"""Phase A — a running job says WHICH step it is on, for HOW long, on WHICH attempt, and can be
stopped. The failure this closes: a build that is busily retrying is indistinguishable from a hung
one, so the only options were "wait" and "kill the server".
"""
import time
from types import SimpleNamespace

import pytest

from core import cancel
from web import jobs as jobs_mod
from web import phases


def _job(**kw):
    return jobs_mod.Job(kind="build", project_id="p", **kw)


# --- the named step ------------------------------------------------------------------------------
@pytest.mark.unit
def test_the_pipelines_own_log_names_the_step():
    """No phase callback is threaded through the pipeline: the step is read off the narration the
    pipeline already emits (web/phases.py), so composition/ and verification/ stay web-agnostic."""
    job = _job()
    job.log("-> using provided outline (2 scenes)")
    assert job.progress()["step"] == phases.PLANNING

    job.log("[llm#3] codegen · deepseek-chat · sys 8.1k · user 0.6k")
    assert job.progress()["step"] == phases.CODEGEN

    job.log("[compile] attempt 2/4: FAILED (exit 1)")
    p = job.progress()
    assert (p["step"], p["attempt"], p["step_label"]) == (phases.RENDER, "2/4", "Rendering")


@pytest.mark.unit
def test_detail_lines_do_not_reset_the_step():
    job = _job()
    job.log("-> rendering (sandboxed, no network; audio mounted in)")
    job.log("[llm#4] ok · 2.4k chars · 17.3s")      # detail WITHIN the step
    job.log("   3 scenes")
    assert job.progress()["step"] == phases.RENDER


@pytest.mark.unit
def test_a_scene_retry_is_its_own_step():
    job = _job()
    job.set_scene(0, "retry 2/3: APIConnectionError")
    p = job.progress()
    assert (p["step"], p["attempt"]) == (phases.RETRYING, "2/3")


@pytest.mark.unit
def test_progress_reports_elapsed_and_keeps_the_old_coarse_contract():
    clock = [100.0]
    job = _job(now=lambda: clock[0])
    job._mark_running()
    job.set_step(phases.RENDER)
    clock[0] += 42
    p = job.progress()
    assert p["elapsed"] == 42 and p["step_elapsed"] == 42
    # the cylinder UI's existing keys must keep working
    assert set(("phase", "label", "pct", "done", "total", "scenes")) <= set(p)


# --- stopping -------------------------------------------------------------------------------------
@pytest.mark.unit
def test_cancelling_a_queued_job_ends_it_immediately():
    job = _job()
    assert job.cancel() is True
    assert job.status == jobs_mod.CANCELLED
    assert job.cancel() is False              # idempotent: already terminal


@pytest.mark.unit
def test_a_stopped_job_is_cancelled_not_failed():
    """Pressing Stop must not be reported to the user as a crash."""
    job = _job()
    started = time.time()

    def work(j):
        while time.time() - started < 5:
            cancel.check()                     # the pipeline's checkpoints, in miniature
            if j.token.cancelled:
                time.sleep(0.01)
            time.sleep(0.01)
        pytest.fail("the job ignored the stop request")

    import threading
    t = threading.Thread(target=jobs_mod.JobQueue._run, args=(job, work))
    t.start()
    while job.status != jobs_mod.RUNNING:
        time.sleep(0.01)
    job.cancel()
    t.join(timeout=5)

    assert job.status == jobs_mod.CANCELLED
    assert job.status != jobs_mod.FAILED
    assert "stopped" in (job.error or "")
    assert job.progress()["phase"] == "cancelled" and job.progress()["label"] == "Stopped"


@pytest.mark.unit
def test_a_job_past_its_deadline_ends_with_a_reason_not_a_hang():
    job = _job()
    job.token.deadline = time.monotonic() - 1      # already out of time

    jobs_mod.JobQueue._run(job, lambda j: cancel.check())

    assert job.status == jobs_mod.CANCELLED
    assert "time limit" in (job.error or "")       # actionable, not "APITimeoutError"
    assert job.step == phases.CANCELLED


@pytest.mark.unit
def test_finished_scenes_are_still_reported_after_a_stop():
    """Partial work is not thrown away: the scenes that rendered stay visible in the job state
    (their clips stay on disk), so a stopped build isn't a total loss."""
    job = _job()
    job.set_scene(0, jobs_mod.S_DONE)
    job.set_scene(1, jobs_mod.S_RENDERING)
    jobs_mod.JobQueue._run(job, lambda j: (_ for _ in ()).throw(cancel.Cancelled()))
    assert job.progress()["scenes"] == {0: "done", 1: "rendering"}
    assert job.progress()["done"] == 1


@pytest.mark.unit
def test_a_completed_job_is_marked_complete_and_uncancellable():
    job = _job()
    jobs_mod.JobQueue._run(job, lambda j: "result")
    p = job.progress()
    assert job.status == jobs_mod.DONE and p["step"] == phases.COMPLETE
    assert p["cancellable"] is False


# --- the endpoint ------------------------------------------------------------------------------
@pytest.mark.unit
def test_cancel_endpoint_stops_a_running_build(tmp_path):
    from fastapi.testclient import TestClient
    from web.app import create_app

    q = jobs_mod.JobQueue(workers=1)
    app = create_app(engine=SimpleNamespace(root=tmp_path), queue=q)
    client = TestClient(app)

    started = time.time()

    def work(j):
        while time.time() - started < 5:
            cancel.check()
            time.sleep(0.01)
        pytest.fail("the job ignored the stop request")

    job = q.submit(work, kind="build", project_id="p")
    while job.status != jobs_mod.RUNNING:
        time.sleep(0.01)

    r = client.post(f"/api/jobs/{job.id}/cancel")
    assert r.status_code == 200 and r.json()["accepted"] is True

    deadline = time.time() + 5
    while not job.done and time.time() < deadline:
        time.sleep(0.01)
    assert job.status == jobs_mod.CANCELLED

    # a job that already ended is a no-op, not an error
    assert client.post(f"/api/jobs/{job.id}/cancel").json()["accepted"] is False
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    q.shutdown()
