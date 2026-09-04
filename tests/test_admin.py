"""The admin console: the usage ledger, attribution across worker threads, the rollups, and the
API's access gate. No Docker, no model, no network — the ledger is a file and the rollups are
pure functions, so all of it is directly testable."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import usage
from web import admin, users as users_mod


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    """Point the ledger + user registry at a temp dir, and reset the read cache between tests."""
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    usage._read_cache.update(key=None, rows=[])
    usage.set_current(usage.Attribution())
    return tmp_path


# --- ledger + attribution ---------------------------------------------------------------------
def test_record_writes_attributed_line(ledger):
    usage.set_current(usage.Attribution(user="u1", project="p1", kind="build", surface="video"))
    usage.record_llm("m", 100, 20, 0.5)
    rows = usage.read()
    assert len(rows) == 1
    assert rows[0]["user"] == "u1" and rows[0]["project"] == "p1" and rows[0]["surface"] == "video"
    assert rows[0]["prompt_tokens"] == 100 and rows[0]["cost_usd"] == 0.5


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(usage, "ledger_path", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    usage.record("llm", model="m")          # telemetry failure must not reach the caller


def test_read_skips_a_torn_line(ledger):
    usage.record_llm("m", 1, 1, 0.1)
    with usage.ledger_path().open("a", encoding="utf-8") as fh:
        fh.write('{"event": "llm", "cost_usd": ')      # killed mid-append
    usage._read_cache.update(key=None, rows=[])
    assert len(usage.read()) == 1


def test_attribution_survives_the_render_fanout(ledger):
    """The real failure mode this guards: scene builds run on a pool, and a worker thread starts
    with an EMPTY context — without carry() every scene's model calls would be unattributed."""
    from composition.pool import run_bounded

    usage.set_current(usage.Attribution(user="u9", project="p9", surface="video"))
    seen = []
    run_bounded([1, 2, 3], lambda item, i: seen.append(usage.current().user), cap=3)
    assert seen == ["u9", "u9", "u9"]


def test_job_queue_attributes_and_records(ledger):
    from web import jobs as jobs_mod

    usage.set_current(usage.Attribution(user="u2"))
    q = jobs_mod.JobQueue(synchronous=True)
    inside = {}
    job = q.submit(lambda j: inside.update(user=usage.current().user,
                                           kind=usage.current().kind,
                                           project=usage.current().project),
                   kind="build", project_id="pX")
    assert inside == {"user": "u2", "kind": "build", "project": "pX"}
    assert job.user == "u2" and job.to_dict()["user"] == "u2"
    rows = [r for r in usage.read() if r["event"] == "job"]
    assert len(rows) == 1 and rows[0]["status"] == "done" and rows[0]["user"] == "u2"


def test_failed_job_is_recorded_as_failed(ledger):
    from web import jobs as jobs_mod

    q = jobs_mod.JobQueue(synchronous=True)

    def boom(_job):
        raise ValueError("nope")

    q.submit(boom, kind="build", project_id="pY")
    rows = [r for r in usage.read() if r["event"] == "job"]
    assert rows[0]["status"] == "failed"


# --- rollups (pure) ---------------------------------------------------------------------------
NOW = 1_700_000_000.0


def _rows():
    return [
        {"ts": NOW - 10, "event": "create", "user": "a", "project": "p1", "surface": "video",
         "topic": "Fourier"},
        {"ts": NOW - 9, "event": "llm", "user": "a", "project": "p1", "surface": "video",
         "model": "m1", "prompt_tokens": 1000, "completion_tokens": 200, "cost_usd": 0.02,
         "priced": True},
        {"ts": NOW - 8, "event": "llm", "user": "a", "project": "p1", "surface": "video",
         "model": "m2", "prompt_tokens": 500, "completion_tokens": 100, "cost_usd": 0.0,
         "priced": False},
        {"ts": NOW - 7, "event": "job", "user": "a", "project": "p1", "kind": "build",
         "status": "done", "seconds": 120, "scenes": 4},
        {"ts": NOW - 6, "event": "create", "user": "b", "project": "d1", "surface": "deck",
         "topic": "Eigenvectors"},
        {"ts": NOW - 5, "event": "job", "user": "b", "project": "d1", "kind": "deck-build",
         "status": "failed", "seconds": 9},
    ]


def _users():
    return [{"id": "a", "first_seen": NOW - 100, "last_seen": NOW - 5, "requests": 12, "label": ""},
            {"id": "b", "first_seen": NOW - 50, "last_seen": NOW - 4, "requests": 3, "label": "Ravi"}]


def test_summarize_counts_users_content_jobs_and_cost():
    s = admin.summarize(_rows(), users=_users(),
                        videos=[{"id": "p1", "topic": "Fourier", "scenes": 4, "built": True}],
                        decks=[{"id": "d1", "ready": False}], threads=[], jobs_live=[], now=NOW)
    assert s["users"]["total"] == 2 and s["users"]["active_24h"] == 2
    assert s["content"]["videos"] == 1 and s["content"]["decks"] == 1 and s["content"]["ready"] == 1
    assert s["jobs"]["done"] == 1 and s["jobs"]["failed"] == 1 and s["jobs"]["success_rate"] == 0.5
    assert s["jobs"]["avg_seconds"] == 120.0
    assert s["cost"]["total"] == 0.02 and s["cost"]["calls"] == 2
    assert s["cost"]["prompt_tokens"] == 1500
    # the honesty counter: one call ran on a model with no price, so the total is a floor
    assert s["cost"]["unpriced_calls"] == 1


def test_summarize_per_video_uses_finished_builds_not_zero():
    s = admin.summarize(_rows(), users=_users(), videos=[], decks=[], threads=[], jobs_live=[], now=NOW)
    assert s["cost"]["per_video"] == 0.02        # 1 finished build, $0.02
    empty = admin.summarize([], users=[], videos=[], decks=[], threads=[], jobs_live=[], now=NOW)
    assert empty["cost"]["per_video"] == 0.0     # and never divides by zero


def test_per_user_splits_spend_and_progress():
    rows = admin.per_user(_rows(), users=_users(),
                          jobs_live=[{"user": "b", "status": "running"}], now=NOW)
    by_id = {r["id"]: r for r in rows}
    assert by_id["a"]["cost"] == 0.02 and by_id["a"]["videos"] == 1 and by_id["a"]["done"] == 1
    assert by_id["a"]["render_minutes"] == 2.0
    assert by_id["b"]["decks"] == 1 and by_id["b"]["failed"] == 1 and by_id["b"]["running"] == 1
    assert by_id["b"]["label"] == "Ravi"
    assert rows[0]["id"] == "a"                  # sorted by spend


def test_per_user_keeps_a_visitor_who_spent_nothing():
    rows = admin.per_user([], users=[{"id": "z", "first_seen": NOW, "last_seen": NOW, "requests": 1}],
                          jobs_live=[], now=NOW)
    assert len(rows) == 1 and rows[0]["cost"] == 0 and rows[0]["videos"] == 0


def test_daily_costs_covers_every_day_including_empty_ones():
    d = admin.daily_costs(_rows(), days=5, now=NOW)
    assert len(d) == 5
    assert sum(b["cost"] for b in d) == 0.02
    assert d[-1]["jobs"] == 2 and d[-1]["failed"] == 1


def test_by_model_and_surface_split_spend():
    m = {r["model"]: r for r in admin.by_model(_rows())}
    assert m["m1"]["cost"] == 0.02 and m["m2"]["priced"] is False
    s = {r["surface"]: r for r in admin.by_surface(_rows())}
    assert s["video"]["calls"] == 2


def test_owner_map_prefers_the_create_row():
    rows = [{"event": "llm", "project": "p1", "user": "wrong", "ts": 1},
            {"event": "create", "project": "p1", "user": "right", "ts": 2}]
    assert admin.owner_map(rows)["p1"] == "right"


# --- the API + its gate -------------------------------------------------------------------------
class FakeEngine:
    root = "."

    def list_projects(self):
        return [{"id": "p1", "topic": "Fourier", "scenes": 2, "built": True}]

    def load(self, pid):
        raise KeyError(pid)          # forces the "half-written project still gets a row" path


class FakeQueue:
    def list(self, **_kw):
        return []


@pytest.fixture
def admin_client(ledger, monkeypatch):
    monkeypatch.setattr("core.config.settings.admin_token", "s3cret")
    monkeypatch.setattr(usage, "provider_credits", lambda **kw: None)
    store = users_mod.UserStore(ledger)
    store.touch("u1", ip="1.2.3.4", agent="pytest")
    app = FastAPI()
    admin.register(app, FakeEngine(), FakeQueue(), deck_store=None, learn_store=None,
                   user_store=store)
    return TestClient(app)


AUTH = {"X-Admin-Token": "s3cret"}


def test_admin_api_requires_the_token(admin_client):
    assert admin_client.get("/api/admin/summary").status_code == 403
    assert admin_client.get("/api/admin/users").status_code == 403
    assert admin_client.get("/api/admin/summary", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert admin_client.get("/api/admin/summary", headers=AUTH).status_code == 200


def test_admin_endpoints_return_the_dashboard_payload(admin_client, ledger):
    usage.set_current(usage.Attribution(user="u1", project="p1", surface="video"))
    usage.record("create", topic="Fourier")
    usage.record_llm("m1", 10, 5, 0.01)

    s = admin_client.get("/api/admin/summary", headers=AUTH).json()
    assert s["users"]["total"] == 1 and s["cost"]["total"] == 0.01
    assert s["config"]["token_protected"] is True

    u = admin_client.get("/api/admin/users", headers=AUTH).json()["users"]
    assert u[0]["id"] == "u1" and u[0]["cost"] == 0.01

    p = admin_client.get("/api/admin/projects", headers=AUTH).json()["projects"]
    assert p[0]["id"] == "p1" and p[0]["owner"] == "u1" and p[0]["cost"] == 0.01

    d = admin_client.get("/api/admin/users/u1", headers=AUTH).json()
    assert d["user"]["id"] == "u1" and d["projects"][0]["id"] == "p1"

    j = admin_client.get("/api/admin/jobs", headers=AUTH).json()
    assert j["live"] == [] and isinstance(j["finished"], list)

    c = admin_client.get("/api/admin/costs?days=3", headers=AUTH).json()
    assert len(c["daily"]) == 3 and c["models"][0]["model"] == "m1"

    e = admin_client.get("/api/admin/events?event=llm", headers=AUTH).json()
    assert e["events"][0]["model"] == "m1"


def test_admin_label_round_trips(admin_client):
    r = admin_client.post("/api/admin/users/u1/label", json={"label": "Ravi"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["label"] == "Ravi"
    assert admin_client.get("/api/admin/users", headers=AUTH).json()["users"][0]["label"] == "Ravi"
    assert admin_client.post("/api/admin/users/nope/label", json={"label": "x"},
                             headers=AUTH).status_code == 404


def test_admin_page_is_reachable_without_the_token(admin_client):
    """The shell has to load so there is somewhere to type the token; it holds no data itself."""
    assert admin_client.get("/admin").status_code == 200


# --- identity -----------------------------------------------------------------------------------
def test_user_store_persists_and_debounces(tmp_path):
    store = users_mod.UserStore(tmp_path)
    store.touch("u1", ip="9.9.9.9", agent="a")
    assert (tmp_path / "admin" / "users.json").exists()      # a NEW user flushes immediately
    store.touch("u1")
    store.flush()
    again = users_mod.UserStore(tmp_path)
    rec = again.get("u1")
    assert rec.requests == 2 and rec.ip == "9.9.9.9"


def test_user_store_survives_a_corrupt_registry(tmp_path):
    (tmp_path / "admin").mkdir(parents=True)
    (tmp_path / "admin" / "users.json").write_text("{not json", encoding="utf-8")
    assert users_mod.UserStore(tmp_path).all() == []


def test_requests_get_an_identity_and_infra_pings_do_not(ledger, monkeypatch):
    """A cookie is minted for real product traffic; /health and /api/admin never invent a user
    (otherwise a uptime probe would read as thousands of customers)."""
    from web import jobs as jobs_mod
    from web.app import create_app

    class Eng:
        root = ledger

        def recover_all(self):
            return []

        def list_projects(self):
            return []

    app = create_app(engine=Eng(), queue=jobs_mod.JobQueue(synchronous=True))
    with TestClient(app) as c:
        c.get("/health")
        assert users_mod.COOKIE not in c.cookies
        c.get("/api/projects")
        assert c.cookies.get(users_mod.COOKIE)


def test_ledger_rotates_when_huge(ledger, monkeypatch):
    monkeypatch.setattr(usage, "MAX_LEDGER_BYTES", 200)
    for _ in range(12):
        usage.record_llm("m", 1, 1, 0.001)
    assert usage.ledger_path().with_name("usage.jsonl.1").exists()


# --- spend must be attributable to the thing it paid for -------------------------------------
def test_planning_spend_lands_on_the_project_it_created(ledger, monkeypatch):
    """The bug this pins: the id used to be minted AFTER the planning call, so the outline/deck
    plan — which is most of what a video costs — was written to the ledger with project="" and the
    admin console showed every project as costing $0."""
    from core.schemas.outline import Outline, OutlineItem
    from web import jobs as jobs_mod
    from web.app import create_app

    class Eng:
        root = ledger

        def recover_all(self):
            return []

        def plan(self, topic, *, max_scenes=None, target_seconds=None, pid=None, log=None):
            usage.record_llm("m", 100, 10, 0.002)          # the call the planner would make
            outline = Outline(topic=topic, items=[OutlineItem(title="A", intent="x")])
            from composition.scene_dag import VideoProject
            return pid or "generated", VideoProject.from_outline(outline)

    app = create_app(engine=Eng(), queue=jobs_mod.JobQueue(synchronous=True))
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"topic": "Fourier"}).json()["id"]

    llm = [r for r in usage.read() if r["event"] == "llm"]
    assert llm[0]["project"] == pid, "planning spend must be billed to the project it created"
    assert llm[0]["surface"] == "video" and llm[0]["user"]


def test_deck_planning_spend_lands_on_the_deck(ledger, monkeypatch):
    from web import jobs as jobs_mod
    from web.app import create_app

    class FakeDeck:
        title = "T"
        slides = []

    def fake_plan_deck(topic, client=None):
        usage.record_llm("m", 100, 10, 0.0013)
        return FakeDeck()

    monkeypatch.setattr("planner.slide_plan.plan_deck", fake_plan_deck)

    class Eng:
        root = ledger

        def recover_all(self):
            return []

        def _client_or_default(self):
            return object()

    app = create_app(engine=Eng(), queue=jobs_mod.JobQueue(synchronous=True))
    with TestClient(app) as c:
        did = c.post("/api/decks", json={"topic": "gradient descent"}).json()["id"]

    llm = [r for r in usage.read() if r["event"] == "llm"]
    assert llm[0]["project"] == did and llm[0]["surface"] == "deck"
