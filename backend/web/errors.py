"""What a person sees when something fails.

Two audiences hit the same URLs. The UI's own code calls the API with `fetch` and reads JSON. A *person*
can also land on an API URL directly: the Download button opens one in a new tab, a link gets shared, a
page is refreshed after sign-in expires. Showing that person `{"detail": "..."}` is wrong twice over: it
looks broken, and it is the server's internal voice. So:

- a browser navigation (it asks for `text/html`) gets a small readable page with a way back;
- the UI's `fetch` calls keep getting JSON, with a stable `code` next to `detail`;
- a 5xx never carries the exception, a path or a stack trace: only a generic sentence and a short
  reference that is also written to the server log, so the owner can find the real cause;
- a failed job's message is one of a few plain sentences. The raw text stays in the usage ledger and
  the admin console, which only the owner can open.

This module imports nothing from the rest of `web/`, so the sign-in middleware can use it too.
"""
from __future__ import annotations

import html
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import settings

log = logging.getLogger("lattice.errors")

# status -> (code, page title, sentence for a person). A sentence here replaces the server's wording for
# statuses where that wording is a machine's ("no project 'ab12cd34'"); the others keep the server's own
# message because it was written for a user ("no final video to export: build the project first").
_TABLE: dict[int, tuple[str, str, str]] = {
    401: ("sign_in_required", "Please sign in", "Please sign in to continue."),
    403: ("forbidden", "Not allowed", "You don't have access to that."),
    404: ("not_found", "Not found",
          "We couldn't find that. It may have been removed, or it may belong to another account."),
    405: ("method_not_allowed", "Not available", "That isn't something this address can do."),
    409: ("not_ready", "Not ready yet", "That isn't ready yet."),
    413: ("too_large", "Too large", "That upload is too large."),
    422: ("invalid_request", "Couldn't use that", "That request wasn't valid. Please check it and try again."),
    429: ("limit_reached", "Limit reached", "You've reached a usage limit. Please try again later."),
}
_MACHINE_VOICE = {401, 403, 404, 405}          # these always use the sentence above, never the server's text
_GENERIC_5XX = "Something went wrong on our side. Please try again in a moment."


def wants_html(request: Request) -> bool:
    """True for a browser navigation (it asks for a page), false for the UI's own fetch/XHR calls."""
    return "text/html" in request.headers.get("accept", "").lower()


def code_for(status: int) -> str:
    if status in _TABLE:
        return _TABLE[status][0]
    return "server_error" if status >= 500 else "error"


def _page(status: int, title: str, message: str, ref: str = "") -> str:
    from web import errors as _self                        # noqa: PLC0415 — keep `home_url` patchable in tests
    home = _self.home_url()
    sign_in = (f'<p><a class="btn" href="{html.escape(home)}">Sign in</a></p>' if status == 401 else
               f'<p><a class="btn" href="{html.escape(home)}">Back to Lattice</a></p>')
    ref_line = f'<p class="mut">Reference: {html.escape(ref)}</p>' if ref else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} — Lattice</title>
<style>:root{{--bg:#fff;--fg:#17171c;--mut:#6b6b78;--ac:#b7791f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e0e12;--fg:#ececf1;--mut:#9a9aa8;--ac:#f0b13c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
display:grid;min-height:100vh;place-items:center;padding:24px;box-sizing:border-box}}
main{{max-width:440px}}h1{{font-size:24px;margin:0 0 8px}}.mut{{color:var(--mut);font-size:14px}}
.btn{{display:inline-block;margin-top:6px;padding:11px 20px;border-radius:8px;background:var(--ac);color:#17171c;
font-weight:650;text-decoration:none}}</style></head><body><main>
<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{sign_in}{ref_line}</main></body></html>"""


def home_url() -> str:
    """Where "Back to Lattice" goes: the separately hosted UI when there is one, else this server."""
    origins = [o.strip().rstrip("/") for o in (settings.frontend_origins or "").split(",") if o.strip()]
    return (origins[0] + "/") if origins else "/"


def respond(request: Request, status: int, detail: Any = None, *, headers: dict | None = None,
            ref: str = "") -> Response:
    """The one way an error leaves this app: a page for a person, JSON for the UI."""
    code, title, sentence = _TABLE.get(status, ("server_error" if status >= 500 else "error",
                                                 "Something went wrong" if status >= 500 else "Couldn't do that", ""))
    text = detail if isinstance(detail, str) and detail.strip() else ""
    if status >= 500:
        message = _GENERIC_5XX
    elif status in _MACHINE_VOICE or not text:
        message = sentence or "That didn't work. Please try again."
    else:
        message = text[:1].upper() + text[1:]
    if wants_html(request):
        return HTMLResponse(_page(status, title, message, ref), status_code=status, headers=headers)
    body: dict[str, Any] = {
        # The UI matches on detail == "sign in required", so a 401 keeps the server's exact string.
        "detail": text if (status == 401 and text) else message,
        "code": code,
    }
    if ref:
        body["ref"] = ref
    return JSONResponse(body, status_code=status, headers=headers)


# --- job failures ---------------------------------------------------------------------------------
_TIME = ("deadline", "timed out", "timeout", "time limit")
_AI = ("ratelimit", "rate limit", "429", "apiconnection", "apitimeout", "openai", "openrouter", "overloaded",
       "502", "503", "504", "connection error", "provider", "api key", "authentication", "model")
_RENDER = ("manim", "render", "docker", "scene", "ffmpeg", "chrome", "playwright", "latex")


def public_job_error(raw: str | None) -> str | None:
    """A failed job's reason as one plain sentence. The exception text and stack trace stay server-side."""
    if not raw:
        return None
    t = raw.lower()
    if any(k in t for k in _TIME):
        return "This took longer than the time limit, so it was stopped. Try a shorter or simpler topic."
    if any(k in t for k in _AI):
        return "The AI service was busy or unreachable just now. Please try again in a minute."
    if any(k in t for k in _RENDER):
        return "We couldn't render one of the scenes. Please try again, or simplify the topic."
    return "Something went wrong while building your video. Please try again."


# --- wiring ---------------------------------------------------------------------------------------
def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code >= 500:
            ref = uuid.uuid4().hex[:8]
            log.error("ref=%s %s %s -> %s %s", ref, request.method, request.url.path, exc.status_code, exc.detail)
            return respond(request, exc.status_code, ref=ref, headers=getattr(exc, "headers", None))
        return respond(request, exc.status_code, exc.detail, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> Response:
        # pydantic's error list names internal fields and models; a person needs one sentence.
        return respond(request, 422)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception) -> Response:
        ref = uuid.uuid4().hex[:8]
        log.error("ref=%s %s %s crashed", ref, request.method, request.url.path, exc_info=exc)
        return respond(request, 500, ref=ref)
