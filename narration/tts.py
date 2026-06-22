"""FR-10 — TTS synthesis, HOST-SIDE (so the render sandbox stays no-network).

The render container runs model code with `--network=none`; gTTS needs the network. We resolve
that by synthesizing audio HERE (trusted host step, network available), caching it by content
hash, and handing the files to the no-net render to play via Manim's `add_sound`. This is the
same secure split M7 wants — TTS = trusted networked step, render = untrusted no-net step.

The engine is swappable (gtts now; OpenAI/Azure later) behind one function — that seam is what
makes FR-33 (voice swap) and FR-34 (multi-language) cheap later.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.cache import content_hash
from core.config import settings


@dataclass
class Clip:
    text: str
    path: Path
    duration: float   # seconds (measured, used to sync/pad the animation)


def _synth_gtts(text: str, out_path: Path, *, lang: str = "en") -> None:
    from gtts import gTTS  # lazy: only needed at synth time, and only on the host
    gTTS(text=text, lang=lang).save(str(out_path))


def _duration(path: Path) -> float:
    from mutagen.mp3 import MP3  # pure-python, no network
    return float(MP3(str(path)).info.length)


def synthesize(text: str, *, out_dir: str | Path, engine: str | None = None,
               lang: str = "en", cache: bool = True) -> Clip:
    """Synthesize one line to an MP3 (cached by content hash) and measure its duration."""
    engine = engine or settings.tts_engine
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = content_hash("tts-v1", engine, lang, text)
    path = out_dir / f"{key}.mp3"

    if not (cache and path.exists()):
        if engine == "gtts":
            _synth_gtts(text, path, lang=lang)
        else:
            raise ValueError(f"unknown TTS engine: {engine!r}")
    return Clip(text, path, _duration(path))


def synthesize_lines(lines: list[str], *, out_dir: str | Path, engine: str | None = None,
                     lang: str = "en") -> list[Clip]:
    return [synthesize(line, out_dir=out_dir, engine=engine, lang=lang) for line in lines]
