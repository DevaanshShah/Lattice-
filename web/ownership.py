"""Who owns each video project, slide deck and lesson thread — and the one check every route uses.

With sign-in on, a user sees and touches only what they created; someone else's item answers 404
exactly like a missing one, so ids can't be probed for existence. With sign-in off (local dev,
tests) nothing is enforced and everything stays shared, as it always was.

Storage is one small JSON index beside the projects (`<engine root>/owners.json`) rather than a
field on each record: the three record types live in three modules with three schemas, and a
project file is also read and rewritten by the render pipeline, which must not need to know about
accounts. Writes only happen when something is created, so a file is plenty here; the seam to
move this into a database table (Supabase `owner_id` + row-level security) is this class alone.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException

from core import usage

VIDEO, DECK, THREAD = "video", "deck", "thread"
KINDS = (VIDEO, DECK, THREAD)
_NOUN = {VIDEO: "project", DECK: "deck", THREAD: "thread"}


def current_user() -> str:
    """The identity `web/users.py` bound to this request (a Supabase user id when signed in)."""
    return usage.current().user or ""


class Ownership:
    def __init__(self, root: str | Path, *, enforce: bool) -> None:
        self.enforce = enforce
        self.path = Path(root) / "owners.json"
        self._lock = threading.Lock()
        self._owners: dict[str, dict[str, str]] = {k: {} for k in KINDS}
        self._seen_mtime: int | None = None
        with self._lock:
            self._sync_locked()

    # --- persistence ---
    # The file is the source of truth, not this process's memory: `scripts.claim_unowned` writes
    # it while the server runs. So reads pick up a changed file (one stat per check), and every
    # write re-reads and merges right before saving instead of dumping a stale copy over it.
    def _sync_locked(self) -> None:
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return
        if mtime == self._seen_mtime:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return                      # mid-replace or damaged: keep what we have, retry next time
        for kind in KINDS:
            rows = raw.get(kind)
            if isinstance(rows, dict):
                self._owners[kind] = {str(k): str(v) for k, v in rows.items() if v}
        self._seen_mtime = mtime

    def _write_locked(self, kind: str, changes: dict[str, str]) -> None:
        self._seen_mtime = None         # force a fresh read: merge onto what is on disk NOW
        self._sync_locked()
        self._owners[kind].update(changes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")   # per process: no clash
        tmp.write_text(json.dumps(self._owners, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)          # atomic: a crash mid-write can't lose every owner at once
        try:
            self._seen_mtime = self.path.stat().st_mtime_ns
        except OSError:
            self._seen_mtime = None

    # --- writes ---
    def claim(self, kind: str, rid: str, uid: str | None = None) -> None:
        """Record the creator. Called once, when the item is made. No identity -> nothing to record."""
        uid = current_user() if uid is None else uid
        if not uid:
            return
        with self._lock:
            self._sync_locked()
            if self._owners[kind].get(rid) != uid:
                self._write_locked(kind, {rid: uid})

    def assign_unowned(self, kind: str, ids: Iterable[str], uid: str) -> list[str]:
        """Give every id that has no owner yet to `uid` (the one-time move to accounts)."""
        with self._lock:
            self._sync_locked()
            taken = [rid for rid in ids if rid not in self._owners[kind]]
            if taken:
                self._write_locked(kind, {rid: uid for rid in taken})
            return taken

    # --- reads ---
    def owner(self, kind: str, rid: str) -> str | None:
        with self._lock:
            self._sync_locked()
            return self._owners[kind].get(rid)

    def can_access(self, kind: str, rid: str, uid: str | None = None) -> bool:
        if not self.enforce:
            return True
        uid = current_user() if uid is None else uid
        return bool(uid) and self.owner(kind, rid) == uid

    def require(self, kind: str, rid: str) -> None:
        """404, not 403: someone else's item must look exactly like one that doesn't exist."""
        if not self.can_access(kind, rid):
            raise HTTPException(404, f"no {_NOUN[kind]} {rid!r}")

    def visible(self, kind: str, rows: list[dict], *, key: str = "id") -> list[dict]:
        if not self.enforce:
            return rows
        uid = current_user()
        return [r for r in rows if self.can_access(kind, str(r.get(key)), uid)]

    def can_access_job(self, job) -> bool:
        """A job belongs to whoever queued it (`Job.user`, stamped from the same identity)."""
        if not self.enforce:
            return True
        uid = current_user()
        return bool(uid) and getattr(job, "user", "") == uid
