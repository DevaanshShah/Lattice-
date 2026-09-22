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
import tempfile
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


def render_html(document: str, out_png: str | Path, *, label: str = "page", timeout: int = 60) -> Path:
    """Rasterise one renderer-owned HTML document to a PNG via headless Chrome."""
    out_png = Path(out_png).resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    html = out_png.with_suffix(".html")
    html.write_text(document, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="lattice-chrome-") as profile:
        cmd = [chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}",
               "--run-all-compositor-stages-before-draw", "--virtual-time-budget=500",
               f"--window-size={W},{H}", f"--screenshot={out_png}", html.resolve().as_uri()]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not out_png.exists():
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise SlideRenderError(f"chrome produced no screenshot for {label}: {detail[:300]}")
    return out_png


def render_slide(slide: Slide, out_png: str | Path, *, footer: str = "", focus: int = -1,
                 timeout: int = 60) -> Path:
    """Rasterise ONE slide to a PNG via headless Chrome. Deterministic: same input -> same pixels.
    `focus` lights up the element the narrator is speaking about and dims the rest."""
    return render_html(page_html(slide, footer=footer, focus=focus), out_png,
                       label=f"slide {slide.kind!r}", timeout=timeout)


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
               fps: int = 30, audio: str | Path | None = None, timeout: int = 300) -> Path:
    """Normalise a PNG (held for `seconds`) OR an mp4 to ONE uniform clip — same size, fps, codec, and
    ALWAYS an audio stream — so Chrome slides and Manim scenes concat and crossfade together.
    `audio` is that clip's narration; silence fills in when there is none. The audio is `apad`ded and
    trimmed with -shortest, so the clip is exactly as long as its video regardless of track length."""
    src, out = Path(src), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    is_img = src.suffix.lower() in (".png", ".jpg", ".jpeg")
    cmd = [_ffmpeg(), "-y"]
    if is_img:
        cmd += ["-loop", "1", "-t", f"{float(seconds or 4.0):.3f}"]
    cmd += ["-i", str(src)]
    if audio:
        cmd += ["-i", str(audio)]
    else:                                    # every clip needs a track or acrossfade has nothing to join
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-vf", (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"),
            "-af", "apad", "-t", f"{float(seconds or (4.0 if is_img else _probe_duration(src))):.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out.exists():
        raise SlideRenderError(f"clip normalise failed ({src.name}): "
                               f"{(res.stderr or b'').decode('utf-8', 'replace')[-240:]}")
    return out


def _probe_duration(path: str | Path) -> float:
    """Exact clip length — the crossfade offsets must be computed from what ffmpeg actually wrote."""
    probe = shutil.which("ffprobe") or "ffprobe"
    res = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, timeout=60)
    try:
        return float((res.stdout or b"").decode().strip())
    except ValueError:
        raise SlideRenderError(f"could not probe duration of {Path(path).name}")


def _xfade_chain(clips: list[Path], out_mp4: Path, *, dur: float = 0.45, timeout: int = 600) -> Path:
    """Concat clips with a crossfade at every seam (video xfade + audio acrossfade, kept in step).

    Each xfade overlaps the pair by `dur`, so the running stream is `dur` shorter per seam — hence the
    offset for seam i is (sum of clip lengths before it) - i*dur. acrossfade shortens the audio by the
    same amount at the same seam, which is what keeps voice and picture locked together."""
    if len(clips) == 1:
        shutil.copyfile(clips[0], out_mp4)
        return out_mp4
    durs = [_probe_duration(c) for c in clips]
    dur = max(0.05, min(dur, min(durs) * 0.4))   # a fade longer than a clip would eat it whole
    cmd = [_ffmpeg(), "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    steps, offset = [], 0.0
    v_prev, a_prev = "[0:v]", "[0:a]"
    for i in range(1, len(clips)):
        offset += durs[i - 1] - dur
        v_out, a_out = f"[v{i}]", f"[a{i}]"
        steps.append(f"{v_prev}[{i}:v]xfade=transition=fade:duration={dur:.3f}:"
                     f"offset={max(offset, 0.0):.3f}{v_out}")
        steps.append(f"{a_prev}[{i}:a]acrossfade=d={dur:.3f}:c1=tri:c2=tri{a_out}")
        v_prev, a_prev = v_out, a_out
    cmd += ["-filter_complex", ";".join(steps), "-map", v_prev, "-map", a_prev,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out_mp4.exists():
        raise SlideRenderError(f"xfade failed: {(res.stderr or b'').decode('utf-8', 'replace')[-300:]}")
    return out_mp4


def _concat_clips(clips: list[Path], out_mp4: Path, *, audio=None, timeout: int = 300) -> Path:
    """Concat uniform clips (stream-copy — they already share codec params)."""
    lst = out_mp4.parent / "clips.txt"
    lst.write_text("\n".join(f"file '{Path(c).resolve().as_posix()}'" for c in clips) + "\n",
                   encoding="utf-8")
    cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio:
        cmd += ["-i", str(audio), "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out_mp4.exists():
        raise SlideRenderError(f"concat failed: {(res.stderr or b'').decode('utf-8', 'replace')[-240:]}")
    return out_mp4


_BEAT_PAD = 0.4     # a breath after each spoken sentence, so beats don't run together


def _mix_music(video: Path, music: str | Path, out_mp4: Path, *, gain: float = 0.20,
               duck: bool = True, timeout: int = 600) -> Path:
    """Lay a music bed UNDER the finished narration (never over it).

    The bed is looped to the video's length and side-chained to the voice: whenever narration is
    present the compressor pulls the music down, and it swells back in the gaps. That is why this
    mixes instead of replacing the track — a bed that competes with the voice is worse than silence.

    amix MUST be duration=shortest, not `first`: `first` means the first INPUT, which is the
    -stream_loop'd music — i.e. infinite, and the render never terminates.
    """
    cmd = [_ffmpeg(), "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(music)]
    bed = f"[1:a]volume={gain:.3f},afade=t=in:d=1.5[m]"
    if duck:
        # asplit: the voice is BOTH the compressor's trigger and the thing mixed back in
        chain = (f"[0:a]asplit=2[voice][key];{bed};"
                 f"[m][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[bed];"
                 f"[bed][voice]amix=inputs=2:duration=shortest:normalize=0[a]")
    else:
        chain = f"{bed};[m][0:a]amix=inputs=2:duration=shortest:normalize=0[a]"
    cmd += ["-filter_complex", chain, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if res.returncode != 0 or not out_mp4.exists():
        raise SlideRenderError(f"music mix failed: {(res.stderr or b'').decode('utf-8', 'replace')[-300:]}")
    return out_mp4


def _slide_clip(slide: Slide, out_dir: Path, idx: int, *, footer: str, seconds: float, fps: int,
                narrate: bool, tts_engine: str | None, math_quality: str) -> Path:
    """One slide -> one narrated clip.

    The sync trick: each beat's audio is synthesized FIRST and measured, then its frame is held for
    exactly that long. Because the track is built from the beats, the highlight cannot drift out of
    step with the voice — no forced alignment, no timing model, nothing to get wrong.
    Beats hard-cut into each other (the highlight should snap, not dissolve); only slide seams fade."""
    from narration.tts import synthesize
    audio_dir = out_dir / "audio"
    dst = out_dir / f"clip_{idx:02d}.mp4"

    if slide.kind == "math":                       # narration plays over the whole Manim animation
        script = slide.script()
        clip = synthesize(script, out_dir=audio_dir, engine=tts_engine) if (narrate and script) else None
        secs = (clip.duration + 1.2) if clip else max(6.0, seconds + 3.0)
        mp4 = render_math_slide(slide, out_dir / f"math_{idx:02d}", seconds=secs, quality=math_quality)
        return _norm_clip(mp4, dst, fps=fps, audio=clip.path if clip else None)

    beats = list(slide.beats) if (narrate and slide.beats) else []
    if not beats:                                  # silent deck: one static frame, fixed duration
        png = render_slide(slide, out_dir / f"slide_{idx:02d}.png", footer=footer)
        return _norm_clip(png, dst, seconds=seconds, fps=fps)

    parts: list[Path] = []
    for j, b in enumerate(beats):
        say = str(b.get("say", "")).strip()
        if not say:
            continue
        clip = synthesize(say, out_dir=audio_dir, engine=tts_engine)
        png = render_slide(slide, out_dir / f"slide_{idx:02d}_{j:02d}.png", footer=footer,
                           focus=int(b.get("focus", -1)))
        parts.append(_norm_clip(png, out_dir / f"beat_{idx:02d}_{j:02d}.mp4",
                                seconds=clip.duration + _BEAT_PAD, fps=fps, audio=clip.path))
    if not parts:
        png = render_slide(slide, out_dir / f"slide_{idx:02d}.png", footer=footer)
        return _norm_clip(png, dst, seconds=seconds, fps=fps)
    return _concat_clips(parts, dst)


def build_deck(slides: list[Slide], out_dir: str | Path, *, seconds: float = 4.0, audio=None,
               footer: str = "", math_quality: str = "final", fps: int = 30,
               narrate: bool = True, tts_engine: str | None = None,
               transition: float = 0.45, music: str | Path | None = None,
               music_gain: float = 0.20) -> Path:
    """HYBRID build: each slide goes to Chrome (fast, free, deterministic) EXCEPT kind="math", which
    goes to Manim (the ~20% CSS can't do). Slides are narrated beat-by-beat with the spoken element
    highlighted, then crossfaded together. Returns the final mp4.

    `music` lays a ducked bed under the narration. `narrate=False` gives fixed-duration silent frames,
    and `audio` then REPLACES the whole track (kept for the silent path). `transition=0` hard-cuts."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    clips = [_slide_clip(s, out_dir, i, footer=footer, seconds=seconds, fps=fps, narrate=narrate,
                         tts_engine=tts_engine, math_quality=math_quality)
             for i, s in enumerate(slides)]
    out = out_dir / "deck.mp4"
    stitched = out if not music else out_dir / "voice.mp4"
    if transition > 0 and len(clips) > 1:
        faded = _xfade_chain(clips, out_dir / "faded.mp4", dur=transition)
        if audio:
            _concat_clips([faded], stitched, audio=audio)
        else:
            shutil.move(str(faded), str(stitched))
    else:
        _concat_clips(clips, stitched, audio=audio)
    if music:
        _mix_music(stitched, music, out, gain=music_gain)
    return out
