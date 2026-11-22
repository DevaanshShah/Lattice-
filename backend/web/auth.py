"""Sign-in with Google, through Supabase Auth — done server-side, kept in httponly cookies.

Why server-side (PKCE against Supabase's REST API) rather than supabase-js in the browser:
- the access + refresh tokens never touch JavaScript, so an injected script can't lift a session;
- the parts of this app that can't send an Authorization header — the SSE progress stream
  (`EventSource`), `<video src>` previews, download links — all send cookies, so they keep working
  with no per-call plumbing in the frontend;
- one place decides who a request belongs to, the same rule `web/users.py` already follows.

Flow:
    GET  /auth/login      -> 302 to Supabase /authorize (provider=google, PKCE challenge)
    GET  /auth/callback   <- Supabase sends ?code=…; exchanged for a session -> cookies -> 302 next
    POST /auth/logout     -> revoke at Supabase (best effort), clear cookies
    GET  /api/auth/me     -> {enabled, required, user}

`AuthMiddleware` resolves the session on every request: it verifies the access token locally (JWKS
for asymmetric signing keys, the shared secret for legacy HS256, or — with neither available — asks
Supabase once per token), refreshes it when it has expired, and writes the rotated cookies onto
WHATEVER response goes out, including `FileResponse` and `StreamingResponse`. That last point is
why this is middleware and not a dependency: a dependency's cookies never reach those responses,
and a refresh token that rotated without being saved logs the user out shortly after.

Sign-in is OFF until `LATTICE_SUPABASE_URL` + `LATTICE_SUPABASE_ANON_KEY` are set; then every
route outside `PUBLIC_*` needs a session (deny by default, so a new endpoint is protected without
remembering to opt in). The admin console keeps its own token gate (`web/admin.py`).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from web import errors as errors_mod

ACCESS_COOKIE = "lattice_at"
REFRESH_COOKIE = "lattice_rt"
PKCE_COOKIE = "lattice_pkce"
REFRESH_MAX_AGE = 60 * 24 * 3600      # Supabase sessions don't expire by default; the cookie needs a cap
PKCE_MAX_AGE = 600                    # a sign-in round trip that takes >10 min starts over
AUDIENCE = "authenticated"            # the `aud` Supabase puts on a signed-in user's access token
CLOCK_LEEWAY_S = 30
PROVIDERS = frozenset({"google"})     # adding GitHub etc. = enable it in Supabase + add it here

# Reachable without a session. Everything else is denied when sign-in is required.
PUBLIC_EXACT = frozenset({"/", "/admin", "/health", "/favicon.ico"})
PUBLIC_PREFIXES = ("/static/", "/admin-assets/", "/auth/", "/api/auth/", "/api/admin/")
# Never worth a token check (and never a network call): assets and infra pings.
NO_RESOLVE_PREFIXES = ("/static/", "/admin-assets/")
NO_RESOLVE_EXACT = frozenset({"/health", "/favicon.ico"})

ASYMMETRIC_ALGS = frozenset({"ES256", "RS256", "EdDSA"})


class AuthError(Exception):
    """The credential is bad: wrong signature, revoked, malformed. Clear it."""


class TokenExpired(AuthError):
    """A valid token whose time is up. Refresh it."""


class AuthUnavailable(AuthError):
    """Supabase couldn't be reached or failed on its side. Keep the cookies; try again later."""


# --- configuration + identity -----------------------------------------------------------------
@dataclass(frozen=True)
class AuthConfig:
    supabase_url: str = ""
    anon_key: str = ""
    jwt_secret: str = ""
    required: bool = True
    public_url: str = ""
    frontend_origins: str = ""  # split deploy: origins of a separately hosted UI that may be returned to
    allowed_emails: str = ""    # invite list: "a@x.com, @school.edu". Empty = anyone with a Google account

    def __post_init__(self) -> None:
        object.__setattr__(self, "supabase_url", self.supabase_url.strip().rstrip("/"))
        object.__setattr__(self, "public_url", self.public_url.strip().rstrip("/"))

    @property
    def enabled(self) -> bool:
        return bool(self.supabase_url and self.anon_key)

    @property
    def frontend_list(self) -> tuple[str, ...]:
        return tuple(o.strip().rstrip("/") for o in self.frontend_origins.split(",") if o.strip())

    def frontend_url(self, path: str) -> str:
        """Where to send the browser after sign-in. A relative path goes to the separately hosted UI
        when there is one (the backend has no page of its own then); an absolute URL passed
        `safe_next` already, so it is on a configured origin and is used as is."""
        origins = self.frontend_list
        if path.startswith("/") and origins:
            return origins[0] + path
        return path

    def allows(self, email: str) -> bool:
        """May this Google account use the app? An entry is an exact email or `@domain` (a whole
        school or company). Case never matters; an account with no email is refused once a list exists."""
        entries = [e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()]
        if not entries:
            return True
        email = (email or "").strip().lower()
        return bool(email) and any(email == e or (e.startswith("@") and email.endswith(e))
                                   for e in entries)

    @property
    def auth_base(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def issuer(self) -> str:
        return self.auth_base

    @classmethod
    def from_settings(cls, s: Any) -> "AuthConfig":
        return cls(supabase_url=s.supabase_url, anon_key=s.supabase_anon_key,
                   jwt_secret=s.supabase_jwt_secret, required=s.auth_required,
                   public_url=s.public_url,
                   allowed_emails=getattr(s, "auth_allowed_emails", "") or "",
                   frontend_origins=getattr(s, "frontend_origins", "") or "")


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str = ""
    name: str = ""
    avatar: str = ""

    @classmethod
    def _build(cls, uid: Any, email: Any, meta: Any) -> "AuthUser":
        if not uid:
            raise AuthError("token has no subject")
        meta = meta if isinstance(meta, dict) else {}
        return cls(id=str(uid), email=str(email or ""),
                   name=str(meta.get("full_name") or meta.get("name") or ""),
                   avatar=str(meta.get("avatar_url") or meta.get("picture") or ""))

    @classmethod
    def from_claims(cls, claims: dict) -> "AuthUser":
        """From a verified access token's claims (`sub` is the Supabase user id)."""
        return cls._build(claims.get("sub"), claims.get("email"), claims.get("user_metadata"))

    @classmethod
    def from_user(cls, user: dict) -> "AuthUser":
        """From a Supabase user object (the `user` in a token response, or GET /user)."""
        return cls._build(user.get("id"), user.get("email"), user.get("user_metadata"))

    def to_dict(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "avatar": self.avatar}


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    user: AuthUser

    @classmethod
    def from_payload(cls, data: Any) -> "Session":
        if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
            raise AuthError("Supabase returned no session")
        return cls(access_token=str(data["access_token"]), refresh_token=str(data["refresh_token"]),
                   expires_in=int(data.get("expires_in") or 3600),
                   user=AuthUser.from_user(data.get("user") or {}))


@dataclass(frozen=True)
class AuthState:
    """What every request carries as `request.state.auth`."""
    enabled: bool
    required: bool = False
    user: AuthUser | None = None


# --- concurrency helper -----------------------------------------------------------------------
class _SingleFlight:
    """Collapse concurrent identical async calls into one, and remember a success for `hold_s`.

    A page load fires several API calls at once; when the access token has just expired, each one
    would otherwise spend the same refresh token. Failures are forgotten immediately so a retry
    really retries. Entries are per event loop — a task can't be awaited from another loop.
    """

    def __init__(self, hold_s: float) -> None:
        self._hold = hold_s
        self._calls: dict[str, tuple[float, asyncio.Task]] = {}

    async def run(self, key: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        loop = asyncio.get_running_loop()
        now = time.monotonic()
        self._calls = {k: v for k, v in self._calls.items()
                       if not (v[1].done() and now - v[0] >= self._hold)}
        hit = self._calls.get(key)
        if hit is None or hit[1].get_loop() is not loop:
            task = loop.create_task(fn())

            def forget_failure(t: asyncio.Task, key: str = key) -> None:
                if (t.cancelled() or t.exception() is not None) and self._calls.get(key, (0, None))[1] is t:
                    self._calls.pop(key, None)

            task.add_done_callback(forget_failure)
            hit = self._calls[key] = (now, task)
        return await asyncio.shield(hit[1])


# --- Supabase Auth (GoTrue) REST calls --------------------------------------------------------
class SupabaseAuthAPI:
    """The handful of Supabase Auth endpoints this app uses. `http` is injectable for tests."""

    def __init__(self, config: AuthConfig, http: httpx.AsyncClient | None = None) -> None:
        self._cfg = config
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=10.0)

    def _client(self) -> httpx.AsyncClient:
        # Shutdown closes the client; a second app lifespan (dev reload, a reused test client)
        # would otherwise find every Supabase call failing with "client has been closed".
        if self._http.is_closed and self._owns_http:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    def authorize_url(self, *, provider: str, redirect_to: str, code_challenge: str) -> str:
        query = urlencode({"provider": provider, "redirect_to": redirect_to,
                           "code_challenge": code_challenge, "code_challenge_method": "s256"})
        return f"{self._cfg.auth_base}/authorize?{query}"

    async def exchange_code(self, code: str, verifier: str) -> Session:
        return Session.from_payload(await self._request(
            "POST", "/token", params={"grant_type": "pkce"},
            json={"auth_code": code, "code_verifier": verifier}))

    async def refresh(self, refresh_token: str) -> Session:
        return Session.from_payload(await self._request(
            "POST", "/token", params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token}))

    async def get_user(self, access_token: str) -> AuthUser:
        return AuthUser.from_user(await self._request("GET", "/user", token=access_token) or {})

    async def jwks(self) -> dict:
        return await self._request("GET", "/.well-known/jwks.json") or {}

    async def logout(self, access_token: str) -> None:
        await self._request("POST", "/logout", params={"scope": "local"}, token=access_token)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, token: str | None = None,
                       params: dict | None = None, json: dict | None = None) -> Any:
        headers = {"apikey": self._cfg.anon_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = await self._client().request(method, self._cfg.auth_base + path, headers=headers,
                                         params=params, json=json)
        except httpx.HTTPError as e:
            raise AuthUnavailable(f"Supabase unreachable: {type(e).__name__}") from e
        if r.status_code >= 500:
            raise AuthUnavailable(f"Supabase error {r.status_code}")
        if r.status_code >= 400:
            raise AuthError(_error_message(r))
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise AuthUnavailable("Supabase sent a non-JSON reply") from e


def _error_message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"Supabase rejected the request ({r.status_code})"
    return str(body.get("error_description") or body.get("msg") or body.get("message")
               or body.get("error") or f"Supabase rejected the request ({r.status_code})")


# --- access-token verification ----------------------------------------------------------------
class TokenVerifier:
    """Turn an access token into an `AuthUser`, or raise.

    - asymmetric keys (ES256/RS256 — the current Supabase default): verified locally against the
      project's JWKS, cached for `JWKS_TTL_S` and refetched early when an unknown `kid` appears
      (key rotation), at most every `JWKS_MIN_REFETCH_S`;
    - legacy HS256 with `LATTICE_SUPABASE_JWT_SECRET` set: verified locally with the secret;
    - legacy HS256 without the secret: Supabase's GET /user is the judge, cached per token until
      it expires, so that costs one network call per token rather than one per request.
    """

    JWKS_TTL_S = 600.0
    JWKS_MIN_REFETCH_S = 30.0
    REMOTE_CACHE_MAX = 4096

    def __init__(self, config: AuthConfig, api: SupabaseAuthAPI) -> None:
        self._cfg = config
        self._api = api
        self._keys: dict[str, Any] = {}
        self._keys_at = float("-inf")
        self._jwks_flight = _SingleFlight(hold_s=0.0)
        self._remote: dict[str, tuple[float, AuthUser]] = {}

    async def verify(self, token: str) -> AuthUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError("malformed token") from e
        alg = header.get("alg")
        if alg in ASYMMETRIC_ALGS:
            return AuthUser.from_claims(self._decode(token, await self._key(header.get("kid")), alg))
        if alg == "HS256":
            if self._cfg.jwt_secret:
                return AuthUser.from_claims(self._decode(token, self._cfg.jwt_secret, alg))
            return await self._verify_remote(token)
        raise AuthError(f"unsupported token algorithm {alg!r}")

    def _decode(self, token: str, key: Any, alg: str) -> dict:
        try:
            return jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE,
                              issuer=self._cfg.issuer, leeway=CLOCK_LEEWAY_S,
                              options={"require": ["exp", "sub"]})
        except jwt.ExpiredSignatureError as e:
            raise TokenExpired("access token expired") from e
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid access token: {e}") from e

    async def _key(self, kid: str | None) -> Any:
        kid = kid or ""
        now = time.monotonic()
        fresh = now - self._keys_at < self.JWKS_TTL_S
        if kid in self._keys and fresh:
            return self._keys[kid]
        if not fresh or now - self._keys_at >= self.JWKS_MIN_REFETCH_S:
            try:
                await self._jwks_flight.run("jwks", self._load_keys)
            except AuthUnavailable:
                if kid not in self._keys:       # a stale key beats no key while Supabase is down
                    raise
        if kid not in self._keys:
            raise AuthError("token signed by an unknown key")
        return self._keys[kid]

    async def _load_keys(self) -> None:
        keys: dict[str, Any] = {}
        for raw in (await self._api.jwks()).get("keys") or []:
            try:
                jwk = jwt.PyJWK(raw)
            except jwt.PyJWTError:
                continue                        # a key type we can't use must not hide the rest
            keys[jwk.key_id or ""] = jwk.key
        self._keys, self._keys_at = keys, time.monotonic()

    async def _verify_remote(self, token: str) -> AuthUser:
        try:
            exp = float(jwt.decode(token, options={"verify_signature": False}).get("exp") or 0)
        except jwt.PyJWTError as e:
            raise AuthError("malformed token") from e
        now = time.time()
        if exp and exp + CLOCK_LEEWAY_S < now:
            raise TokenExpired("access token expired")
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = self._remote.get(key)
        if hit and hit[0] > now:
            return hit[1]
        user = await self._api.get_user(token)
        if len(self._remote) >= self.REMOTE_CACHE_MAX:
            self._remote = {k: v for k, v in self._remote.items() if v[0] > now}
            if len(self._remote) >= self.REMOTE_CACHE_MAX:
                self._remote.clear()
        self._remote[key] = (exp or now + 60, user)
        return user


# --- the service: sessions, cookies, the gate -------------------------------------------------
class AuthService:
    REFRESH_HOLD_S = 10.0   # matches Supabase's default refresh-token reuse interval

    def __init__(self, config: AuthConfig, api: SupabaseAuthAPI | None = None,
                 verifier: TokenVerifier | None = None) -> None:
        self.config = config
        self.api = api or SupabaseAuthAPI(config)
        self.verifier = verifier or TokenVerifier(config, self.api)
        self._refresh_flight = _SingleFlight(hold_s=self.REFRESH_HOLD_S)

    @classmethod
    def from_settings(cls, s: Any) -> "AuthService":
        return cls(AuthConfig.from_settings(s))

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @staticmethod
    def is_public(path: str) -> bool:
        return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)

    async def resolve(self, request: Request) -> tuple[AuthUser | None, list[str]]:
        """Who is this request, plus any Set-Cookie headers the response must carry.

        An account that is not on the invite list is signed out here, on EVERY request, not only at
        sign-in: removing someone from the list must end their session, not wait for it to expire."""
        user, cookies = await self._resolve(request)
        if user is not None and not self.config.allows(user.email):
            return None, self.clear_cookies(request)
        return user, cookies

    async def _resolve(self, request: Request) -> tuple[AuthUser | None, list[str]]:
        access = request.cookies.get(ACCESS_COOKIE, "")
        refresh = request.cookies.get(REFRESH_COOKIE, "")
        if not access and not refresh:
            return None, []
        if access:
            try:
                return await self.verifier.verify(access), []
            except AuthUnavailable:
                return None, []                 # can't tell right now; don't destroy the session
            except AuthError:
                pass                            # expired or bad: a refresh token may still save it
        if not refresh:
            return None, self.clear_cookies(request)
        try:
            session = await self._refresh_flight.run(
                hashlib.sha256(refresh.encode()).hexdigest(), lambda: self.api.refresh(refresh))
        except AuthUnavailable:
            return None, []
        except AuthError:
            return None, self.clear_cookies(request)
        # The rotated tokens MUST be saved now: the old refresh token is spent.
        return session.user, self.session_cookies(request, session)

    async def aclose(self) -> None:
        await self.api.aclose()

    # --- urls + cookies ---
    def base_url(self, request: Request) -> str:
        """Where the browser reached us — the OAuth return address is built from it.

        Supabase only redirects to URLs on its allow-list, so a forged Host can't send a sign-in
        elsewhere; still, set LATTICE_PUBLIC_URL in production so the address is never guessed."""
        if self.config.public_url:
            return self.config.public_url
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
        host = (request.headers.get("x-forwarded-host", "").split(",")[0].strip()
                or request.headers.get("host") or request.url.netloc)
        return f"{proto}://{host}"

    def _secure(self, request: Request) -> bool:
        return self.base_url(request).startswith("https://")

    def session_cookies(self, request: Request, session: Session) -> list[str]:
        secure = self._secure(request)
        return [_cookie(ACCESS_COOKIE, session.access_token, max_age=session.expires_in, secure=secure),
                _cookie(REFRESH_COOKIE, session.refresh_token, max_age=REFRESH_MAX_AGE, secure=secure)]

    def clear_cookies(self, request: Request) -> list[str]:
        secure = self._secure(request)
        return [_expired_cookie(ACCESS_COOKIE, secure=secure),
                _expired_cookie(REFRESH_COOKIE, secure=secure)]


def _cookie(name: str, value: str, *, max_age: int, secure: bool, path: str = "/") -> str:
    r = Response()
    r.set_cookie(name, value, max_age=max_age, path=path, secure=secure, httponly=True, samesite="lax")
    return r.headers["set-cookie"]


def _expired_cookie(name: str, *, secure: bool, path: str = "/") -> str:
    r = Response()
    r.delete_cookie(name, path=path, secure=secure, httponly=True, samesite="lax")
    return r.headers["set-cookie"]


def _with_cookies(response: Response, cookies: list[str]) -> Response:
    for c in cookies:
        response.headers.append("set-cookie", c)
    return response


def safe_next(raw: str | None, origins: tuple[str, ...] = ()) -> str:
    """Where to go after sign-in: a path on this site, or (split deploy) a URL on a configured frontend
    origin. `//evil.com` and a backslash variant are other sites to a browser, and so is
    `https://app.example.com.evil.com`, which is why an origin must be followed by `/`, `?` or `#`."""
    raw = (raw or "").strip()
    if raw.startswith("/") and not raw.startswith(("//", "/" + chr(92))):
        return raw
    for origin in origins:
        if raw == origin or raw.startswith((origin + "/", origin + "?", origin + "#")):
            return raw
    return "/"

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# --- ASGI middleware ----------------------------------------------------------------------------
class AuthMiddleware:
    """Resolve the session once per request, enforce the gate, and persist rotated cookies.

    Pure ASGI (not BaseHTTPMiddleware) so streamed responses pass straight through untouched.
    """

    def __init__(self, app: ASGIApp, service: AuthService) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cfg = self.service.config
        state = scope.setdefault("state", {})
        path = scope.get("path", "")
        if not cfg.enabled or _skips_resolve(path):
            state["auth"] = AuthState(enabled=cfg.enabled, required=cfg.required)
            await self.app(scope, receive, send)
            return

        try:
            user, cookies = await self.service.resolve(Request(scope))
        except Exception as e:  # noqa: BLE001 — a sign-in fault must not 500 every request
            print(f"[auth] session check failed: {type(e).__name__}: {e}")
            user, cookies = None, []
        state["auth"] = AuthState(enabled=True, required=cfg.required, user=user)

        if user is None and cfg.required and not self.service.is_public(path):
            denied = _with_cookies(errors_mod.respond(Request(scope), 401, "sign in required"), cookies)
            await denied(scope, receive, send)
            return
        if not cookies:
            await self.app(scope, receive, send)
            return

        raw = [(b"set-cookie", c.encode("latin-1")) for c in cookies]
        started = False

        async def send_with_cookies(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                # A route that sets the session cookies itself (sign-out, sign-in) has the last
                # word: appending ours after its would undo it, since browsers apply them in order.
                if not any(_sets_session_cookie(v) for k, v in headers if k.lower() == b"set-cookie"):
                    headers += raw
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_cookies)
        except Exception:
            # The refresh already spent the old refresh token. If the route crashed before replying,
            # the error page must still carry the new cookies, or the session dies with it.
            if not started:
                await _with_cookies(PlainTextResponse("Internal Server Error", status_code=500),
                                    cookies)(scope, receive, send)
            raise


def _skips_resolve(path: str) -> bool:
    """Assets, infra pings and the sign-in routes themselves: no session check, no network.

    Exact names, not prefixes, so a future `/health-details` route doesn't slip past the gate.
    The /auth/* routes handle their own cookies; resolving there would refresh a session that
    sign-out is about to clear.
    """
    return (path.startswith(NO_RESOLVE_PREFIXES) or path in NO_RESOLVE_EXACT
            or path.startswith("/auth/"))


def _sets_session_cookie(header: bytes) -> bool:
    name = header.split(b"=", 1)[0].strip().decode("latin-1")
    return name in (ACCESS_COOKIE, REFRESH_COOKIE)


# --- routes -----------------------------------------------------------------------------------
def install(app: FastAPI, service: AuthService) -> None:
    """Wire sign-in into `app`: the middleware plus the /auth routes."""
    app.add_middleware(AuthMiddleware, service=service)
    app.state.auth = service

    @app.get("/api/auth/me")
    def me(request: Request) -> dict:
        auth: AuthState = getattr(request.state, "auth", None) or AuthState(enabled=False)
        return {"enabled": auth.enabled, "required": auth.enabled and auth.required,
                "user": auth.user.to_dict() if auth.user else None}

    @app.get("/auth/login")
    def login(request: Request, next: str = "/", provider: str = "google") -> Response:
        if not service.enabled:
            return RedirectResponse("/", status_code=302)
        if provider not in PROVIDERS:
            return _fail(f"sign-in with {provider!r} isn't available")
        verifier = secrets.token_urlsafe(48)        # 64 chars of [A-Za-z0-9_-]: a valid PKCE verifier
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        target = service.api.authorize_url(provider=provider,
                                           redirect_to=f"{service.base_url(request)}/auth/callback",
                                           code_challenge=challenge)
        # The verifier rides in a short-lived httponly cookie scoped to /auth; `next` rides with it
        # (base64, so no cookie-unsafe characters) and is re-checked on the way back.
        pkce = f"{verifier}.{_b64url(safe_next(next, service.config.frontend_list).encode())}"
        return _with_cookies(RedirectResponse(target, status_code=302),
                             [_cookie(PKCE_COOKIE, pkce, max_age=PKCE_MAX_AGE,
                                      secure=service._secure(request), path="/auth")])

    @app.get("/auth/callback")
    async def callback(request: Request, code: str = "", error: str = "",
                       error_description: str = "") -> Response:
        secure = service._secure(request)
        spent = [_expired_cookie(PKCE_COOKIE, secure=secure, path="/auth")]
        home = service.config.frontend_list[0] if service.config.frontend_list else ""

        def _fail(message: str) -> RedirectResponse:       # the reason is shown by the UI, wherever it lives
            return _fail_to(home, message)
        if error:
            return _with_cookies(_fail(error_description or error), spent)
        verifier, _, packed_next = request.cookies.get(PKCE_COOKIE, "").partition(".")
        if not code or not verifier:
            return _with_cookies(_fail("That sign-in link expired. Please try again."), spent)
        try:
            session = await service.api.exchange_code(code, verifier)
        except AuthUnavailable:
            return _with_cookies(_fail("Couldn't reach the sign-in service. Please try again."), spent)
        except AuthError as e:
            return _with_cookies(_fail(str(e)), spent)
        if not service.config.allows(session.user.email):
            try:
                await service.api.logout(session.access_token)     # don't leave a live session behind
            except AuthError:
                pass
            return _with_cookies(_fail("This account isn't on the invite list yet. "
                                       "Ask the owner to add your email."), spent)
        try:
            next_path = safe_next(base64.urlsafe_b64decode(packed_next + "=" * (-len(packed_next) % 4)).decode(),
                                  service.config.frontend_list)
        except (ValueError, UnicodeDecodeError):
            next_path = "/"
        return _with_cookies(RedirectResponse(service.config.frontend_url(next_path), status_code=302),
                             spent + service.session_cookies(request, session))

    @app.post("/auth/logout")
    async def logout(request: Request) -> Response:
        """Revoke at Supabase (so a copied refresh token dies too), then clear the cookies.

        After an idle hour only the refresh cookie is left; it is traded for an access token
        purely to make the revoke call. Every failure still signs out here."""
        if service.enabled:
            access = request.cookies.get(ACCESS_COOKIE, "")
            refresh = request.cookies.get(REFRESH_COOKIE, "")
            try:
                if not access and refresh:
                    access = (await service.api.refresh(refresh)).access_token
                if access:
                    await service.api.logout(access)
            except AuthError:
                pass                                # an already-dead session still signs out here
        return _with_cookies(JSONResponse({"ok": True}), service.clear_cookies(request))


def _fail_to(base: str, message: str) -> RedirectResponse:
    """Back to the app with the reason in the URL; the sign-in screen shows it. `base` is the
    separately hosted frontend's origin on a split deploy, empty when the backend serves the UI."""
    return RedirectResponse(f"{base}/?auth_error={quote(message[:200])}", status_code=302)


def _fail(message: str) -> RedirectResponse:
    return _fail_to("", message)
