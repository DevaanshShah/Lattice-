"""Render a code-walkthrough scene through the DETERMINISTIC scaffold.

Each scene is the full snippet with one line highlighted (generation.code_scaffold) + spoken narration.
This reuses the pipeline's own primitives — compile_repair (render), narration.tts (gTTS), and
decoupled.mux_audio (ffmpeg mux) — writing the same `narrated.mp4` layout the engine's stitch expects,
but with NO codegen LLM call (the layout is fixed). Engine._build_walkthrough drives this per scene and
then restitches, exactly like the freeform build.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from composition.decoupled import mux_audio
from generation import code_scaffold
from narration import tts
from verification import compile_repair


def narration_seconds(text: str) -> float:
    """Hold long enough for the spoken line to finish (~2.6 words/s + buffer), clamped to a sane range,
    so the muxed audio is never cut short and short lines don't drag."""
    words = len((text or "").split())
    return max(3.5, min(14.0, words / 2.6 + 1.2))


def render_scene(work_dir: str | Path, *, lines: list[str], active: list[int], caption: str,
                 title: str, narration: str, quality: str = "preview", log=None) -> Path | None:
    """Render one walkthrough scene -> work_dir/narrated.mp4. Returns the path, or None if the (fixed,
    should-always-compile) scaffold somehow fails to render."""
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    seconds = narration_seconds(narration)
    code = code_scaffold.render_scene_code(lines, active, caption, title, seconds)
    (wd / "scene.py").write_text(code, encoding="utf-8")

    rep = compile_repair.repair(code, wd, quality=quality, log=lambda _m: None)
    if not rep.ok or not rep.mp4:
        say(f"[walkthrough] scaffold render failed: {(rep.error or '')[:160]}")
        return None

    narration = (narration or "").strip()
    (wd / "narration.txt").write_text(narration or "(no narration)", encoding="utf-8")
    narrated = wd / "narrated.mp4"
    video_rel = Path(rep.mp4).resolve().relative_to(wd.resolve()).as_posix()
    try:
        if not narration:
            raise RuntimeError("empty narration")
        clip = tts.synthesize(narration, out_dir=wd)
        audio_rel = Path(clip.path).resolve().relative_to(wd.resolve()).as_posix()
        if not mux_audio(wd, video_rel, audio_rel, "narrated.mp4"):
            raise RuntimeError("mux failed")
        return narrated
    except Exception as e:  # noqa: BLE001 — a TTS/mux hiccup must not lose a good silent render
        say(f"[walkthrough] narration/mux skipped ({type(e).__name__}); shipping silent scene")
        shutil.copyfile(rep.mp4, narrated)
        return narrated
