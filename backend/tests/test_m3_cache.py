"""M3 unit tests — content-hash cache (T-8). No network/docker.

Assert the DoD: keys are deterministic, a spec change busts the render key, JSON key reorder
does NOT, and save/has/load round-trips (copying the artifact into the cache).
"""
import pytest


@pytest.mark.unit
def test_content_hash_deterministic_and_sensitive():
    from core.cache import content_hash
    assert content_hash("a", "b") == content_hash("a", "b")      # deterministic
    assert content_hash("a", "b") != content_hash("b", "a")      # order matters
    assert content_hash("a", "b") != content_hash("ab", "")      # NUL-separated, no collision


@pytest.mark.unit
def test_spec_key_changes_with_prompt_and_model():
    from core.cache import spec_key
    base = spec_key("explain X", model="m1")
    assert spec_key("explain X", model="m1") == base            # same -> same
    assert spec_key("explain Y", model="m1") != base            # prompt change busts
    assert spec_key("explain X", model="m2") != base            # model change busts


@pytest.mark.unit
def test_render_key_ignores_json_reordering_but_not_content():
    from core.cache import render_key
    a = render_key('{"title":"T","narration":"N"}', model="m", quality="preview")
    reordered = render_key('{"narration":"N","title":"T"}', model="m", quality="preview")
    changed = render_key('{"title":"T2","narration":"N"}', model="m", quality="preview")
    quality = render_key('{"title":"T","narration":"N"}', model="m", quality="final")
    assert a == reordered      # trivial reordering/whitespace reuses the cache
    assert a != changed        # a meaningful spec change busts it
    assert a != quality        # quality is part of the key


@pytest.mark.unit
def test_cache_save_has_load_roundtrip_with_artifact(tmp_path):
    from core.cache import Cache
    mp4 = tmp_path / "scene.mp4"
    mp4.write_bytes(b"\x00\x01video")
    cache = Cache(tmp_path / "cache")

    assert cache.has("k1") is False
    stored = cache.save("k1", {"prompt": "p", "score": 90}, copy={"mp4": mp4})
    assert cache.has("k1") is True

    man = cache.load("k1")
    assert man["prompt"] == "p" and man["score"] == 90
    # the manifest points at the COPY inside the cache, and the bytes survived
    from pathlib import Path
    assert Path(man["mp4"]).exists() and Path(man["mp4"]).read_bytes() == b"\x00\x01video"
    assert Path(man["mp4"]) != mp4


@pytest.mark.unit
def test_cache_miss_returns_none(tmp_path):
    from core.cache import Cache
    assert Cache(tmp_path / "c").load("nope") is None
