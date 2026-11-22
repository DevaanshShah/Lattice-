"""Each account sees only what it made (web/ownership.py), across videos, decks, lessons and jobs.

Two signed-in users, A and B, against the real app with sign-in on. B must get a 404 for anything A
made: the same answer as a missing id, so ids can't be probed. With sign-in off, nothing changes.
"""
import json
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from composition.scene_dag import VideoProject
from core import usage
from test_auth import SECRET, URL, make_token
from web import auth, jobs as jobs_mod
from web.app import create_app
from web.engine import Engine
from web.ownership import DECK, THREAD, VIDEO, Ownership

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"


class ChatClient:
    """The Learn turn's one model call: a plain answer, no video offer."""

    def chat(self, messages, **k):
        return json.dumps({"answer": "Because.", "offer": False, "offer_label": "", "video_prompt": ""})


def save_project(engine, pid, topic):
    (engine.root / pid).mkdir(parents=True, exist_ok=True)
    project = VideoProject(topic=topic)
    engine.save(pid, project)
    return project


class PlanEngine(Engine):
    """Planning writes a bare project instead of calling a model."""

    def plan(self, topic, *, pid=None, **k):
        return pid, save_project(self, pid, topic)


@dataclass
class FakeDeck:
    title: str
    slides: list = field(default_factory=list)


@pytest.fixture
def app_parts(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    monkeypatch.setattr("planner.slide_plan.plan_deck", lambda topic, **k: FakeDeck(title=topic))
    usage.set_current(usage.Attribution())
    engine = PlanEngine(root=tmp_path / "web", client=ChatClient())
    queue = jobs_mod.JobQueue(synchronous=True)
    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    app = create_app(engine=engine, queue=queue, auth=auth.AuthService(config))
    return app, queue


def as_user(app, uid) -> TestClient:
    c = TestClient(app)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(sub=uid))
    return c


def test_videos_are_private_to_their_creator(app_parts):
    app, _ = app_parts
    a, b = as_user(app, A), as_user(app, B)
    pid = a.post("/api/projects", json={"topic": "TCP"}).json()["id"]

    assert [p["id"] for p in a.get("/api/projects").json()["projects"]] == [pid]
    assert a.get(f"/api/projects/{pid}").status_code == 200
    assert b.get("/api/projects").json()["projects"] == []
    for path in (f"/api/projects/{pid}", f"/api/projects/{pid}/final", f"/api/projects/{pid}/script",
                 f"/api/projects/{pid}/download", f"/api/projects/{pid}/scenes/0/preview"):
        r = b.get(path)
        assert r.status_code == 404 and r.json()["detail"] == f"no project {pid!r}", path
    assert b.post(f"/api/projects/{pid}/build", json={}).status_code == 404
    assert b.delete(f"/api/projects/{pid}/scenes/0").status_code == 404


def test_someone_elses_item_looks_exactly_like_a_missing_one(app_parts):
    app, _ = app_parts
    a, b = as_user(app, A), as_user(app, B)
    pid = a.post("/api/projects", json={"topic": "TCP"}).json()["id"]
    theirs, missing = b.get(f"/api/projects/{pid}"), b.get("/api/projects/zzzzzzzz")
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["detail"].replace(pid, "X") == missing.json()["detail"].replace("zzzzzzzz", "X")


def test_jobs_belong_to_whoever_queued_them(app_parts):
    app, queue = app_parts
    usage.set_current(usage.Attribution(user=A))
    job = queue.submit(lambda j: None, kind="build", project_id="p1")
    usage.set_current(usage.Attribution())
    a, b = as_user(app, A), as_user(app, B)
    for path in (f"/api/jobs/{job.id}", f"/api/jobs/{job.id}/events", f"/api/jobs/{job.id}/stream"):
        assert a.get(path).status_code == 200, path
        assert b.get(path).status_code == 404, path
    assert b.post(f"/api/jobs/{job.id}/cancel").status_code == 404


def test_decks_are_private_to_their_creator(app_parts):
    app, _ = app_parts
    a, b = as_user(app, A), as_user(app, B)
    did = a.post("/api/decks", json={"topic": "Fourier"}).json()["id"]
    assert [d["id"] for d in a.get("/api/decks").json()["decks"]] == [did]
    assert b.get("/api/decks").json()["decks"] == []
    assert b.get(f"/api/decks/{did}").status_code == 404
    assert b.get(f"/api/decks/{did}/video").status_code == 404
    assert b.post(f"/api/decks/{did}/build", json={}).status_code == 404


def test_lesson_threads_are_private_to_their_creator(app_parts):
    app, _ = app_parts
    a, b = as_user(app, A), as_user(app, B)
    tid = a.post("/api/learn/threads", json={"message": "why is the sky blue"}).json()["id"]
    assert [t["id"] for t in a.get("/api/learn/threads").json()["threads"]] == [tid]
    assert a.post(f"/api/learn/threads/{tid}/messages", json={"message": "more"}).status_code == 200
    assert b.get("/api/learn/threads").json()["threads"] == []
    assert b.get(f"/api/learn/threads/{tid}").status_code == 404
    assert b.post(f"/api/learn/threads/{tid}/messages", json={"message": "hi"}).status_code == 404
    assert b.post(f"/api/learn/threads/{tid}/video", json={"prompt": "x"}).status_code == 404
    assert b.get(f"/api/learn/threads/{tid}/video/m1").status_code == 404


def test_items_with_no_owner_are_hidden_once_sign_in_is_on(app_parts):
    """Made before accounts existed: nobody's, so nobody's list, until claim_unowned hands them out."""
    app, _ = app_parts
    engine = app.state.engine
    save_project(engine, "old00001", "legacy")
    assert as_user(app, A).get("/api/projects").json()["projects"] == []
    assert as_user(app, A).get("/api/projects/old00001").status_code == 404


def test_without_sign_in_everything_stays_shared(tmp_path):
    owners = Ownership(tmp_path, enforce=False)
    assert owners.can_access(VIDEO, "anything", "")
    assert owners.visible(DECK, [{"id": "x"}]) == [{"id": "x"}]


def test_ownership_survives_a_restart(tmp_path):
    Ownership(tmp_path, enforce=True).claim(THREAD, "t1", A)
    again = Ownership(tmp_path, enforce=True)
    assert again.owner(THREAD, "t1") == A
    assert again.can_access(THREAD, "t1", A) and not again.can_access(THREAD, "t1", B)


def test_claim_unowned_hands_legacy_items_to_one_account(tmp_path, monkeypatch, capsys):
    from scripts import claim_unowned
    from web.users import UserStore

    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    UserStore(tmp_path).touch(A, email="ada@example.com")
    engine = Engine(root=tmp_path / "web", client=object())
    save_project(engine, "old00001", "legacy")
    save_project(engine, "new00001", "someone's")
    Ownership(engine.root, enforce=True).claim(VIDEO, "new00001", B)

    assert claim_unowned.main(["--email", "ADA@example.com", "--dry-run"]) == 0
    assert Ownership(engine.root, enforce=True).owner(VIDEO, "old00001") is None   # dry run: no change

    assert claim_unowned.main(["--email", "ada@example.com"]) == 0
    owners = Ownership(engine.root, enforce=True)
    assert owners.owner(VIDEO, "old00001") == A
    assert owners.owner(VIDEO, "new00001") == B                                   # owned stays put
    assert claim_unowned.main(["--email", "nobody@example.com"]) == 1


def test_two_processes_writing_owners_never_lose_each_others_claims(tmp_path):
    """The server and scripts.claim_unowned share the file. Neither may overwrite the other with a
    stale copy, and the server must see the script's claims without a restart."""
    server = Ownership(tmp_path, enforce=True)
    script = Ownership(tmp_path, enforce=True)
    script.assign_unowned(VIDEO, ["old1", "old2"], A)
    assert server.owner(VIDEO, "old1") == A           # seen live, no restart
    server.claim(VIDEO, "new1", B)                    # a later write from the server's side...
    fresh = Ownership(tmp_path, enforce=True)
    assert {fresh.owner(VIDEO, i) for i in ("old1", "old2")} == {A}   # ...kept the migration
    assert fresh.owner(VIDEO, "new1") == B
