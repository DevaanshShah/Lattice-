"""The privacy policy and terms that Google's consent screen requires must be readable by anyone.

They are linked from the sign-in screen's publishing review, so a visitor (or a reviewer) opens them
BEFORE signing in. The deny-by-default gate must therefore let `/static/*.html` through.
"""
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
        text = (Path(__file__).parent.parent / "frontend" / "static" / name).read_text(encoding="utf-8")
        assert "{{CONTACT}}" in text, name                # deploy replaces it with a real address
