"""M4 driver — prompt -> narrated, synced, captioned scene.

    python -m scripts.narrate "<prompt>" [--quality preview|final]

LIVE (needs the LLM key + Docker; TTS uses the host network). Writes out/m4/.
"""
from __future__ import annotations

import sys

from core.config import settings
from core.console import enable_utf8
from generation import scene_spec as ss
from narration import narrate


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Generate a narrated scene (M4).")
    ap.add_argument("prompt")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    out = settings.out_dir / "m4"
    print(f"-> scene spec for: {args.prompt!r}")
    spec = ss.generate(args.prompt)
    print(f"   {len(spec.objects)} objects, {len(spec.beats)} beats — {spec.title}")

    res = narrate.build(spec, work_dir=out, quality=args.quality, log=print)
    print("---")
    if res.mp4:
        print(f"[OK] narrated MP4: {res.mp4}")
        print(f"     captions:     {res.srt}")
        print(f"     narration:    {len(res.lines)} lines, {sum(c.duration for c in res.clips):.1f}s")
        return 0
    print("[X] narrated render failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
