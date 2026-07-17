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

Two delivery FORMATS, both derived from the SAME 16:9 build:
- "youtube": the 1920x1080 render as-is (the historical behaviour).
- "reel": 1080x1920 for Shorts/Reels/TikTok, produced by ONE ffmpeg pass that scales the finished
  video to the phone's width and pads above/below with the scene background colour.

Reframing at export (rather than rendering a native 9:16 frame) is deliberate. The whole grid
scaffold in `generation/lattice_scene.py` is dimensioned for Manim's 14.22x8.0 landscape frame
(`_MAIN_X`, `_MAIN_Y`, the 12.4x5.8 `fit_content` safe area, the title width caps), and layout
quality has repeatedly proven to be the pipeline's most fragile property. A portrait frame would
re-open that whole failure class AND cost a second LLM build per format. Padding costs one ffmpeg
pass, no tokens, and cannot regress a scene that already rendered correctly. The trade is that the
diagram occupies a band in the middle rather than the full height — the freed space is where the
burned captions go, which is the conventional explainer-reel layout anyway.
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

FORMATS = ("youtube", "reel")
REEL_W, REEL_H = 1080, 1920           # the 9:16 canvas Shorts/Reels/TikTok all expect
_REEL_SUB_STYLE = "FontSize=17,MarginV=300"  # lift captions off the bottom edge, into the pad band
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def nominal_bg() -> str:
    """The scene background as an ffmpeg colour (`0xRRGGBB`) — the FALLBACK pad colour.

    Imported lazily: `composition.decoupled` pulls in the LLM/codegen stack, and export is used on
    paths (captions, sidecar SRT) that have no business paying for that.
    """
    from composition.decoupled import BG_COLOR
    m = _HEX.match(BG_COLOR)
    return f"0x{m.group(1).upper()}" if m else "0x000000"


def sample_bg(work_dir: str | Path, in_rel: str, *, network: bool | None = None,
              image: str | None = None) -> str:
    """The colour the finished video's background ACTUALLY decodes to, as `0xRRGGBB`.

    NOT the same as the nominal `#101015` the scenes are painted with: h264 stores luma in limited
    range, so that constant round-trips through encode/decode ~7/255 darker, around `#090A0F`.
    Padding with the nominal colour therefore leaves a visibly LIGHTER band above and below the
    video. Sampling the top-left corner of a frame one second in (the grid scaffold keeps all
    content inside a margin, so the corner is always background) makes the pad match whatever the
    encoder actually produced, and self-corrects if the background ever changes. Falls back to
    `nominal_bg()` if the probe fails — a faint seam beats a failed export.
    """
    img = image or settings.render_image
    cmd = ["docker", "run", *sandbox.hardening_args(network=network)]
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img,
            "ffmpeg", "-loglevel", "error", "-ss", "1", "-i", in_rel,
            "-vf", "crop=16:16:0:0", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=settings.render_timeout_s)
        px = proc.stdout
        if proc.returncode != 0 or len(px) < 3:
            return nominal_bg()
        n = len(px) // 3
        r, g, b = (round(sum(px[i::3]) / n) for i in range(3))
        return f"0x{r:02X}{g:02X}{b:02X}"
    except (OSError, subprocess.SubprocessError):
        return nominal_bg()


def build_filters(fmt: str, *, srt_rel: str | None = None, bg: str | None = None) -> str:
    """The ffmpeg `-vf` chain for one export format (pure). Empty string = no video pass needed.

    For "reel" the video is scaled to the full 1080 width and centred in a 1080x1920 canvas; the
    `-2` height keeps the aspect and rounds to an even number (libx264 rejects odd dimensions).
    `bg` is the pad colour — pass `sample_bg()`'s result so the band matches the video's own pixels.
    Padding happens BEFORE the subtitle filter so the captions are laid onto the tall frame and can
    sit in the bottom band rather than being scaled down along with the video.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt!r}")
    parts: list[str] = []
    if fmt == "reel":
        parts.append(f"scale={REEL_W}:-2")
        parts.append(f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color={bg or nominal_bg()}")
    if srt_rel:
        # only the reel needs restyling; the 16:9 burn stays byte-identical to what it always was
        parts.append(f"subtitles={srt_rel}:force_style='{_REEL_SUB_STYLE}'"
                     if fmt == "reel" else f"subtitles={srt_rel}")
    return ",".join(parts)


def build_export_command(work_dir: str | Path, in_rel: str, out_rel: str, *, vf: str,
                         network: bool | None = None, image: str | None = None,
                         name: str | None = None) -> list[str]:
    """ffmpeg argv applying the `vf` chain to `in_rel` -> `out_rel` (re-encodes video, copies audio).

    Runs in the same pinned, hardened sandbox image as every other container step.
    """
    img = image or settings.render_image
    cmd = ["docker", "run", *sandbox.hardening_args(network=network, name=name)]
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img,
            "ffmpeg", "-loglevel", "error", "-y", "-i", in_rel,
            "-vf", vf, "-c:a", "copy", out_rel]
    return cmd


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
    """ffmpeg argv that burns `srt_rel` into `in_rel`, writing `out_rel` — the 16:9 subtitle pass."""
    return build_export_command(work_dir, in_rel, out_rel,
                                vf=build_filters("youtube", srt_rel=srt_rel),
                                network=network, image=image, name=name)


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
           fmt: str = "youtube", out_name: str = "export.mp4", log=print) -> dict:
    """Produce the downloadable artifact(s). Returns {'mp4': path, 'srt': path|None}.

    subtitles: "none" -> no captions; "separate" -> a sidecar merged .srt alongside the MP4;
    "burn" -> the captions rendered into the pixels.
    fmt: "youtube" -> the 16:9 render as-is; "reel" -> reframed to 1080x1920.

    A video pass only runs when the request actually changes pixels, so "youtube"+"none" still
    hands back the existing final.mp4 without re-encoding it.
    """
    if subtitles not in ("none", "separate", "burn"):
        raise ValueError(f"unknown subtitles mode: {subtitles!r}")
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt!r}")
    if not project.final_mp4 or not Path(project.final_mp4).exists():
        raise FileNotFoundError("no final video to export — build the project first")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)
    final = Path(project.final_mp4)

    srt_path: Path | None = None
    if subtitles in ("separate", "burn"):
        say("-> merging per-scene captions into one track")
        srt_path = out / "captions.srt"
        srt_path.write_text(merged_captions(project), encoding="utf-8")

    # only re-encode when the request actually changes pixels
    if fmt == "youtube" and subtitles != "burn":
        return {"mp4": str(final), "srt": str(srt_path) if srt_path else None}

    import shutil
    import uuid

    say(f"-> encoding the {fmt} export" + (" with captions burned in" if subtitles == "burn" else ""))
    work = out
    in_rel = "export_in.mp4"
    shutil.copy2(final, work / in_rel)
    # the SRT lives in the work dir too, so the filter can name it relatively (resolves in-container)
    vf = build_filters(fmt, srt_rel=(srt_path.name if subtitles == "burn" else None),
                       bg=(sample_bg(work, in_rel) if fmt == "reel" else None))
    name = f"lattice-export-{uuid.uuid4().hex[:12]}"
    cmd = build_export_command(work, in_rel, out_name, vf=vf, name=name)
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=settings.render_timeout_s)
    produced = work / out_name
    if proc.returncode != 0 or not produced.exists():
        raise RuntimeError(f"{fmt} export failed: {proc.stderr[-800:]}")
    return {"mp4": str(produced), "srt": str(srt_path) if srt_path else None}
