"""FR-15 — concatenate per-scene MP4s into one continuous video.

Uses the container's ffmpeg (no host ffmpeg) via the concat demuxer. All scenes come off the
same pinned pipeline (h264+aac), so we try stream-copy first (fast, lossless) and fall back to
a re-encode if the clips' params don't line up — so the stitch never silently fails.

`build_concat_command` is pure (unit-testable without Docker); `stitch` does the file work.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.config import settings


class StitchError(RuntimeError):
    pass


def build_concat_command(work_dir: str | Path, list_file: str, out_rel: str, *,
                         reencode: bool = False, network: bool | None = None,
                         image: str | None = None) -> list[str]:
    net = settings.render_network if network is None else network
    img = image or settings.render_image
    cmd = ["docker", "run", "--rm"]
    if not net:
        cmd.append("--network=none")
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img,
            "ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", list_file]
    cmd += (["-c:v", "libx264", "-c:a", "aac"] if reencode else ["-c", "copy"])
    cmd += [out_rel]
    return cmd


def stitch(mp4_paths: list[str | Path], *, work_dir: str | Path, out_name: str = "final.mp4",
           reencode: bool = False, network: bool | None = None, image: str | None = None,
           timeout: int | None = None) -> Path:
    """Concatenate mp4_paths (in order) into work_dir/out_name and return its path."""
    if not mp4_paths:
        raise StitchError("no clips to stitch")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    parts = work_dir / "parts"
    parts.mkdir(exist_ok=True)
    for p in parts.glob("*.mp4"):
        p.unlink()

    rels: list[str] = []
    for i, src in enumerate(mp4_paths):
        dst = parts / f"part_{i:03d}.mp4"
        shutil.copy2(src, dst)
        rels.append(f"parts/{dst.name}")
    (work_dir / "concat.txt").write_text("".join(f"file '{r}'\n" for r in rels), encoding="utf-8")

    cmd = build_concat_command(work_dir, "concat.txt", out_name, reencode=reencode,
                               network=network, image=image)
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=timeout or settings.render_timeout_s)
    out = work_dir / out_name
    if proc.returncode == 0 and out.exists():
        return out
    if not reencode:  # stream-copy failed (param mismatch) -> re-encode once
        return stitch(mp4_paths, work_dir=work_dir, out_name=out_name, reencode=True,
                      network=network, image=image, timeout=timeout)
    raise StitchError(proc.stderr[-1500:] or "ffmpeg concat failed")
