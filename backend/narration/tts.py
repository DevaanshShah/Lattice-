"""FR-10 — TTS synthesis, HOST-SIDE (so the render sandbox stays no-network).

The render container runs model code with `--network=none`; gTTS needs the network. We resolve
that by synthesizing audio HERE (trusted host step, network available), caching it by content
hash, and handing the files to the no-net render to play via Manim's `add_sound`. This is the
same secure split M7 wants — TTS = trusted networked step, render = untrusted no-net step.

The engine is swappable (gtts now; OpenAI/Azure later) behind one function — that seam is what
makes FR-33 (voice swap) and FR-34 (multi-language) cheap later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.cache import content_hash
from core.config import settings


@dataclass
class Clip:
    text: str
    path: Path
    duration: float   # seconds (measured, used to sync/pad the animation)


# gTTS has no NLP context — it reads jargon phonetically wrong ("bigram" -> "bee-gram",
# "n-gram" -> "n gram"). We rewrite ONLY the audio input to a phonetic spelling; the saved/
# on-screen script keeps the correct spelling. Ordered longest-first so "bigrams" wins over "bigram".
_PRONUNCIATION: list[tuple[str, str]] = [
    (r"\bn-?grams\b", "en-grams"),   (r"\bn-?gram\b", "en-gram"),
    (r"\bbigrams\b", "by-grams"),    (r"\bbigram\b", "by-gram"),
    (r"\btrigrams\b", "try-grams"),  (r"\btrigram\b", "try-gram"),
    (r"\bunigrams\b", "you-nih-grams"), (r"\bunigram\b", "you-nih-gram"),
]


def _for_speech(text: str) -> str:
    """Phonetic rewrite of terms gTTS mispronounces (audio only, not the displayed script)."""
    out = text
    for pat, rep in _PRONUNCIATION:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out


def _synth_gtts(text: str, out_path: Path, *, lang: str = "en") -> None:
    from gtts import gTTS  # lazy: only needed at synth time, and only on the host
    gTTS(text=text, lang=lang).save(str(out_path))


_KOKORO = None  # Kokoro model is loaded ONCE (a few hundred MB) and reused across every line.


def _synth_kokoro(text: str, out_path: Path, *, lang: str = "en") -> None:
    """Local, offline, free neural TTS (Kokoro-82M via onnxruntime). Writes a WAV. Requires
    `pip install kokoro-onnx soundfile` and the model files at settings.kokoro_model/kokoro_voices."""
    import soundfile as sf
    from kokoro_onnx import Kokoro
    global _KOKORO
    if _KOKORO is None:
        _KOKORO = Kokoro(settings.kokoro_model, settings.kokoro_voices)
    samples, sr = _KOKORO.create(text, voice=settings.kokoro_voice, speed=settings.kokoro_speed,
                                 lang="en-us" if lang == "en" else lang)
    sf.write(str(out_path), samples, sr)


def _duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        import soundfile as sf  # pure-python, no network
        info = sf.info(str(path))
        return float(info.frames) / float(info.samplerate)
    from mutagen.mp3 import MP3  # pure-python, no network
    return float(MP3(str(path)).info.length)


def synthesize(text: str, *, out_dir: str | Path, engine: str | None = None,
               lang: str = "en", cache: bool = True) -> Clip:
    """Synthesize one line to an MP3 (cached by content hash) and measure its duration."""
    engine = engine or settings.tts_engine
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    speech = _for_speech(text)  # phonetic rewrite for the audio; display text stays original
    key = content_hash("tts-v2", engine, lang, settings.kokoro_voice if engine == "kokoro" else "", speech)
    ext = "wav" if engine == "kokoro" else "mp3"     # kokoro emits raw samples -> WAV; gtts -> MP3
    path = out_dir / f"{key}.{ext}"

    if not (cache and path.exists()):
        if engine == "gtts":
            _synth_gtts(speech, path, lang=lang)
        elif engine == "kokoro":
            _synth_kokoro(speech, path, lang=lang)
        else:
            raise ValueError(f"unknown TTS engine: {engine!r}")
    return Clip(text, path, _duration(path))


def synthesize_lines(lines: list[str], *, out_dir: str | Path, engine: str | None = None,
                     lang: str = "en") -> list[Clip]:
    return [synthesize(line, out_dir=out_dir, engine=engine, lang=lang) for line in lines]
