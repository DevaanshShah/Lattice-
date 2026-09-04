"""Anonymous, cookie-scoped identity — the smallest thing that makes "per user" a real number.

Lattice has no accounts (nothing in the product asks anyone to sign in), so an admin dashboard
would have nothing to group by: every build would belong to "the server". A first-party cookie
gives each browser a stable id, which is enough to answer how many people showed up, what each
one is building, how far their videos got, and what they cost.

This is deliberately NOT authentication and never claims to be: two browsers are two users, a
cleared cookie is a new user, and nothing here can stop someone forging an id. It is a usage
attribution key. When real accounts land, `dependency()` is the single seam to swap — everything
downstream only ever sees `usage.Attribution.user`.

Registered as a global FastAPI dependency, so every request is attributed without a single
endpoint having to opt in. It must be `async def`: an async dependency runs in the SAME task as
the endpoint, so the ContextVar it sets is visible to the handler (and to the threadpool the sync
handlers run on, which copies the context). A sync dependency would run on its own worker thread
and the binding would be thrown away.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import Request, Response

from core import usage

COOKIE = "lattice_uid"
COOKIE_MAX_AGE = 400 * 24 * 3600        # ~400 days: the ceiling Chrome clamps cookie lifetime to
FLUSH_SECONDS = 5.0                     # debounce: a returning visitor must not cost a disk write

# Paths that must never MINT a new identity: infra pings and the admin console itself. A monitoring
# probe hitting /health every 10s would otherwise look like thousands of users, and the owner
# reading their own dashboard would look like a customer.
SKIP_PREFIXES = ("/health", "/api/admin", "/admin", "/static", "/favicon")


@dataclass
class UserRecord:
    id: str
    first_seen: float
    last_seen: float
    requests: int = 0
    agent: str = ""                     # last User-Agent, trimmed — tells desktop from phone
    ip: str = ""                        # last client ip (proxy-aware), for the owner's own console
    label: str = ""                     # optional human name the admin can pin on a user

    def to_dict(self) -> dict:
        return asdict(self)


class UserStore:
    """Every visitor ever seen, in one JSON file next to the usage ledger.

    Held in memory and flushed at most every FLUSH_SECONDS (a new user flushes immediately, so a
    first visit is never lost), because `touch()` runs on the hot path of every single request.
    """

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / "admin" / "users.json"
        self._lock = threading.Lock()
        self._users: dict[str, UserRecord] = {}
        self._dirty = False
        self._last_flush = 0.0
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for uid, row in (raw.get("users") or {}).items():
            try:
                self._users[uid] = UserRecord(**row)
            except TypeError:
                continue                # a record from an older shape must not break startup

    def _flush_locked(self, *, force: bool = False) -> None:
        now = time.time()
        if not self._dirty or (not force and now - self._last_flush < FLUSH_SECONDS):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {"users": {u: r.to_dict() for u, r in self._users.items()}}, indent=2),
                encoding="utf-8")
            tmp.replace(self.path)      # atomic: a crash mid-write can't truncate the registry
            self._dirty, self._last_flush = False, now
        except OSError:
            pass                        # a full disk must not take the product down

    def touch(self, uid: str, *, ip: str = "", agent: str = "") -> UserRecord:
        now = time.time()
        with self._lock:
            rec = self._users.get(uid)
            fresh = rec is None
            if rec is None:
                rec = UserRecord(id=uid, first_seen=now, last_seen=now)
                self._users[uid] = rec
            rec.last_seen = now
            rec.requests += 1
            if ip:
                rec.ip = ip
            if agent:
                rec.agent = agent[:180]
            self._dirty = True
            self._flush_locked(force=fresh)
            return rec

    def get(self, uid: str) -> UserRecord | None:
        with self._lock:
            return self._users.get(uid)

    def all(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._users.values()]

    def set_label(self, uid: str, label: str) -> UserRecord | None:
        with self._lock:
            rec = self._users.get(uid)
            if rec is None:
                return None
            rec.label = label[:80]
            self._dirty = True
            self._flush_locked(force=True)
            return rec

    def flush(self) -> None:
        with self._lock:
            self._flush_locked(force=True)


def _client_ip(request) -> str:
    """Real client ip when a proxy (Railway/Render/Cloudflare) is in front of us."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return getattr(getattr(request, "client", None), "host", "") or ""


def dependency(store: UserStore):
    """Build the global identity dependency bound to `store`.

    Request/Response are imported at MODULE level on purpose: `from __future__ import annotations`
    turns these hints into strings, and FastAPI resolves them against the module globals — hidden
    inside this factory they resolve to nothing and both get treated as required query params.
    """
    async def identify(request: Request, response: Response) -> str:
        uid = request.cookies.get(COOKIE) or ""
        path = request.url.path
        skip = path.startswith(SKIP_PREFIXES)
        if not uid:
            if skip:
                return ""               # infra/admin traffic is not a user
            uid = uuid4().hex[:16]
        # Re-set on every request so an active visitor's cookie keeps sliding forward instead of
        # silently expiring mid-project. (Only lands on responses FastAPI builds — a raw
        # FileResponse download skips it, which is fine: the page load already minted the id.)
        response.set_cookie(COOKIE, uid, max_age=COOKIE_MAX_AGE, httponly=True,
                            samesite="lax", path="/")
        if not skip:
            store.touch(uid, ip=_client_ip(request), agent=request.headers.get("user-agent", ""))
        # The one binding the whole request inherits: every model call underneath, and every job it
        # queues, is now attributed to this user.
        usage.set_current(usage.Attribution(user=uid))
        return uid

    return identify
