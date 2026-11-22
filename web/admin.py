"""The admin console — who is using Lattice, what they built, and what it cost.

Two data sources, joined here and nowhere else:
- `core.usage`'s ledger: every model call, every created project/deck/thread, every finished job,
  each tagged with the user that caused it. Durable, so it survives restarts.
- the live `JobQueue` + the on-disk stores: what is running RIGHT NOW and what actually exists on
  disk (a project created before the ledger existed still shows up in the counts).

The rollups are plain functions over a list of ledger rows, so they are unit-tested directly with
no HTTP, no engine and no disk.

Access: `LATTICE_ADMIN_TOKEN` gates everything. With no token set the console is reachable only
from loopback — that keeps local dev frictionless while making a public deploy fail CLOSED instead
of publishing every user's activity to anyone who guesses the URL.
"""
from __future__ import annotations

import hmac
import time
from pathlib import Path
from typing import Any, Iterable

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core import usage
from core.config import settings

DAY = 86_400
STATIC_DIR = Path(__file__).resolve().parent / "static"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class LabelReq(BaseModel):
    label: str = Field("", max_length=80)


# --- rollups (pure: rows in, numbers out) ------------------------------------------------------
def _num(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def owner_map(rows: Iterable[dict]) -> dict[str, str]:
    """project/deck/thread id -> the user who created it.

    `create` rows are authoritative; anything else that mentions the project is a fallback, so work
    started before this ledger existed still gets attributed rather than vanishing into "unknown".
    """
    owners: dict[str, str] = {}
    for r in rows:
        pid, user = str(r.get("project") or ""), str(r.get("user") or "")
        if not pid or not user:
            continue
        if r.get("event") == "create" or pid not in owners:
            owners[pid] = user
    return owners


def topic_map(rows: Iterable[dict]) -> dict[str, str]:
    return {str(r.get("project")): str(r.get("topic") or "")
            for r in rows if r.get("event") == "create" and r.get("project") and r.get("topic")}


def cost_window(rows: Iterable[dict], *, since: float) -> float:
    return sum(_num(r, "cost_usd") for r in rows
               if r.get("event") == "llm" and _num(r, "ts") >= since)


def summarize(rows: list[dict], *, users: list[dict], videos: list[dict], decks: list[dict],
              threads: list[dict], jobs_live: list[dict], now: float | None = None) -> dict:
    """The headline tiles: users, content, job health, spend."""
    now = now or time.time()
    llm = [r for r in rows if r.get("event") == "llm"]
    jobs = [r for r in rows if r.get("event") == "job"]

    cost_total = sum(_num(r, "cost_usd") for r in llm)
    unpriced = sum(1 for r in llm if r.get("priced") is False)
    done = sum(1 for r in jobs if r.get("status") == "done")
    failed = sum(1 for r in jobs if r.get("status") == "failed")
    durations = [_num(r, "seconds") for r in jobs if r.get("status") == "done" and _num(r, "seconds") > 0]
    active_jobs = [j for j in jobs_live if j.get("status") in ("queued", "running")]

    videos_ready = sum(1 for p in videos if p.get("built")) + sum(1 for d in decks if d.get("ready"))
    made = done or 1                     # the denominator for "what does one finished video cost"

    return {
        "generated_at": now,
        "users": {
            "total": len(users),
            "active_24h": sum(1 for u in users if now - float(u.get("last_seen") or 0) < DAY),
            "active_7d": sum(1 for u in users if now - float(u.get("last_seen") or 0) < 7 * DAY),
            "new_24h": sum(1 for u in users if now - float(u.get("first_seen") or 0) < DAY),
        },
        "content": {
            "videos": len(videos), "decks": len(decks), "threads": len(threads),
            "ready": videos_ready,
            "scenes": sum(int(p.get("scenes") or 0) for p in videos),
        },
        "jobs": {
            "total": len(jobs), "done": done, "failed": failed,
            "running": sum(1 for j in active_jobs if j.get("status") == "running"),
            "queued": sum(1 for j in active_jobs if j.get("status") == "queued"),
            "success_rate": round(done / (done + failed), 4) if (done + failed) else None,
            "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "last_24h": sum(1 for r in jobs if now - _num(r, "ts") < DAY),
        },
        "cost": {
            "total": round(cost_total, 4),
            "d1": round(cost_window(llm, since=now - DAY), 4),
            "d7": round(cost_window(llm, since=now - 7 * DAY), 4),
            "d30": round(cost_window(llm, since=now - 30 * DAY), 4),
            "calls": len(llm),
            "prompt_tokens": int(sum(_num(r, "prompt_tokens") for r in llm)),
            "completion_tokens": int(sum(_num(r, "completion_tokens") for r in llm)),
            "per_video": round(cost_total / made, 4),
            "per_user": round(cost_total / max(1, len(users)), 4),
            # Honesty tile: calls whose model is missing from the price table contribute $0, so the
            # total above is a FLOOR, not the truth. The dashboard says so when this is non-zero.
            "unpriced_calls": unpriced,
            "since": min((_num(r, "ts") for r in rows), default=None),
        },
    }


def per_user(rows: list[dict], *, users: list[dict], jobs_live: list[dict],
             now: float | None = None) -> list[dict]:
    """One row per visitor: what they made, how far it got, what they cost. Never drops a user with
    no spend — someone who looked around and left is a real (and interesting) row."""
    now = now or time.time()
    agg: dict[str, dict[str, Any]] = {}

    def slot(uid: str) -> dict:
        return agg.setdefault(uid, {"cost": 0.0, "calls": 0, "prompt_tokens": 0,
                                    "completion_tokens": 0, "videos": 0, "decks": 0, "threads": 0,
                                    "builds": 0, "done": 0, "failed": 0, "seconds": 0.0,
                                    "last_activity": 0.0})

    for r in rows:
        uid = str(r.get("user") or "")
        if not uid:
            continue
        s = slot(uid)
        s["last_activity"] = max(s["last_activity"], _num(r, "ts"))
        ev = r.get("event")
        if ev == "llm":
            s["cost"] += _num(r, "cost_usd")
            s["calls"] += 1
            s["prompt_tokens"] += int(_num(r, "prompt_tokens"))
            s["completion_tokens"] += int(_num(r, "completion_tokens"))
        elif ev == "create":
            key = {"video": "videos", "deck": "decks", "learn": "threads"}.get(
                str(r.get("surface") or ""), "videos")
            s[key] += 1
        elif ev == "job":
            s["builds"] += 1
            s["seconds"] += _num(r, "seconds")
            s["done" if r.get("status") == "done" else "failed"] += 1

    running: dict[str, int] = {}
    for j in jobs_live:
        if j.get("status") in ("queued", "running"):
            running[str(j.get("user") or "")] = running.get(str(j.get("user") or ""), 0) + 1

    out: list[dict] = []
    for u in users:
        uid = str(u.get("id"))
        s = slot(uid)
        out.append({
            "id": uid, "label": u.get("label") or "", "first_seen": u.get("first_seen"),
            "email": u.get("email") or "", "name": u.get("name") or "",
            "last_seen": u.get("last_seen"), "requests": u.get("requests"),
            "agent": u.get("agent") or "", "ip": u.get("ip") or "",
            "cost": round(s["cost"], 4), "calls": s["calls"],
            "tokens": s["prompt_tokens"] + s["completion_tokens"],
            "videos": s["videos"], "decks": s["decks"], "threads": s["threads"],
            "builds": s["builds"], "done": s["done"], "failed": s["failed"],
            "running": running.get(uid, 0),
            "render_minutes": round(s["seconds"] / 60, 1),
            "last_activity": max(s["last_activity"], float(u.get("last_seen") or 0)),
            "online": now - float(u.get("last_seen") or 0) < 120,
        })
    # Spend first: the row that costs money is the row the owner needs to see.
    out.sort(key=lambda r: (r["cost"], r["last_activity"] or 0), reverse=True)
    return out


def daily_costs(rows: list[dict], *, days: int = 14, now: float | None = None) -> list[dict]:
    """One bucket per UTC day, oldest first — including days with nothing, so the chart has a
    flat stretch instead of silently compressing time."""
    now = now or time.time()
    start_day = int((now - (days - 1) * DAY) // DAY)
    buckets = {start_day + i: {"day": start_day + i, "cost": 0.0, "calls": 0, "tokens": 0,
                               "jobs": 0, "failed": 0}
               for i in range(days)}
    for r in rows:
        d = int(_num(r, "ts") // DAY)
        b = buckets.get(d)
        if b is None:
            continue
        if r.get("event") == "llm":
            b["cost"] += _num(r, "cost_usd")
            b["calls"] += 1
            b["tokens"] += int(_num(r, "prompt_tokens") + _num(r, "completion_tokens"))
        elif r.get("event") == "job":
            b["jobs"] += 1
            if r.get("status") == "failed":
                b["failed"] += 1
    out = []
    for d in sorted(buckets):
        b = buckets[d]
        out.append({**b, "ts": d * DAY, "cost": round(b["cost"], 4)})
    return out


def by_model(rows: list[dict]) -> list[dict]:
    """Spend split by model — the fastest way to see which model is actually eating the budget."""
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("event") != "llm":
            continue
        m = str(r.get("model") or "?")
        s = agg.setdefault(m, {"model": m, "calls": 0, "cost": 0.0, "prompt_tokens": 0,
                               "completion_tokens": 0, "priced": True})
        s["calls"] += 1
        s["cost"] += _num(r, "cost_usd")
        s["prompt_tokens"] += int(_num(r, "prompt_tokens"))
        s["completion_tokens"] += int(_num(r, "completion_tokens"))
        if r.get("priced") is False:
            s["priced"] = False
    for s in agg.values():
        s["cost"] = round(s["cost"], 4)
    return sorted(agg.values(), key=lambda s: s["cost"], reverse=True)


def by_surface(rows: list[dict]) -> list[dict]:
    """Spend split by product path (video / deck / learn) — which surface the money goes to."""
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("event") != "llm":
            continue
        k = str(r.get("surface") or r.get("kind") or "other") or "other"
        s = agg.setdefault(k, {"surface": k, "calls": 0, "cost": 0.0})
        s["calls"] += 1
        s["cost"] += _num(r, "cost_usd")
    for s in agg.values():
        s["cost"] = round(s["cost"], 4)
    return sorted(agg.values(), key=lambda s: s["cost"], reverse=True)


# --- HTTP --------------------------------------------------------------------------------------
def _authorized(request: Request) -> bool:
    token = (settings.admin_token or "").strip()
    if token:
        given = (request.headers.get("x-admin-token")
                 or request.query_params.get("token")
                 or request.cookies.get("lattice_admin") or "")
        return hmac.compare_digest(given, token)
    host = getattr(getattr(request, "client", None), "host", "") or ""
    return host in LOOPBACK          # no token configured -> local dev only, never public


def require_admin(request: Request) -> None:
    if not _authorized(request):
        raise HTTPException(403, "admin access requires LATTICE_ADMIN_TOKEN "
                                 "(send it as the X-Admin-Token header), or a request from localhost")


def register(app, engine, queue, *, deck_store=None, learn_store=None, user_store=None):
    """Mount the admin console. Additive: no existing route or model is touched."""
    guard = [Depends(require_admin)]

    def _live_jobs() -> list[dict]:
        out = []
        for j in queue.list():
            d = j.to_dict()
            d["progress"] = j.progress()
            out.append(d)
        return sorted(out, key=lambda d: d.get("created_at") or 0, reverse=True)

    def _videos() -> list[dict]:
        try:
            return engine.list_projects()
        except Exception:            # noqa: BLE001 — a broken workspace must not blank the console
            return []

    def _decks() -> list[dict]:
        try:
            return deck_store.list() if deck_store else []
        except Exception:            # noqa: BLE001
            return []

    def _threads() -> list[dict]:
        try:
            return learn_store.list() if learn_store else []
        except Exception:            # noqa: BLE001
            return []

    def _users() -> list[dict]:
        return user_store.all() if user_store else []

    @app.get("/api/admin/summary", dependencies=guard)
    def admin_summary() -> dict:
        rows = usage.read()
        data = summarize(rows, users=_users(), videos=_videos(), decks=_decks(),
                         threads=_threads(), jobs_live=_live_jobs())
        data["provider"] = usage.provider_credits()
        data["config"] = {
            "model": settings.llm_model, "critic_model": settings.critic_model,
            "provider_pin": settings.llm_provider_pin or None,
            "job_workers": settings.job_workers, "scene_workers": settings.scene_workers,
            "exec_mode": settings.exec_mode,
            "token_protected": bool((settings.admin_token or "").strip()),
        }
        return data

    @app.get("/api/admin/users", dependencies=guard)
    def admin_users() -> dict:
        return {"users": per_user(usage.read(), users=_users(), jobs_live=_live_jobs())}

    @app.get("/api/admin/users/{uid}", dependencies=guard)
    def admin_user(uid: str) -> dict:
        rows = usage.read()
        mine = [r for r in rows if str(r.get("user") or "") == uid]
        row = next((u for u in per_user(rows, users=_users(), jobs_live=_live_jobs())
                    if u["id"] == uid), None)
        if row is None:
            raise HTTPException(404, f"no user {uid!r}")
        owned = {str(r.get("project")) for r in mine if r.get("project")}
        return {
            "user": row,
            "projects": [p for p in admin_projects()["projects"] if p["id"] in owned],
            "daily": daily_costs(mine, days=14),
            "models": by_model(mine),
            "events": mine[-100:][::-1],
        }

    @app.post("/api/admin/users/{uid}/label", dependencies=guard)
    def admin_label(uid: str, body: LabelReq) -> dict:
        rec = user_store.set_label(uid, body.label) if user_store else None
        if rec is None:
            raise HTTPException(404, f"no user {uid!r}")
        return rec.to_dict()

    @app.get("/api/admin/jobs", dependencies=guard)
    def admin_jobs(limit: int = Query(40, ge=1, le=200)) -> dict:
        rows = usage.read()
        topics = topic_map(rows)
        # copied, never mutated in place: these dicts are the shared read cache
        finished = [{**r, "topic": topics.get(str(r.get("project") or ""), "")}
                    for r in rows if r.get("event") == "job"][-limit:][::-1]
        return {"live": _live_jobs(), "finished": finished}

    @app.get("/api/admin/costs", dependencies=guard)
    def admin_costs(days: int = Query(14, ge=1, le=90)) -> dict:
        rows = usage.read()
        return {"daily": daily_costs(rows, days=days), "models": by_model(rows),
                "surfaces": by_surface(rows), "provider": usage.provider_credits()}

    @app.get("/api/admin/projects", dependencies=guard)
    def admin_projects() -> dict:
        """Everything anyone has made, with its real progress — video projects (scenes built out of
        scenes planned), decks and learn threads, each tagged with its owner."""
        rows = usage.read()
        owners, topics = owner_map(rows), topic_map(rows)
        cost: dict[str, float] = {}
        for r in rows:
            if r.get("event") == "llm" and r.get("project"):
                pid = str(r["project"])
                cost[pid] = cost.get(pid, 0.0) + _num(r, "cost_usd")

        out: list[dict] = []
        for p in _videos():
            pid = str(p.get("id"))
            built = total = 0
            try:                       # per-scene progress needs the project file itself
                project = engine.load(pid)
                total = len(project.scenes)
                built = sum(1 for s in project.scenes if s.mp4)
            except Exception:          # noqa: BLE001 — a half-written project still gets a row
                total = int(p.get("scenes") or 0)
            out.append({"id": pid, "surface": "video", "title": p.get("topic") or topics.get(pid, ""),
                        "owner": owners.get(pid, ""), "scenes": total, "built": built,
                        "ready": bool(p.get("built")), "cost": round(cost.get(pid, 0.0), 4),
                        "pct": int(100 * built / total) if total else 0, "created_at": None})
        for d in _decks():
            did = str(d.get("id"))
            out.append({"id": did, "surface": "deck", "title": d.get("title") or "",
                        "owner": owners.get(did, ""), "scenes": int(d.get("slides") or 0),
                        "built": int(d.get("slides") or 0) if d.get("ready") else 0,
                        "ready": bool(d.get("ready")), "cost": round(cost.get(did, 0.0), 4),
                        "pct": 100 if d.get("ready") else 0, "created_at": d.get("created_at")})
        for t in _threads():
            tid = str(t.get("id"))
            out.append({"id": tid, "surface": "learn", "title": t.get("title") or "",
                        "owner": owners.get(tid, ""), "scenes": int(t.get("videos") or 0),
                        "built": int(t.get("videos") or 0), "ready": bool(t.get("videos")),
                        "cost": round(cost.get(tid, 0.0), 4), "pct": 100 if t.get("videos") else 0,
                        "created_at": t.get("last_at")})
        out.sort(key=lambda r: (r.get("created_at") or 0, r["cost"]), reverse=True)
        return {"projects": out}

    @app.get("/api/admin/events", dependencies=guard)
    def admin_events(limit: int = Query(150, ge=1, le=1000),
                     event: str | None = Query(None)) -> dict:
        rows = usage.read()
        if event:
            rows = [r for r in rows if r.get("event") == event]
        return {"events": rows[-limit:][::-1], "total": len(rows)}

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page() -> str:
        """Served unguarded on purpose: it is an empty shell that renders nothing until its API
        calls succeed, and the token is typed into it. Guarding it too would leave nowhere to log in."""
        page = STATIC_DIR / "admin.html"
        return page.read_text(encoding="utf-8") if page.exists() else "<h1>admin</h1>"

    return app
