"""Requests per minute per client address (web/ratelimit.py).

What has to hold: a burst is refused with a readable answer and Retry-After; one address's burst does not
touch another's; the limit can't be dodged by inventing X-Forwarded-For values; pages, static files and
/health are never limited; and a separately hosted UI can still read the refusal (CORS).
"""
import pytest
from fastapi.testclient import TestClient

from test_ownership import A, app_parts, as_user  # noqa: F401
from web import ratelimit
from web.app import create_app

BROWSER = {"Accept": "text/html"}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


# --- the counter --------------------------------------------------------------------------------
def test_the_window_allows_the_limit_then_refuses_then_recovers():
    clock = Clock()
    rl = ratelimit.RateLimiter({"write": 3}, now=clock)
    assert [rl.hit("write", "1.1.1.1") for _ in range(3)] == [None, None, None]
    wait = rl.hit("write", "1.1.1.1")
    assert wait == pytest.approx(60.0)
    clock.t += 30
    assert rl.hit("write", "1.1.1.1") == pytest.approx(30.0)      # refused hits are not counted
    clock.t += 30.01
    assert rl.hit("write", "1.1.1.1") is None                       # the oldest hit left the window


def test_addresses_and_buckets_are_counted_separately():
    rl = ratelimit.RateLimiter({"write": 1, "read": 1}, now=Clock())
    assert rl.hit("write", "a") is None and rl.hit("write", "a") is not None
    assert rl.hit("write", "b") is None                              # another address
    assert rl.hit("read", "a") is None                               # another bucket


def test_zero_turns_a_bucket_off():
    rl = ratelimit.RateLimiter({"auth": 0}, now=Clock())
    assert all(rl.hit("auth", "a") is None for _ in range(500))


def test_memory_stays_bounded_under_a_flood_of_new_addresses():
    rl = ratelimit.RateLimiter({"read": 5}, now=Clock(), max_keys=100)
    for i in range(5000):
        rl.hit("read", f"10.0.{i // 256}.{i % 256}")
    assert len(rl._hits) <= 101


@pytest.mark.parametrize("method,path,bucket", [
    ("GET", "/auth/login", "auth"), ("GET", "/auth/callback", "auth"), ("POST", "/auth/logout", None),
    ("POST", "/api/projects", "write"), ("DELETE", "/api/projects/x/scenes/0", "write"),
    ("GET", "/api/jobs/1/events", "read"), ("GET", "/", None), ("GET", "/static/app.js", None),
    ("GET", "/health", None), ("GET", "/admin", None),
])
def test_which_requests_count(method, path, bucket):
    assert ratelimit.bucket_for(method, path) == bucket


def test_the_address_is_the_one_the_proxy_wrote_not_the_one_the_client_claims():
    scope = {"headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.7")], "client": ("127.0.0.1", 5000)}
    assert ratelimit.client_address(scope) == "203.0.113.7"
    assert ratelimit.client_address({"headers": [], "client": ("198.51.100.2", 1)}) == "198.51.100.2"


# --- through the real app -----------------------------------------------------------------------
@pytest.fixture
def limited(app_parts, monkeypatch):
    def build(**limits):
        for k, v in limits.items():
            monkeypatch.setattr(f"core.config.settings.rate_limit_{k}_per_min", v)
        app, _ = app_parts
        return create_app(engine=app.state.engine, queue=app.state.queue, auth=app.state.auth)
    return build


def test_a_burst_of_sign_in_attempts_is_refused_with_a_readable_answer(limited):
    c = TestClient(limited(auth=3), follow_redirects=False)
    for _ in range(3):
        assert c.get("/auth/login").status_code != 429
    page = c.get("/auth/login", headers=BROWSER)
    assert page.status_code == 429 and page.headers["content-type"].startswith("text/html")
    assert "Too many requests" in page.text and int(page.headers["retry-after"]) >= 1
    ui = c.get("/auth/login", headers={"Accept": "*/*"})
    assert ui.json()["code"] == "limit_reached"


def test_inventing_forwarded_addresses_does_not_dodge_the_limit(limited):
    c = TestClient(limited(auth=2), follow_redirects=False)
    codes = [c.get("/auth/login", headers={"X-Forwarded-For": f"10.9.8.{i}, 203.0.113.7"}).status_code
             for i in range(5)]
    assert codes[:2] != [429, 429] and codes[2:] == [429, 429, 429]


def test_one_address_flooding_does_not_block_another(limited):
    c = TestClient(limited(auth=1), follow_redirects=False)
    c.get("/auth/login", headers={"X-Forwarded-For": "203.0.113.1"})
    assert c.get("/auth/login", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    assert c.get("/auth/login", headers={"X-Forwarded-For": "203.0.113.2"}).status_code != 429


def test_pages_static_files_and_health_are_never_limited(limited):
    c = TestClient(limited(auth=1, writes=1, reads=1))
    for _ in range(20):
        assert c.get("/health").status_code == 200
        assert c.get("/static/feedback.js").status_code == 200


def test_writes_are_limited_before_the_session_check(limited):
    a = as_user(limited(writes=2), A)
    a.post("/api/projects", json={"topic": "a"})
    a.post("/api/projects", json={"topic": "b"})
    assert a.post("/api/projects", json={"topic": "c"}).status_code == 429


def test_a_separately_hosted_ui_can_read_the_refusal(limited, monkeypatch):
    monkeypatch.setattr("core.config.settings.frontend_origins", "https://app.example.com")
    c = TestClient(limited(reads=1))
    c.get("/api/projects", headers={"Origin": "https://app.example.com"})
    r = c.get("/api/projects", headers={"Origin": "https://app.example.com"})
    assert r.status_code == 429 and r.headers["access-control-allow-origin"] == "https://app.example.com"
