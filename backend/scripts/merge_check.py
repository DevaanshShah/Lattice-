"""Will this branch merge into another checkout of the repo — and if not, exactly where?

    python -m scripts.merge_check ../Franko            # against that tree's WORKING copy
    python -m scripts.merge_check ../Franko --show     # print the conflicting hunks too

Written for the case this repo is actually in: two agent sessions editing two checkouts of the same
project at once, one of them with uncommitted work that is not on any branch. `git merge` cannot
answer that — the other side's changes exist only in its working tree. This runs the same three-way
merge git would (`git merge-file`), per file, with the merge base's version as the base, this tree's
file as OURS and the other tree's file as THEIRS.

Line endings are normalised first: this repo is `core.autocrlf=true`, so a naive compare between a
blob (LF) and a working file (CRLF) reports every single file as conflicting.

Exit code is the number of conflicting files, so it works as a gate.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str, cwd: Path = ROOT):
    # encoding is explicit: Windows would otherwise decode git's output as cp1252 and choke on the
    # em dashes this codebase is full of.
    return subprocess.run(["git", "-c", f"safe.directory={cwd}", *args], cwd=cwd,
                          capture_output=True, check=False, text=True,
                          encoding="utf-8", errors="replace")


def _lf(data: "str | None") -> str:
    return (data or "").replace("\r\n", "\n")   # None = the file is not in the base


def _base_ref(other: Path) -> str:
    """The commit both sides descend from — the other tree's HEAD if we can see it, else ours."""
    theirs = _git("rev-parse", "HEAD", cwd=other).stdout.strip()
    if theirs:
        merged = _git("merge-base", "HEAD", theirs).stdout.strip()
        if merged:
            return merged
    return "HEAD"


def check(other: Path, *, show: bool = False) -> int:
    base_ref = _base_ref(other)
    tracked = [p for p in _git("ls-files").stdout.splitlines() if p]
    conflicted = 0

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for rel in tracked:
            mine_p, theirs_p = ROOT / rel, other / rel
            if not mine_p.is_file() or not theirs_p.is_file():
                continue
            base = _git("show", f"{base_ref}:{rel}").stdout
            try:
                mine, theirs = mine_p.read_text(encoding="utf-8"), theirs_p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue                     # binary asset: nothing textual to merge
            if _lf(mine) == _lf(theirs):
                continue                     # identical on both sides, or neither side touched it
            files = {}
            for name, text in (("mine", mine), ("base", base), ("theirs", theirs)):
                files[name] = tmp / name
                files[name].write_text(_lf(text), encoding="utf-8")
            res = _git("merge-file", "--diff3", "-p",
                       str(files["mine"]), str(files["base"]), str(files["theirs"]))
            if res.returncode == 0:
                print(f"  clean      {rel}")
                continue
            conflicted += 1
            print(f"  CONFLICT   {rel}  ({res.returncode} hunk(s))")
            if show:
                inside = False
                for line in res.stdout.splitlines():
                    if line.startswith("<<<<<<<"):
                        inside = True
                    if inside:
                        print(f"      {line}")
                    if line.startswith(">>>>>>>"):
                        inside = False
    return conflicted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("other", help="path to the other checkout of this repo")
    ap.add_argument("--show", action="store_true", help="print the conflicting hunks")
    args = ap.parse_args()

    other = Path(args.other).expanduser().resolve()
    if not (other / ".git").exists():
        print(f"{other} is not a git checkout", file=sys.stderr)
        return 2
    print(f"three-way merge check: {ROOT.name} (ours) vs {other.name} (theirs)")
    n = check(other, show=args.show)
    print(f"\n{n} conflicting file(s)" if n else "\nno conflicts — this merges clean")
    return n


if __name__ == "__main__":
    raise SystemExit(main())
