"""The privacy policy and terms that Google's consent screen requires must be readable by anyone.

They are linked from the sign-in screen's publishing review, so a visitor (or a reviewer) opens them
BEFORE signing in. The deny-by-default gate must therefore let `/static/*.html` through.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from test_ownership import app_parts  # noqa: F401 — fixture: the real app with sign-in ON


def test_privacy_and_terms_are_public_even_with_sign_in_on(app_parts):
    app, _ = app_parts
    c = TestClient(app)                                   # no session at all
    assert c.get("/api/projects").status_code == 401      # the gate really is on
    for path, heading in (("/static/privacy.html", "Privacy Policy"),
                          ("/static/terms.html", "Terms of Service")):
        r = c.get(path)
        assert r.status_code == 200 and heading in r.text, path


def test_the_contact_placeholder_is_there_to_be_filled_in_at_deploy_time():
    from pathlib import Path
    for name in ("privacy.html", "terms.html"):
        text = (Path(__file__).parent.parent.parent / "frontend" / "static" / name).read_text(encoding="utf-8")
        assert "{{CONTACT}}" in text, name                # deploy replaces it with a real address


# --- link previews and the tab icon --------------------------------------------------------------
def test_the_page_has_an_icon_and_a_link_preview_with_an_absolute_image(app_parts, monkeypatch):
    monkeypatch.setattr("core.config.settings.public_url", "")       # a developer's .env must not decide this
    app, _ = app_parts
    c = TestClient(app)
    html = c.get("/").text
    assert 'rel="icon" href="/static/favicon.svg"' in html
    for tag in ('property="og:title"', 'property="og:description"', 'name="twitter:card"'):
        assert tag in html, tag
    assert 'property="og:image" content="http://testserver/static/og.png"' in html      # absolute, from the request
    assert c.get("/static/og.png").status_code == 200 and c.get("/static/favicon.svg").status_code == 200
    r = c.get("/favicon.ico", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/static/favicon.svg"


def test_the_preview_image_uses_the_public_address_when_one_is_set(app_parts, monkeypatch):
    monkeypatch.setattr("core.config.settings.public_url", "https://lattice.example.com/")
    app, _ = app_parts
    assert 'content="https://lattice.example.com/static/og.png"' in TestClient(app).get("/").text


def test_the_vercel_homepage_has_the_same_preview_and_its_files_exist():
    site = Path(__file__).parent.parent.parent / "deploy" / "vercel-site"
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'property="og:image" content="https://' in html and 'rel="icon"' in html
    assert (site / "og.png").exists() and (site / "favicon.svg").exists()
