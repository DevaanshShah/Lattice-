"""Regenerate one scene of the current video and re-stitch (FR-16).

    python -m scripts.regen_scene <index> [--quality preview|final]

Operates on out/video/project.json; rebuilds only that scene, reuses the rest, re-stitches.
"""
from __future__ import annotations

import sys

from composition import regen
from composition.scene_dag import VideoProject
from core.config import settings
from core.console import enable_utf8


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Regenerate one scene and re-stitch (M5).")
    ap.add_argument("index", type=int)
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    out = settings.out_dir / "video"
    project = VideoProject.load(out / "project.json")
    if not (0 <= args.index < len(project.scenes)):
        print(f"[X] scene index {args.index} out of range (0..{len(project.scenes) - 1})")
        return 1

    regen.regenerate_scene(project, args.index, out_dir=out, quality=args.quality, log=print)
    print("---")
    print(f"[OK] regenerated scene {args.index}; final: {project.final_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
