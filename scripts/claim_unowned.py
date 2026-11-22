"""Give everything made before sign-in existed to one account.

    python -m scripts.claim_unowned --email you@gmail.com [--dry-run]

Videos, decks and lesson threads created while the app had no accounts have no owner, so with
sign-in on nobody sees them. This hands every unowned item to the account with that email. The
account must have signed in at least once (that is how its Supabase id gets recorded). Items
that already have an owner are never touched, so running it twice is harmless.
"""
from __future__ import annotations

import argparse
import sys

from core.config import settings
from core.console import enable_utf8


def main(argv: list[str] | None = None) -> int:
    enable_utf8()
    ap = argparse.ArgumentParser(prog="claim_unowned", description=__doc__.splitlines()[0])
    ap.add_argument("--email", required=True, help="the signed-in account to receive the items")
    ap.add_argument("--dry-run", action="store_true", help="list what would move; change nothing")
    args = ap.parse_args(argv)

    from web.decks import DeckStore
    from web.engine import Engine
    from web.learn import ThreadStore
    from web.ownership import DECK, THREAD, VIDEO, Ownership
    from web.users import UserStore

    email = args.email.strip().lower()
    matches = [u for u in UserStore(settings.out_dir).all() if (u.get("email") or "").lower() == email]
    if not matches:
        print(f"No signed-in account with email {args.email!r}. Sign in once with it, then rerun.")
        return 1
    uid = matches[0]["id"]

    engine = Engine(client=object())             # listing only: no model is ever called
    found = {
        VIDEO: [p["id"] for p in engine.list_projects()],
        DECK: [d["id"] for d in DeckStore(engine.root).list()],
        THREAD: [t["id"] for t in ThreadStore(engine.root).list()],
    }
    owners = Ownership(engine.root, enforce=True)
    total = 0
    for kind, ids in found.items():
        unowned = [i for i in ids if owners.owner(kind, i) is None]
        moved = unowned if args.dry_run else owners.assign_unowned(kind, unowned, uid)
        total += len(moved)
        print(f"{kind:7} {len(moved):4} {'would move' if args.dry_run else 'moved'}"
              f"   ({len(ids)} in all)")
    print(f"{'Would give' if args.dry_run else 'Gave'} {total} item(s) to {args.email} ({uid}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
