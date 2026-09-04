"""Cloudflare R2 helper — verify the credentials, then move what is already on disk into the bucket.

    python -m scripts.r2 check              # can we reach the bucket? (do this first)
    python -m scripts.r2 push               # upload every finished video in out/ that isn't there
    python -m scripts.r2 push --delete      # ...and free the local copy afterwards
    python -m scripts.r2 list [prefix]      # what is in the bucket, and how much it costs
    python -m scripts.r2 backup             # snapshot the admin ledger + user registry
    python -m scripts.r2 pull <key> <dest>  # fetch one object back

`check` is the one that matters when setting this up: it writes a tiny object, reads it back and
deletes it, so a wrong secret or a bucket in the wrong account fails HERE with a clear message
instead of silently swallowing every upload during a render.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from core import storage
from core.config import settings
from core.console import enable_utf8


def _fail(msg: str) -> int:
    print(f"[X] {msg}")
    return 1


def cmd_check() -> int:
    if not storage.configured():
        missing = [n for n, v in (("LATTICE_R2_ACCOUNT_ID", settings.r2_account_id),
                                  ("LATTICE_R2_BUCKET", settings.r2_bucket),
                                  ("LATTICE_R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                                  ("LATTICE_R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key))
                   if not v]
        return _fail("R2 is not configured — missing in .env: " + ", ".join(missing))
    if storage.client() is None:
        return _fail("boto3 is not installed. Run: pip install boto3")

    print(f"endpoint: {storage.endpoint()}")
    print(f"bucket:   {settings.r2_bucket}")
    key = f"_healthcheck/{int(time.time())}.txt"
    tmp = Path(settings.out_dir) / "admin" / "_r2check.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("lattice r2 check", encoding="utf-8")
    try:
        if not storage.put(tmp, key, log=print):
            return _fail("upload failed — check the Access Key / Secret and that the token has "
                         "Object Read & Write on this bucket")
        if not storage.exists(key):
            return _fail("uploaded, but the object is not readable back")
        url = storage.url_for(key, expires=60)
        print(f"read back: OK\npresigned: {(url or '')[:90]}...")
        storage.delete(key)
        print("[OK] R2 is working. Finished videos will be stored there from the next build.")
        if not settings.r2_public_base:
            print("     (no LATTICE_R2_PUBLIC_BASE set — videos are served via presigned URLs, "
                  "which keeps the bucket private. That is the safe default.)")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


def _local_artifacts() -> list[tuple[Path, str]]:
    """(file, key) for everything worth keeping: stitched videos, decks, learn videos."""
    root = Path(settings.out_dir) / "web"
    found: list[tuple[Path, str]] = []
    for proj in sorted(root.glob("*/project.json")):
        pid = proj.parent.name
        for mp4 in sorted(proj.parent.glob("final/*.mp4")):
            found.append((mp4, storage.video_key(pid, mp4.name)))
    for deck in sorted(root.glob("decks/*/deck.json")):
        did = deck.parent.name
        for mp4 in sorted(deck.parent.rglob("*.mp4")):
            found.append((mp4, storage.deck_key(did) if mp4.name == "deck.mp4"
                          else f"decks/{did}/{mp4.name}"))
    for thread in sorted(root.glob("learn/*/thread.json")):
        tid = thread.parent.name
        for mp4 in sorted(thread.parent.rglob("*.mp4")):
            found.append((mp4, f"learn/{tid}/{mp4.name}"))
    return found


def cmd_push(delete_local: bool) -> int:
    if storage.client() is None:
        return _fail("R2 is not configured (run: python -m scripts.r2 check)")
    items = _local_artifacts()
    if not items:
        print("nothing on disk to upload")
        return 0
    total = uploaded = skipped = 0
    for path, key in items:
        total += 1
        if storage.exists(key):
            skipped += 1
            continue
        if storage.put(path, key, log=print):
            uploaded += 1
            if delete_local:
                path.unlink(missing_ok=True)
    print(f"[OK] {uploaded} uploaded, {skipped} already there, {total} total"
          + (" (local copies removed)" if delete_local else ""))
    return 0


def cmd_list(prefix: str) -> int:
    if storage.client() is None:
        return _fail("R2 is not configured (run: python -m scripts.r2 check)")
    rows = storage.listing(prefix)
    size = sum(r["size"] for r in rows)
    for r in rows[:200]:
        print(f"  {r['size'] / 1e6:8.1f} MB  {r['key']}")
    if len(rows) > 200:
        print(f"  ... and {len(rows) - 200} more")
    gb = size / 1e9
    # R2 pricing at time of writing: $0.015/GB-month stored, $0 egress.
    print(f"\n{len(rows)} objects · {gb:.2f} GB · about ${gb * 0.015:.2f}/month to store")
    return 0


def cmd_backup() -> int:
    """The admin ledger and user registry are small files on an ephemeral disk — snapshot them."""
    if storage.client() is None:
        return _fail("R2 is not configured (run: python -m scripts.r2 check)")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    for name in ("usage.jsonl", "users.json"):
        path = Path(settings.out_dir) / "admin" / name
        if path.is_file() and storage.put(path, f"admin/{stamp}/{name}", log=print):
            n += 1
    print(f"[OK] {n} file(s) backed up under admin/{stamp}/")
    return 0


def cmd_pull(key: str, dest: str) -> int:
    if storage.client() is None:
        return _fail("R2 is not configured (run: python -m scripts.r2 check)")
    out = storage.get(key, dest)
    if not out:
        return _fail(f"could not fetch {key}")
    print(f"[OK] {key} -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    enable_utf8()
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = args[0] if args else "check"
    if cmd == "check":
        return cmd_check()
    if cmd == "push":
        return cmd_push("--delete" in args)
    if cmd == "list":
        rest = [a for a in args[1:] if not a.startswith("-")]
        return cmd_list(rest[0] if rest else "")
    if cmd == "backup":
        return cmd_backup()
    if cmd == "pull":
        if len(args) < 3:
            return _fail("usage: python -m scripts.r2 pull <key> <dest>")
        return cmd_pull(args[1], args[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
