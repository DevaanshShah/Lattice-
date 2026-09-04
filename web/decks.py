"""HTTP surface for the slide-deck path — ADDITIVE, and deliberately self-contained.

A deck is not a VideoProject: it has no scenes, no outline, no style spec, and nothing to repair or
critique. Forcing it into that schema would drag the Manim path's whole vocabulary somewhere it has no
meaning, so decks get their own tiny record and their own store, sitting beside projects on disk.

What it DOES reuse is the JobQueue — so `/api/jobs/{id}` and `/api/jobs/{id}/stream` already report
deck builds with no new streaming code.

Everything is registered through `register(app, engine, queue)`, which is the only line app.py needs.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from core import storage, usage
from web import jobs as jobs_mod

_MUSIC_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class CreateDeck(BaseModel):
    topic: str = Field(..., min_length=3, max_length=2_000)


class BuildDeck(BaseModel):
    keep: list[int] | None = None
    narrate: bool = True
    transition: float = Field(0.45, ge=0.0, le=2.0)
    math_quality: str = Field("final", pattern="^(draft|preview|high|final)$")
    # A NAME resolved against assets/music — never a path. Taking a caller-supplied path here would
    # let any request mux an arbitrary file off the server's disk into a downloadable video.
    music: str | None = None


@dataclass
class DeckRecord:
    id: str
    topic: str
    title: str
    slides: list[dict] = field(default_factory=list)
    mp4: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class DeckStore:
    """One dir per deck: <root>/decks/<did>/deck.json (+ the render's working files)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root) / "decks"
        self.root.mkdir(parents=True, exist_ok=True)

    def workspace(self, did: str) -> Path:
        return self.root / did

    def save(self, rec: DeckRecord) -> None:
        ws = self.workspace(rec.id)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "deck.json").write_text(json.dumps(rec.to_dict(), indent=2), encoding="utf-8")

    def load(self, did: str) -> DeckRecord:
        path = self.workspace(did) / "deck.json"
        if not path.exists():
            raise HTTPException(404, f"no deck {did!r}")
        return DeckRecord(**json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            f = d / "deck.json"
            if not f.is_file():
                continue
            try:
                rec = DeckRecord(**json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                continue                       # a half-written deck must not break the listing
            out.append({"id": rec.id, "title": rec.title, "slides": len(rec.slides),
                        "ready": bool(rec.mp4 and Path(rec.mp4).exists()),
                        "created_at": rec.created_at})
        return sorted(out, key=lambda r: r["created_at"], reverse=True)


def deck_dto(rec: DeckRecord) -> dict:
    """The review payload. `slides` carries the full script because the beats ARE the gate — the user
    reads what the video will say before any render is paid for."""
    return {"id": rec.id, "topic": rec.topic, "title": rec.title, "slides": rec.slides,
            "ready": bool(rec.mp4 and Path(rec.mp4).exists()),
            "routes": [("manim" if s.get("kind") == "math" else "slide") for s in rec.slides],
            "created_at": rec.created_at}


def _music_path(name: str | None) -> Path | None:
    if not name:
        return None
    if not _MUSIC_NAME.match(name):
        raise HTTPException(422, "music must be a bare name from assets/music (letters, digits, _ or -)")
    for ext in (".mp3", ".m4a", ".wav", ".ogg"):
        p = Path("assets/music") / f"{name}{ext}"
        if p.exists():
            return p
    raise HTTPException(422, f"no music track named {name!r} in assets/music")


def register(app, engine, queue: jobs_mod.JobQueue) -> DeckStore:
    """Mount the deck routes. Additive: no existing route or model is touched."""
    store = DeckStore(engine.root)

    def _client():
        get = getattr(engine, "_client_or_default", None)
        if callable(get):
            return get()
        from core.llm import get_client
        return get_client()

    @app.post("/api/decks")
    def create_deck(body: CreateDeck) -> dict:
        from planner.slide_plan import SlidePlanError, plan_deck
        # The id is minted BEFORE the call that costs money: planning is ~all of a deck's spend, and
        # tagging afterwards would file it under no project at all.
        did = uuid4().hex[:8]
        usage.tag(surface="deck", kind="plan", project=did)
        try:
            deck = plan_deck(body.topic, client=_client())
        except SlidePlanError as e:      # invalid after retries — the script lint never passed
            raise HTTPException(422, str(e))
        rec = DeckRecord(id=did, topic=body.topic, title=deck.title,
                         slides=[asdict(s) for s in deck.slides], created_at=time.time())
        store.save(rec)
        usage.record("create", surface="deck", project=rec.id, topic=body.topic)
        return deck_dto(rec)

    @app.get("/api/decks")
    def list_decks() -> dict:
        return {"decks": store.list()}

    @app.get("/api/decks/{did}")
    def get_deck(did: str) -> dict:
        return deck_dto(store.load(did))

    @app.post("/api/decks/{did}/build")
    def build_deck_route(did: str, body: BuildDeck) -> dict:
        from generation.slide_deck import Slide
        rec = store.load(did)
        usage.tag(surface="deck")
        music = _music_path(body.music)              # validate BEFORE queueing, so it 422s not fails
        keep = body.keep if body.keep is not None else list(range(len(rec.slides)))
        chosen = [rec.slides[i] for i in keep if 0 <= i < len(rec.slides)]
        if not chosen:
            raise HTTPException(422, "no slides kept")

        def run(job: jobs_mod.Job):
            from composition.slides import build_deck
            for i in range(len(chosen)):
                job.set_scene(i, jobs_mod.S_QUEUED)

            def say(msg: str) -> None:
                job.log(msg)

            say(f"deck {rec.title!r}: {len(chosen)} slides "
                f"({sum(1 for s in chosen if s.get('kind') == 'math')} via Manim)")
            slides = [Slide.from_dict(s) for s in chosen]
            for i, s in enumerate(slides):
                job.set_scene(i, jobs_mod.S_RENDERING)
                say(f"slide {i}: {s.kind} — {s.title}")
                job.set_scene(i, jobs_mod.S_DONE)
            mp4 = build_deck(slides, store.workspace(did) / "render", narrate=body.narrate,
                             transition=body.transition, math_quality=body.math_quality,
                             music=music, footer="Lattice")
            rec.mp4 = str(mp4)
            store.save(rec)
            storage.offload(mp4, storage.deck_key(did), log=say)
            say(f"done: {mp4}")
            return deck_dto(rec)

        job = queue.submit(run, kind="deck-build", project_id=did)
        return {"job_id": job.id}

    @app.get("/api/decks/{did}/video")
    def deck_video(did: str):
        rec = store.load(did)
        if rec.mp4 and Path(rec.mp4).exists():
            return FileResponse(rec.mp4, media_type="video/mp4", filename=f"{did}.mp4")
        # Local copy gone (redeploy, or r2_delete_local) — hand the browser the object in R2.
        url = storage.url_for(storage.deck_key(did), filename=f"{did}.mp4") if rec.mp4 else None
        if url and storage.exists(storage.deck_key(did)):
            return RedirectResponse(url, status_code=307)
        raise HTTPException(409, "deck is not built yet")

    return store
