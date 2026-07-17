"""M4 unit tests — host-side TTS synth + cache (T-10). No network: synth/duration faked.

These pin engine="gtts" rather than letting `synthesize` fall back to settings.tts_engine. The default
is gtts, but LATTICE_TTS_ENGINE in a real .env overrides it — so on a machine set to kokoro these mocked
_synth_gtts and ran the actual local neural model instead. The cache test caught it by failing; the
other two just quietly stopped testing what they claim to.
"""
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

    c1 = tts.synthesize("hello world", out_dir=tmp_path, engine="gtts")
    c2 = tts.synthesize("hello world", out_dir=tmp_path, engine="gtts")   # same text -> cache hit
    assert calls["n"] == 1                                  # synthesized once, reused
    assert c1.path == c2.path and c1.duration == 1.5 and c1.path.exists()


@pytest.mark.unit
def test_different_text_different_file(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_synth_gtts",
                        lambda text, out_path, **k: out_path.write_bytes(b"x"))
    monkeypatch.setattr(tts, "_duration", lambda p: 1.0)
    a = tts.synthesize("alpha", out_dir=tmp_path, engine="gtts")
    b = tts.synthesize("beta", out_dir=tmp_path, engine="gtts")
    assert a.path != b.path


@pytest.mark.unit
def test_synthesize_lines_returns_clip_per_line(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_synth_gtts",
                        lambda text, out_path, **k: out_path.write_bytes(b"x"))
    monkeypatch.setattr(tts, "_duration", lambda p: 2.0)
    clips = tts.synthesize_lines(["one", "two", "three"], out_dir=tmp_path, engine="gtts")
    assert len(clips) == 3 and all(c.duration == 2.0 for c in clips)


@pytest.mark.unit
def test_engine_defaults_to_configured_engine(tmp_path, monkeypatch):
    """The bug the pinning above hides: an unpinned call follows settings, whatever the .env says."""
    from narration import tts
    seen = {}
    monkeypatch.setattr(tts.settings, "tts_engine", "gtts")
    monkeypatch.setattr(tts, "_synth_gtts",
                        lambda text, out_path, **k: (seen.setdefault("engine", "gtts"),
                                                     out_path.write_bytes(b"x")))
    monkeypatch.setattr(tts, "_duration", lambda p: 1.0)
    tts.synthesize("hello", out_dir=tmp_path)
    assert seen["engine"] == "gtts"


@pytest.mark.unit
def test_unknown_engine_raises(tmp_path, monkeypatch):
    from narration import tts
    monkeypatch.setattr(tts, "_duration", lambda p: 1.0)
    with pytest.raises(ValueError):
        tts.synthesize("x", out_dir=tmp_path, engine="bogus")
