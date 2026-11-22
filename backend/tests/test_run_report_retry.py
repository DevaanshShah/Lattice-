from pathlib import Path

import pytest

from core.run_report import RunReport, classify_exception


@pytest.mark.unit
def test_report_retries_transient_windows_replace_lock(monkeypatch, tmp_path):
    original = Path.replace
    calls = 0

    def temporarily_locked(path, target):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("temporary reader lock")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    report = RunReport(tmp_path, topic="test", recipe="test")
    assert report.path.exists()
    assert calls == 3
    assert classify_exception(PermissionError("locked"), "clip") == "filesystem"
