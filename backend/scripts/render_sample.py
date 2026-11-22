"""M0 acceptance - render the hand-written sample scene in the sandbox.

    python -m scripts.render_sample [--quality preview|final|both]

Produces, under out/render/media/: a preview MP4, a final MP4, and a keyframe PNG -
proving shapes + LaTeX render and a frame can be exported (the vision-critic hook).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from core.config import PROJECT_ROOT, settings
from render import sandbox

SCENE = "SampleScene"
SRC = PROJECT_ROOT / "render" / "sample_scene.py"


def _prep_work() -> Path:
    wd = settings.out_dir / "render"
    wd.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, wd / "scene.py")  # mount a minimal work dir, not the whole repo
    return wd


def _render(quality: str) -> Path | None:
    wd = _prep_work()
    net = "on" if settings.render_network else "none"
    print(f"-> rendering {SCENE} @ {quality} (sandboxed, --network={net})...")
    res = sandbox.render(wd, "scene.py", SCENE, quality=quality)
    if not res.ok:
        print(res.stderr[-2000:])
        print(f"[X] render failed (exit {res.returncode})")
        return None
    mp4 = next((o for o in res.outputs if o.suffix == ".mp4"), None)
    print(f"[OK] {quality} MP4: {mp4}")
    return mp4


def _keyframe() -> Path | None:
    wd = _prep_work()
    print("-> exporting keyframe PNG (-s, last frame)...")
    res = sandbox.render(wd, "scene.py", SCENE, quality="preview", still=True)
    if not res.ok:
        print(res.stderr[-2000:])
        print("[X] keyframe export failed")
        return None
    png = next((o for o in res.outputs if o.suffix == ".png"), None)
    print(f"[OK] keyframe PNG: {png}")
    return png


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", choices=["preview", "final", "both"], default="both")
    args = ap.parse_args()

    ok = True
    if args.quality in ("preview", "both"):
        ok &= _render("preview") is not None
    if args.quality in ("final", "both"):
        ok &= _render("final") is not None
    ok &= _keyframe() is not None

    print("---")
    print("[OK] M0 render path works." if ok else "[X] M0 render path FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
