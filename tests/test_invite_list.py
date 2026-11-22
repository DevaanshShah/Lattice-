"""The invite list (LATTICE_AUTH_ALLOWED_EMAILS): who may sign in at all.

Closes the gap the per-account limits leave open: one person with many Google accounts. Checked at
sign-in AND on every request, so removing an email ends a live session, not just future sign-ins.
"""
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from test_auth import (USER, build, fake, is_cleared, make_token, set_cookies,  # noqa: F401
                       store)
from web import auth


def cfg(allowed):
    return auth.AuthConfig(supabase_url="https://p.supabase.co", anon_key="k", allowed_emails=allowed)


# --- the rule -------------------------------------------------------------------------------
def test_an_empty_list_lets_anyone_in():
    assert cfg("").allows("anyone@example.com")
    assert cfg("  ,  ").allows("")          # only blanks is still "no list"


@pytest.mark.parametrize("email,ok", [
    ("ada@example.com", True),
    ("ADA@Example.COM", True),               # case never matters
    ("grace@school.edu", True),              # a whole domain
    ("grace@sub.school.edu", False),         # but not a look-alike or subdomain
    ("evil@notschool.edu", False),
    ("evil@school.edu.evil.com", False),
    ("other@example.com", False),
    ("", False),                             # no email on the account: refused once a list exists
])
def test_entries_are_exact_emails_or_a_whole_domain(email, ok):
    assert cfg("Ada@example.com, @school.edu").allows(email) is ok


def test_settings_wire_through_to_the_config():
    class S:
        supabase_url, supabase_anon_key, supabase_jwt_secret = "https://p.supabase.co", "k", ""
        auth_required, public_url, auth_allowed_emails = True, "", "a@b.com"
    assert auth.AuthConfig.from_settings(S()).allows("a@b.com")
    assert not auth.AuthConfig.from_settings(S()).allows("c@d.com")


# --- through the app ------------------------------------------------------------------------
def sign_in(c, fake):
    r = c.get("/auth/login")
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    fake.challenge = q["code_challenge"]
    return c.get("/auth/callback", params={"code": "good-code"})


def test_an_invited_account_signs_in(fake, store, tmp_path):
    c = build(fake, store, tmp_path, allowed_emails=USER["email"])
    r = sign_in(c, fake)
    assert r.headers["location"] == "/"
    assert c.get("/api/whoami").json() == {"user": USER["id"]}


def test_an_uninvited_account_is_turned_away_with_a_reason_and_no_session(fake, store, tmp_path):
    c = build(fake, store, tmp_path, allowed_emails="someone-else@example.com")
    r = sign_in(c, fake)
    assert r.status_code == 302 and "invite" in r.headers["location"].lower() or \
        "invite%20list" in r.headers["location"]
    assert auth.ACCESS_COOKIE not in set_cookies(r) and auth.REFRESH_COOKIE not in set_cookies(r)
    assert "POST /logout" in fake.calls                    # the Supabase session is revoked too
    assert c.get("/api/whoami").status_code == 401


def test_removing_someone_from_the_list_ends_their_live_session(fake, store, tmp_path):
    c = build(fake, store, tmp_path, allowed_emails="someone-else@example.com")
    c.cookies.set(auth.ACCESS_COOKIE, make_token())        # a valid token from before they were removed
    r = c.get("/api/whoami")
    assert r.status_code == 401
    assert "max-age=0" in set_cookies(r)[auth.ACCESS_COOKIE].lower() or \
        "expires" in set_cookies(r)[auth.ACCESS_COOKIE].lower()


def test_no_list_means_open_as_before(fake, store, tmp_path):
    c = build(fake, store, tmp_path)
    c.cookies.set(auth.ACCESS_COOKIE, make_token())
    assert c.get("/api/whoami").json() == {"user": USER["id"]}
