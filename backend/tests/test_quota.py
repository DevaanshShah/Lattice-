"""Per-account limits (web/quota.py): videos, edits and model spend in a rolling 24 hours.

The rules are tested on `Quota` directly with a fake clock, then through the real app so the two
enforcement points are proved: the job queue (every spending job) and the POST guard (spend that
never goes through the queue).
"""
import json

import pytest
from fastapi.testclient import TestClient

from composition.scene_dag import VideoProject
from core import usage
from test_auth import SECRET, URL, make_token
from test_ownership import ChatClient, PlanEngine, A, B, save_project
from web import auth, jobs as jobs_mod
from web.app import create_app
from web.quota import EDIT, VIDEO, WINDOW_S, Quota, QuotaExceeded, category

UID = "user-1"


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


def make(tmp_path, clock, **kw):
    kw.setdefault("enforce", True)
    return Quota(tmp_path, now=clock, **kw)


# --- the rules ------------------------------------------------------------------------------
def test_a_video_over_the_limit_is_refused_with_when_it_frees_up(tmp_path, clock):
    q = make(tmp_path, clock, videos=2)
    q.charge(UID, "build")
    clock.t += 3600
    q.charge(UID, "deck-build")
    with pytest.raises(QuotaExceeded) as e:
        q.charge(UID, "learn-video")
    assert "all 2 videos" in e.value.message
    assert "23h" in e.value.message                  # the FIRST charge frees up first, 23h from now
    assert e.value.retry_after == WINDOW_S - 3600


def test_the_window_rolls_so_a_slot_frees_exactly_24h_after_use(tmp_path, clock):
    q = make(tmp_path, clock, videos=1)
    q.charge(UID, "build")
    clock.t += WINDOW_S - 1
    with pytest.raises(QuotaExceeded):
        q.charge(UID, "build")
    clock.t += 2
    q.charge(UID, "build")                           # no midnight reset to wait for, no timezone


def test_every_job_kind_is_limited_edits_by_their_own_cap(tmp_path, clock):
    q = make(tmp_path, clock, videos=1, edits=2)
    assert category("build") == category("deck-build") == category("learn-video") == VIDEO
    for kind in ("regenerate", "tweak", "narration", "insert", "some-future-kind"):
        assert category(kind) == EDIT                # a new kind is capped, never silently unlimited
    q.charge(UID, "tweak")
    q.charge(UID, "regenerate")
    with pytest.raises(QuotaExceeded) as e:
        q.charge(UID, "narration")
    assert "2 edits" in e.value.message
    q.charge(UID, "build")                           # edits never use up the video allowance


def test_accounts_are_counted_separately(tmp_path, clock):
    q = make(tmp_path, clock, videos=1)
    q.charge(UID, "build")
    q.charge("user-2", "build")
    with pytest.raises(QuotaExceeded):
        q.charge(UID, "build")


def test_a_restart_does_not_reset_the_count(tmp_path, clock):
    make(tmp_path, clock, videos=1).charge(UID, "build")
    with pytest.raises(QuotaExceeded):
        make(tmp_path, clock, videos=1).charge(UID, "build")


def test_a_damaged_file_does_not_stop_the_server(tmp_path, clock):
    (tmp_path / "admin").mkdir()
    (tmp_path / "admin" / "quota.json").write_text("{not json", encoding="utf-8")
    make(tmp_path, clock, videos=1).charge(UID, "build")


def test_a_failed_job_gives_its_slot_back(tmp_path, clock):
    q = make(tmp_path, clock, videos=1)
    receipt = q.charge(UID, "build")
    q.refund(UID, "build", receipt)
    q.charge(UID, "build")


def test_zero_turns_a_rule_off_and_exempt_accounts_are_never_limited(tmp_path, clock):
    q = make(tmp_path, clock, videos=0, edits=0, spend_usd=0)
    for _ in range(50):
        q.charge(UID, "build")
        q.charge(UID, "tweak")
    owner = make(tmp_path, clock, videos=1, exempt="Owner@Example.com, uid-9",
                 email_of=lambda uid: "owner@example.com" if uid == "u-owner" else "")
    for uid in ("u-owner", "uid-9"):                 # by email (any case) or by user id
        for _ in range(5):
            owner.charge(uid, "build")


def test_nothing_is_limited_without_sign_in_or_without_an_identity(tmp_path, clock):
    off = make(tmp_path, clock, enforce=False, videos=1)
    for _ in range(5):
        off.charge(UID, "build")
    on = make(tmp_path / "x", clock, videos=1)
    for _ in range(5):
        on.charge("", "build")                       # CLI / background work has no account


def test_spend_ceiling_stops_new_work_but_counts_only_this_account_and_window(
        tmp_path, clock, monkeypatch):
    rows = [{"ts": clock.t - 100, "event": "llm", "user": UID, "cost_usd": 0.6},
            {"ts": clock.t - 50, "event": "llm", "user": UID, "cost_usd": 0.5},
            {"ts": clock.t - 50, "event": "llm", "user": "someone-else", "cost_usd": 9.0},
            {"ts": clock.t - 50, "event": "build", "user": UID, "cost_usd": 9.0}]
    monkeypatch.setattr(usage, "read", lambda since=None: [r for r in rows if r["ts"] >= (since or 0)])
    q = make(tmp_path, clock, videos=5, spend_usd=1.0)
    with pytest.raises(QuotaExceeded):
        q.check_spend(UID)
    q.check_spend("someone-else-2")                  # nothing recorded for them
    clock.t += WINDOW_S                              # both rows fall out of the window
    q._spend_cache.clear()
    q.check_spend(UID)


def test_status_reports_use_and_when_a_slot_frees(tmp_path, clock):
    q = make(tmp_path, clock, videos=3, edits=0)
    q.charge(UID, "build")
    clock.t += 60
    s = q.status(UID)
    assert s["video"] == {"used": 1, "limit": 3, "free_in_s": WINDOW_S - 60}
    assert s["edit"]["limit"] is None
    assert make(tmp_path, clock, enforce=False).status(UID) == {"enforced": False}


# --- through the real app -------------------------------------------------------------------
class QuotaEngine(PlanEngine):
    """A build that just succeeds (or fails on demand), so only the quota is under test."""
    fail = False

    def check_build(self, pid, keep):
        return None

    def build(self, pid, keep=None, quality="preview", log=None, on_scene=None):
        if self.fail:
            raise RuntimeError("render crashed")
        return save_project(self, pid, "built")


def signed_in(app, uid):
    c = TestClient(app)
    c.cookies.set(auth.ACCESS_COOKIE, make_token(sub=uid))
    return c


@pytest.fixture
def parts(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    monkeypatch.setattr("core.config.settings.quota_videos_per_day", 2)
    monkeypatch.setattr("core.config.settings.quota_edits_per_day", 0)
    monkeypatch.setattr("core.config.settings.quota_spend_usd_per_day", 1.0)
    monkeypatch.setattr("core.config.settings.quota_exempt", "")
    usage.set_current(usage.Attribution())
    engine = QuotaEngine(root=tmp_path / "web", client=ChatClient())
    queue = jobs_mod.JobQueue(synchronous=True)
    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    return create_app(engine=engine, queue=queue, auth=auth.AuthService(config)), engine


def build(client, pid):
    return client.post(f"/api/projects/{pid}/build", json={})


def test_the_third_build_in_a_day_is_a_429_for_that_account_only(parts):
    app, _ = parts
    a, b = signed_in(app, A), signed_in(app, B)
    pids = [a.post("/api/projects", json={"topic": f"t{i}"}).json()["id"] for i in range(3)]
    assert build(a, pids[0]).status_code == 200
    assert build(a, pids[1]).status_code == 200
    r = build(a, pids[2])
    assert r.status_code == 429 and "all 2 videos" in r.json()["detail"]
    assert int(r.headers["Retry-After"]) > 0
    pid_b = b.post("/api/projects", json={"topic": "mine"}).json()["id"]
    assert build(b, pid_b).status_code == 200        # one account's limit is not everyone's


def test_a_refused_build_leaves_no_job_behind(parts):
    app, _ = parts
    a = signed_in(app, A)
    pids = [a.post("/api/projects", json={"topic": f"t{i}"}).json()["id"] for i in range(3)]
    for pid in pids[:2]:
        build(a, pid)
    queue = app.state.queue
    before = len(queue._jobs)
    assert build(a, pids[2]).status_code == 429
    assert len(queue._jobs) == before


def test_a_build_that_crashes_does_not_cost_the_user_a_try(parts):
    app, engine = parts
    a = signed_in(app, A)
    pid = a.post("/api/projects", json={"topic": "t"}).json()["id"]
    engine.fail = True
    for _ in range(4):                               # more crashes than the limit of 2
        assert build(a, pid).status_code == 200
    engine.fail = False
    assert build(a, pid).status_code == 200          # the allowance is intact


def test_quota_endpoint_shows_usage_to_the_signed_in_user(parts):
    app, _ = parts
    a = signed_in(app, A)
    pid = a.post("/api/projects", json={"topic": "t"}).json()["id"]
    build(a, pid)
    s = a.get("/api/quota").json()
    assert s["enforced"] and s["video"]["used"] == 1 and s["video"]["limit"] == 2
    assert TestClient(app).get("/api/quota").status_code == 401     # not public


def test_over_the_spend_ceiling_new_posts_are_refused_but_reading_and_signing_out_work(
        parts, monkeypatch):
    app, _ = parts
    a = signed_in(app, A)
    pid = a.post("/api/projects", json={"topic": "t"}).json()["id"]
    import time
    rows = [{"ts": time.time(), "event": "llm", "user": A, "cost_usd": 5.0}]
    monkeypatch.setattr(usage, "read", lambda since=None: rows)
    app.state.quota._spend_cache.clear()
    r = a.post("/api/learn/threads", json={"message": "why is the sky blue"})   # no queue involved
    assert r.status_code == 429
    assert a.get("/api/projects").status_code == 200
    assert a.get(f"/api/projects/{pid}").status_code == 200
    assert a.post("/auth/logout").status_code != 429
    other = signed_in(app, B)
    assert other.post("/api/learn/threads", json={"message": "hello"}).status_code == 200


def test_the_owner_can_be_exempted_by_email(parts, monkeypatch):
    app, _ = parts
    monkeypatch.setattr("core.config.settings.quota_exempt", "ADMIN@example.com")
    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    app2 = create_app(engine=parts[1], queue=jobs_mod.JobQueue(synchronous=True),
                      auth=auth.AuthService(config))
    from test_auth import USER
    monkeypatch.setitem(USER, "email", "admin@example.com")
    c = signed_in(app2, A)
    pid = c.post("/api/projects", json={"topic": "t"}).json()["id"]
    for _ in range(4):
        assert build(c, pid).status_code == 200


def test_without_sign_in_there_are_no_limits(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    monkeypatch.setattr("core.config.settings.quota_videos_per_day", 1)
    usage.set_current(usage.Attribution())
    engine = QuotaEngine(root=tmp_path / "web", client=ChatClient())
    app = create_app(engine=engine, queue=jobs_mod.JobQueue(synchronous=True),
                     auth=auth.AuthService(auth.AuthConfig(supabase_url="", anon_key="")))
    c = TestClient(app)
    pid = c.post("/api/projects", json={"topic": "t"}).json()["id"]
    for _ in range(4):
        assert build(c, pid).status_code == 200


# --- the global ceiling (every account together) --------------------------------------------
def spend_rows(monkeypatch, clock, rows):
    monkeypatch.setattr(usage, "read", lambda since=None: [
        {"ts": clock.t - 10, "event": "llm", **r} for r in rows])


def test_the_global_ceiling_blocks_every_account_even_one_that_has_spent_nothing(
        tmp_path, clock, monkeypatch):
    spend_rows(monkeypatch, clock, [{"user": "a", "cost_usd": 0.7}, {"user": "b", "cost_usd": 0.7},
                                    {"user": "", "cost_usd": 0.2}])         # 1.6 across all of them
    q = make(tmp_path, clock, videos=5, spend_usd=1.0, global_spend_usd=1.5)
    for uid in ("a", "b", "brand-new-account"):
        with pytest.raises(QuotaExceeded) as e:
            q.charge(uid, "build")
        assert "daily capacity" in e.value.message
    q.check_spend("")                                # no identity (CLI): never limited


def test_below_the_global_ceiling_only_the_per_account_rules_apply(tmp_path, clock, monkeypatch):
    spend_rows(monkeypatch, clock, [{"user": "a", "cost_usd": 0.4}, {"user": "b", "cost_usd": 0.4}])
    q = make(tmp_path, clock, videos=5, spend_usd=1.0, global_spend_usd=1.5)
    q.charge("a", "build")
    q.charge("c", "build")


def test_the_owner_keeps_working_when_the_service_is_at_capacity(tmp_path, clock, monkeypatch):
    spend_rows(monkeypatch, clock, [{"user": "a", "cost_usd": 50.0}])
    q = make(tmp_path, clock, videos=1, global_spend_usd=1.0, exempt="owner-1")
    q.charge("owner-1", "build")
    q.check_spend("owner-1")
    with pytest.raises(QuotaExceeded):
        q.charge("stranger", "build")


def test_capacity_returns_as_old_spend_leaves_the_window(tmp_path, clock, monkeypatch):
    rows = [{"ts": clock.t - 10, "event": "llm", "user": "a", "cost_usd": 5.0}]
    monkeypatch.setattr(usage, "read",
                        lambda since=None: [r for r in rows if r["ts"] >= (since or 0)])
    q = make(tmp_path, clock, global_spend_usd=1.0)
    with pytest.raises(QuotaExceeded):
        q.check_spend("x")
    clock.t += WINDOW_S
    q.check_spend("x")


def test_global_ceiling_zero_is_off(tmp_path, clock, monkeypatch):
    spend_rows(monkeypatch, clock, [{"user": "a", "cost_usd": 999.0}])
    make(tmp_path, clock, spend_usd=0, global_spend_usd=0).check_spend("x")


def test_over_the_global_ceiling_the_app_refuses_new_posts_for_everyone(parts, monkeypatch):
    app, _ = parts
    monkeypatch.setattr("core.config.settings.quota_global_spend_usd_per_day", 1.0)
    import time
    config = auth.AuthConfig(supabase_url=URL, anon_key="anon", jwt_secret=SECRET)
    app2 = create_app(engine=parts[1], queue=jobs_mod.JobQueue(synchronous=True),
                      auth=auth.AuthService(config))
    monkeypatch.setattr(usage, "read", lambda since=None: [
        {"ts": time.time(), "event": "llm", "user": "someone-else", "cost_usd": 9.0}])
    r = signed_in(app2, A).post("/api/learn/threads", json={"message": "hello"})
    assert r.status_code == 429 and "daily capacity" in r.json()["detail"]
    assert signed_in(app2, A).get("/api/projects").status_code == 200       # reading still works
