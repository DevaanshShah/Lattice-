"""The frontend and backend can be deployed apart (UI on Vercel, API on your own server).

What has to hold:
- every request the UI sends to the backend goes through `U()`, so one setting moves it;
- the backend answers a configured frontend origin with CORS + credentials, and nobody else;
- sign-in returns the browser to the FRONTEND, never to an arbitrary URL;
- with nothing configured, the single-server deploy behaves exactly as before.
"""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from test_auth import build, fake, set_cookies, store  # noqa: F401 — fixtures
from test_ownership import app_parts  # noqa: F401 — the real app with sign-in ON
from web import auth

FRONT = "https://app.example.com"
STATIC = Path(__file__).parent.parent / "frontend" / "static"


# --- the frontend never hard-codes the backend's address ------------------------------------
# An allowed call is either wrapped in U(...) or handed to a helper that itself calls api() (which
# wraps it). Anything else is a relative URL that would hit the FRONTEND's host after a split.
ALLOWED_BEFORE = (r"\bU\($", r"\bapi\(\s*(?:\"[A-Z]+\"|method),\s*$", r"\b(?:sceneJob|structural)\(\s*$")


def _backend_literals(text):
    for m in re.finditer(r"""(["`'])/(?:api|auth)/""", text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line = text[line_start:text.find("\n", m.start())]
        if line.lstrip().startswith("//"):
            continue
        yield m, text[max(0, m.start() - 60):m.start()], line


@pytest.mark.parametrize("name", ["app.js", "learn.js", "decks.js", "intro.js"])
def test_every_backend_url_in_the_ui_goes_through_the_one_helper(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    bad = []
    for _m, before, line in _backend_literals(text):
        if "closest(" in line:                        # the click selector for sign-in links, not a request
            continue
        if not any(re.search(p, before) for p in ALLOWED_BEFORE):
            bad.append(line.strip()[:110])
    assert not bad, f"{name}: backend URL not wrapped in U(): {bad}"


def test_the_guard_actually_catches_a_raw_url():
    sample = 'const r = await fetch("/api/projects");'
    hits = [b for _, b, _l in _backend_literals(sample) if not any(re.search(p, b) for p in ALLOWED_BEFORE)]
    assert hits, "the pattern must flag a bare fetch of a backend path"


def test_config_defaults_to_the_same_server_and_the_helper_prefixes_cleanly():
    text = (STATIC / "config.js").read_text(encoding="utf-8")
    assert 'window.LATTICE_API = "";' in text          # default = single server, nothing to configure
    assert 'replace(/\\/$/, "")' in text               # a trailing slash must not produce //api/...


def test_index_loads_the_config_before_any_script_that_uses_it():
    html = (STATIC.parent / "index.html").read_text(encoding="utf-8")
    order = [m.group(1) for m in re.finditer(r'<script[^>]*src="/static/([^"]+)"', html)]
    assert order.index("config.js") < min(order.index(n) for n in ("decks.js", "learn.js", "app.js"))


# --- CORS -----------------------------------------------------------------------------------
@pytest.fixture
def split_app(app_parts, monkeypatch):
    monkeypatch.setattr("core.config.settings.frontend_origins", f"{FRONT}/, https://other.example.org")
    from web.app import create_app
    app, _ = app_parts
    return create_app(engine=app.state.engine, queue=app.state.queue, auth=app.state.auth)


def test_a_configured_frontend_gets_cors_with_credentials(split_app):
    r = TestClient(split_app).get("/health", headers={"Origin": FRONT})
    assert r.headers["access-control-allow-origin"] == FRONT      # the exact origin, never "*"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_a_preflight_is_answered_without_a_session(split_app):
    r = TestClient(split_app).options("/api/projects", headers={
        "Origin": FRONT, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == FRONT
    assert "POST" in r.headers["access-control-allow-methods"]


def test_the_session_gate_still_applies_and_its_401_is_readable_by_the_frontend(split_app):
    r = TestClient(split_app).get("/api/projects", headers={"Origin": FRONT})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == FRONT      # else the UI sees an opaque network error


@pytest.mark.parametrize("origin", ["https://evil.example.net", "https://app.example.com.evil.net",
                                    "http://app.example.com"])
def test_any_other_origin_gets_no_cors_headers(split_app, origin):
    r = TestClient(split_app).get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers


def test_with_nothing_configured_there_is_no_cors_at_all(app_parts):
    app, _ = app_parts
    r = TestClient(app).get("/health", headers={"Origin": FRONT})
    assert "access-control-allow-origin" not in r.headers


# --- where sign-in returns to ---------------------------------------------------------------
ORIGINS = (FRONT,)


@pytest.mark.parametrize("raw,expect", [
    ("/studio?x=1", "/studio?x=1"),
    (f"{FRONT}/studio?x=1", f"{FRONT}/studio?x=1"),
    (FRONT, FRONT),
    (f"{FRONT}?a=1", f"{FRONT}?a=1"),
    ("https://evil.example.net/", "/"),
    (f"{FRONT}.evil.net/", "/"),                  # a look-alike that merely STARTS with the origin
    (f"{FRONT}@evil.net/", "/"),
    ("//evil.net", "/"),
    ("/\\evil.net", "/"),
    ("javascript:alert(1)", "/"),
    ("", "/"),
])
def test_safe_next_only_returns_to_a_path_or_a_configured_frontend(raw, expect):
    assert auth.safe_next(raw, ORIGINS) == expect


def test_without_frontend_origins_safe_next_is_exactly_what_it_was():
    assert auth.safe_next(f"{FRONT}/x") == "/"
    assert auth.safe_next("/ok") == "/ok"


def sign_in(c, fake, next_="/"):
    r = c.get("/auth/login", params={"next": next_})
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    fake.challenge = q["code_challenge"]
    return c.get("/auth/callback", params={"code": "good-code"})


def test_sign_in_returns_to_the_frontend_when_it_asked_to(fake, store, tmp_path):
    c = build(fake, store, tmp_path, frontend_origins=FRONT)
    r = sign_in(c, fake, next_=f"{FRONT}/studio")
    assert r.status_code == 302 and r.headers["location"] == f"{FRONT}/studio"
    assert auth.ACCESS_COOKIE in set_cookies(r) or auth.REFRESH_COOKIE in set_cookies(r)


def test_a_hostile_next_cannot_turn_sign_in_into_an_open_redirect(fake, store, tmp_path):
    c = build(fake, store, tmp_path, frontend_origins=FRONT)
    r = sign_in(c, fake, next_="https://evil.example.net/steal")
    assert r.headers["location"] == f"{FRONT}/"          # falls back to the frontend's home, not the attacker's


def test_a_relative_next_lands_on_the_frontend_not_the_api_host(fake, store, tmp_path):
    c = build(fake, store, tmp_path, frontend_origins=FRONT)
    assert sign_in(c, fake, next_="/studio").headers["location"] == f"{FRONT}/studio"


def test_a_sign_in_error_is_shown_by_the_frontend(fake, store, tmp_path):
    c = build(fake, store, tmp_path, frontend_origins=FRONT, allowed_emails="someone@else.com")
    r = sign_in(c, fake)
    assert r.headers["location"].startswith(f"{FRONT}/?auth_error=")
    c2 = build(fake, store, tmp_path, frontend_origins=FRONT)
    assert c2.get("/auth/callback", params={"error": "access_denied"}).headers["location"] \
        .startswith(f"{FRONT}/?auth_error=")


def test_the_single_server_deploy_still_returns_to_itself(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    assert sign_in(c, fake, next_="/studio?x=1").headers["location"] == "/studio?x=1"
    bad = build(fake, store, tmp_path).get("/auth/callback", params={"error": "nope"})
    assert bad.headers["location"].startswith("/?auth_error=")


# --- the owner's console is part of the backend ---------------------------------------------
def test_admin_page_and_its_assets_are_served_by_the_backend_alone(app_parts):
    app, _ = app_parts
    c = TestClient(app)
    assert c.get("/admin").status_code == 200
    html = c.get("/admin").text
    refs = re.findall(r'(?:src|href)="(/admin-assets/[^"]+)"', html)
    assert refs, "admin.html should load its own assets from /admin-assets/"
    for ref in refs:
        assert c.get(ref).status_code == 200, ref
    assert "/static/" not in html          # no dependency on the UI's files


# --- a half-deployed server keeps its UI -----------------------------------------------------
def test_a_server_without_the_new_frontend_folder_keeps_serving_its_old_ui(tmp_path):
    """New Python files copied without the new `frontend/` folder must not blank the live UI."""
    from web.app import resolve_frontend
    web = tmp_path / "web"
    (web / "static").mkdir(parents=True)
    (web / "static" / "index.html").write_text("old", encoding="utf-8")
    assert resolve_frontend(web) == (web / "static", web / "static")      # old layout, still served


def test_the_new_frontend_folder_wins_when_it_is_present(tmp_path):
    from web.app import resolve_frontend
    web = tmp_path / "web"
    (web / "static").mkdir(parents=True)
    (web / "static" / "index.html").write_text("old", encoding="utf-8")
    (tmp_path / "frontend" / "static").mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("new", encoding="utf-8")
    assert resolve_frontend(web) == (tmp_path / "frontend", tmp_path / "frontend" / "static")


def test_a_backend_only_deploy_serves_the_api_and_no_page(tmp_path):
    from web.app import resolve_frontend
    web = tmp_path / "web"
    (web / "static").mkdir(parents=True)                  # admin assets only: no index.html anywhere
    frontend, static = resolve_frontend(web)
    assert not (frontend / "index.html").exists() and frontend == tmp_path / "frontend"
