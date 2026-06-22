"""Make stdout/stderr UTF-8 so progress glyphs (→, —, ✓) don't crash on Windows cp1252.

Call enable_utf8() once at a script entry point (main()). It reconfigures the process
streams, so every print after it — including library `say`/log callbacks — is safe.
"""
from __future__ import annotations

import sys


def enable_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass  # already UTF-8, or a stream that can't be reconfigured (e.g. captured in tests)
