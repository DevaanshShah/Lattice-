"""Requests per minute, per client address: a ceiling on how fast any one machine can use the app.

The per-account limits (web/quota.py) bound what each Google account can spend, and the global spend
ceiling bounds the bill. Neither stops one machine from hammering the sign-in flow, cycling through
throwaway accounts, or flooding the API. This does, cheaply, before the session check runs:

    auth    GET /auth/login and /auth/callback                       default 20 a minute
    write   POST, PUT, PATCH, DELETE under /api/                       default 60 a minute
    read    every other /api/ request (status polling, videos)        default 600 a minute

Pages, static files and /health are never limited. A refusal is the same readable page or JSON as every
other error (web/errors.py), with Retry-After.

The client address is the LAST X-Forwarded-For entry: the one the proxy in front of us (Caddy) wrote.
The first entry is whatever the client chose to send, so keying on it would let anyone dodge the limit
by inventing a new address per request. Counts are in memory: a restart clears them, which is fine for a
limit measured in seconds.
"""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from web import errors as errors_mod

WINDOW_S = 60.0
AUTH_PATHS = ("/auth/login", "/auth/callback")
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_address(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-for":
            last = value.decode("latin-1").split(",")[-1].strip()
            if last:
                return last[:45]
    client = scope.get("client")
    return (client[0] if client else "") or "unknown"


def bucket_for(method: str, path: str) -> str | None:
    if path.startswith(AUTH_PATHS):
        return "auth"
    if path.startswith("/api/"):
        return "write" if method.upper() in WRITES else "read"
    return None


class RateLimiter:
    """Sliding window: at most `limit` hits per `WINDOW_S` seconds for each (bucket, address)."""

    def __init__(self, limits: dict[str, int], *, now: Callable[[], float] = time.monotonic,
                 max_keys: int = 20000) -> None:
        self.limits = {k: max(0, int(v)) for k, v in limits.items()}
        self._now = now
        self._max_keys = max_keys
        self._hits: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def hit(self, bucket: str, address: str) -> float | None:
        """Record one request. Returns None if allowed, else the seconds until the next one is."""
        limit = self.limits.get(bucket, 0)
        if not limit:
            return None
        now = self._now()
        key = (bucket, address)
        q = self._hits.get(key)
        if q is None:
            q = self._hits[key] = deque()
            if len(self._hits) > self._max_keys:         # bounded memory under a flood of new addresses
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        while q and q[0] <= now - WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            return max(1.0, q[0] + WINDOW_S - now)
        q.append(now)
        return None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            bucket = bucket_for(scope.get("method", "GET"), scope.get("path", ""))
            if bucket:
                wait = self.limiter.hit(bucket, client_address(scope))
                if wait is not None:
                    seconds = int(wait + 0.999)
                    response = errors_mod.respond(
                        Request(scope), 429,
                        f"Too many requests from your connection. Please wait {seconds} seconds and try again.",
                        headers={"Retry-After": str(seconds)})
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


# --- request size --------------------------------------------------------------------------------
# Every free-text field the model reads is paid for by the token. Field limits catch the known fields;
# this catches the rest (a field someone adds later without a limit, a body padded with junk). Learn
# messages carry a pasted image as a data URL, so those two routes get room for one; nothing else needs
# more than a few kilobytes (a pasted code snippet is capped at 20,000 characters).
import re  # noqa: E402

MAX_BODY = 64 * 1024
IMAGE_BODY = 12 * 1024 * 1024
_IMAGE_ROUTES = re.compile(r"/api/learn/threads(/[^/]+/messages)?/?")


class _TooLarge(Exception):
    pass


def body_limit_for(method: str, path: str) -> int | None:
    if method.upper() not in WRITES or not path.startswith("/api/"):
        return None
    return IMAGE_BODY if _IMAGE_ROUTES.fullmatch(path) else MAX_BODY


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        kb = limit // 1024
        size = f"{kb // 1024} MB" if kb >= 1024 else f"{kb} KB"
        await errors_mod.respond(Request(scope), 413, f"That request is too large (the limit is {size}).")(
            scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = body_limit_for(scope.get("method", ""), scope.get("path", "")) if scope["type"] == "http" else None
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope.get("headers") or [] if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._refuse(scope, receive, send, limit)
            return
        received = 0

        async def counted() -> dict:          # a body sent without Content-Length is counted as it arrives
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, counted, send)
        except _TooLarge:
            await self._refuse(scope, receive, send, limit)
