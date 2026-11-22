"""The deploy preflight: does it catch the misconfigurations that fail late and quietly?

Each of these corresponds to a way this app breaks in production without saying so at boot —
silent videos, an OOM-killed container, an admin console nobody can reach, videos that die with
the container.
"""
import pytest

from core.config import settings
from scripts import preflight as pf


@pytest.mark.unit
@pytest.mark.parametrize("text, gib", [
    ("2g", 2.0), ("1500m", 1500 / 1024), ("512k", 512 / 1024 / 1024),
    ("2G", 2.0), ("1073741824", 1.0), ("", None), ("lots", None),
])
def test_parse_size(text, gib):
    got = pf.parse_size(text)
    assert got is None if gib is None else abs(got - gib) < 1e-9


@pytest.mark.unit
def test_worst_case_renders_multiplies_the_two_knobs(monkeypatch):
    """The sizing trap: it is jobs TIMES scenes, not whichever number you happened to read."""
    monkeypatch.setattr(settings, "job_workers", 2)
    monkeypatch.setattr(settings, "scene_workers", 3)
    assert pf.worst_case_renders() == 6


@pytest.mark.unit
def test_memory_check_fails_when_the_knobs_oversubscribe_the_box(monkeypatch):
    monkeypatch.setattr(settings, "job_workers", 2)
    monkeypatch.setattr(settings, "scene_workers", 3)
    monkeypatch.setattr(settings, "render_memory", "2g")
    c = pf.memory_check(4.0)                       # 12 GiB of renders on a 4 GiB box
    assert c.level == pf.FAIL
    assert "12.0 GiB" in c.detail and "4.0 GiB" in c.detail
    assert "LATTICE_JOB_WORKERS" in c.detail       # names the knob to turn, not just the problem


@pytest.mark.unit
def test_memory_check_warns_when_it_only_just_fits(monkeypatch):
    monkeypatch.setattr(settings, "job_workers", 1)
    monkeypatch.setattr(settings, "scene_workers", 2)
    monkeypatch.setattr(settings, "render_memory", "2g")
    assert pf.memory_check(4.5).level == pf.WARN    # 4 of 4.5 GiB leaves nothing for the web process
    assert pf.memory_check(8.0).level == pf.OK


@pytest.mark.unit
def test_memory_check_degrades_to_a_warning_when_the_limit_is_unknown():
    assert pf.memory_check(None).level == pf.WARN   # a Windows dev box, not a failure


@pytest.mark.unit
def test_missing_voice_models_are_a_failure_not_a_footnote(monkeypatch, tmp_path):
    """Without the files, narration raises and every scene ships SILENT — the product still
    'works', which is exactly why this has to be loud."""
    monkeypatch.setattr(settings, "tts_engine", "kokoro")
    monkeypatch.setattr(settings, "kokoro_model", str(tmp_path / "nope.onnx"))
    monkeypatch.setattr(settings, "kokoro_voices", str(tmp_path / "nope.bin"))
    c = pf.check_voice()[0]
    assert c.level == pf.FAIL and "SILENT" in c.detail


@pytest.mark.unit
def test_half_configured_object_storage_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "out_dir", tmp_path)
    monkeypatch.setattr(settings, "r2_account_id", "acct")
    monkeypatch.setattr(settings, "r2_bucket", "vids")
    monkeypatch.setattr(settings, "r2_access_key_id", "")
    monkeypatch.setattr(settings, "r2_secret_access_key", "")
    storage = pf.check_storage()[0]
    assert storage.level == pf.FAIL
    assert "r2_access_key_id" in storage.detail or "key" in storage.detail


@pytest.mark.unit
def test_no_object_storage_warns_that_videos_die_with_the_container(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "out_dir", tmp_path)
    for f in ("r2_account_id", "r2_bucket", "r2_access_key_id", "r2_secret_access_key"):
        monkeypatch.setattr(settings, f, "")
    assert pf.check_storage()[0].level == pf.WARN


@pytest.mark.unit
def test_unwritable_state_directory_fails(monkeypatch, tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(settings, "out_dir", blocker / "out")
    assert [c for c in pf.check_storage() if c.name == "state directory"][0].level == pf.FAIL


@pytest.mark.unit
def test_admin_token_warnings(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    assert pf.check_admin()[0].level == pf.WARN      # loopback-only == unreachable on a server
    monkeypatch.setattr(settings, "admin_token", "short")
    assert pf.check_admin()[0].level == pf.WARN
    monkeypatch.setattr(settings, "admin_token", "x" * 32)
    assert pf.check_admin()[0].level == pf.OK


@pytest.mark.unit
def test_missing_model_key_fails(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "   ")
    assert pf.check_model()[0].level == pf.FAIL


@pytest.mark.unit
def test_local_exec_mode_always_warns_that_it_is_not_a_sandbox(monkeypatch):
    monkeypatch.setattr(settings, "exec_mode", "local")
    monkeypatch.setattr(pf.shutil, "which", lambda t: "/usr/bin/" + t)
    levels = {c.name: c for c in pf.check_execution()}
    assert levels["local toolchain"].level == pf.OK
    assert levels["sandbox"].level == pf.WARN and "NOT a sandbox" not in levels["sandbox"].detail
    assert "filesystem and network" in levels["sandbox"].detail


@pytest.mark.unit
def test_docker_mode_fails_without_a_daemon(monkeypatch):
    monkeypatch.setattr(settings, "exec_mode", "docker")
    monkeypatch.setattr(pf, "_docker_reachable", lambda: False)
    c = pf.check_execution()[0]
    assert c.level == pf.FAIL and "LATTICE_EXEC_MODE=local" in c.detail


@pytest.mark.unit
def test_docker_mode_fails_when_the_render_image_is_absent(monkeypatch):
    monkeypatch.setattr(settings, "exec_mode", "docker")
    monkeypatch.setattr(pf, "_docker_reachable", lambda: True)
    monkeypatch.setattr(pf, "_image_present", lambda image: False)
    names = {c.name: c for c in pf.check_execution()}
    assert names["render image"].level == pf.FAIL
    assert "docker build" in names["render image"].detail


@pytest.mark.unit
def test_run_returns_every_check_and_main_exit_code_counts_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "out_dir", tmp_path)
    monkeypatch.setattr(pf, "_docker_reachable", lambda: True)
    monkeypatch.setattr(pf, "_image_present", lambda image: True)
    checks = pf.run()
    assert {"model key", "voice", "object storage", "state directory", "admin console",
            "job deadline", "memory budget"} <= {c.name for c in checks}
    assert all(c.level in (pf.OK, pf.WARN, pf.FAIL) for c in checks)

    monkeypatch.setattr(pf, "run", lambda: [pf.Check("a", pf.FAIL), pf.Check("b", pf.OK)])
    assert pf.main() == 1


# --- host tools and access (the gaps the first real deploy found) ---------------------------
@pytest.mark.unit
def test_a_box_without_ffmpeg_fails_even_in_docker_mode(monkeypatch):
    """The first deploy passed preflight and could not build a video: slides and stitching call
    ffmpeg on the HOST, which docker mode does not cover."""
    monkeypatch.setattr(pf.shutil, "which", lambda name: None)
    c = {x.name: x for x in pf.check_host_tools()}["ffmpeg"]
    assert c.level == pf.FAIL and "ffmpeg" in c.detail and "ffprobe" in c.detail
    monkeypatch.setattr(pf.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert {x.name: x for x in pf.check_host_tools()}["ffmpeg"].level == pf.OK


@pytest.mark.unit
def test_a_box_without_chrome_fails_and_says_how_to_fix_it(monkeypatch):
    import composition.slides as slides

    def none():
        raise slides.SlideRenderError("no Chrome/Chromium found")
    monkeypatch.setattr(slides, "chrome_path", none)
    c = {x.name: x for x in pf.check_host_tools()}["chrome"]
    assert c.level == pf.FAIL and "google-chrome-stable" in c.detail and "LATTICE_CHROME" in c.detail
    monkeypatch.setattr(slides, "chrome_path", lambda: "/usr/bin/google-chrome")
    assert {x.name: x for x in pf.check_host_tools()}["chrome"].level == pf.OK


@pytest.mark.unit
def test_a_box_without_the_playwright_package_fails(monkeypatch):
    import builtins
    real = builtins.__import__

    def deny(name, *a, **k):
        if name == "playwright":
            raise ImportError("no playwright")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", deny)
    c = {x.name: x for x in pf.check_host_tools()}["playwright"]
    assert c.level == pf.FAIL and "requirements.txt" in c.detail


@pytest.mark.unit
def test_sign_in_off_is_a_warning_not_silence(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    c = pf.check_access()
    assert [x.name for x in c] == ["sign-in"] and c[0].level == pf.WARN


@pytest.mark.unit
def test_open_sign_in_without_a_global_ceiling_is_called_out(monkeypatch):
    for k, v in dict(supabase_url="https://p.supabase.co", supabase_anon_key="k",
                     public_url="https://x.example", auth_allowed_emails="",
                     quota_global_spend_usd_per_day=0.0).items():
        monkeypatch.setattr(settings, k, v)
    c = {x.name: x for x in pf.check_access()}
    assert c["spend ceiling"].level == pf.WARN and "LATTICE_QUOTA_GLOBAL_SPEND_USD_PER_DAY" in c["spend ceiling"].detail
    monkeypatch.setattr(settings, "quota_global_spend_usd_per_day", 3.0)
    c = {x.name: x for x in pf.check_access()}
    assert "$3" in c["invite list"].detail and "spend ceiling" not in c
    monkeypatch.setattr(settings, "auth_allowed_emails", "a@b.com")
    assert {x.name: x for x in pf.check_access()}["invite list"].level == pf.OK


@pytest.mark.unit
def test_a_missing_public_url_with_sign_in_on_warns(monkeypatch):
    for k, v in dict(supabase_url="https://p.supabase.co", supabase_anon_key="k", public_url="").items():
        monkeypatch.setattr(settings, k, v)
    assert {x.name: x for x in pf.check_access()}["public url"].level == pf.WARN
