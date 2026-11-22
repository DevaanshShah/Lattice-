"""Persisted, attributed usage ledger — the data layer under the admin dashboard.

`core.llm` already counts tokens, but in ONE process-wide accumulator that evals reset, that dies
with the process, and that has no idea WHO or WHAT spent it. The admin page needs the opposite:
durable, attributed, queryable. So every LLM call also appends one line to `out/admin/usage.jsonl`
tagged with the user, project and job that caused it — plus `create` lines (a project/deck/thread
was started) and `job` lines (a build finished or failed, and how long it took). That single file
answers every question the dashboard asks: how many users, what each one is building, how far each
build got, and what it cost.

Attribution rides a ContextVar, so a request handler sets it ONCE and every call underneath
inherits it — including calls made deep inside the render fan-out. A worker thread starts with a
fresh, empty context, which is why `carry()` re-binds the captured value on the way in (and why it
binds per invocation instead of using Context.run: the same wrapper is reused by threads running
concurrently, and one Context cannot be entered twice at once).

Everything here is best-effort. Telemetry must never break a render, so `record()` swallows.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator

from core.config import settings

# Roll over rather than grow without bound: the dashboard reads the whole live file.
MAX_LEDGER_BYTES = 32 * 1024 * 1024


# --- attribution ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Attribution:
    """Who/what a unit of spend belongs to. Empty strings mean 'unattributed', never a fake id."""
    user: str = ""       # anonymous browser id (web.users); "" for CLI / background work
    project: str = ""    # project id | deck id | learn thread id
    kind: str = ""       # "build" | "deck-build" | "plan" | "chat" | ...
    surface: str = ""    # "video" | "deck" | "learn" — which product path

    def merged(self, **over: str) -> "Attribution":
        """A copy with the non-empty overrides applied (an empty value never erases a known one)."""
        return replace(self, **{k: v for k, v in over.items() if v})


_NONE = Attribution()
_CURRENT: ContextVar[Attribution] = ContextVar("lattice_attribution", default=_NONE)


def current() -> Attribution:
    return _CURRENT.get()


def set_current(attr: Attribution) -> None:
    """Bind for the rest of THIS context (a request task, a worker thread). No reset token: each
    request runs in its own asyncio task and each job on its own thread, so nothing leaks across."""
    _CURRENT.set(attr)


def tag(**over: str) -> Attribution:
    """Refine the ambient attribution for the rest of this request/thread — e.g. a handler saying
    `tag(surface="deck", kind="plan")` so the calls it is about to make land in the right bucket."""
    attr = current().merged(**over)
    set_current(attr)
    return attr


@contextmanager
def bind(attr: Attribution) -> Iterator[Attribution]:
    token = _CURRENT.set(attr)
    try:
        yield attr
    finally:
        try:
            _CURRENT.reset(token)
        except ValueError:      # reset from a different context — nothing to restore
            pass


def carry(fn: Callable, **over: str) -> Callable:
    """Bind `fn` to the CALLER's attribution so it survives the hop onto a worker thread.

    Capture happens now, in the calling thread; the value is re-bound on every invocation, so one
    wrapper is safe to hand to many threads at once.
    """
    attr = current().merged(**over)

    def wrapper(*a: Any, **k: Any) -> Any:
        with bind(attr):
            return fn(*a, **k)
    return wrapper


# --- the ledger -------------------------------------------------------------------------------
_write_lock = threading.Lock()
_read_lock = threading.Lock()
_read_cache: dict[str, Any] = {"key": None, "rows": []}


def ledger_path() -> Path:
    """Resolved per call, not at import, so a test that repoints out_dir is honoured."""
    return Path(settings.out_dir) / "admin" / "usage.jsonl"


def _rotate_if_huge(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LEDGER_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def record(event: str, **fields: Any) -> None:
    """Append one attributed line. Explicit fields win over the ambient attribution."""
    try:
        attr = current()
        row: dict[str, Any] = {
            "ts": round(time.time(), 3), "event": event,
            "user": attr.user, "project": attr.project,
            "kind": attr.kind, "surface": attr.surface,
        }
        row.update({k: v for k, v in fields.items() if v is not None})
        path = ledger_path()
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_huge(path)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:           # noqa: BLE001 — telemetry never breaks the caller
        pass


def record_llm(model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float,
               *, priced: bool = True) -> None:
    """One model call. `priced=False` marks a model missing from the price table, so the dashboard
    can say 'cost is understated' instead of quietly reporting a too-small number."""
    record("llm", model=model or "?", prompt_tokens=int(prompt_tokens),
           completion_tokens=int(completion_tokens), cost_usd=round(float(cost_usd), 6),
           priced=bool(priced))


def read(since: float | None = None) -> list[dict]:
    """Every ledger row (oldest first), cached until the file changes. Torn lines are skipped."""
    path = ledger_path()
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _read_lock:
        if _read_cache["key"] != key:
            rows: list[dict] = []
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue        # a half-written last line during a concurrent append
            except OSError:
                return []
            _read_cache.update(key=key, rows=rows)
        rows = list(_read_cache["rows"])
    if since is None:
        return rows
    return [r for r in rows if float(r.get("ts") or 0) >= since]


# --- provider balance (account-level, not per user) --------------------------------------------
_credits_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def provider_credits(*, ttl: float = 60.0) -> dict | None:
    """Account + key balance straight from the provider (OpenRouter-compatible `/credits` and
    `/auth/key`). The ledger says what WE think we spent; this says what the provider actually
    charged — worth showing side by side, since an unpriced model shows up as the gap between them.

    None when the provider has no such endpoint or is unreachable; the dashboard hides the tile.
    """
    now = time.time()
    if _credits_cache["data"] is not None and now - float(_credits_cache["ts"]) < ttl:
        return _credits_cache["data"]
    base, key = settings.llm_base_url.rstrip("/"), settings.llm_api_key
    if not key or "openrouter" not in base:
        return None

    def _get(path: str) -> dict:
        req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.load(resp)

    data: dict[str, Any] = {}
    try:
        c = _get("/credits")["data"]
        purchased, used = float(c.get("total_credits", 0.0)), float(c.get("total_usage", 0.0))
        data.update(purchased=purchased, used=used, remaining=purchased - used)
    except Exception:           # noqa: BLE001
        pass
    try:
        k = _get("/auth/key")["data"]
        limit = k.get("limit")
        data.update(key_used=float(k.get("usage", 0.0)),
                    key_limit=(float(limit) if limit is not None else None))
    except Exception:           # noqa: BLE001
        pass
    out = data or None
    _credits_cache.update(ts=now, data=out)
    return out
