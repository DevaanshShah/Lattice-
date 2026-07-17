"""Render a designed HTML slide deck -> PNGs -> MP4. ADDITIVE: parallel to the Manim path.

Pipeline: generation.slide_deck builds the page HTML (fixed layout/CSS) -> headless Chrome screenshots
it -> ffmpeg stitches the stills into a video with per-slide durations (+ optional audio track).

No LLM writes layout here, so there is nothing to compile-repair, lint, or vision-critique: CSS flexbox
cannot push a card off-frame or overlap two labels. A slide renders in ~0.2s for $0.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from generation.slide_deck import H, W, Slide, page_html

_CHROME_CANDIDATES = (
    os.environ.get("LATTICE_CHROME") or "",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


class SlideRenderError(RuntimeError):
    pass


def chrome_path() -> str:
    """The headless browser used to rasterise slides. LATTICE_CHROME overrides; else common paths."""
    for c in _CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise SlideRenderError("no Chrome/Chromium found — set LATTICE_CHROME to the browser binary")


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def render_slide(slide: Slide, out_png: str | Path, *, footer: str = "", timeout: int = 60) -> Path:
    """Rasterise ONE slide to a PNG via headless Chrome. Deterministic: same input -> same pixels."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    html = out_png.with_suffix(".html")
    html.write_text(page_html(slide, footer=footer), encoding="utf-8")
    cmd = [chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={W},{H}", f"--screenshot={out_png}", html.resolve().as_uri()]
    subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not out_png.exists():
        raise SlideRenderError(f"chrome produced no screenshot for slide {slide.kind!r}")
    return out_png


def render_deck(slides: list[Slide], out_dir: str | Path, *, footer: str = "") -> list[Path]:
    """Rasterise every slide. Returns the PNG paths in order."""
    out_dir = Path(out_dir)
    return [render_slide(s, out_dir / f"slide_{i:02d}.png", footer=footer) for i, s in enumerate(slides)]


def stitch_slides(pngs: list[str | Path], out_mp4: str | Path, *, seconds=4.0,
                  audio: str | Path | None = None, fps: int = 30, timeout: int = 300) -> Path:
    """Stills -> MP4 via the ffmpeg concat demuxer. `seconds` is a float (all slides) or a per-slide list.
    `audio` optionally muxes a track (music or narration) and trims to the shorter stream."""
    pngs = [Path(p) for p in pngs]
    if not pngs:
        raise SlideRenderError("no slides to stitch")
    out_mp4 = Path(out_mp4); out_mp4.parent.mkdir(parents=True, exist_ok=True)
    durs = [float(seconds)] * len(pngs) if isinstance(seconds, (int, float)) else [float(x) for x in seconds]
    lst = out_mp4.parent / "slides.txt"
    lines = []
    for p, d in zip(pngs, durs):
        lines.append(f"file '{p.resolve().as_posix()}'")
        lines.append(f"duration {d:.3f}")
    lines.append(f"file '{pngs[-1].resolve().as_posix()}'")     # concat demuxer needs the last frame twice
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio:
        cmd += ["-i", str(audio)]
    # scale to EVEN dimensions before yuv420p: libx264 rejects odd width/height outright
    cmd += ["-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out_mp4.exists():
        raise SlideRenderError(f"ffmpeg stitch failed: {(res.stderr or b'').decode('utf-8', 'replace')[:300]}")
    return out_mp4
