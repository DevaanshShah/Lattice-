"""FR-30 — export the finished video: download the MP4, optionally with subtitles.

Two subtitle modes, the choice the PRD calls for:
- "separate": the final MP4 plus a sidecar `.srt` track (a merged, time-offset concatenation of
  every scene's captions) the player can toggle.
- "burn": the captions rendered permanently into the pixels (one ffmpeg `subtitles=` pass).
- "none": just the stitched MP4.

Per-scene SRTs are relative to each scene's own start; the stitched video plays them back-to-back,
so the merge offsets scene k's cues by the summed duration of scenes 0..k-1 and renumbers. The
offset math (`merge_srt`) and the ffmpeg argv (`build_burn_command`) are pure and unit-tested;
`export` does the file/probe/render work (needs the container).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from composition.scene_dag import VideoProject
from core.config import settings
from render import sandbox

_TS = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _shift_block(text: str, offset: float) -> list[tuple[float, float, str]]:
    """Parse one scene's SRT into (start, end, body) cues, each shifted by `offset` seconds.

    Blank-line-delimited blocks (the SRT standard): index line, timestamp line, then the text.
    We locate the timestamp line and take everything after it as the body, so the index line is
    dropped (we renumber on output) and multi-line cues survive intact.
    """
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        ts_idx = next((i for i, ln in enumerate(lines) if _TS.search(ln)), None)
        if ts_idx is None:
            continue
        g = _TS.search(lines[ts_idx]).groups()
        start = _to_seconds(*g[0:4]) + offset
        end = _to_seconds(*g[4:8]) + offset
        body = "\n".join(lines[ts_idx + 1:]).strip()
        if body:
            cues.append((start, end, body))
    return cues


def merge_srt(scenes: list[tuple[str, float]]) -> str:
    """Merge per-scene SRTs into one continuous track.

    `scenes` is an ORDERED list of (srt_text, scene_duration_seconds). Scene k's cues are offset by
    the cumulative duration of scenes before it, then everything is renumbered from 1. Empty SRTs
    are skipped but still advance the offset (a silent scene still consumes time).
    """
    cues: list[tuple[float, float, str]] = []
    offset = 0.0
    for text, dur in scenes:
        if text and text.strip():
            cues.extend(_shift_block(text, offset))
        offset += max(0.0, dur)
    out: list[str] = []
    for i, (start, end, txt) in enumerate(cues, start=1):
        out.append(str(i))
        out.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        out.append(txt)
        out.append("")
    return "\n".join(out).rstrip() + ("\n" if out else "")


def build_burn_command(work_dir: str | Path, in_rel: str, srt_rel: str, out_rel: str, *,
                       network: bool | None = None, image: str | None = None,
                       name: str | None = None) -> list[str]:
    """ffmpeg argv that burns `srt_rel` into `in_rel`, writing `out_rel` (re-encodes video, copies audio).

    Runs in the same pinned, hardened sandbox image as every other container step.
    """
    img = image or settings.render_image
    cmd = ["docker", "run", *sandbox.hardening_args(network=network, name=name)]
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img,
            "ffmpeg", "-loglevel", "error", "-y", "-i", in_rel,
            "-vf", f"subtitles={srt_rel}", "-c:a", "copy", out_rel]
    return cmd


def _probe_duration(mp4: str | Path) -> float:
    """Clip duration in seconds via the container's ffprobe (0.0 if it can't be read)."""
    from render import worker  # reuse the worker's sandboxed ffprobe wrapper
    p = Path(mp4)
    try:
        proc = subprocess.run(
            worker.build_probe_command(p.parent, p.name),
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=settings.render_timeout_s,
        )
        return float((proc.stdout or "").strip()) if proc.returncode == 0 else 0.0
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def merged_captions(project: VideoProject) -> str:
    """Build the whole-video SRT by offsetting each scene's captions (probes scene durations)."""
    scenes: list[tuple[str, float]] = []
    for s in project.scenes:
        text = Path(s.srt).read_text(encoding="utf-8") if (s.srt and Path(s.srt).exists()) else ""
        dur = _probe_duration(s.mp4) if s.mp4 else 0.0
        scenes.append((text, dur))
    return merge_srt(scenes)


def export(project: VideoProject, *, out_dir: str | Path, subtitles: str = "none",
           out_name: str = "export.mp4", log=print) -> dict:
    """Produce the downloadable artifact(s). Returns {'mp4': path, 'srt': path|None}.

    subtitles: "none" -> the final MP4 as-is; "separate" -> MP4 + a sidecar merged .srt;
    "burn" -> a new MP4 with captions rendered in.
    """
    if subtitles not in ("none", "separate", "burn"):
        raise ValueError(f"unknown subtitles mode: {subtitles!r}")
    if not project.final_mp4 or not Path(project.final_mp4).exists():
        raise FileNotFoundError("no final video to export — build the project first")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)
    final = Path(project.final_mp4)

    if subtitles == "none":
        return {"mp4": str(final), "srt": None}

    say("-> merging per-scene captions into one track")
    merged = merged_captions(project)
    srt_path = out / "captions.srt"
    srt_path.write_text(merged, encoding="utf-8")

    if subtitles == "separate":
        return {"mp4": str(final), "srt": str(srt_path)}

    # burn: ffmpeg subtitles pass, in the work dir so relative paths resolve in-container
    import shutil
    import uuid

    say("-> burning captions into the video")
    work = out
    in_rel = "burn_in.mp4"
    shutil.copy2(final, work / in_rel)
    (work / "burn.srt").write_text(merged, encoding="utf-8")
    name = f"lattice-export-{uuid.uuid4().hex[:12]}"
    cmd = build_burn_command(work, in_rel, "burn.srt", out_name, name=name)
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=settings.render_timeout_s)
    burned = work / out_name
    if proc.returncode != 0 or not burned.exists():
        raise RuntimeError(f"subtitle burn-in failed: {proc.stderr[-800:]}")
    return {"mp4": str(burned), "srt": str(srt_path)}
