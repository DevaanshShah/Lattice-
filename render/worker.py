"""FR-22 — the render worker the verification loops call repeatedly.

Wraps the sandboxed render (`render/sandbox.py`) and adds the one thing the vision critic
needs that a single `-s` keyframe can't give: **multiple** frames sampled across the whole
clip (mid-animation problems — a label that overlaps only while moving — are invisible in
the last frame alone). Each call writes the code to a fresh `scene.py`, renders, and pulls
N evenly-spaced PNGs out of the MP4 with FFmpeg (already in the pinned image), all inside
the same no-network sandbox.

Pure command builders (`build_extract_command`, `build_probe_command`) are unit-testable
without Docker; `render_code` / `render_file` execute them.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings
from core.schemas.scene_spec import SCENE_CLASS
from render import sandbox


@dataclass
class WorkerResult:
    """Outcome of one render. `ok` is the free, deterministic compile signal."""
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    mp4: Path | None
    frames: list[Path] = field(default_factory=list)
    command: list[str] = field(default_factory=list)


def _docker_run(work_dir: Path, *tool_args: str, network: bool | None = None,
                image: str | None = None) -> list[str]:
    """`docker run` prefix mirroring the sandbox (no-net, image's non-root user), then a tool.

    Lets us run `ffmpeg`/`ffprobe` in the *same* pinned, sandboxed image as `manim` without
    touching the M0-verified `sandbox.build_command` (which is manim-specific).
    """
    net = settings.render_network if network is None else network
    img = image or settings.render_image
    cmd = ["docker", "run", "--rm"]
    if not net:
        cmd.append("--network=none")
    cmd += ["-v", f"{work_dir.resolve().as_posix()}:/manim", "-w", "/manim", img, *tool_args]
    return cmd


def build_probe_command(work_dir: str | Path, mp4_rel: str, **kw) -> list[str]:
    """ffprobe argv that prints the clip duration in seconds (bare float)."""
    return _docker_run(
        Path(work_dir), "ffprobe", "-v", "error",
        "-show_entries", "format=duration", "-of", "csv=p=0", mp4_rel, **kw,
    )


def build_extract_command(work_dir: str | Path, mp4_rel: str, out_pattern: str,
                          *, vf: str, n: int, **kw) -> list[str]:
    """ffmpeg argv that samples up to `n` frames (via the `-vf` filter) to PNGs."""
    return _docker_run(
        Path(work_dir), "ffmpeg", "-loglevel", "error", "-y", "-i", mp4_rel,
        "-vf", vf, "-frames:v", str(n), out_pattern, **kw,
    )


def _run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, encoding="utf-8", errors="replace",
        timeout=timeout or settings.render_timeout_s,
    )


def _probe_duration(work_dir: Path, mp4_rel: str) -> float:
    try:
        proc = _run(build_probe_command(work_dir, mp4_rel))
        return float((proc.stdout or "").strip()) if proc.returncode == 0 else 0.0
    except (ValueError, subprocess.SubprocessError):
        return 0.0


def extract_frames(work_dir: str | Path, mp4: Path, n: int = 3) -> list[Path]:
    """Sample up to `n` evenly-spaced PNGs across the MP4 (one ffprobe + one ffmpeg call).

    Spreads frames over the whole clip via `fps = n/duration` so the critic sees the start,
    middle, and end — not just the last frame. Degrades gracefully (single frame, then none)
    so a flaky extraction never hangs or aborts the loop.
    """
    work_dir = Path(work_dir).resolve()
    n = max(1, n)
    out_dir = work_dir / "frames"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)  # no stale frames bleed into this render
    out_dir.mkdir(parents=True, exist_ok=True)

    mp4_rel = mp4.resolve().relative_to(work_dir).as_posix()
    dur = _probe_duration(work_dir, mp4_rel)
    vf = f"fps={n / dur:.6f}" if (dur and n > 1) else "fps=1"

    try:
        _run(build_extract_command(work_dir, mp4_rel, "frames/frame_%03d.png", vf=vf, n=n))
    except subprocess.SubprocessError:
        pass
    pngs = sorted(out_dir.glob("*.png"))[:n]
    if pngs:
        return pngs

    # fallback: grab a single frame so the critic always has something to look at
    try:
        _run(build_extract_command(work_dir, mp4_rel, "frames/frame_000.png", vf="select=eq(n\\,0)", n=1))
    except subprocess.SubprocessError:
        pass
    return sorted(out_dir.glob("*.png"))


def render_code(code: str, work_dir: str | Path, *, quality: str = "preview",
                frames: int = 3, scene_name: str = SCENE_CLASS,
                timeout: int | None = None) -> WorkerResult:
    """Render a Manim code string to MP4 + keyframe PNGs. Callable repeatedly in one run.

    State doesn't leak between calls: `scene.py` is overwritten and the `frames/` dir is
    rebuilt each time; `sandbox.render` already scopes MP4 discovery to this quality's
    resolution dir.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "scene.py").write_text(code, encoding="utf-8")

    res = sandbox.render(work_dir, "scene.py", scene_name, quality=quality, timeout=timeout)
    if not res.ok:
        return WorkerResult(False, res.returncode, res.stdout, res.stderr, None, [], res.command)

    mp4 = next((o for o in res.outputs if o.suffix == ".mp4"), None)
    pngs = extract_frames(work_dir, mp4, frames) if mp4 else []
    return WorkerResult(True, 0, res.stdout, res.stderr, mp4, pngs, res.command)


def render_file(scene_file: str | Path, *, work_dir: str | Path | None = None,
                quality: str = "preview", frames: int = 3,
                scene_name: str = SCENE_CLASS) -> WorkerResult:
    """Render an existing scene file (CLI entry); renders in its own directory by default."""
    scene_file = Path(scene_file)
    wd = Path(work_dir) if work_dir else scene_file.resolve().parent
    return render_code(scene_file.read_text(encoding="utf-8"), wd,
                       quality=quality, frames=frames, scene_name=scene_name)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Render a Manim scene file to MP4 + keyframe PNGs.")
    ap.add_argument("scene_file")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--frames", type=int, default=3)
    args = ap.parse_args(argv)

    res = render_file(args.scene_file, quality=args.quality, frames=args.frames)
    if not res.ok:
        print(res.stderr[-1500:])
        print(f"[X] render failed (exit {res.returncode})")
        return 1
    print(f"[OK] MP4:    {res.mp4}")
    print(f"[OK] frames: {len(res.frames)} -> " + ", ".join(p.name for p in res.frames))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
