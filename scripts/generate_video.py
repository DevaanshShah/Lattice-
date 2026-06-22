"""M5 driver — topic -> approved outline -> multi-scene narrated video (the demo).

    python -m scripts.generate_video "<topic>" [--yes] [--quality preview|final]
                                      [--max-scenes N] [--cap N]

The outline-approval gate prints the scenes; without --yes you can reorder/cut BEFORE any
scene renders. LIVE (needs the LLM key + Docker; TTS uses the host network). Writes out/video/.
"""
from __future__ import annotations

import sys

from composition import video
from core.config import settings
from core.console import enable_utf8
from planner import approval


def _make_approver(auto: bool, max_scenes: int = 0):
    def approve(outline):
        if max_scenes and len(outline.items) > max_scenes:
            outline = approval.apply_edits(outline, keep=list(range(max_scenes)))
        print(approval.render_for_review(outline))
        if auto:
            print("(auto-approved with --yes)")
            return outline
        resp = input("\nApprove? [Enter=yes | 'keep 0 2 3'=reorder/cut | 'drop 1' | 'q'=abort]: ").strip()
        if resp.lower() in ("q", "quit", "abort"):
            raise SystemExit("aborted at the outline gate.")
        if not resp:
            return outline
        parts = resp.split()
        cmd, idxs = parts[0].lower(), [int(x) for x in parts[1:] if x.lstrip("-").isdigit()]
        if cmd == "keep":
            return approval.apply_edits(outline, keep=idxs)
        if cmd == "drop":
            return approval.apply_edits(outline, drop=idxs)
        print("(unrecognized — approving as-is)")
        return outline

    return approve


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Generate a multi-scene narrated video (M5).")
    ap.add_argument("topic")
    ap.add_argument("--yes", action="store_true", help="auto-approve the outline (non-interactive)")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--max-scenes", type=int, default=0, help="cap scenes (0 = planner default)")
    ap.add_argument("--cap", type=int, default=0, help="parallel render cap (0 = config default)")
    args = ap.parse_args(argv)

    out = settings.out_dir / "video"
    proj = video.generate_video(
        args.topic, approve_fn=_make_approver(args.yes, args.max_scenes),
        quality=args.quality, out_dir=out, cap=(args.cap or None), log=print,
    )

    print("---")
    rendered = sum(1 for s in proj.scenes if s.mp4)
    print(f"scenes: {rendered}/{len(proj.scenes)} rendered")
    if proj.final_mp4:
        print(f"[OK] final video: {proj.final_mp4}")
        print(f"     project:     {out / 'project.json'}")
        return 0
    print("[X] no final video produced.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
