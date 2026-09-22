"""M7 / FR-28 (+24/26/27/30) — the web API, exercised end-to-end through the REAL Engine + a
synchronous JobQueue, with only the heavy leaves faked (planner/style/render/stitch). This proves
the wiring is a thin pass-through to the engine: plan -> approve -> build -> stream -> edit ->
download, no Docker / model / network."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.schemas.scene_spec import SceneSpec
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from core.schemas.outline import Outline, OutlineItem
from core.schemas.style import StyleSpec
from narration.narrate import NarratedResult

SPEC = SceneSpec.model_validate({
    "title": "A", "prompt": "p", "narration": "n",
    "objects": [{"id": "o", "kind": "square"}],
    "beats": [{"action": "create", "targets": ["o"]}]})

LESSON = LessonPlan.model_validate({
    "topic": "TCP", "skill_id": "workflow_explainer", "learning_objective": "Trace TCP",
    "scenes": [
        {"id": "s0", "title": "Connect", "learning_goal": "Open the connection",
         "beats": [{"id": "b0", "spoken_text": "Send SYN", "claim_ids": ["c0"],
                    "visual_anchors": ["SYN"]}]},
        {"id": "s1", "title": "Confirm", "learning_goal": "Confirm the connection",
         "beats": [{"id": "b1", "spoken_text": "Receive ACK", "claim_ids": ["c1"],
                    "visual_anchors": ["ACK"]}]},
    ]})

VISUAL = BrowserVisualPlan.model_validate({
    "topic": "TCP", "skill_id": "workflow_explainer", "scenes": [
        {"lesson_scene_id": "s0", "pattern": "workflow",
         "objects": [{"id": "syn", "kind": "message", "role": "input", "label": "SYN"}],
         "beats": [{"narration_beat_id": "b0", "actions": [{"kind": "appear", "target_ids": ["syn"]}],
                    "evidence": [{"claim_ids": ["c0"], "object_ids": ["syn"], "kind": "label"}]}],
         "opening_visible_ids": [], "closing_visible_ids": ["syn"]},
        {"lesson_scene_id": "s1", "pattern": "workflow",
         "objects": [{"id": "ack", "kind": "message", "role": "output", "label": "ACK"}],
         "beats": [{"narration_beat_id": "b1", "actions": [{"kind": "appear", "target_ids": ["ack"]}],
                    "evidence": [{"claim_ids": ["c1"], "object_ids": ["ack"], "kind": "label"}]}],
         "opening_visible_ids": [], "closing_visible_ids": ["ack"]},
    ]})


@pytest.fixture
def client(tmp_path, monkeypatch):
    from web.engine import Engine
    from web import jobs as jobs_mod
    from web.app import create_app

    # --- fake the heavy leaves (everything that would touch a model or Docker) ---
    monkeypatch.setattr("planner.outline.generate",
                        lambda topic, **k: Outline(topic=topic, items=[
                            OutlineItem(title="A", intent="x"), OutlineItem(title="B", intent="y")]))
    monkeypatch.setattr("generation.style.generate",
                        lambda topic, outline, **k: StyleSpec(palette={"primary": "#111"}))

    def fake_build_video(prompt, *, outline=None, client=None, quality="preview", out_dir,
                         out_name="final.mp4", on_scene=None, log=print, **k):
        # mirror composition.decoupled.build_video's ON-DISK layout so the engine's
        # _populate_from_decoupled reads it back: scenes/scene_<i>/{narrated.mp4,narration.txt,
        # scene.py,spec.json}, plus a stitched final.
        out = Path(out_dir)
        items = list(outline.items) if outline is not None else []
        for i, _item in enumerate(items):
            if on_scene:
                on_scene(i, "rendering")
            sdir = out / "scenes" / f"scene_{i}"
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "narrated.mp4").write_bytes(b"v")
            (sdir / "narration.txt").write_text("n", encoding="utf-8")
            (sdir / "scene.py").write_text("class GeneratedScene(LatticeScene):\n    pass\n",
                                           encoding="utf-8")
            (sdir / "spec.json").write_text(SPEC.model_dump_json(), encoding="utf-8")
            log(f"built scene {i}")
            if on_scene:
                on_scene(i, "done")
        final = out / "final" / out_name
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"f")
        return final

    def fake_build_scene(node, project, *, scenes_dir, quality="preview", client=None, log=print):
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)
        mp4 = Path(scenes_dir) / f"scene_{node.sid}.mp4"
        mp4.write_bytes(b"v2")
        node.mp4, node.compiled = str(mp4), True
        node.spec = node.spec or SPEC
        node.script = node.script or ["n"]
        return node

    def fake_build_scene_decoupled(item, outline, index, *, work_dir, spec=None, base_code=None,
                                   narration_override=None, **k):
        # mirror composition.decoupled.build_scene's on-disk outputs for the edit ops
        wd = Path(work_dir)
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "narrated.mp4").write_bytes(b"v2")
        (wd / "scene.py").write_text(base_code or "class GeneratedScene(LatticeScene):\n    pass\n",
                                     encoding="utf-8")
        (wd / "spec.json").write_text((spec or SPEC).model_dump_json(), encoding="utf-8")
        text = "\n".join(narration_override) if narration_override else "n"
        (wd / "narration.txt").write_text(text, encoding="utf-8")
        return wd / "narrated.mp4"

    def fake_stitch(mp4s, *, work_dir, out_name="final.mp4", **k):
        p = Path(work_dir) / out_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"f")
        return p

    def fake_narrate_build(spec, *, work_dir, quality="preview", client=None, style=None,
                           lines=None, log=print):
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        mp4 = Path(work_dir) / "narr.mp4"
        mp4.write_bytes(b"v3")
        srt = Path(work_dir) / "narr.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        return NarratedResult(True, "code", mp4, srt, [], lines or ["n"])

    monkeypatch.setattr("composition.decoupled.build_video", fake_build_video)
    monkeypatch.setattr("composition.decoupled.build_scene", fake_build_scene_decoupled)
    monkeypatch.setattr("composition.video.build_scene", fake_build_scene)
    monkeypatch.setattr("composition.stitch.stitch", fake_stitch)
    monkeypatch.setattr("editing.tweak.apply_tweak", lambda spec, instruction, **k: spec)
    monkeypatch.setattr("narration.narrate.build", fake_narrate_build)
    monkeypatch.setattr("planner.lesson_plan.generate", lambda topic, skill, **k: LESSON)
    monkeypatch.setattr("planner.browser_visual_plan.generate", lambda lesson, skill, **k: VISUAL)

    def fake_browser_build(lesson, plan, skill, *, out_dir, on_scene=None, log=None, **k):
        from composition.browser_video import BrowserVideoResult
        out = Path(out_dir)
        clips = []
        for index, _scene in enumerate(lesson.scenes):
            if on_scene:
                on_scene(index, "rendering")
            clip = out / f"scene_{index:02d}.mp4"
            clip.write_bytes(b"v")
            clips.append(clip)
            if log:
                log(f"[browser:scene_stitch] passed: {clip}")
            if on_scene:
                on_scene(index, "done")
        final = out / "browser-video.mp4"
        final.write_bytes(b"f")
        return BrowserVideoResult(final, clips, [])

    monkeypatch.setattr("composition.browser_video.build", fake_browser_build)

    engine = Engine(root=tmp_path / "web", client=object())
    queue = jobs_mod.JobQueue(synchronous=True)   # jobs complete inline -> deterministic
    return TestClient(create_app(engine=engine, queue=queue))


def _build_project(client) -> str:
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    job = client.post(f"/api/projects/{pid}/build", json={"quality": "preview"}).json()
    assert client.get(f"/api/jobs/{job['job_id']}").json()["status"] == "done"
    return pid


@pytest.mark.unit
def test_health():
    from web.app import create_app
    c = TestClient(create_app())
    assert c.get("/health").json() == {"status": "ok"}


@pytest.mark.unit
def test_plan_returns_editable_outline_without_rendering(client):
    r = client.post("/api/projects", json={"topic": "how TCP works"})
    assert r.status_code == 200
    dto = r.json()
    assert dto["id"] and len(dto["scenes"]) == 2
    assert [s["title"] for s in dto["scenes"]] == ["A", "B"]
    assert all(not s["built"] for s in dto["scenes"])      # planned, nothing rendered yet
    assert dto["final_ready"] is False


@pytest.mark.unit
def test_build_job_renders_all_scenes_with_per_scene_status(client):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    job_id = client.post(f"/api/projects/{pid}/build",
                         json={"quality": "preview", "keep": [0, 1]}).json()["job_id"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["scenes"] == {"0": "done", "1": "done"}      # FR-24: queued->rendering->done per scene

    proj = client.get(f"/api/projects/{pid}").json()
    assert all(s["built"] for s in proj["scenes"]) and proj["final_ready"] is True


@pytest.mark.unit
def test_browser_v2_web_project_plans_builds_and_previews_through_existing_api(client):
    planned = client.post("/api/projects", json={
        "topic": "TCP", "renderer": "browser_v2", "recipe": "auto", "max_scenes": 2,
    })
    assert planned.status_code == 200
    dto = planned.json()
    assert dto["renderer"] == "browser_v2"
    assert [scene["title"] for scene in dto["scenes"]] == ["Connect", "Confirm"]
    assert [scene["narration"] for scene in dto["scenes"]] == [["Send SYN"], ["Receive ACK"]]

    pid = dto["id"]
    job_id = client.post(f"/api/projects/{pid}/build", json={"keep": [1]}).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["scenes"] == {"0": "done"}

    built = client.get(f"/api/projects/{pid}").json()
    assert built["renderer"] == "browser_v2" and built["final_ready"] is True
    assert [scene["title"] for scene in built["scenes"]] == ["Confirm"]
    assert built["scenes"][0]["narration"] == ["Receive ACK"]
    assert client.get(f"/api/projects/{pid}/scenes/0/preview").status_code == 200
    assert client.get(f"/api/projects/{pid}/final").status_code == 200


@pytest.mark.unit
def test_outline_gate_cut_before_render(client):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    # keep only scene 1 ("B") — the gate cuts scene 0 BEFORE any render
    job_id = client.post(f"/api/projects/{pid}/build", json={"keep": [1]}).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    proj = client.get(f"/api/projects/{pid}").json()
    assert len(proj["scenes"]) == 1 and proj["scenes"][0]["title"] == "B"


@pytest.mark.unit
def test_job_events_and_stream(client):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    job_id = client.post(f"/api/projects/{pid}/build", json={}).json()["job_id"]

    ev = client.get(f"/api/jobs/{job_id}/events?cursor=0").json()
    assert ev["status"] == "done" and ev["events"]
    assert ev["next_cursor"] >= len(ev["events"])
    assert ev["progress"]["phase"] == "done" and ev["progress"]["pct"] == 100

    stream = client.get(f"/api/jobs/{job_id}/stream")
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "event: done" in stream.text and "built scene" in stream.text   # raw log still available
    assert "event: progress" in stream.text                                # coarse cylinder feed


@pytest.mark.unit
def test_regenerate_is_async_and_isolated(client):
    pid = _build_project(client)
    before = client.get(f"/api/projects/{pid}").json()["scenes"][1]["sid"]
    job_id = client.post(f"/api/projects/{pid}/scenes/0/regenerate",
                         json={"quality": "final"}).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done" and job["scenes"]["0"] == "done"
    after = client.get(f"/api/projects/{pid}").json()
    assert after["scenes"][0]["built"] and after["scenes"][1]["sid"] == before  # scene 1 untouched


@pytest.mark.unit
def test_structural_reorder_and_delete_no_render(client):
    pid = _build_project(client)
    reordered = client.post(f"/api/projects/{pid}/scenes/reorder", json={"frm": 0, "to": 1}).json()
    assert [s["title"] for s in reordered["scenes"]] == ["B", "A"]

    after_del = client.delete(f"/api/projects/{pid}/scenes/1").json()
    assert [s["title"] for s in after_del["scenes"]] == ["B"]

    # cannot delete the only remaining scene
    assert client.delete(f"/api/projects/{pid}/scenes/0").status_code == 400


@pytest.mark.unit
def test_tweak_and_narration_endpoints_complete(client):
    pid = _build_project(client)
    t = client.post(f"/api/projects/{pid}/scenes/0/tweak",
                    json={"instruction": "move the box left"}).json()
    assert client.get(f"/api/jobs/{t['job_id']}").json()["status"] == "done"

    n = client.post(f"/api/projects/{pid}/scenes/0/narration",
                    json={"lines": ["a new line", "and another"]}).json()
    assert client.get(f"/api/jobs/{n['job_id']}").json()["status"] == "done"


@pytest.mark.unit
def test_edit_ops_use_structural_decoupled(client, monkeypatch):
    # the whole point of step 2: per-scene edits go through the DECOUPLED STRUCTURAL path (not the
    # old freehand editing modules). Spy on build_scene to confirm structural=True flows through.
    pid = _build_project(client)
    seen = {}
    import composition.decoupled as cd
    real = cd.build_scene   # the fixture's fake
    monkeypatch.setattr("composition.decoupled.build_scene",
                        lambda item, outline, index, **k: (seen.update(structural=k.get("structural")),
                                                           real(item, outline, index, **k))[1])
    job = client.post(f"/api/projects/{pid}/scenes/0/regenerate", json={"quality": "preview"}).json()
    assert client.get(f"/api/jobs/{job['job_id']}").json()["status"] == "done"
    assert seen["structural"] is True


@pytest.mark.unit
def test_insert_scene_renders_and_grows_video(client):
    pid = _build_project(client)
    before = len(client.get(f"/api/projects/{pid}").json()["scenes"])
    job = client.post(f"/api/projects/{pid}/scenes/insert",
                      json={"pos": 1, "title": "New", "intent": "z"}).json()
    assert client.get(f"/api/jobs/{job['job_id']}").json()["status"] == "done"
    after = client.get(f"/api/projects/{pid}").json()["scenes"]
    assert len(after) == before + 1
    assert after[1]["title"] == "New" and after[1]["built"]


@pytest.mark.unit
def test_preview_and_download(client):
    pid = _build_project(client)
    assert client.get(f"/api/projects/{pid}/scenes/0/preview").status_code == 200
    dl = client.get(f"/api/projects/{pid}/download?subtitles=none")
    assert dl.status_code == 200 and dl.content == b"f"


@pytest.mark.unit
def test_script_view_and_download(client):
    pid = _build_project(client)
    # whole-video transcript
    whole = client.get(f"/api/projects/{pid}/script")
    assert whole.status_code == 200 and whole.text.startswith("# TCP")
    assert "## Scene 1 — A" in whole.text and "## Scene 2 — B" in whole.text
    # one scene's script as plain text
    one = client.get(f"/api/projects/{pid}/script?index=0")
    assert one.status_code == 200 and one.text.strip() == "n"   # fake build set script=["n"]
    # out-of-range scene -> 400
    assert client.get(f"/api/projects/{pid}/script?index=9").status_code == 400


@pytest.mark.unit
def test_download_before_build_is_409(client):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    assert client.get(f"/api/projects/{pid}/download").status_code == 409


@pytest.mark.unit
def test_quality_flows_through_to_engine(client, monkeypatch):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    seen = {}
    import composition.decoupled as cd
    real = cd.build_video   # the fixture's fake
    monkeypatch.setattr("composition.decoupled.build_video",
                        lambda prompt, **k: (seen.update(quality=k.get("quality")), real(prompt, **k))[1])
    client.post(f"/api/projects/{pid}/build", json={"quality": "final"})
    assert seen["quality"] == "final"


@pytest.mark.unit
def test_unknown_project_and_job_404(client):
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/projects/nope/build", json={}).status_code == 404


@pytest.mark.unit
def test_build_failure_is_surfaced_as_failed_job(client):
    pid = client.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    # keep=[] -> empty outline -> engine raises inside the job -> job FAILED (not a 500)
    job_id = client.post(f"/api/projects/{pid}/build", json={"keep": []}).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]
