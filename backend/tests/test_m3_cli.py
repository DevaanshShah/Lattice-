"""M3 unit tests — generate-scene CLI (T-6). No network/docker: the pipeline is injected.

Assert the DoD: first run executes the pipeline and caches; the same prompt is a cache hit
(pipeline NOT called again); --no-cache forces a re-run; different prompts don't collide.
"""
from pathlib import Path

import pytest


class _Res:
    def __init__(self, mp4, passed=True, score=90):
        self.mp4 = mp4
        self.passed = passed
        self._s = score

    def score(self):
        return self._s


class _PR:
    def __init__(self, result):
        self.result = result


def _mp4(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00video")
    return p


@pytest.mark.unit
def test_first_run_executes_then_second_is_cache_hit(tmp_path):
    from cli.__main__ import generate_scene
    from core.cache import Cache

    mp4 = _mp4(tmp_path)
    calls = {"n": 0}

    def fake_pipeline(prompt, **kw):
        calls["n"] += 1
        return _PR(_Res(mp4, passed=True, score=88))

    cache = Cache(tmp_path / "cache")
    r1 = generate_scene("explain X", cache=cache, pipeline=fake_pipeline,
                        out_dir=tmp_path / "o", log=lambda m: None)
    assert calls["n"] == 1 and r1["cached"] is False and Path(r1["mp4"]).exists()

    r2 = generate_scene("explain X", cache=cache, pipeline=fake_pipeline,
                        out_dir=tmp_path / "o", log=lambda m: None)
    assert calls["n"] == 1            # pipeline NOT called again — full cache hit
    assert r2["cached"] is True and r2["mp4"] == r1["mp4"]


@pytest.mark.unit
def test_no_cache_forces_rerun(tmp_path):
    from cli.__main__ import generate_scene
    from core.cache import Cache

    mp4 = _mp4(tmp_path)
    calls = {"n": 0}

    def fake_pipeline(prompt, **kw):
        calls["n"] += 1
        return _PR(_Res(mp4))

    cache = Cache(tmp_path / "cache")
    generate_scene("p", cache=cache, pipeline=fake_pipeline, out_dir=tmp_path / "o", log=lambda m: None)
    generate_scene("p", cache=cache, pipeline=fake_pipeline, no_cache=True,
                   out_dir=tmp_path / "o", log=lambda m: None)
    assert calls["n"] == 2            # --no-cache bypasses the hit


@pytest.mark.unit
def test_different_prompts_do_not_collide(tmp_path):
    from cli.__main__ import generate_scene
    from core.cache import Cache

    mp4 = _mp4(tmp_path)
    calls = {"n": 0}

    def fake_pipeline(prompt, **kw):
        calls["n"] += 1
        return _PR(_Res(mp4))

    cache = Cache(tmp_path / "cache")
    generate_scene("a", cache=cache, pipeline=fake_pipeline, out_dir=tmp_path / "o", log=lambda m: None)
    generate_scene("b", cache=cache, pipeline=fake_pipeline, out_dir=tmp_path / "o", log=lambda m: None)
    assert calls["n"] == 2            # different prompt -> different key -> both run
