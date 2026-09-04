"""Cooperative cancellation + deadlines for long builds.

A build is minutes of nested loops (scene retries -> compile repairs -> critic iterations -> model
calls), so "stop" has to be something the pipeline *asks about*, not something done to it: killing a
worker mid-render would strand a Docker container and half-written files. Every loop in the pipeline
calls `check()`; when the job's token is tripped the call raises `Cancelled` and the stack unwinds
through the normal `finally` handlers.

Two ways a token trips:
  - a user pressing Stop (`token.cancel()`),
  - a DEADLINE passing — the bound that turns "silently retrying for 20 minutes" into a job that
    ends with a message naming what ran out of time.

The token is AMBIENT (thread-local) rather than an argument threaded through twenty signatures:
`web.jobs` installs it around the job body, and `composition.decoupled` re-installs it inside its
scene-worker threads (thread-locals do not inherit). Deep modules just call `cancel.check()`.

`Cancelled` derives from BaseException — like `asyncio.CancelledError` and for the same reason: the
pipeline is full of `except Exception` handlers that retry or degrade gracefully, and every one of
them would otherwise swallow a stop request and keep spending. Code that must observe cancellation
(the job runner) catches it explicitly.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class Cancelled(BaseException):
    """Raised by check() when the ambient token is stopped or out of time."""

    def __init__(self, reason: str = "cancelled", detail: str = "") -> None:
        self.reason = reason          # "cancelled" | "deadline"
        self.detail = detail
        super().__init__(detail or reason)


class CancelToken:
    """One job's stop switch. Thread-safe; shared by the job thread and its scene workers."""

    def __init__(self, *, deadline_s: float | None = None,
                 now=time.monotonic) -> None:
        self._now = now
        self._event = threading.Event()
        self._reason = ""
        self._detail = ""
        self.deadline = (now() + deadline_s) if deadline_s else None

    def cancel(self, reason: str = "cancelled", detail: str = "") -> None:
        self._reason, self._detail = reason, detail
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or ("cancelled" if self.cancelled else "")

    def expired(self) -> bool:
        return self.deadline is not None and self._now() > self.deadline

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled(self._reason or "cancelled", self._detail or "stopped by request")
        if self.expired():
            self.cancel("deadline", "the job ran past its time limit")
            raise Cancelled("deadline", "the job ran past its time limit")


# --- ambient token (per thread) ---------------------------------------------------------------
_local = threading.local()


def set_current(token: CancelToken | None) -> None:
    """Install `token` as this thread's ambient token. Also the ThreadPoolExecutor `initializer`."""
    _local.token = token
    _local.deadline = None


def current() -> CancelToken | None:
    return getattr(_local, "token", None)


def check() -> None:
    """Raise Cancelled if this thread's job was stopped or has run out of time. No-op when no
    token is installed — so the CLI, evals and tests run unchanged."""
    tok = current()
    if tok is not None:
        tok.check()
    until = getattr(_local, "deadline", None)
    if until is not None and time.monotonic() > until:
        _local.deadline = None       # one raise per scope; the unwind is what stops the work
        raise Cancelled("deadline", "this step ran past its time limit")


@contextmanager
def scope(token: CancelToken | None):
    """Install a token for the duration of a block (restores the previous one)."""
    prev, prev_dl = current(), getattr(_local, "deadline", None)
    set_current(token)
    try:
        yield token
    finally:
        _local.token, _local.deadline = prev, prev_dl


def carry(fn):
    """Bind `fn` to the CALLER's token so it survives the hop onto a worker thread — the same
    idiom as `usage.carry`, because thread-locals do not inherit and a scene rendering on a pool
    thread must still see its job's stop switch. Each invocation gets a fresh, own deadline clock."""
    tok = current()

    def wrapper(*a, **k):
        with scope(tok):
            return fn(*a, **k)
    return wrapper


@contextmanager
def deadline(seconds: float | None):
    """A tighter, THREAD-LOCAL time limit for one step (e.g. one scene), on top of the job's.
    Thread-local because scenes run in parallel: each worker gets its own clock."""
    prev = getattr(_local, "deadline", None)
    if seconds and seconds > 0:
        mine = time.monotonic() + seconds
        _local.deadline = mine if prev is None else min(prev, mine)
    try:
        yield
    finally:
        _local.deadline = prev
