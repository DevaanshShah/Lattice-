"""Per-account daily limits: how many videos, how many edits and how much model spend one signed-in
account may use in a rolling 24 hours.

Why one module and two enforcement points rather than a check in each route: a new endpoint that
spends money must not be free until someone remembers to guard it.

- `JobQueue.submit` calls `charge(uid, kind)`. Every build, deck, lesson video and scene edit goes
  through that one method, so the VIDEO and EDIT counts cannot be skipped by a route.
- A global dependency on POST requests calls `check_spend(uid)`. It covers what bypasses the queue
  (planning a storyboard, Learn chat): once an account's model spend in the window reaches the
  ceiling, it can read and watch but cannot start anything new.
- The same check also enforces a GLOBAL ceiling across every account. Per-account limits count
  Google accounts, and with sign-in open to anyone, accounts are free to make: N accounts times the
  per-account ceiling is the real worst case. The global ceiling is what bounds the owner's bill
  regardless of how many accounts show up.

The window is a rolling 24 hours rather than a calendar day, so there is no timezone to pick and no
midnight reset to farm. Counts persist in `<out_dir>/admin/quota.json` so a restart cannot be used
to reset them. Spend is read from the usage ledger (core/usage.py), the same numbers the admin
console shows.

Enforced only with sign-in on, like ownership: a guest's cookie id is cheap to discard, so limits on
it would be theatre; locally and in tests nothing is limited. A limit of 0 turns that rule off.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from core import usage

WINDOW_S = 24 * 3600
VIDEO, EDIT = "video", "edit"
# Job kinds that produce a whole video. Everything else a job can be (regenerate, tweak, narration,
# insert) is an edit of one that exists, so a new kind is limited by the edit cap, never unlimited.
VIDEO_KINDS = frozenset({"build", "deck-build", "learn-video"})
_SPEND_TTL_S = 5.0          # the ledger can be large; a burst of requests reads it once


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = max(1, int(retry_after))


def _wait(seconds: float) -> str:
    minutes = max(1, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def category(kind: str) -> str:
    return VIDEO if kind in VIDEO_KINDS else EDIT


class Quota:
    def __init__(self, root: str | Path, *, enforce: bool, videos: int = 5, edits: int = 40,
                 spend_usd: float = 1.0, global_spend_usd: float = 0.0, exempt: str = "",
                 email_of: Callable[[str], str] | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self.enforce = enforce
        self.limits = {VIDEO: max(0, int(videos)), EDIT: max(0, int(edits))}
        self.spend_usd = max(0.0, float(spend_usd))
        self.global_spend_usd = max(0.0, float(global_spend_usd))
        self._global_cache: tuple[float, float] | None = None
        self._exempt = {x.strip().lower() for x in (exempt or "").split(",") if x.strip()}
        self._email_of = email_of or (lambda _uid: "")
        self._now = now
        self.path = Path(root) / "admin" / "quota.json"
        self._lock = threading.Lock()
        self._used: dict[str, dict[str, list[float]]] = {}
        self._spend_cache: dict[str, tuple[float, float]] = {}
        self._load()

    # --- persistence ---
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for uid, row in (raw.get("used") or {}).items():
            try:
                self._used[uid] = {c: [float(t) for t in row.get(c, [])] for c in (VIDEO, EDIT)}
            except (TypeError, ValueError, AttributeError):
                continue                # a damaged row must not stop the server from starting

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"used": self._used}), encoding="utf-8")
            tmp.replace(self.path)      # atomic: a crash mid-write cannot wipe everyone's counts
        except OSError:
            pass                        # a full disk must not take the product down

    # --- rules ---
    def exempt(self, uid: str) -> bool:
        return uid.lower() in self._exempt or (self._email_of(uid) or "").lower() in self._exempt

    def applies(self, uid: str) -> bool:
        return bool(self.enforce and uid and not self.exempt(uid))

    def _live_locked(self, uid: str, cat: str) -> list[float]:
        cutoff = self._now() - WINDOW_S
        rows = self._used.setdefault(uid, {VIDEO: [], EDIT: []})
        rows[cat] = [t for t in rows.get(cat, []) if t > cutoff]
        return rows[cat]

    def spent(self, uid: str) -> float:
        now = self._now()
        cached = self._spend_cache.get(uid)
        if cached and now - cached[0] < _SPEND_TTL_S:
            return cached[1]
        total = sum(float(r.get("cost_usd") or 0) for r in usage.read(since=now - WINDOW_S)
                    if r.get("event") == "llm" and r.get("user") == uid)
        self._spend_cache[uid] = (now, total)
        return total

    def spent_everyone(self) -> float:
        now = self._now()
        if self._global_cache and now - self._global_cache[0] < _SPEND_TTL_S:
            return self._global_cache[1]
        total = sum(float(r.get("cost_usd") or 0) for r in usage.read(since=now - WINDOW_S)
                    if r.get("event") == "llm")
        self._global_cache = (now, total)
        return total

    def check_spend(self, uid: str) -> None:
        if not self.applies(uid):
            return
        if self.global_spend_usd and self.spent_everyone() >= self.global_spend_usd:
            raise QuotaExceeded(
                "Lattice has reached its daily capacity and is paused for new work. "
                "Please try again later.", WINDOW_S / 4)
        if not self.spend_usd:
            return
        if self.spent(uid) >= self.spend_usd:
            raise QuotaExceeded(
                "You've reached today's usage limit for this account. It frees up gradually over "
                "the next 24 hours.", WINDOW_S / 4)

    def charge(self, uid: str, kind: str) -> float | None:
        """Take one slot for a job of `kind`, or raise QuotaExceeded. Returns a receipt for `refund`."""
        if not self.applies(uid):
            return None
        self.check_spend(uid)
        cat, limit = category(kind), self.limits[category(kind)]
        if not limit:
            return None
        with self._lock:
            live = self._live_locked(uid, cat)
            if len(live) >= limit:
                wait = live[0] + WINDOW_S - self._now()
                what = "videos" if cat == VIDEO else "edits"
                raise QuotaExceeded(
                    f"You've used all {limit} {what} for the last 24 hours. "
                    f"The next one is free in {_wait(wait)}.", wait)
            ts = self._now()
            live.append(ts)
            self._save_locked()
            return ts

    def refund(self, uid: str, kind: str, receipt: float | None) -> None:
        """Give the slot back when the job failed: a crash on our side must not cost the user a try."""
        if receipt is None:
            return
        with self._lock:
            live = self._live_locked(uid, category(kind))
            if receipt in live:
                live.remove(receipt)
                self._save_locked()

    def forget(self, uid: str) -> None:
        """Drop one account's counts (scripts/delete_user.py)."""
        with self._lock:
            if self._used.pop(uid, None) is not None:
                self._save_locked()

    def status(self, uid: str) -> dict:
        """What the account has used and when it frees up, for the UI. Unlimited fields are None."""
        if not self.applies(uid):
            return {"enforced": False}
        out: dict = {"enforced": True, "window_hours": WINDOW_S // 3600}
        with self._lock:
            for cat in (VIDEO, EDIT):
                live = self._live_locked(uid, cat)
                limit = self.limits[cat]
                out[cat] = {"used": len(live), "limit": limit or None,
                            "free_in_s": int(live[0] + WINDOW_S - self._now()) if live else 0}
        out["spend_usd"] = round(self.spent(uid), 4)
        out["spend_limit_usd"] = self.spend_usd or None
        return out
