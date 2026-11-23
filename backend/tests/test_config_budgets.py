"""Phase B — every bound that can extend a build is CONFIGURATION, not a literal.

The failure this guards against: `.env` says LATTICE_SCENE_WORKERS=6, the code says `workers=3`,
and the operator tunes a knob that was never wired to anything. Each test moves a setting and
asserts the runtime moved with it. No network, no docker, no model.
"""
import pytest

from core.config import settings


# --- scene fan-out + whole-scene retry budget -------------------------------------------------
@pytest.mark.unit
def test_build_video_takes_workers_and_retries_from_settings(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from composition import decoupled
    from core.schemas.outline import Outline, OutlineItem
    from core.schemas.style import StyleSpec

    seen = {}

    class RecordingPool(ThreadPoolExecutor):
        def __init__(self, max_workers=None, **kw):
            seen["workers"] = max_workers
            super().__init__(max_workers=max_workers, **kw)

    clip = tmp_path / "scene.mp4"
    clip.write_bytes(b"v")
    monkeypatch.setattr(decoupled, "ThreadPoolExecutor", RecordingPool)
    monkeypatch.setattr(decoupled, "_build_with_retry",
                        lambda item, outline, index, **kw: (seen.__setitem__("retries", kw["retries"]),
                                                            (index, clip))[1])
    monkeypatch.setattr(decoupled.stitch, "stitch",
                        lambda clips, *, work_dir, out_name: tmp_path / out_name)
    monkeypatch.setattr(settings, "scene_workers", 5)
    monkeypatch.setattr(settings, "scene_retries", 2)

    outline = Outline(topic="t", items=[OutlineItem(title="A", intent="x")])
    decoupled.build_video("t", outline=outline, style=StyleSpec(palette={"primary": "#111"}),
                          client=object(), out_dir=tmp_path, log=lambda _m: None)

    assert seen["workers"] == 5      # LATTICE_SCENE_WORKERS, not the old literal 3
    assert seen["retries"] == 2      # LATTICE_SCENE_RETRIES, not the old literal 3


@pytest.mark.unit
def test_build_video_explicit_args_still_override_settings(monkeypatch, tmp_path):
    """An eval or test must still be able to pin the fan-out for one call."""
    from concurrent.futures import ThreadPoolExecutor
    from composition import decoupled
    from core.schemas.outline import Outline, OutlineItem
    from core.schemas.style import StyleSpec

    seen = {}

    class RecordingPool(ThreadPoolExecutor):
        def __init__(self, max_workers=None, **kw):
            seen["workers"] = max_workers
            super().__init__(max_workers=max_workers, **kw)

    monkeypatch.setattr(decoupled, "ThreadPoolExecutor", RecordingPool)
    monkeypatch.setattr(decoupled, "_build_with_retry", lambda item, outline, index, **kw: (index, None))
    monkeypatch.setattr(settings, "scene_workers", 5)

    outline = Outline(topic="t", items=[OutlineItem(title="A", intent="x")])
    decoupled.build_video("t", outline=outline, style=StyleSpec(palette={"primary": "#111"}),
                          client=object(), out_dir=tmp_path, workers=1, log=lambda _m: None)
    assert seen["workers"] == 1


@pytest.mark.unit
def test_scene_retry_does_not_sleep_after_the_last_attempt(monkeypatch, tmp_path):
    """The backoff rides out a provider 500-streak between attempts; after the final attempt
    there is nothing left to wait for, so sleeping there is pure dead time on a failed job."""
    from composition import decoupled

    slept = []
    monkeypatch.setattr(decoupled.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(decoupled, "build_scene",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(settings, "scene_retry_backoff_s", 0.5)

    index, mp4 = decoupled._build_with_retry(
        object(), object(), 0, scenes_dir=tmp_path, client=object(), style=None,
        use_components=True, use_critic=False, structural=True, quality="preview",
        retries=3, on_scene=None)

    assert mp4 is None
    assert slept == [0.5, 0.5]       # 3 attempts -> 2 gaps, not 3


# --- web job pool -----------------------------------------------------------------------------
@pytest.mark.unit
def test_job_queue_workers_come_from_settings(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from web import app as app_mod

    seen = {}

    class FakeQueue:
        def __init__(self, *, workers=None, **kw):
            seen["workers"] = workers

    monkeypatch.setattr(app_mod.jobs_mod, "JobQueue", FakeQueue)
    monkeypatch.setattr(settings, "job_workers", 4)
    app_mod.create_app(engine=SimpleNamespace(root=tmp_path))   # deck/learn routes only need .root
    assert seen["workers"] == 4      # LATTICE_JOB_WORKERS, not the old literal 2


# --- one model call: a real deadline, and exactly one retry authority -------------------------
@pytest.mark.unit
def test_llm_client_gets_a_timeout_and_no_hidden_sdk_retries(monkeypatch):
    """Without timeout= the SDK waits on its own 10-minute default before our retry policy runs.
    With the SDK's max_retries left at its default, its retries would multiply with ours."""
    import openai
    from core.llm import LLMClient

    seen = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: seen.update(kw) or object())
    monkeypatch.setattr(settings, "llm_timeout_s", 42.0)

    LLMClient(model="m").client
    assert seen["timeout"] == 42.0
    assert seen["max_retries"] == 0   # _create is the ONLY retry loop


@pytest.mark.unit
def test_transient_retry_count_comes_from_settings(monkeypatch):
    from core import llm as llm_mod

    class APIConnectionError(Exception):   # _is_transient matches on the type NAME
        pass

    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)
            raise APIConnectionError("dropped")

    fake = type("C", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(settings, "llm_attempts", 3)

    c = llm_mod.LLMClient(model="m")
    c._client = fake
    with pytest.raises(APIConnectionError):
        c._create(messages=[{"role": "user", "content": "hi"}], model="m")
    assert len(calls) == 3           # LATTICE_LLM_ATTEMPTS, not the old literal 6


@pytest.mark.unit
def test_openrouter_calls_sort_their_fallbacks_and_leave_out_low_precision_hosts(monkeypatch):
    """Live 2026-11-23: the pinned provider no longer served the model, so every call fell back
    to whichever of ~37 hosts came up, fp4 ones among them, and long lessons came back with every
    list of ids empty. A pin now still sorts its fallbacks, and low-precision hosts are left out."""
    from types import SimpleNamespace

    from core import llm as llm_mod
    from core.config import settings

    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=None)

    monkeypatch.setattr(settings, "llm_provider_pin", "DeepSeek")
    monkeypatch.setattr(settings, "llm_provider_sort", "throughput")
    monkeypatch.setattr(settings, "llm_provider_quantizations", "fp8,bf16")
    c = llm_mod.LLMClient(base_url="https://openrouter.ai/api/v1", model="m")
    c._client = type("C", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    c._create(messages=[{"role": "user", "content": "hi"}], model="m")
    provider = calls[0]["extra_body"]["provider"]
    assert provider["order"] == ["DeepSeek"] and provider["allow_fallbacks"] is True
    assert provider["sort"] == "throughput" and provider["quantizations"] == ["fp8", "bf16"]
    monkeypatch.setattr(settings, "llm_provider_quantizations", "")
    c._create(messages=[{"role": "user", "content": "hi"}], model="m")
    assert "quantizations" not in calls[1]["extra_body"]["provider"]
