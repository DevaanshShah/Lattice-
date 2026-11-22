"""M7 / FR-23 — run an arbitrary python file in the HARDENED render sandbox and report.

    python -m scripts.render_sandbox <file.py>
    lattice render-sandbox tests/fixtures/fork_bomb.py   ; echo "exit=$?"
    lattice render-sandbox tests/fixtures/net_egress.py  ; echo "exit=$?"

The containment harness: untrusted code runs under --network=none + --memory/--cpus +
--pids-limit + non-root, killed on wall-clock overrun. A hostile snippet (network egress /
fork bomb) is contained by the caps, not the host — it exits non-zero and the machine is fine.
Needs Docker; not a unit test (the sandbox.* command builders are unit-tested instead).
"""
from __future__ import annotations

import sys

from core.console import enable_utf8
from render import sandbox


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(prog="render-sandbox",
                                 description="Run a python file in the hardened render sandbox (FR-23).")
    ap.add_argument("file", help="path to the python file to execute inside the sandbox")
    ap.add_argument("--timeout", type=int, default=30, help="wall-clock cap in seconds (default 30)")
    ap.add_argument("--allow-network", action="store_true",
                    help="DANGEROUS: drop --network=none (only for trusted, explicit use)")
    args = ap.parse_args(argv)

    print(f"-> running {args.file} in the hardened sandbox (timeout={args.timeout}s)")
    res = sandbox.run_python_file(
        args.file, network=(True if args.allow_network else None), timeout=args.timeout
    )
    if res.stdout:
        print(res.stdout.rstrip())
    if res.stderr:
        print(res.stderr.rstrip(), file=sys.stderr)

    if res.timed_out:
        print("[contained] wall-clock cap hit — container killed; host untouched.")
        return res.returncode
    if res.ok:
        # exit 0 from untrusted code = it ran to completion without hitting a guard. For the
        # hostile fixtures that is the FAILURE signal (egress succeeded / no cap tripped).
        print("[note] snippet exited 0 (ran to completion inside the sandbox).")
        return 0
    print(f"[contained] snippet exited {res.returncode} inside the sandbox; host untouched.")
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
