"""M7 — serve the Lattice web UI (FR-28).

    python -m scripts.serve [--host 127.0.0.1] [--port 8000] [--reload]
    lattice serve

Thin uvicorn launcher over `web.app:app` (the real engine + a threaded job queue). The browser
flow — topic → approve outline → scenes render async with live progress → preview/edit → download
— needs the LLM key + Docker (renders run in the hardened sandbox). The HTTP layer itself is
unit-tested separately with fakes, so this file stays a one-liner launcher.
"""
from __future__ import annotations

import sys

from core.console import enable_utf8


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(prog="serve", description="Serve the Lattice web UI (M7).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = ap.parse_args(argv)

    import uvicorn

    print(f"-> Lattice web UI on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run("web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
