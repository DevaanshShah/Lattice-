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


def _docker_prefix(work_dir: str | Path, *, network: bool | None, image: str | None) -> list[str]:
    net = settings.render_network if network is None else network
    cmd = ["docker", "run", "--rm"]
    if not net:
        cmd.append("--network=none")
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", image or settings.render_image]
    return cmd


def build_probe_audio_command(work_dir: str | Path, mp4_rel: str, *,
                              network: bool | None = None, image: str | None = None) -> list[str]:
    """ffprobe argv that prints audio stream indices (empty output => the clip has no audio)."""
    return _docker_prefix(work_dir, network=network, image=image) + [
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
        "-of", "csv=p=0", mp4_rel]


def build_add_silent_audio_command(work_dir: str | Path, in_rel: str, out_rel: str, *,
                                   network: bool | None = None, image: str | None = None) -> list[str]:
    """ffmpeg argv that muxes a silent stereo AAC track onto a video-only clip (copies the video)."""
    return _docker_prefix(work_dir, network=network, image=image) + [
        "ffmpeg", "-loglevel", "error", "-y", "-i", in_rel,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", out_rel]


def _ensure_uniform_audio(work_dir: str | Path, part_rels: list[str], *,
                          network: bool | None = None, image: str | None = None,
                          timeout: int | None = None) -> None:
    """If clips have MIXED audio presence, the concat demuxer drops audio from the whole film. Give
    any silent clip a silent track so one bad scene can't mute everything. No-op when uniform."""
    if len(part_rels) <= 1:
        return
    t = timeout or settings.render_timeout_s

    def has_audio(rel: str) -> bool:
        try:
            p = subprocess.run(build_probe_audio_command(work_dir, rel, network=network, image=image),
                               capture_output=True, encoding="utf-8", errors="replace", timeout=t)
            return p.returncode == 0 and bool((p.stdout or "").strip())
        except (OSError, subprocess.SubprocessError):
            return True  # can't tell -> assume fine, don't rewrite

    have = [has_audio(r) for r in part_rels]
    if all(have) or not any(have):
        return  # uniform (all voiced or all silent) -> the concat handles it fine
    for rel, ok in zip(part_rels, have):
        if ok:
            continue
        tmp = rel + ".aud.mp4"
        try:
            p = subprocess.run(build_add_silent_audio_command(work_dir, rel, tmp, network=network, image=image),
                               capture_output=True, encoding="utf-8", errors="replace", timeout=t)
        except (OSError, subprocess.SubprocessError):
            continue
        out = Path(work_dir) / tmp
        if p.returncode == 0 and out.exists():
            out.replace(Path(work_dir) / rel)  # swap the silent clip for one carrying a silent track


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
    # one silent scene must not mute the whole film: give any voiceless clip a silent track first
    _ensure_uniform_audio(work_dir, rels, network=network, image=image, timeout=timeout)
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
