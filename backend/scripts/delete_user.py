"""Delete one account's data, as the privacy policy promises: run it when someone asks.

    python -m scripts.delete_user --email someone@gmail.com          # shows what would be deleted
    python -m scripts.delete_user --email someone@gmail.com --yes    # deletes it

Stop the server first (`sudo systemctl stop lattice`): the running app keeps the account list and the
daily-limit counts in memory and would write them back. The script refuses while a server answers on
--port, unless you pass --force.

What goes:
  - every video project, slide deck and lesson thread the account owns (folders, and R2 copies if any)
  - the ownership rows for them, the account record, the daily-limit counts
  - in the usage ledger, the account id becomes "deleted-user" and any text it typed (topics, titles,
    prompts) is removed. The cost figures stay, so the spend history still adds up.
What does not: the Google sign-in itself, which lives in Supabase. The script tells you where to remove it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from core.config import settings
from core.console import enable_utf8

ANON = "deleted-user"
PRIVATE_FIELDS = ("topic", "title", "prompt", "message", "text", "email", "name", "ip", "agent")


def server_running(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        return True
    except Exception:       # noqa: BLE001
        return False


def size_of(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def anonymize_ledger(uid: str, *, dry_run: bool) -> int:
    """Rewrite the usage ledger (and its rotated copy) with this account's rows anonymized."""
    from core import usage
    changed = 0
    base = usage.ledger_path()
    for path in (base, base.with_name(base.name + ".1")):
        if not path.exists():
            continue
        out, hit = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                out.append(line)
                continue
            if row.get("user") == uid:
                hit += 1
                row["user"] = ANON
                for k in PRIVATE_FIELDS:
                    row.pop(k, None)
                line = json.dumps(row, ensure_ascii=False)
            out.append(line)
        changed += hit
        if hit and not dry_run:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
            tmp.replace(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    enable_utf8()
    ap = argparse.ArgumentParser(prog="delete_user", description=__doc__.splitlines()[0])
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="the account's Google email")
    who.add_argument("--id", help="the account's user id (from the admin console)")
    ap.add_argument("--yes", action="store_true", help="actually delete (without it, only list)")
    ap.add_argument("--force", action="store_true", help="run even though a server answers on --port")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)

    from core import storage
    from web.decks import DeckStore
    from web.learn import ThreadStore
    from web.ownership import DECK, THREAD, VIDEO, Ownership
    from web.quota import Quota
    from web.users import UserStore

    users = UserStore(settings.out_dir)
    if args.email:
        email = args.email.strip().lower()
        matches = [u for u in users.all() if (u.get("email") or "").lower() == email]
        if not matches:
            print(f"No account with email {args.email!r} has signed in here. Nothing to delete.")
            return 1
        uid, label = matches[0]["id"], args.email
    else:
        uid, label = args.id, args.id
        if users.get(uid) is None:
            print(f"No account with id {uid!r}. Nothing to delete.")
            return 1

    if args.yes and not args.force and server_running(args.port):
        print("A server is running. Stop it first (sudo systemctl stop lattice), then run this again:"
              " it keeps accounts and limit counts in memory and would write them back.")
        return 2

    root = settings.out_dir / "web"
    owners = Ownership(root, enforce=True)
    owned = owners.owned_by(uid)
    folders = {
        VIDEO: [root / pid for pid in owned[VIDEO]],
        DECK: [DeckStore(root).workspace(did) for did in owned[DECK]],
        THREAD: [ThreadStore(root).workspace(tid) for tid in owned[THREAD]],
    }
    prefixes = ([f"videos/{i}/" for i in owned[VIDEO]] + [f"decks/{i}/" for i in owned[DECK]]
                + [f"learn/{i}/" for i in owned[THREAD]])
    remote = [o["key"] for p in prefixes for o in storage.listing(p)] if storage.enabled() else []
    ledger_rows = anonymize_ledger(uid, dry_run=True)

    verb = "Deleting" if args.yes else "Would delete"
    print(f"{verb} the data of {label} ({uid}):")
    for kind, paths in folders.items():
        mb = sum(size_of(p) for p in paths) / 1e6
        print(f"  {kind:7} {len(paths):4} item(s)  {mb:8.1f} MB")
    print(f"  object storage: {len(remote)} file(s)" if storage.enabled() else "  object storage: not configured")
    print(f"  usage ledger:   {ledger_rows} row(s) anonymized")
    if not args.yes:
        print("\nNothing changed. Add --yes to delete (stop the server first).")
        return 0

    for kind, paths in folders.items():
        for p in paths:
            shutil.rmtree(p, ignore_errors=True)
        owners.forget(kind, owned[kind])
    for key in remote:
        storage.delete(key)
    Quota(settings.out_dir, enforce=True).forget(uid)
    anonymize_ledger(uid, dry_run=False)
    users.forget(uid)
    print("\nDone. Last step, by hand: remove the sign-in itself in Supabase ->"
          " Authentication -> Users -> find the email -> Delete user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
