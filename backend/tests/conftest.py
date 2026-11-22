"""Make the repo root importable so `from core... import ...` works under pytest,
regardless of where pytest is invoked from."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True, scope="session")
def isolate_out_dir(tmp_path_factory):
    """Keep the whole test run out of the real `out/`.

    The usage ledger and the user registry live there now, so a suite that submits ~100 fake jobs
    and spins up a dozen TestClients would otherwise write itself into the admin console as real
    users and real builds. Every test that needs a workspace already passes its own out_dir, so
    redirecting the default costs nothing.
    """
    from core.config import settings
    original = settings.out_dir
    settings.out_dir = tmp_path_factory.mktemp("lattice-out")
    yield
    settings.out_dir = original


@pytest.fixture(autouse=True)
def jev_stays_offline(monkeypatch):
    """A developer's `.env` may switch Jev on with a real key. Tests never call it: one that
    wants a Jev answer switches it on itself and supplies the answer."""
    from core.config import settings
    monkeypatch.setattr(settings, "jev_enabled", False)


@pytest.fixture(autouse=True)
def sign_in_stays_off(monkeypatch):
    """A developer's `.env` may hold real Supabase keys, which would put every `create_app()` in
    the suite behind the sign-in gate (and reach for the network). Tests that exercise sign-in
    build their own `AuthService` with a fake Supabase (tests/test_auth.py)."""
    from core.config import settings
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
