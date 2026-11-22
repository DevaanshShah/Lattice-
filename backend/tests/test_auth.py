"""Google sign-in via Supabase (web/auth.py) — the whole round trip against a fake Supabase.

No network: Supabase Auth is an `httpx.MockTransport`, tokens are signed here (HS256 with a test
secret, or a real ES256 key served from a fake JWKS). Covers the gate, the PKCE round trip,
refresh + cookie rotation on every response type, the three verification modes, and that the
identity seam (`web/users.py`) attributes work to the signed-in user.
"""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from core import usage
from web import auth, users as users_mod

URL = "https://proj.supabase.co"
ISSUER = f"{URL}/auth/v1"
SECRET = "test-secret-that-is-long-enough-for-hs256"
USER = {"id": "11111111-2222-3333-4444-555555555555", "email": "ada@example.com",
        "user_metadata": {"full_name": "Ada Lovelace", "avatar_url": "https://img/ada.png"}}


def make_token(*, exp_in=3600, key=SECRET, alg="HS256", kid=None, sub=USER["id"], aud="authenticated"):
    claims = {"sub": sub, "aud": aud, "iss": ISSUER, "exp": int(time.time()) + exp_in,
              "email": USER["email"], "user_metadata": USER["user_metadata"], "role": "authenticated"}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid} if kid else None)


class FakeSupabase:
    """Just enough GoTrue: /token (pkce + refresh), /user, /logout, /.well-known/jwks.json."""

    def __init__(self):
        self.calls: list[str] = []
        self.challenge = None               # set by the test from the /authorize URL
        self.refresh_tokens = {"rt-1": "rt-2"}
        self.jwks = {"keys": []}
        self.down = False

    def session(self, refresh_token):
        return {"access_token": make_token(), "refresh_token": refresh_token, "expires_in": 3600,
                "token_type": "bearer", "user": USER}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/auth/v1")
        grant = req.url.params.get("grant_type")
        self.calls.append(f"{req.method} {path}" + (f"?{grant}" if grant else ""))
        if self.down:
            raise httpx.ConnectError("down", request=req)
        assert req.headers["apikey"] == "anon"
        body = json.loads(req.content) if req.content else {}
        if path == "/token" and grant == "pkce":
            verifier = body["code_verifier"]
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if body["auth_code"] != "good-code" or digest != self.challenge:
                return httpx.Response(400, json={"error_description": "invalid flow state"})
            return httpx.Response(200, json=self.session("rt-1"))
        if path == "/token" and grant == "refresh_token":
            nxt = self.refresh_tokens.pop(body["refresh_token"], None)
            if nxt is None:
                return httpx.Response(400, json={"error_description": "Invalid Refresh Token"})
            return httpx.Response(200, json=self.session(nxt))
        if path == "/user":
            ok = req.headers.get("authorization", "").startswith("Bearer ")
            return httpx.Response(200, json=USER) if ok else httpx.Response(401, json={"msg": "no"})
        if path == "/logout":
            return httpx.Response(204)
        if path == "/.well-known/jwks.json":
            return httpx.Response(200, json=self.jwks)
        return httpx.Response(404)


@pytest.fixture
def fake():
    return FakeSupabase()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    usage.set_current(usage.Attribution())
    return users_mod.UserStore(tmp_path)


def build(fake, store, tmp_path, **cfg) -> TestClient:
    config = auth.AuthConfig(**{"supabase_url": URL, "anon_key": "anon", "jwt_secret": SECRET, **cfg})
    api = auth.SupabaseAuthAPI(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    service = auth.AuthService(config, api=api)
    app = FastAPI(dependencies=[Depends(users_mod.dependency(store))])
    auth.install(app, service)

    @app.get("/")
    def index():
        return {"page": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/whoami")
    def whoami(request: Request):
        return {"user": usage.current().user}

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 16)

    @app.get("/api/video")
    def get_video():
        return FileResponse(str(video), media_type="video/mp4")

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("route crashed")

    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


def set_cookies(resp) -> dict[str, str]:
    """name -> raw Set-Cookie header, for the cookies a response wrote."""
    return {h.split("=", 1)[0]: h for h in resp.headers.get_list("set-cookie")}


def is_cleared(header: str) -> bool:
    return 'max-age=0' in header.lower() or '=""' in header


# --- off by default ---------------------------------------------------------------------------
def test_disabled_is_a_pass_through(fake, store, tmp_path):
    c = build(fake, store, tmp_path, supabase_url="", anon_key="")
    assert c.get("/api/auth/me").json() == {"enabled": False, "required": False, "user": None}
    r = c.get("/api/whoami")
    assert r.status_code == 200 and r.json()["user"]          # anonymous cookie identity as before
    assert users_mod.COOKIE in set_cookies(r)
    assert c.get("/auth/login").headers["location"] == "/"
    assert fake.calls == []


def test_settings_without_supabase_leave_sign_in_off():
    from core.config import Settings
    assert not auth.AuthService.from_settings(Settings(_env_file=None)).enabled


# --- the gate ---------------------------------------------------------------------------------
def test_signed_out_api_is_refused_but_public_paths_are_open(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    assert c.get("/api/whoami").status_code == 401
    assert c.get("/api/video").status_code == 401
    assert c.get("/").status_code == 200
    assert c.get("/health").status_code == 200
    assert c.get("/api/auth/me").json() == {"enabled": True, "required": True, "user": None}
    assert store.all() == []                                   # a refused visitor isn't a user


def test_guest_mode_keeps_the_app_open(fake, store, tmp_path):
    c = build(fake, store, tmp_path, required=False)
    r = c.get("/api/whoami")
    assert r.status_code == 200 and r.json()["user"]           # anonymous identity still works


@pytest.mark.parametrize("path", ["/api/projects", "/api/learn/threads", "/api/decks/x/video",
                                  "/api/jobs/1/stream", "/anything-new"])
def test_gate_denies_by_default(path):
    assert not auth.AuthService.is_public(path)


@pytest.mark.parametrize("path", ["/", "/health", "/static/app.js", "/auth/callback",
                                  "/api/auth/me", "/admin", "/api/admin/summary"])
def test_public_paths(path):
    assert auth.AuthService.is_public(path)


# --- signed in --------------------------------------------------------------------------------
def test_valid_token_identifies_the_user_everywhere(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
    me = c.get("/api/auth/me").json()["user"]
    assert me == {"id": USER["id"], "email": USER["email"], "name": "Ada Lovelace",
                  "avatar": "https://img/ada.png"}
    rec = store.get(USER["id"])
    assert rec.email == USER["email"] and rec.name == "Ada Lovelace"
    assert users_mod.COOKIE not in set_cookies(c.get("/api/whoami"))   # no anonymous id minted
    assert fake.calls == []                                    # HS256 + secret: verified offline


@pytest.mark.parametrize("token", [
    make_token(key="some-other-secret-that-is-also-long-enough"),   # forged signature
    make_token(aud="anon"),                                          # an anon key, not a user token
    "not-a-jwt",
])
def test_bad_token_is_refused_and_cleared(fake, store, tmp_path, token):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, token)
    r = c.get("/api/whoami")
    assert r.status_code == 401
    assert is_cleared(set_cookies(r)[auth.ACCESS_COOKIE])


# --- refresh ----------------------------------------------------------------------------------
def test_expired_token_refreshes_and_rotates_cookies_even_on_a_file_response(fake, store, tmp_path):
    """The case a dependency can't handle: the refresh happens on a FileResponse. If the rotated
    refresh token weren't saved there, the next refresh would spend a dead token."""
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(exp_in=-3600))
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    r = c.get("/api/video")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    cookies = set_cookies(r)
    assert cookies[auth.REFRESH_COOKIE].startswith(f"{auth.REFRESH_COOKIE}=rt-2;")
    assert "httponly" in cookies[auth.ACCESS_COOKIE].lower()
    assert fake.calls == ["POST /token?refresh_token"]


def test_missing_access_cookie_refreshes_from_the_refresh_cookie(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    assert c.get("/api/whoami").json() == {"user": USER["id"]}


def test_revoked_refresh_token_signs_out(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(exp_in=-3600))
    c.cookies.set(auth.REFRESH_COOKIE, "rt-revoked")
    r = c.get("/api/whoami")
    assert r.status_code == 401
    cookies = set_cookies(r)
    assert is_cleared(cookies[auth.ACCESS_COOKIE]) and is_cleared(cookies[auth.REFRESH_COOKIE])


def test_supabase_outage_keeps_the_session(fake, store, tmp_path):
    """Down is not the same as revoked: the cookies must survive so the user is back when it is."""
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(exp_in=-3600))
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    fake.down = True
    r = c.get("/api/whoami")
    assert r.status_code == 401 and set_cookies(r) == {}


def test_concurrent_refreshes_spend_the_refresh_token_once(fake):
    """A page load fires several calls at once with the same just-expired session."""
    import asyncio
    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    api = auth.SupabaseAuthAPI(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    service = auth.AuthService(config, api=api)

    def req():
        return Request({"type": "http", "method": "GET", "path": "/api/x", "scheme": "http",
                        "query_string": b"", "server": ("testserver", 80),
                        "headers": [(b"host", b"testserver"),
                                    (b"cookie", f"{auth.REFRESH_COOKIE}=rt-1".encode())]})

    async def burst():
        return await asyncio.gather(*(service.resolve(req()) for _ in range(5)))

    results = asyncio.run(burst())
    assert all(user and user.id == USER["id"] for user, _ in results)
    assert all(auth.REFRESH_COOKIE + "=rt-2;" in "".join(cookies) for _, cookies in results)
    assert fake.calls == ["POST /token?refresh_token"]


# --- verification modes -----------------------------------------------------------------------
def test_asymmetric_tokens_verify_against_jwks_and_cache_the_keys(fake, store, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ec
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    fake.jwks = {"keys": [{**jwk, "kid": "k1", "alg": "ES256", "use": "sig"}]}
    c = build(fake, store, tmp_path, jwt_secret="")
    c.cookies.set(auth.ACCESS_COOKIE, make_token(key=private, alg="ES256", kid="k1"))
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
    assert fake.calls == ["GET /.well-known/jwks.json"]       # fetched once, then cached

    other = ec.generate_private_key(ec.SECP256R1())             # right kid, wrong key: forged
    c.cookies.set(auth.ACCESS_COOKIE, make_token(key=other, alg="ES256", kid="k1"))
    assert c.get("/api/whoami").status_code == 401


def test_hs256_without_secret_asks_supabase_once_per_token(fake, store, tmp_path):
    c = build(fake, store, tmp_path, jwt_secret="")
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
    assert fake.calls == ["GET /user"]


# --- the PKCE round trip ----------------------------------------------------------------------
def test_login_callback_round_trip(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    r = c.get("/auth/login", params={"next": "/studio?x=1"})
    assert r.status_code == 302
    target = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{ISSUER}/authorize"
    assert q["provider"] == "google" and q["code_challenge_method"] == "s256"
    assert q["redirect_to"] == "http://testserver/auth/callback"
    pkce = set_cookies(r)[auth.PKCE_COOKIE].lower()
    assert "httponly" in pkce and "path=/auth" in pkce
    fake.challenge = q["code_challenge"]

    r = c.get("/auth/callback", params={"code": "good-code"})
    assert r.status_code == 302 and r.headers["location"] == "/studio?x=1"
    cookies = set_cookies(r)
    assert cookies[auth.REFRESH_COOKIE].startswith(f"{auth.REFRESH_COOKIE}=rt-1;")
    assert is_cleared(cookies[auth.PKCE_COOKIE])               # the verifier is single-use
    assert c.get("/api/whoami").json() == {"user": USER["id"]}


def test_callback_without_the_login_cookie_fails_politely(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    r = c.get("/auth/callback", params={"code": "good-code"})
    assert r.headers["location"].startswith("/?auth_error=")
    assert fake.calls == []


def test_callback_reports_a_provider_error(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    r = c.get("/auth/callback", params={"error": "access_denied", "error_description": "User cancelled"})
    assert r.headers["location"] == "/?auth_error=User%20cancelled"


def test_callback_reports_a_rejected_code(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.get("/auth/login")
    fake.challenge = "something-else"
    r = c.get("/auth/callback", params={"code": "good-code"})
    assert r.headers["location"] == "/?auth_error=invalid%20flow%20state"


@pytest.mark.parametrize("raw,expected", [
    ("/studio", "/studio"), ("//evil.com", "/"), ("/\\evil.com", "/"),
    ("https://evil.com", "/"), ("", "/"), (None, "/"),
])
def test_safe_next_only_allows_same_site_paths(raw, expected):
    assert auth.safe_next(raw) == expected


def test_public_url_sets_the_return_address_and_secure_cookies(fake, store, tmp_path):
    c = build(fake, store, tmp_path, public_url="https://lattice.example.com/")
    r = c.get("/auth/login")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_to"] == ["https://lattice.example.com/auth/callback"]
    assert "secure" in set_cookies(r)[auth.PKCE_COOKIE].lower()


def test_unknown_provider_is_refused(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    assert c.get("/auth/login", params={"provider": "myspace"}).headers["location"].startswith("/?auth_error=")


# --- sign out ---------------------------------------------------------------------------------
def test_logout_revokes_and_clears(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    r = c.post("/auth/logout")
    assert r.json() == {"ok": True}
    cookies = set_cookies(r)
    assert is_cleared(cookies[auth.ACCESS_COOKIE]) and is_cleared(cookies[auth.REFRESH_COOKIE])
    assert fake.calls == ["POST /logout"]


# --- the real app wires it --------------------------------------------------------------------
def test_create_app_installs_sign_in(store, tmp_path):
    from web import jobs as jobs_mod
    from web.app import create_app
    from web.engine import Engine

    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    c = TestClient(create_app(engine=Engine(root=tmp_path / "web", client=object()),
                              queue=jobs_mod.JobQueue(synchronous=True),
                              auth=auth.AuthService(config)))
    assert c.get("/api/projects").status_code == 401
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    assert c.get("/api/projects").json() == {"projects": []}


# --- regressions from the independent review --------------------------------------------------
def test_logout_after_an_idle_hour_really_signs_out(fake, store, tmp_path):
    """Only the refresh cookie is left after an hour. Sign-out must still revoke the session at
    Supabase and clear the cookies, rather than having a refresh put fresh ones back."""
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    r = c.post("/auth/logout")
    headers = r.headers.get_list("set-cookie")
    assert all(is_cleared(h) for h in headers if h.startswith((auth.ACCESS_COOKIE, auth.REFRESH_COOKIE)))
    assert fake.calls == ["POST /token?refresh_token", "POST /logout"]


def test_a_crashing_route_still_saves_the_refreshed_session(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(exp_in=-3600))
    c.cookies.set(auth.REFRESH_COOKIE, "rt-1")
    r = c.get("/api/boom")
    assert r.status_code == 500
    assert set_cookies(r)[auth.REFRESH_COOKIE].startswith(f"{auth.REFRESH_COOKIE}=rt-2;")


def test_an_unexpected_session_fault_is_a_sign_out_not_a_500(fake, store, tmp_path, monkeypatch):
    c = build(fake, store, tmp_path)

    async def broken(self, request):
        raise KeyError("surprise")

    monkeypatch.setattr(auth.AuthService, "resolve", broken)
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    assert c.get("/api/whoami").status_code == 401
    assert c.get("/").status_code == 200


@pytest.mark.parametrize("path", ["/health-details", "/healthz", "/favicon-admin"])
def test_lookalike_paths_are_not_public(fake, store, tmp_path, path):
    assert not auth.AuthService.is_public(path)
    c = build(fake, store, tmp_path)
    assert c.get(path).status_code == 401        # gated, not waved through by a prefix


def test_supabase_client_survives_a_closed_lifespan():
    import asyncio
    api = auth.SupabaseAuthAPI(auth.AuthConfig(supabase_url=URL, anon_key="anon"))
    asyncio.run(api.aclose())
    assert not api._client().is_closed
