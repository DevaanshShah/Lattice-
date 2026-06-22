"""M4 unit tests — host-side TTS synth + cache (T-10). No network: synth/duration faked."""
import pytest


@pytest.mark.unit
def test_synthesize_caches_second_call(tmp_path, monkeypatch):
    from narration import tts

    calls = {"n": 0}

    def fake_synth(text, out_path, *, lang="en"):
        calls["n"] += 1
        from pathlib import Path
        Path(out_path).write_bytes(b"fake-mp3")

    monkeypatch.setattr(tts, "_synth_gtts", fake_synth)
    monkeypatch.setattr(tts, "_duration", lambda p: 1.5)

    c1 = tts.synthesize("hello world", out_dir=tmp_path)
    c2 = tts.synthesize("hello world", out_dir=tmp_path)   # same text -> cache hit
    assert calls["n"] == 1                                  # synthesized once, reused
    assert c1.path == c2.path and c1.duration == 1.5 and c1.path.exists()


@pytest.mark.unit
def test_different_text_different_file(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_synth_gtts",
                        lambda text, out_path, **k: out_path.write_bytes(b"x"))
    monkeypatch.setattr(tts, "_duration", lambda p: 1.0)
    a = tts.synthesize("alpha", out_dir=tmp_path)
    b = tts.synthesize("beta", out_dir=tmp_path)
    assert a.path != b.path


@pytest.mark.unit
def test_synthesize_lines_returns_clip_per_line(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_synth_gtts",
                        lambda text, out_path, **k: out_path.write_bytes(b"x"))
    monkeypatch.setattr(tts, "_duration", lambda p: 2.0)
    clips = tts.synthesize_lines(["one", "two", "three"], out_dir=tmp_path)
    assert len(clips) == 3 and all(c.duration == 2.0 for c in clips)


@pytest.mark.unit
def test_unknown_engine_raises(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_duration", lambda p: 1.0)
    with pytest.raises(ValueError):
        tts.synthesize("x", out_dir=tmp_path, engine="bogus")
