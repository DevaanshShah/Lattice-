"""Clip durations drive the narration timing, so they must be exact, for both voice engines' formats."""
import shutil
import subprocess

import pytest
import soundfile as sf

from narration.tts import _duration


@pytest.mark.parametrize("seconds", [1.0, 2.5, 7.25])
def test_wav_duration_is_exact(tmp_path, seconds):
    p = tmp_path / "c.wav"
    sf.write(str(p), [0.0] * int(24000 * seconds), 24000)
    assert abs(_duration(p) - seconds) < 0.001


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed to make an MP3")
@pytest.mark.parametrize("seconds", [1.0, 2.5, 7.25])
def test_mp3_duration_is_exact_not_padded(tmp_path, seconds):
    """gTTS writes MP3. The old reader (mutagen) counted encoder padding and ran ~60 ms long."""
    p = tmp_path / "c.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-ar", "24000", "-ac", "1", "-b:a", "64k", str(p), "-y"], check=True)
    assert abs(_duration(p) - seconds) < 0.01


def test_no_gpl_audio_dependency_is_needed():
    import narration.tts as tts
    code = [ln for ln in open(tts.__file__, encoding="utf-8").read().splitlines() if "import" in ln]
    assert not any("mutagen" in ln for ln in code)                     # no import left, only the explanation
    assert "mutagen" not in open("requirements.txt", encoding="utf-8").read()
