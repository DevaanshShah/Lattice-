"""Can one user misuse the app against another, or against the owner's bill? Attacks, run for real.

Account A is the victim, account B the attacker, plus a visitor with no session. Every attack below goes
through the real app (sign-in on, the real routes, the real middleware). The route sweeps are generated
from the app's own route table, so a route added later is covered without anyone remembering to add it.
"""
import base64
import json
import re
import threading

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core import usage
from test_auth import SECRET, make_token
from test_ownership import A, B, app_parts, as_user  # noqa: F401
from web import ratelimit
from web.app import create_app
from web.quota import Quota, QuotaExceeded

VICTIM_TEXT = "victim-private-topic-7f3a"
# One body that satisfies every write route's model (unknown fields are ignored), so an attack reaches
# the ownership check instead of stopping at input validation.
ANY_BODY = {"instruction": "x", "lines": ["x"], "pos": 0, "title": "t", "intent": "i", "frm": 0, "to": 0,
            "version": 1, "message": "hi", "prompt": "x", "keep": None}


@pytest.fixture
def victim(app_parts):
    """Account A owns one of everything: a video project, a deck, a lesson thread and a job."""
    app, queue = app_parts
    a = as_user(app, A)
    pid = a.post("/api/projects", json={"topic": VICTIM_TEXT}).json()["id"]
    did = a.post("/api/decks", json={"topic": VICTIM_TEXT}).json()["id"]
    thread = a.post("/api/learn/threads", json={"message": VICTIM_TEXT}).json()
    usage.set_current(usage.Attribution(user=A))
    job = queue.submit(lambda j: None, kind="build", project_id=pid)
    usage.set_current(usage.Attribution())
    mid = (thread.get("messages") or [{"id": "m1"}])[-1]["id"]
    ids = {"pid": pid, "did": did, "tid": thread["id"], "job_id": job.id, "index": "0", "mid": mid}
    return app, a, ids


def owned_routes(app):
    """Every route that addresses something an account owns (an id in the path), from the route table."""
    for r in app.routes:
        if isinstance(r, APIRoute) and not r.path.startswith("/api/admin"):
            if set(re.findall(r"{(\w+)}", r.path)) & {"pid", "did", "tid", "job_id"}:
                for method in r.methods:
                    yield method, r.path


def call(client, method, path, ids, **kw):
    url = re.sub(r"{(\w+)}", lambda m: ids[m.group(1)], path)
    if method in ("POST", "PUT", "PATCH"):
        return client.request(method, url, json=ANY_BODY, **kw)
    return client.request(method, url, **kw)


# --- 1. another account cannot read, change, run or stop anything of yours --------------------------
def test_no_route_lets_one_account_touch_another_accounts_things(victim):
    app, a, ids = victim
    b = as_user(app, B)
    routes = sorted(set(owned_routes(app)))
    assert len(routes) >= 25                       # the sweep really covers the app, not a handful
    leaked = []
    for method, path in routes:
        r = call(b, method, path, ids)
        if r.status_code < 400 or r.status_code >= 500 or VICTIM_TEXT in r.text:
            leaked.append(f"{method} {path} -> {r.status_code}")
    assert not leaked, "account B reached account A's data: " + "; ".join(leaked)

    # ...and after all of that, A's things are exactly as they were
    assert a.get(f"/api/projects/{ids['pid']}").json()["topic"] == VICTIM_TEXT
    assert a.get(f"/api/decks/{ids['did']}").status_code == 200
    assert a.get(f"/api/learn/threads/{ids['tid']}").status_code == 200
    assert a.get(f"/api/jobs/{ids['job_id']}").json()["cancelled"] is False


def test_lists_never_show_another_accounts_items(victim):
    app, _, ids = victim
    b = as_user(app, B)
    for path, key in (("/api/projects", "projects"), ("/api/decks", "decks"), ("/api/learn/threads", "threads")):
        body = b.get(path).json()
        assert body[key] == [] and VICTIM_TEXT not in json.dumps(body), path


def test_another_accounts_item_looks_exactly_like_one_that_does_not_exist(victim):
    """So ids can't be probed: 'exists but not yours' and 'does not exist' must be indistinguishable."""
    app, _, ids = victim
    b = as_user(app, B)
    theirs = b.get(f"/api/projects/{ids['pid']}")
    missing = b.get("/api/projects/zzzzzzzz")
    assert theirs.status_code == missing.status_code == 404 and theirs.json() == missing.json()


def test_headers_cannot_claim_someone_elses_identity(victim):
    app, _, ids = victim
    b = as_user(app, B)
    spoof = {"X-User-Id": A, "X-Forwarded-User": A, "X-Remote-User": A, "X-Auth-Request-User": A,
             "X-Supabase-User": A, "X-Admin-Token": "guess"}
    assert b.get(f"/api/projects/{ids['pid']}", headers=spoof).status_code == 404
    assert b.get("/api/projects", headers=spoof).json()["projects"] == []


# --- 2. no session, no access -----------------------------------------------------------------------
def test_without_a_session_every_api_route_is_refused(victim):
    app, _, ids = victim
    anon = TestClient(app)
    open_ok = {"/api/auth/me"}
    leaked = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/") and not r.path.startswith("/api/admin"):
            if r.path in open_ok:
                continue
            for method in r.methods:
                resp = call(anon, method, r.path, ids)
                if resp.status_code != 401 or VICTIM_TEXT in resp.text:
                    leaked.append(f"{method} {r.path} -> {resp.status_code}")
    assert not leaked, "reachable without signing in: " + "; ".join(leaked)


@pytest.mark.parametrize("forge", ["wrong_key", "alg_none", "expired", "swapped_identity"])
def test_a_forged_or_stolen_looking_session_is_not_accepted(victim, forge):
    app, _, ids = victim
    if forge == "wrong_key":
        token = make_token(sub=A, key="an-attacker-guessed-secret-of-enough-length")
    elif forge == "alg_none":
        claims = jwt.decode(make_token(sub=A), options={"verify_signature": False})
        token = jwt.encode(claims, None, algorithm="none")
    elif forge == "expired":
        token = make_token(sub=A, exp_in=-60)
    else:   # take B's genuine token and swap the identity inside it, keeping B's signature
        head, body, sig = make_token(sub=B).split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        claims["sub"] = A
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        token = f"{head}.{body}.{sig}"
    c = TestClient(app)
    from web import auth
    c.cookies.set(auth.ACCESS_COOKIE, token)
    r = c.get(f"/api/projects/{ids['pid']}")
    assert r.status_code == 401 and VICTIM_TEXT not in r.text


# --- 3. the owner's console --------------------------------------------------------------------------
@pytest.fixture
def admin_app(app_parts, monkeypatch):
    monkeypatch.setattr("core.config.settings.admin_token", "the-real-admin-token-0123456789abcdef")
    app, _ = app_parts
    return create_app(engine=app.state.engine, queue=app.state.queue, auth=app.state.auth)


@pytest.mark.parametrize("how", ["none", "wrong_header", "in_the_url", "as_a_cookie"])
def test_the_admin_console_refuses_anything_but_the_token_in_its_header(admin_app, how):
    b = as_user(admin_app, B)                       # a normal signed-in account
    token = "the-real-admin-token-0123456789abcdef"
    kw = {"none": {}, "wrong_header": {"headers": {"X-Admin-Token": "nope"}},
          "in_the_url": {"params": {"token": token}}}.get(how, {})
    if how == "as_a_cookie":
        b.cookies.set("lattice_admin", token)
    assert b.get("/api/admin/users", **kw).status_code == 403


def test_the_admin_console_works_with_the_token_in_its_header(admin_app):
    r = TestClient(admin_app).get("/api/admin/users", headers={"X-Admin-Token": "the-real-admin-token-0123456789abcdef"})
    assert r.status_code == 200


def test_with_no_admin_token_configured_the_console_answers_only_this_machine(app_parts, monkeypatch):
    monkeypatch.setattr("core.config.settings.admin_token", "")
    app, _ = app_parts
    assert as_user(app, B).get("/api/admin/users").status_code == 403     # a remote client, signed in


# --- 4. the bill: limits can't be dodged ---------------------------------------------------------------
def test_firing_many_builds_at_once_cannot_beat_the_daily_limit(tmp_path):
    """30 requests racing each other for an allowance of 3: exactly 3 get through."""
    q = Quota(tmp_path, enforce=True, videos=3)
    wins, losses = [], []
    start = threading.Barrier(30)

    def go():
        start.wait()
        try:
            q.charge(A, "build")
            wins.append(1)
        except QuotaExceeded:
            losses.append(1)
    threads = [threading.Thread(target=go) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 3 and len(losses) == 27


def test_one_machine_cycling_through_many_accounts_is_still_limited(app_parts, monkeypatch):
    """The per-account allowance resets per account; the per-address limit does not care whose account."""
    monkeypatch.setattr("core.config.settings.rate_limit_writes_per_min", 5)
    app, _ = app_parts
    app2 = create_app(engine=app.state.engine, queue=app.state.queue, auth=app.state.auth)
    codes = [as_user(app2, f"acct-{i:02d}-0000-0000-0000-000000000000").post(
             "/api/projects", json={"topic": f"t{i}"}).status_code for i in range(10)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 5


# --- 5. inputs that would run up the bill or break things ------------------------------------------------
@pytest.mark.parametrize("path,body", [
    ("/api/projects", {"topic": "x" * 2_001}),
    ("/api/projects/{pid}/scenes/0/tweak", {"instruction": "x" * 1_001}),
    ("/api/projects/{pid}/scenes/0/narration", {"lines": ["x"] * 61}),
    ("/api/projects/{pid}/scenes/0/narration", {"lines": ["x" * 1_001]}),
    ("/api/projects/{pid}/scenes/insert", {"pos": 0, "title": "t" * 201, "intent": "i"}),
    ("/api/projects/{pid}/build", {"quality": "x" * 13}),
    ("/api/projects/{pid}/build", {"quality": "../../etc"}),
])
def test_oversized_or_malformed_fields_are_refused_before_any_work(victim, path, body):
    app, a, ids = victim
    r = a.post(path.replace("{pid}", ids["pid"]), json=body)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_a_huge_request_body_is_refused_whatever_field_it_hides_in(victim):
    app, a, ids = victim
    junk = "x" * (ratelimit.MAX_BODY + 1)
    # MakeVideo.prompt has no field limit of its own; the body cap still stops it
    r = a.post(f"/api/learn/threads/{ids['tid']}/video", json={"prompt": junk})
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    r = a.post("/api/projects", json={"topic": "ok", "padding": junk})
    assert r.status_code == 413


def test_a_huge_body_sent_without_a_length_header_is_still_refused(victim):
    app, a, ids = victim
    before = len(a.get("/api/projects").json()["projects"])

    def chunks():
        yield b'{"topic": "'
        for _ in range(100):
            yield b"x" * 1024
        yield b'"}'
    r = a.post("/api/projects", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 413)
    assert len(a.get("/api/projects").json()["projects"]) == before        # nothing was created


def test_a_lesson_message_may_still_carry_a_pasted_image(victim):
    assert ratelimit.body_limit_for("POST", "/api/learn/threads/abc/messages") == ratelimit.IMAGE_BODY
    assert ratelimit.body_limit_for("POST", "/api/learn/threads") == ratelimit.IMAGE_BODY
    assert ratelimit.body_limit_for("POST", "/api/learn/threads/abc/video") == ratelimit.MAX_BODY


# --- 6. reaching files that are not meant to be served -------------------------------------------------
@pytest.mark.parametrize("path", [
    "/static/../web/auth.py", "/static/..%2f..%2fbackend%2f.env", "/static/%2e%2e/%2e%2e/backend/.env",
    "/admin-assets/../../.env", "/admin-assets/..%2fauth.py", "/static/..%5c..%5cbackend%5c.env",
])
def test_static_paths_cannot_climb_out_to_code_or_secrets(victim, path):
    app, a, _ = victim
    r = a.get(path)
    assert r.status_code in (400, 404) or ("import " not in r.text and "LATTICE_" not in r.text)
    assert "SUPABASE" not in r.text and "def " not in r.text


@pytest.mark.parametrize("pid", ["..", "%2e%2e", "..%2f..%2fadmin", "%2e%2e%2fowners.json"])
def test_an_id_cannot_climb_out_of_the_data_folder(victim, pid):
    app, a, _ = victim
    r = a.get(f"/api/projects/{pid}")
    assert r.status_code in (404, 400, 405) and VICTIM_TEXT not in r.text


# --- 7. a malicious display name cannot run code in the owner's console ---------------------------------
def test_the_admin_console_escapes_everything_a_user_controls():
    """A Google display name is whatever the user typed. The admin page keeps the admin token in the
    browser, so any user field it shows must go through esc() before it becomes HTML."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "web" / "static" / "admin.js").read_text(encoding="utf-8").splitlines()
    field = re.compile(r"\b\w+\.(name|email|label|topic|agent|title|ip|model|detail|error|message|owner)\b")
    bad = []
    for i, line in enumerate(src, 1):
        for m in re.finditer(r"\$\{([^}]*)\}", line):
            if field.search(m.group(1)) and not re.search(r"\besc\(|encodeURIComponent", m.group(1)):
                bad.append(f"line {i}: ${{{m.group(1).strip()}}}")
        for m in re.finditer(r"\+\s*(\w+\.(?:name|email|label|topic|agent|title|ip|model|owner))\b(?!\s*\))", line):
            if "esc(" not in line[max(0, m.start() - 6):m.end() + 1]:
                bad.append(f"line {i}: + {m.group(1)}")
    assert not bad, "user-controlled text reaches the admin page unescaped: " + "; ".join(bad)
