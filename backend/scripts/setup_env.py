"""M0 setup - one command, from clean: verify Docker, build the pinned render image.

    python -m scripts.setup_env

Builds `lattice-render` from `manimcommunity/manim:v0.18.1` (Manim CE + LaTeX + FFmpeg).
The first run downloads the base image (~2 GB) and needs network; after that it's cached.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from core.config import settings


def main() -> int:
    if not shutil.which("docker"):
        print("[X] docker not found on PATH. Install Docker Desktop and re-run.")
        return 1

    info = subprocess.run(["docker", "info"], text=True, capture_output=True)
    if info.returncode != 0:
        print("[X] Docker daemon not reachable. Start Docker Desktop, wait for it to go green, then re-run.")
        tail = (info.stderr or "").strip().splitlines()
        if tail:
            print("  " + tail[-1])
        return 1
    print("[OK] Docker daemon up.")

    print(f"-> Building {settings.render_image} from {settings.manim_base_image} "
          f"(Manim {settings.manim_version} + LaTeX + FFmpeg). First run pulls ~2 GB...")
    build = subprocess.run(["docker", "build", "-t", settings.render_image, "."])
    if build.returncode != 0:
        print("[X] docker build failed (see output above).")
        print("  If the base tag is unavailable, check hub.docker.com/r/manimcommunity/manim/tags")
        return 1

    print(f"[OK] Image {settings.render_image} ready.")
    print("-> Next: python -m scripts.render_sample")
    return 0


if __name__ == "__main__":
    sys.exit(main())
