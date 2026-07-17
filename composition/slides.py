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


# --- HYBRID deck: HTML slides + a Manim math scene where the topic actually needs motion -----

def render_math_slide(slide, work_dir: str | Path, *, seconds: float = 7.0,
                      quality: str = "final") -> Path:
    """Render a kind="math" slide through Manim (plot + a dot rolling the curve). The layout comes from
    the proven self.graph() component, so there is no generated layout to repair."""
    from generation.math_scene import render_scene_code
    from verification import compile_repair
    work_dir = Path(work_dir); work_dir.mkdir(parents=True, exist_ok=True)
    code = render_scene_code(slide.fn, slide.x_range, title=slide.title, dots=slide.dots,
                             x_label=slide.x_label, y_label=slide.y_label, seconds=seconds)
    rep = compile_repair.repair(code, work_dir, quality=quality, log=lambda _m: None)
    if not rep.ok or not rep.mp4:
        raise SlideRenderError(f"math scene render failed: {(rep.error or '')[:200]}")
    return Path(rep.mp4)


def _norm_clip(src: str | Path, out: str | Path, *, seconds: float | None = None,
               fps: int = 30, timeout: int = 300) -> Path:
    """Normalise a PNG (held for `seconds`) OR an mp4 to ONE uniform clip (same size/fps/codec) so the
    Chrome slides and the Manim scene can be concatenated together."""
    src, out = Path(src), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    is_img = src.suffix.lower() in (".png", ".jpg", ".jpeg")
    cmd = [_ffmpeg(), "-y"]
    if is_img:
        cmd += ["-loop", "1", "-t", f"{float(seconds or 4.0):.3f}"]
    cmd += ["-i", str(src),
            "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(out)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise SlideRenderError(f"clip normalise failed ({src.name}): "
                               f"{(res.stderr or b'').decode('utf-8', 'replace')[-240:]}")
    return out


def _concat_clips(clips: list[Path], out_mp4: Path, *, audio=None, timeout: int = 300) -> Path:
    """Concat uniform clips (stream-copy — they already share codec params)."""
    lst = out_mp4.parent / "clips.txt"
    lst.write_text("\n".join(f"file '{Path(c).resolve().as_posix()}'" for c in clips) + "\n",
                   encoding="utf-8")
    cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio:
        cmd += ["-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += [str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out_mp4.exists():
        raise SlideRenderError(f"concat failed: {(res.stderr or b'').decode('utf-8', 'replace')[-240:]}")
    return out_mp4


def build_deck(slides: list[Slide], out_dir: str | Path, *, seconds: float = 4.0, audio=None,
               footer: str = "", math_quality: str = "final", fps: int = 30) -> Path:
    """HYBRID build: each slide goes to Chrome (fast, free, deterministic) EXCEPT kind="math", which
    goes to Manim (the ~20% CSS can't do). Everything is normalised to one clip format and concatenated.
    Returns the final mp4."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for i, s in enumerate(slides):
        dst = out_dir / f"clip_{i:02d}.mp4"
        if s.kind == "math":
            mp4 = render_math_slide(s, out_dir / f"math_{i:02d}",
                                    seconds=max(6.0, seconds + 3.0), quality=math_quality)
            clips.append(_norm_clip(mp4, dst, fps=fps))
        else:
            png = render_slide(s, out_dir / f"slide_{i:02d}.png", footer=footer)
            clips.append(_norm_clip(png, dst, seconds=seconds, fps=fps))
    return _concat_clips(clips, out_dir / "deck.mp4", audio=audio)
