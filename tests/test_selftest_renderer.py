import subprocess
from types import SimpleNamespace

import pytest

from core.config import settings
from scripts import selftest


@pytest.mark.unit
def test_missing_docker_stops_the_legacy_run_but_only_warns_for_browser_v2(monkeypatch):
    monkeypatch.setattr(settings, "exec_mode", "docker")
    monkeypatch.setattr(selftest.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "daemon not running"))
    legacy, browser = selftest.Report("t"), selftest.Report("t")
    assert selftest._docker_ok(legacy) is False
    assert [check.name for check in legacy.critical_failed] == ["docker daemon reachable"]
    assert selftest._docker_ok(browser, critical=False) is True
    assert browser.passed and [check.name for check in browser.warnings] == ["docker daemon reachable"]


@pytest.mark.unit
def test_browser_v2_grade_checks_the_requested_length_instead_of_a_theme(monkeypatch, tmp_path):
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    final = tmp_path / "browser-video.mp4"
    final.write_bytes(b"0" * 20_000)
    clips = []
    for index in range(2):
        clip = tmp_path / f"scene_{index:02d}.mp4"
        clip.write_bytes(b"0")
        clips.append(SimpleNamespace(index=index, mp4=str(clip), script=["Order 42 is validated."]))
    project = SimpleNamespace(scenes=clips, target_seconds=60, style=None)
    probed = []

    def fake_duration(work_dir, mp4, *, host=False):
        probed.append(host)
        return 16.0 if mp4 == final else 8.0

    monkeypatch.setattr(selftest, "_duration", fake_duration)
    report = selftest.Report("t")
    selftest.grade(report, project, tmp_path, final, renderer="browser_v2")
    names = {check.name: check for check in report.checks}
    assert all(probed)                                   # every probe ran on the host, not in Docker
    assert report.passed and "theme/style applied" not in names
    length = names["video length within 20% of the requested duration"]
    assert not length.ok and not length.critical and "16.0s for a 60s request" in length.detail


@pytest.mark.unit
@pytest.mark.parametrize("renderer", ["legacy", "browser_v2"])
def test_renderer_choice_reaches_the_engine(monkeypatch, tmp_path, renderer):
    seen = {}

    class FakeEngine:
        def __init__(self, *, root):
            pass

        def plan(self, topic, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after plan")

    import web.engine

    monkeypatch.setattr(web.engine, "Engine", FakeEngine)
    monkeypatch.setattr(settings, "out_dir", tmp_path)
    monkeypatch.setattr(selftest, "preflight", lambda rep, renderer="legacy": True)
    code = selftest.main(["A topic", "--renderer", renderer])
    assert code == 1                                     # the fake build "failed", which is a FAIL
    assert seen.get("renderer") == (None if renderer == "legacy" else "browser_v2")
