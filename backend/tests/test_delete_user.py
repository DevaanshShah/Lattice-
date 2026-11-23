"""Deleting one account's data on request (scripts/delete_user.py), as the privacy policy promises.

Two accounts each own things. Deleting one must remove exactly that account's items, records and
counts, anonymize its ledger rows while keeping the cost figures, and leave the other account untouched.
"""
import json

import pytest

from core import storage, usage
from scripts import delete_user
from web.decks import DeckStore
from web.learn import ThreadStore
from web.ownership import DECK, THREAD, VIDEO, Ownership
from web.quota import Quota
from web.users import UserStore

GONE, KEPT = "uid-gone", "uid-kept"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.settings.out_dir", tmp_path)
    monkeypatch.setattr(delete_user, "server_running", lambda port: False)
    root = tmp_path / "web"
    users = UserStore(tmp_path)
    users.touch(GONE, email="gone@example.com", name="Gone", ip="1.2.3.4")
    users.touch(KEPT, email="kept@example.com", name="Kept")
    owners = Ownership(root, enforce=True)
    made = {}
    for uid, tag in ((GONE, "g"), (KEPT, "k")):
        for kind, folder in ((VIDEO, root / f"p{tag}"), (DECK, DeckStore(root).workspace(f"d{tag}")),
                             (THREAD, ThreadStore(root).workspace(f"t{tag}"))):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "data.json").write_text("{}", encoding="utf-8")
            owners.claim(kind, folder.name, uid)
            made[(uid, kind)] = folder
    q = Quota(tmp_path, enforce=True)
    q.charge(GONE, "build")
    q.charge(KEPT, "build")
    for uid in (GONE, KEPT):
        with usage.bind(usage.Attribution(user=uid)):
            usage.record("create", topic=f"secret topic of {uid}", ip="9.9.9.9")
            usage.record_llm("m", 10, 10, 0.25)
    return made, tmp_path


def rows():
    return [json.loads(x) for x in usage.ledger_path().read_text(encoding="utf-8").splitlines()]


def test_a_dry_run_changes_nothing(world, capsys):
    made, _ = world
    assert delete_user.main(["--email", "gone@example.com"]) == 0
    out = capsys.readouterr().out
    assert "Would delete" in out and "Nothing changed" in out
    assert all(p.exists() for p in made.values())
    assert any(r["user"] == GONE for r in rows())


def test_deleting_removes_exactly_that_accounts_data(world, capsys):
    made, root = world
    assert delete_user.main(["--email", "GONE@example.com", "--yes"]) == 0      # any case
    for kind in (VIDEO, DECK, THREAD):
        assert not made[(GONE, kind)].exists(), kind
        assert made[(KEPT, kind)].exists(), kind                                # the other account untouched
    owners = Ownership(root / "web", enforce=True)
    assert owners.owned_by(GONE) == {VIDEO: [], DECK: [], THREAD: []}
    assert all(len(v) == 1 for v in owners.owned_by(KEPT).values())
    users = UserStore(root)
    assert users.get(GONE) is None and users.get(KEPT) is not None
    q = json.loads((root / "admin" / "quota.json").read_text(encoding="utf-8"))["used"]
    assert GONE not in q and KEPT in q
    assert "Supabase" in capsys.readouterr().out                               # the manual last step is named


def test_the_ledger_keeps_the_costs_but_loses_the_person(world):
    delete_user.main(["--email", "gone@example.com", "--yes"])
    all_rows = rows()
    assert not any(r.get("user") == GONE for r in all_rows)
    anon = [r for r in all_rows if r.get("user") == delete_user.ANON]
    assert anon and not any("topic" in r or "ip" in r for r in anon)
    assert sum(r.get("cost_usd", 0) for r in anon) == pytest.approx(0.25)     # the spend still adds up
    kept = [r for r in all_rows if r.get("user") == KEPT]
    assert any(r.get("topic") == f"secret topic of {KEPT}" for r in kept)      # nobody else is rewritten


def test_an_unknown_account_is_reported_and_nothing_happens(world, capsys):
    made, _ = world
    assert delete_user.main(["--email", "nobody@example.com", "--yes"]) == 1
    assert all(p.exists() for p in made.values())


def test_it_refuses_while_a_server_is_running(world, monkeypatch, capsys):
    made, _ = world
    monkeypatch.setattr(delete_user, "server_running", lambda port: True)
    assert delete_user.main(["--email", "gone@example.com", "--yes"]) == 2
    assert "Stop it first" in capsys.readouterr().out and made[(GONE, VIDEO)].exists()


def test_object_storage_copies_are_deleted_too(world, monkeypatch):
    deleted = []
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "listing", lambda prefix: [{"key": prefix + "final.mp4"}])
    monkeypatch.setattr(storage, "delete", lambda key: deleted.append(key) or True)
    delete_user.main(["--id", GONE, "--yes"])
    assert sorted(deleted) == ["decks/dg/final.mp4", "learn/tg/final.mp4", "videos/pg/final.mp4"]
