"""What a person sees when something fails (web/errors.py).

The bug that prompted this: the Download button opens the API address in a new tab. For a project with
no finished video the server answered with its error as JSON, and the browser showed
`{"detail":"no final video to export - build the project first"}` as the page. A person must get a
readable page; the UI's own fetch calls must keep getting JSON; and nothing the server knows about
itself (exceptions, paths, stack traces, the API schema, prompts, raw logs) may reach a browser.
"""
import html
import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from test_ownership import A, app_parts, as_user  # noqa: F401 — the real app with sign-in ON
from web import errors, jobs as jobs_mod
from web.app import create_app

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
FETCH = {"Accept": "*/*"}


def request_with(accept):
    return Request({"type": "http", "method": "GET", "path": "/x", "query_string": b"",
                    "headers": [(b"accept", accept.encode())]})


# --- the reported case ----------------------------------------------------------------------
def test_download_with_no_finished_video_shows_a_page_to_a_browser_not_json(app_parts):
    app, _ = app_parts
    a = as_user(app, A)
    pid = a.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    url = f"/api/projects/{pid}/download?subtitles=none&format=youtube"

    page = a.get(url, headers=BROWSER)
    assert page.status_code == 409
    assert page.headers["content-type"].startswith("text/html")
    assert "build the project first" in page.text                # the useful sentence survives
    assert '{"detail"' not in page.text and "Back to Lattice" in page.text

    ui = a.get(url, headers=FETCH)                                # what the UI's own code receives
    assert ui.status_code == 409 and ui.headers["content-type"].startswith("application/json")
    assert ui.json()["code"] == "not_ready" and "build the project first" in ui.json()["detail"]


def test_an_unknown_address_is_a_friendly_page_not_a_json_not_found(app_parts):
    app, _ = app_parts
    a = as_user(app, A)
    page = a.get("/definitely/not/here", headers=BROWSER)
    assert page.status_code == 404 and page.headers["content-type"].startswith("text/html")
    assert "couldn't find that" in html.unescape(page.text).lower() and '"detail"' not in page.text
    assert a.get("/definitely/not/here", headers=FETCH).json()["code"] == "not_found"


def test_a_signed_out_visitor_on_an_api_address_gets_a_sign_in_page(app_parts):
    app, _ = app_parts
    c = TestClient(app)
    page = c.get("/api/projects", headers=BROWSER)
    assert page.status_code == 401 and page.headers["content-type"].startswith("text/html")
    assert "Please sign in" in page.text and ">Sign in<" in page.text and '"detail"' not in page.text
    ui = c.get("/api/projects", headers=FETCH)
    assert ui.status_code == 401
    assert ui.json() == {"detail": "sign in required", "code": "sign_in_required"}    # the UI matches this string


def test_the_page_escapes_whatever_the_message_contains():
    page = errors.respond(request_with("text/html"), 409, "<script>alert(1)</script>").body.decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize("accept,html", [("text/html", True), ("TEXT/HTML,*/*", True), ("*/*", False),
                                         ("application/json", False), ("text/event-stream", False), ("", False)])
def test_only_a_request_for_a_page_gets_a_page(accept, html):
    assert errors.wants_html(request_with(accept)) is html


def test_the_limit_message_reaches_a_browser_as_a_page_too():
    r = errors.respond(request_with("text/html"), 429, "You've used all 5 videos. The next one is free in 3h 12m.",
                       headers={"Retry-After": "11520"})
    assert r.status_code == 429 and r.headers["retry-after"] == "11520"
    assert "3h 12m" in r.body.decode()


# --- nothing internal reaches a browser ---------------------------------------------------------
def test_a_crash_never_shows_the_exception_and_leaves_a_reference_in_the_log(app_parts, caplog):
    app, _ = app_parts

    @app.get("/api/_boom")
    def boom():
        raise RuntimeError("secret /srv/lattice/engine.py api_key=hunter2")

    a = TestClient(app, raise_server_exceptions=False)
    a.cookies.update(as_user(app, A).cookies)
    with caplog.at_level(logging.ERROR, logger="lattice.errors"):
        ui = a.get("/api/_boom", headers=FETCH)
        page = a.get("/api/_boom", headers=BROWSER)
    for body in (ui.text, page.text):
        assert "secret" not in body and "hunter2" not in body and "/srv" not in body and "Traceback" not in body
    assert ui.status_code == page.status_code == 500
    ref = ui.json()["ref"]
    assert ui.json()["code"] == "server_error" and len(ref) == 8
    assert "Reference:" in page.text                                 # a person can quote it
    logged = "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "") for r in caplog.records)
    assert ref in logged and "hunter2" in logged                    # the OWNER can still find the cause


def test_a_validation_error_is_one_sentence_not_the_models_internals(app_parts):
    app, _ = app_parts
    r = as_user(app, A).post("/api/projects", json={}, headers=FETCH)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert isinstance(r.json()["detail"], str) and "loc" not in r.text and "pydantic" not in r.text.lower()


@pytest.fixture
def make_app(app_parts, monkeypatch):
    def build(**settings):
        for k, v in settings.items():
            monkeypatch.setattr(f"core.config.settings.{k}", v)
        app, _ = app_parts
        return create_app(engine=app.state.engine, queue=app.state.queue, auth=app.state.auth)
    return build


def test_the_api_schema_and_docs_are_not_public(make_app):
    app = make_app()
    a = as_user(app, A)                       # a signed-in account, which is anyone with a Google account
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert a.get(path, headers=FETCH).status_code == 404, path


def test_the_docs_can_be_turned_on_for_local_development(make_app):
    a = as_user(make_app(api_docs=True), A)
    r = a.get("/openapi.json")
    assert r.status_code == 200 and "paths" in r.json()


# --- a failed build tells the user what happened, in words ----------------------------------------
RAW = ("RuntimeError: Manim scene search failed: docker: error during connect\n"
       "Traceback (most recent call last):\n  File \"/srv/lattice/composition/browser_video.py\", line 95")


def failed_job(raw=RAW):
    q = jobs_mod.JobQueue(synchronous=True)

    def run(job):
        raise RuntimeError(raw)
    return q.submit(run, kind="build", project_id="p1")


def test_a_failed_job_shows_users_a_sentence_and_keeps_the_trace_for_the_owner():
    job = failed_job()
    assert job.status == jobs_mod.FAILED
    public = job.to_dict()["error"]
    assert public == "We couldn't render one of the scenes. Please try again, or simplify the topic."
    assert "/srv" not in public and "Traceback" not in public
    assert "/srv/lattice" in job.to_dict(debug=True)["error"]       # the admin console still sees everything


@pytest.mark.parametrize("raw,fragment", [
    ("deadline exceeded after 3600s", "time limit"),
    ("Request timed out", "time limit"),
    ("openai.RateLimitError: 429 too many requests", "AI service"),
    ("APIConnectionError: connection error", "AI service"),
    ("ffmpeg exited with 1", "couldn't render"),
    ("KeyError: 'topic'", "Something went wrong"),
])
def test_job_failures_map_to_a_plain_reason(raw, fragment):
    assert fragment in errors.public_job_error(raw)


def test_nothing_in_a_job_with_no_error_is_invented():
    assert errors.public_job_error(None) is None and errors.public_job_error("") is None


def test_a_stopped_job_keeps_its_own_short_message():
    q = jobs_mod.JobQueue(synchronous=True)
    job = q.submit(lambda j: None, kind="build", project_id="p")
    job.cancel()
    assert job.to_dict()["status"] in ("done", "cancelled")          # finished-or-stopped jobs are not rewritten
    stopped = jobs_mod.Job(kind="build", project_id="p")
    stopped._mark_finished(jobs_mod.CANCELLED, error="stopped by request")
    assert stopped.to_dict()["error"] == "stopped by request"


def test_the_job_endpoint_gives_the_browser_the_plain_sentence(app_parts):
    app, queue = app_parts
    from core import usage
    usage.set_current(usage.Attribution(user=A))
    job = queue.submit(lambda j: (_ for _ in ()).throw(RuntimeError(RAW)), kind="build", project_id="p1")
    usage.set_current(usage.Attribution())
    body = as_user(app, A).get(f"/api/jobs/{job.id}").json()
    assert body["status"] == "failed" and "/srv" not in json.dumps(body) and "Traceback" not in json.dumps(body)


# --- the developer console is the owner's, not the visitors' --------------------------------------
def test_the_developer_console_is_off_by_default_and_says_so(app_parts):
    app, _ = app_parts
    a = as_user(app, A)
    pid = a.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    r = a.get(f"/api/projects/{pid}/scenes/0/source", headers=FETCH)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_the_raw_job_log_is_not_sent_to_users_unless_the_console_is_on(app_parts, monkeypatch):
    app, queue = app_parts
    from core import usage
    usage.set_current(usage.Attribution(user=A))
    job = queue.submit(lambda j: j.log("calling model gpt-4o at /srv/lattice with prompt ..."), kind="build", project_id="p1")
    usage.set_current(usage.Attribution())
    a = as_user(app, A)
    assert a.get(f"/api/jobs/{job.id}/events?cursor=0").json()["events"] == []
    assert "event: log" not in a.get(f"/api/jobs/{job.id}/stream").text
    monkeypatch.setattr("core.config.settings.dev_console", True)
    assert a.get(f"/api/jobs/{job.id}/events?cursor=0").json()["events"]
    assert "event: log" in a.get(f"/api/jobs/{job.id}/stream").text


def test_asking_for_a_scene_the_project_does_not_have_is_a_404_not_a_crash(app_parts):
    app, _ = app_parts
    a = as_user(app, A)
    pid = a.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    r = TestClient(app, raise_server_exceptions=False)
    r.cookies.update(a.cookies)
    got = r.get(f"/api/projects/{pid}/scenes/7/preview", headers=FETCH)
    assert got.status_code == 404 and got.json()["code"] == "not_found"
