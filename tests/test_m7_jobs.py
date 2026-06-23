"""M7 / FR-24 + FR-29 — job queue + streamable progress. Synchronous mode runs jobs inline, so
status transitions, per-scene state, the replay cursor, and failure capture are all deterministic
and need no threads/network/docker."""
import pytest

from web import jobs as J


@pytest.mark.unit
def test_synchronous_job_runs_and_records_result_and_events():
    q = J.JobQueue(synchronous=True)

    def work(job):
        job.log("starting")
        job.set_scene(0, J.S_RENDERING)
        job.set_scene(0, J.S_DONE)
        job.log("finished")
        return {"ok": True}

    job = q.submit(work, kind="build", project_id="p1")
    assert job.status == J.DONE
    assert job.result == {"ok": True}
    assert job.scenes == {0: J.S_DONE}
    assert [e.message for e in job.events] == ["starting", "finished"]
    assert job.error is None


@pytest.mark.unit
def test_failed_job_is_captured_not_raised():
    q = J.JobQueue(synchronous=True)

    def boom(job):
        job.log("about to fail")
        raise RuntimeError("render exploded")

    job = q.submit(boom, kind="regenerate", project_id="p1", scene_index=2)
    assert job.status == J.FAILED
    assert "render exploded" in job.error
    assert job.scene_index == 2
    # the failure was also logged for the progress stream
    assert any("render exploded" in e.message for e in job.events)


@pytest.mark.unit
def test_events_since_cursor_supports_replay():
    job = J.Job(kind="build", project_id="p1")
    job.log("a")
    job.log("b")
    job.log("c")
    assert [e.message for e in job.events_since(0)] == ["a", "b", "c"]
    assert [e.message for e in job.events_since(2)] == ["c"]      # reconnect from cursor=2
    assert job.events_since(3) == []                             # nothing new yet


@pytest.mark.unit
def test_jobs_are_independent_and_listed_per_project():
    q = J.JobQueue(synchronous=True)
    a = q.submit(lambda j: j.log("a"), kind="build", project_id="p1")
    b = q.submit(lambda j: j.log("b"), kind="build", project_id="p2")
    c = q.submit(lambda j: j.log("c"), kind="build", project_id="p1")
    assert q.get(a.id) is a and q.get(b.id) is b
    assert {j.id for j in q.list(project_id="p1")} == {a.id, c.id}
    assert q.get("nope") is None


@pytest.mark.unit
def test_progress_phases_thinking_rendering_merging_done():
    job = J.Job(kind="build", project_id="p1")
    # no scenes seeded yet -> thinking
    assert job.progress()["phase"] == "thinking"

    for i in range(4):                          # 4 scenes queued -> still thinking (0 done)
        job.set_scene(i, J.S_QUEUED)
    assert job.progress()["phase"] == "thinking"

    job.set_scene(0, J.S_RENDERING)
    p = job.progress()
    assert p["phase"] == "rendering" and p["label"] == "Scene 1 of 4"

    for i in range(4):
        job.set_scene(i, J.S_DONE)
    assert job.progress()["phase"] == "merging" and job.progress()["pct"] == 95

    job._mark_finished(J.DONE)
    done = job.progress()
    assert done["phase"] == "done" and done["pct"] == 100


@pytest.mark.unit
def test_progress_pct_climbs_with_scenes_done():
    job = J.Job(kind="build", project_id="p1")
    for i in range(5):
        job.set_scene(i, J.S_QUEUED)
    job.set_scene(0, J.S_DONE)
    job.set_scene(1, J.S_RENDERING)
    p = job.progress()
    assert p["done"] == 1 and p["total"] == 5
    assert 10 < p["pct"] < 90 and p["label"] == "Scene 2 of 5"


@pytest.mark.unit
def test_progress_failed():
    job = J.Job(kind="regenerate", project_id="p1", scene_index=0)
    job.set_scene(0, J.S_RENDERING)
    job._mark_finished(J.FAILED, error="boom")
    assert job.progress()["phase"] == "failed"


@pytest.mark.unit
def test_job_to_dict_shape():
    job = J.Job(kind="tweak", project_id="p9", scene_index=3)
    job.set_scene(3, J.S_RENDERING)
    d = job.to_dict()
    assert d["kind"] == "tweak" and d["project_id"] == "p9" and d["scene_index"] == 3
    assert d["status"] == J.QUEUED and d["scenes"] == {3: J.S_RENDERING}
    assert d["event_count"] == 0
