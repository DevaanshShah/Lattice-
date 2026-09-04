"""HTTP surface for Learn — a chat-shaped tutor, ADDITIVE and self-contained like web/decks.py.

The constraint that shapes this whole module: a video takes real time to render (even the deck path
is ~30-60s), but a chat turn has to feel instant. So a turn is TEXT by default — one fast, cheap LLM
call that answers and separately DECIDES whether the idea is worth animating — and a video is only
built when the student asks for it. The model's offer/video_prompt fields make that decision instead
of the frontend guessing from keywords.

Video generation reuses the deck pipeline (planner.slide_plan + composition.slides.build_deck), not
the Manim path: at ~$0.002 and roughly a minute, it is the only one of the two fast/cheap enough to
sit inside a conversation. "Refine" re-plans a deck with the instruction folded into the topic and
renders a new version — a full re-plan, not a per-slide patch (the deck path has no slide-level edit
yet), and that's stated plainly in the API so nothing overclaims what it does.

register(app, engine, queue) is the only line app.py needs.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from core import storage, usage
from core.textutil import extract_json
from web import jobs as jobs_mod


class NewThread(BaseModel):
    message: str = Field(..., min_length=1, max_length=4_000)


class NewMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=4_000)


class MakeVideo(BaseModel):
    # The message_id whose offer is being accepted, OR a free prompt if the student typed their own
    # request instead of clicking the offer. Exactly one must be given.
    message_id: str | None = None
    prompt: str | None = None


class Refine(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=1_000)


@dataclass
class ThreadRecord:
    id: str
    title: str
    created_at: float
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ThreadStore:
    """One dir per thread: <root>/learn/<tid>/thread.json (+ each video's render working files).

    A thread is written from two places that can race: the request handling a new chat message, and
    the background job patching in a finished video. `edit()` serializes both behind a per-thread
    lock and reloads from disk immediately before the callback runs, so a slow video completion can
    never clobber a chat message written while it was rendering (or vice versa).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root) / "learn"
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, tid: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(tid, threading.Lock())

    def workspace(self, tid: str) -> Path:
        return self.root / tid

    def save(self, rec: ThreadRecord) -> None:
        ws = self.workspace(rec.id)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "thread.json").write_text(json.dumps(rec.to_dict(), indent=2), encoding="utf-8")

    def edit(self, tid: str, fn) -> ThreadRecord:
        """Load-mutate-save under the thread's lock. `fn(rec)` mutates `rec` in place or returns a
        replacement; its return value (if not None) becomes the record that gets saved."""
        with self._lock_for(tid):
            rec = self.load(tid)
            result = fn(rec)
            rec = result if result is not None else rec
            self.save(rec)
            return rec

    def load(self, tid: str) -> ThreadRecord:
        path = self.workspace(tid) / "thread.json"
        if not path.exists():
            raise HTTPException(404, f"no thread {tid!r}")
        return ThreadRecord(**json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            f = d / "thread.json"
            if not f.is_file():
                continue
            try:
                rec = ThreadRecord(**json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                continue                        # a half-written thread must not break the listing
            videos = sum(1 for m in rec.messages if m.get("kind") == "video")
            last = rec.messages[-1]["created_at"] if rec.messages else rec.created_at
            out.append({"id": rec.id, "title": rec.title, "videos": videos, "last_at": last})
        return sorted(out, key=lambda r: r["last_at"], reverse=True)


def thread_dto(rec: ThreadRecord) -> dict:
    return {"id": rec.id, "title": rec.title, "created_at": rec.created_at, "messages": rec.messages}


def _msg(role: str, kind: str, **extra) -> dict:
    return {"id": uuid4().hex[:10], "role": role, "kind": kind, "created_at": time.time(), **extra}


_SYSTEM_FALLBACK = {"answer": "", "offer": False, "offer_label": "", "video_prompt": ""}


def register(app, engine, queue: jobs_mod.JobQueue) -> ThreadStore:
    """Mount the Learn routes. Additive: no existing route or model changes."""
    store = ThreadStore(engine.root)

    def _client():
        get = getattr(engine, "_client_or_default", None)
        if callable(get):
            return get()
        from core.llm import get_client
        return get_client()

    def _reply(rec: ThreadRecord, user_text: str) -> dict:
        """One fast LLM call: answer the message AND decide whether a video is worth offering.
        Falls back to a plain, un-offered answer if the model's JSON doesn't parse — a chat turn
        must never hard-fail just because the offer fields came back malformed."""
        from prompts.loader import load
        history = [{"role": m["role"], "content": m.get("text", "")}
                   for m in rec.messages[-8:] if m.get("kind") == "text"]
        messages = [{"role": "system", "content": load("learn-chat")},
                   *history, {"role": "user", "content": user_text}]
        raw = _client().chat(messages)
        try:
            data = extract_json(raw)
            return {**_SYSTEM_FALLBACK, **{k: v for k, v in data.items() if k in _SYSTEM_FALLBACK}}
        except ValueError:
            return {**_SYSTEM_FALLBACK, "answer": raw.strip()[:4000] or "Sorry, could you rephrase that?"}

    def _append_reply(tid: str, user_text: str) -> ThreadRecord:
        def mutate(rec: ThreadRecord):
            data = _reply(rec, user_text)               # history built BEFORE this turn is appended,
            rec.messages.append(_msg("user", "text", text=user_text))   # or it would double up below
            rec.messages.append(_msg("assistant", "text", text=data["answer"],
                offer=({"label": data["offer_label"], "video_prompt": data["video_prompt"]}
                       if data["offer"] and data["video_prompt"] else None)))
        return store.edit(tid, mutate)

    def _queue_video(tid: str, prompt: str, *, refine_of: str | None = None,
                     version: int = 1, note: str = "") -> dict:
        from planner.slide_plan import SlidePlanError, plan_deck
        vmsg = _msg("assistant", "video", status="gen", title=prompt[:60], version=version,
                    refine_of=refine_of, update_note=note, mp4=None)
        store.edit(tid, lambda rec: rec.messages.append(vmsg))
        vdir = store.workspace(tid) / vmsg["id"]

        def patch(mid: str, **fields):
            def mutate(rec: ThreadRecord):
                rec.messages = [{**m, **fields} if m["id"] == mid else m for m in rec.messages]
            store.edit(tid, mutate)

        def run(job: jobs_mod.Job):
            try:
                deck = plan_deck(prompt, client=_client())
            except SlidePlanError as e:
                patch(vmsg["id"], status="failed", error=str(e))
                raise
            for i in range(len(deck.slides)):
                job.set_scene(i, jobs_mod.S_QUEUED)
            job.log(f"{deck.title}: {len(deck.slides)} slides "
                    f"({sum(1 for s in deck.slides if s.kind == 'math')} via Manim)")
            for i in range(len(deck.slides)):
                job.set_scene(i, jobs_mod.S_RENDERING)
            from composition.slides import build_deck
            mp4 = build_deck(deck.slides, vdir, footer="Lattice")
            for i in range(len(deck.slides)):
                job.set_scene(i, jobs_mod.S_DONE)
            patch(vmsg["id"], status="ready", title=deck.title, mp4=str(mp4))
            storage.offload(mp4, storage.learn_key(tid, vmsg["id"]), log=job.log)
            job.log(f"done: {mp4}")
            return {"mp4": str(mp4)}

        job = queue.submit(run, kind="learn-video", project_id=tid)
        return {"job_id": job.id, "message_id": vmsg["id"]}

    @app.post("/api/learn/threads")
    def create_thread(body: NewThread) -> dict:
        rec = ThreadRecord(id=uuid4().hex[:8], title=body.message[:60], created_at=time.time())
        store.save(rec)                                  # so _append_reply's edit() can load it back
        usage.tag(surface="learn", kind="chat", project=rec.id)
        usage.record("create", surface="learn", project=rec.id, topic=rec.title)
        rec = _append_reply(rec.id, body.message)
        return thread_dto(rec)

    @app.get("/api/learn/threads")
    def list_threads() -> dict:
        return {"threads": store.list()}

    @app.get("/api/learn/threads/{tid}")
    def get_thread(tid: str) -> dict:
        return thread_dto(store.load(tid))

    @app.post("/api/learn/threads/{tid}/messages")
    def add_message(tid: str, body: NewMessage) -> dict:
        store.load(tid)                                    # 404s up front, before the LLM call
        usage.tag(surface="learn", kind="chat", project=tid)
        rec = _append_reply(tid, body.message)
        return thread_dto(rec)

    @app.post("/api/learn/threads/{tid}/video")
    def make_video(tid: str, body: MakeVideo) -> dict:
        rec = store.load(tid)
        usage.tag(surface="learn")
        prompt = (body.prompt or "").strip()
        if body.message_id:
            src = next((m for m in rec.messages if m["id"] == body.message_id), None)
            if not src or not src.get("offer"):
                raise HTTPException(422, "that message has no video offer")
            prompt = src["offer"]["video_prompt"]
        if not prompt:
            raise HTTPException(422, "message_id or prompt is required")
        return _queue_video(tid, prompt)

    @app.post("/api/learn/threads/{tid}/messages/{mid}/refine")
    def refine_video(tid: str, mid: str, body: Refine) -> dict:
        """Re-plans and re-renders the WHOLE deck with the instruction folded in — not a per-slide
        patch (the deck path has no slide-level edit yet). Honest about that in the version note."""
        rec = store.load(tid)
        usage.tag(surface="learn")
        src = next((m for m in rec.messages if m["id"] == mid and m.get("kind") == "video"), None)
        if not src:
            raise HTTPException(404, f"no video message {mid!r}")
        if src.get("status") != "ready":
            raise HTTPException(409, "that video isn't ready yet")
        prompt = f"{src['title']}\n\nAdditional instruction for this version: {body.instruction}"
        return _queue_video(tid, prompt, refine_of=mid, version=int(src.get("version", 1)) + 1,
                            note=body.instruction)

    @app.get("/api/learn/threads/{tid}/video/{mid}")
    def get_video(tid: str, mid: str):
        rec = store.load(tid)
        msg = next((m for m in rec.messages if m["id"] == mid), None)
        if not msg or not msg.get("mp4"):
            raise HTTPException(409, "video is not ready yet")
        if Path(msg["mp4"]).exists():
            return FileResponse(msg["mp4"], media_type="video/mp4", filename=f"{mid}.mp4")
        key = storage.learn_key(tid, mid)                  # local copy gone: serve it from R2
        url = storage.url_for(key, filename=f"{mid}.mp4")
        if url and storage.exists(key):
            return RedirectResponse(url, status_code=307)
        raise HTTPException(409, "video is not ready yet")

    return store
