"""FR-28 — the browser API over the engine. A THIN HTTP skin: every endpoint delegates to
`web.engine.Engine` (which delegates to the M1–M6 modules); no scene logic lives here.

Shape:
- planning + the outline-approval gate:  POST /api/projects  ->  outline ;  POST .../build
- async render jobs (FR-24):             build/regenerate/tweak/narration/insert -> {job_id}
- status + streaming (FR-29):            GET /api/jobs/{id} ,  GET /api/jobs/{id}/stream (SSE)
- structural edits (no render):          reorder / delete / rollback  -> updated project
- quality toggle (FR-26):                every render endpoint takes quality=preview|final
- export/download (FR-30):               GET .../download?subtitles=none|burn , GET .../captions

`create_app(engine=?, queue=?)` injects fakes in tests, so the whole API is exercised without
Docker, a model, or the network. The default app wires a real Engine + a threaded JobQueue.
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import storage, usage
from core.config import settings
from web import jobs as jobs_mod
from web import users as users_mod
from web.engine import Engine, ProjectNotFound, project_dto

STATIC_DIR = Path(__file__).resolve().parent / "static"


# --- request bodies -------------------------------------------------------------------------
class CreateProject(BaseModel):
    topic: str = Field(..., min_length=1)
    max_scenes: int | None = None
    target_seconds: int | None = Field(None, ge=15, le=600)   # the user's duration pick (30/60/150...)
    renderer: Literal["legacy", "browser_v2"] = "legacy"
    recipe: str | None = None


class FromCodeReq(BaseModel):
    code: str = Field(..., min_length=1, max_length=20_000)    # snippet -> segment-by-segment walkthrough
    language: str | None = None
    target_seconds: int | None = Field(None, ge=15, le=600)


class FromImageReq(BaseModel):
    image: str = Field(..., min_length=1)                      # data:image/...;base64,... -> derived topic
    max_scenes: int | None = None
    target_seconds: int | None = Field(None, ge=15, le=600)


class BuildReq(BaseModel):
    keep: list[int] | None = None         # outline edit: indices to keep, in new order (reorder+cut)
    quality: str = "preview"


class QualityReq(BaseModel):
    quality: str = "preview"


class ReorderReq(BaseModel):
    frm: int
    to: int


class InsertReq(BaseModel):
    pos: int
    title: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=1)
    quality: str = "preview"


class NarrationReq(BaseModel):
    lines: list[str] = Field(..., min_length=1)
    quality: str = "preview"


class TweakReq(BaseModel):
    instruction: str = Field(..., min_length=1)
    quality: str = "preview"


class RollbackReq(BaseModel):
    version: int


def create_app(*, engine: Engine | None = None, queue: jobs_mod.JobQueue | None = None) -> FastAPI:
    engine = engine or Engine()
    queue = queue or jobs_mod.JobQueue(workers=settings.job_workers)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # On boot, heal any project left half-built by an interrupted run (a killed render leaves good
        # scene clips on disk but an unsaved project). Best-effort + guarded so a fake engine in tests
        # (no recover_all) or a scan hiccup can never block the server from starting.
        recover = getattr(engine, "recover_all", None)
        if callable(recover):
            try:
                recovered = recover()
                if recovered:
                    print(f"[startup] recovered {len(recovered)} interrupted project(s): "
                          f"{', '.join(recovered)}")
            except Exception as e:  # noqa: BLE001
                print(f"[startup] recovery skipped: {type(e).__name__}: {e}")
        yield

    # Anonymous per-browser identity, applied to EVERY route as a global dependency: one place
    # decides who a request belongs to, so no endpoint has to remember to attribute itself.
    user_store = users_mod.UserStore(settings.out_dir)
    app = FastAPI(title="Lattice", version="0.1.0", lifespan=lifespan,
                  dependencies=[Depends(users_mod.dependency(user_store))])

    def _load_or_404(pid: str):
        try:
            return engine.load(pid)
        except ProjectNotFound:
            raise HTTPException(404, f"no project {pid!r}")

    # --- slide decks (additive path: HTML slides + Manim only where the topic needs it) ----
    from web import decks as decks_mod
    deck_store = decks_mod.register(app, engine, queue)

    # --- learn chat (additive path: fast text turns, a deck video only when it's asked for) ----
    from web import learn as learn_mod
    learn_store = learn_mod.register(app, engine, queue)

    # --- admin console (usage, spend, per-user activity; token- or loopback-gated) ----------
    from web import admin as admin_mod
    admin_mod.register(app, engine, queue, deck_store=deck_store, learn_store=learn_store,
                       user_store=user_store)

    # --- health ---------------------------------------------------------------------------
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # --- projects: plan (outline gate) ----------------------------------------------------
    @app.post("/api/projects")
    def create_project(body: CreateProject) -> dict:
        # Mint the id BEFORE planning: the outline call is the first spend, and tagging it after
        # the fact would leave that cost with no project to bill it to.
        pid = uuid4().hex[:8]
        usage.tag(surface="video", kind="plan", project=pid)
        kwargs = {"max_scenes": body.max_scenes, "target_seconds": body.target_seconds,
                  "pid": pid, "log": lambda _m: None}
        if body.renderer == "browser_v2":
            kwargs.update(renderer="browser_v2", recipe=body.recipe or "auto")
        pid, project = engine.plan(body.topic, **kwargs)
        usage.record("create", surface="video", project=pid, topic=body.topic)
        return project_dto(pid, project)

    @app.post("/api/projects/from-code")
    def create_from_code(body: FromCodeReq) -> dict:
        from planner.code_walkthrough import CodeWalkthroughError
        pid = uuid4().hex[:8]
        usage.tag(surface="video", kind="plan-code", project=pid)
        try:
            pid, project = engine.plan_from_code(body.code, body.language, pid=pid,
                                                 target_seconds=body.target_seconds, log=lambda _m: None)
        except (ValueError, CodeWalkthroughError) as e:   # empty snippet or an unparseable walkthrough
            raise HTTPException(422, str(e))
        usage.record("create", surface="video", project=pid, topic=project.topic)
        return project_dto(pid, project)

    @app.post("/api/projects/from-image")
    def create_from_image(body: FromImageReq) -> dict:
        from web.seed import SeedError
        pid = uuid4().hex[:8]
        usage.tag(surface="video", kind="plan-image", project=pid)
        try:
            pid, project = engine.plan_from_image(body.image, max_scenes=body.max_scenes, pid=pid,
                                                  target_seconds=body.target_seconds, log=lambda _m: None)
        except SeedError as e:   # bad/unsupported/oversize image or empty vision reply
            raise HTTPException(422, str(e))
        usage.record("create", surface="video", project=pid, topic=project.topic)
        return project_dto(pid, project)

    @app.get("/api/projects")
    def list_projects() -> dict:
        return {"projects": engine.list_projects()}

    @app.get("/api/projects/{pid}")
    def get_project(pid: str) -> dict:
        return project_dto(pid, _load_or_404(pid))

    # --- build (async render of the approved outline) -------------------------------------
    @app.post("/api/projects/{pid}/build")
    def build(pid: str, body: BuildReq) -> dict:
        project = _load_or_404(pid)
        try:    # an unbuildable scene selection is the user's to fix now, not a failed job later
            engine.check_build(pid, body.keep)
        except ValueError as e:
            raise HTTPException(400, str(e))
        usage.tag(surface="video")

        def run(job: jobs_mod.Job):
            scene_count = len(project.scenes) if body.keep is None else len(body.keep)
            for index in range(scene_count):   # seed the approved sequence, after reorder/cut
                job.set_scene(index, jobs_mod.S_QUEUED)
            built = engine.build(pid, keep=body.keep, quality=body.quality,
                                 log=job.log, on_scene=job.set_scene)
            return project_dto(pid, built)

        job = queue.submit(run, kind="build", project_id=pid)
        return {"job_id": job.id}

    # --- single-scene render ops (async) --------------------------------------------------
    def _scene_job(pid: str, index: int, kind: str, fn) -> dict:
        _load_or_404(pid)
        usage.tag(surface="video")

        def run(job: jobs_mod.Job):
            job.set_scene(index, jobs_mod.S_RENDERING)
            project = fn(job)
            return project_dto(pid, project)

        job = queue.submit(run, kind=kind, project_id=pid, scene_index=index)
        return {"job_id": job.id}

    @app.post("/api/projects/{pid}/scenes/{index}/regenerate")
    def regenerate(pid: str, index: int, body: QualityReq) -> dict:
        return _scene_job(pid, index, "regenerate",
                          lambda job: engine.regenerate(pid, index, quality=body.quality,
                                                        log=job.log, on_scene=job.set_scene))

    @app.post("/api/projects/{pid}/scenes/{index}/tweak")
    def tweak(pid: str, index: int, body: TweakReq) -> dict:
        return _scene_job(pid, index, "tweak",
                          lambda job: engine.tweak(pid, index, body.instruction, quality=body.quality,
                                                   log=job.log, on_scene=job.set_scene))

    @app.post("/api/projects/{pid}/scenes/{index}/narration")
    def narration(pid: str, index: int, body: NarrationReq) -> dict:
        return _scene_job(pid, index, "narration",
                          lambda job: engine.edit_narration(pid, index, body.lines, quality=body.quality,
                                                           log=job.log, on_scene=job.set_scene))

    @app.post("/api/projects/{pid}/scenes/insert")
    def insert(pid: str, body: InsertReq) -> dict:
        _load_or_404(pid)

        def run(job: jobs_mod.Job):
            project = engine.insert(pid, body.pos, body.title, body.intent, quality=body.quality,
                                    log=job.log, on_scene=job.set_scene)
            return project_dto(pid, project)

        job = queue.submit(run, kind="insert", project_id=pid, scene_index=body.pos)
        return {"job_id": job.id}

    # --- structural edits (no render: respond synchronously) ------------------------------
    @app.post("/api/projects/{pid}/scenes/reorder")
    def reorder(pid: str, body: ReorderReq) -> dict:
        _load_or_404(pid)
        try:
            return project_dto(pid, engine.reorder(pid, body.frm, body.to, log=lambda _m: None))
        except (IndexError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/projects/{pid}/scenes/{index}")
    def delete(pid: str, index: int) -> dict:
        _load_or_404(pid)
        try:
            return project_dto(pid, engine.delete(pid, index, log=lambda _m: None))
        except (IndexError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/projects/{pid}/scenes/{index}/history")
    def history(pid: str, index: int) -> dict:
        _load_or_404(pid)
        try:
            return {"versions": engine.scene_history(pid, index)}
        except IndexError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/projects/{pid}/scenes/{index}/rollback")
    def rollback(pid: str, index: int, body: RollbackReq) -> dict:
        _load_or_404(pid)
        try:
            return project_dto(pid, engine.rollback(pid, index, body.version, log=lambda _m: None))
        except (IndexError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))

    # --- jobs: status + streaming (FR-24 / FR-29) -----------------------------------------
    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id!r}")
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str) -> dict:
        """Ask a running job to stop. Cooperative (core/cancel.py): the pipeline notices at its
        next checkpoint — between model calls, repair attempts, critic rounds and scenes — so this
        returns "asked", not "already stopped". Worst case it finishes one in-flight render first.
        Idempotent, and a job that already ended reports accepted=False rather than erroring."""
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id!r}")
        accepted = job.cancel()
        return {"accepted": accepted, "status": job.status, "progress": job.progress()}

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, cursor: int = Query(0, ge=0)) -> dict:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id!r}")
        evs = job.events_since(cursor)
        return {
            "status": job.status,
            "scenes": dict(job.scenes),
            "progress": job.progress(),            # coarse phase + fill for the cylinder UI
            "next_cursor": (evs[-1].seq + 1 if evs else cursor),
            "events": [{"seq": e.seq, "ts": e.ts, "message": e.message} for e in evs],
        }

    @app.get("/api/jobs/{job_id}/stream")
    def job_stream(job_id: str):
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id!r}")

        def gen():
            cursor = 0
            last_prog = None
            # bounded so a stuck job can never wedge the connection forever
            deadline = time.time() + 3600
            while True:
                # raw engine lines go out as `log` (the UI keeps them in a hidden details pane)
                for e in job.events_since(cursor):
                    cursor = e.seq + 1
                    yield f"event: log\ndata: {json.dumps({'seq': e.seq, 'message': e.message})}\n\n"
                # the coarse, user-facing progress — only pushed when it actually changes
                prog = job.progress()
                if prog != last_prog:
                    last_prog = prog
                    yield f"event: progress\ndata: {json.dumps(prog)}\n\n"
                if job.done or time.time() > deadline:
                    yield f"event: status\ndata: {json.dumps(job.to_dict())}\n\n"
                    yield "event: done\ndata: {}\n\n"
                    return
                time.sleep(0.25)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # --- previews + export/download (FR-26 / FR-30) ---------------------------------------
    @app.get("/api/projects/{pid}/scenes/{index}/preview")
    def preview(pid: str, index: int):
        _load_or_404(pid)
        mp4 = engine.scene_mp4(pid, index)
        if not mp4:
            raise HTTPException(404, f"scene {index} not rendered yet")
        return FileResponse(str(mp4), media_type="video/mp4")

    @app.get("/api/projects/{pid}/final")
    def final_video(pid: str):
        """Stream the stitched lesson inline (for the Learn watch view — the whole video, not per-scene)."""
        _load_or_404(pid)
        mp4 = engine.final_mp4(pid)
        if mp4:
            return FileResponse(str(mp4), media_type="video/mp4")
        # No local copy: stream it straight from object storage rather than 404ing on a video that
        # exists — and without paying to pull the whole file through this container first.
        key = storage.video_key(pid)
        url = storage.url_for(key)
        if url and storage.exists(key):
            return RedirectResponse(url, status_code=307)
        raise HTTPException(404, "final video not ready yet")

    @app.get("/api/projects/{pid}/scenes/{index}/source")
    def scene_source(pid: str, index: int) -> dict:
        """Developer inspection: the generated code + the exact codegen prompt + spec + narration."""
        _load_or_404(pid)
        try:
            return engine.scene_source(pid, index)
        except IndexError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/projects/{pid}/download")
    def download(pid: str, subtitles: str = Query("none", pattern="^(none|burn)$"),
                 fmt: str = Query("youtube", alias="format", pattern="^(youtube|reel)$")):
        _load_or_404(pid)
        engine.ensure_final(pid)      # export reads the file, so fetch it back if R2 holds it
        try:
            res = engine.export(pid, subtitles=subtitles, fmt=fmt, log=lambda _m: None)
        except FileNotFoundError as e:
            raise HTTPException(409, str(e))
        return FileResponse(res["mp4"], media_type="video/mp4", filename=f"{pid}-{fmt}.mp4")

    @app.get("/api/projects/{pid}/script")
    def script(pid: str, index: int | None = Query(None)):
        """The narration transcript as plain text — whole video, or one scene with ?index=N.

        Returned inline (so it can be viewed in a tab); the UI's download link adds a filename.
        """
        _load_or_404(pid)
        if index is None:
            return PlainTextResponse(engine.full_script(pid))
        try:
            return PlainTextResponse(engine.scene_script(pid, index))
        except IndexError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/projects/{pid}/captions")
    def captions(pid: str):
        _load_or_404(pid)
        try:
            res = engine.export(pid, subtitles="separate", log=lambda _m: None)
        except FileNotFoundError as e:
            raise HTTPException(409, str(e))
        if not res.get("srt"):
            raise HTTPException(404, "no captions available")
        return FileResponse(res["srt"], media_type="application/x-subrip", filename=f"{pid}.srt")

    # --- frontend -------------------------------------------------------------------------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        idx = STATIC_DIR / "index.html"
        return idx.read_text(encoding="utf-8") if idx.exists() else "<h1>Lattice</h1>"

    app.state.engine = engine
    app.state.queue = queue
    return app


# module-level app for `uvicorn web.app:app`
app = create_app()
