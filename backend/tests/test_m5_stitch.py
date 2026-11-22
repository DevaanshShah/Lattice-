"""M5 unit tests — FFmpeg stitch (T-16). No Docker: subprocess is faked."""
import subprocess

import pytest


@pytest.mark.unit
def test_concat_command_is_sandboxed_copy():
    from composition.stitch import build_concat_command
    cmd = build_concat_command("wd", "concat.txt", "final.mp4")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in cmd and "ffmpeg" in cmd
    assert "concat" in cmd and "-c" in cmd and "copy" in cmd and "final.mp4" in cmd


@pytest.mark.unit
def test_concat_command_reencode():
    from composition.stitch import build_concat_command
    cmd = build_concat_command("wd", "concat.txt", "final.mp4", reencode=True)
    assert "libx264" in cmd and "aac" in cmd and "copy" not in cmd


@pytest.mark.unit
def test_stitch_copies_parts_writes_list_and_returns_output(tmp_path, monkeypatch):
    from composition import stitch as stitch_mod

    a = tmp_path / "a.mp4"
    a.write_bytes(b"a")
    b = tmp_path / "b.mp4"
    b.write_bytes(b"b")
    wd = tmp_path / "video"

    def fake_run(cmd, **kw):
        # simulate ffmpeg: create the output file under the work dir
        (wd / "final.mp4").write_bytes(b"stitched")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(stitch_mod.subprocess, "run", fake_run)
    out = stitch_mod.stitch([a, b], work_dir=wd)

    assert out == wd / "final.mp4" and out.exists()
    parts = sorted((wd / "parts").glob("*.mp4"))
    assert [p.name for p in parts] == ["part_000.mp4", "part_001.mp4"]
    listing = (wd / "concat.txt").read_text(encoding="utf-8")
    assert "parts/part_000.mp4" in listing and "parts/part_001.mp4" in listing


@pytest.mark.unit
def test_stitch_falls_back_to_reencode_then_errors(tmp_path, monkeypatch):
    from composition import stitch as stitch_mod

    a = tmp_path / "a.mp4"
    a.write_bytes(b"a")
    calls = {"n": 0}

    def always_fail(cmd, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(stitch_mod.subprocess, "run", always_fail)
    with pytest.raises(stitch_mod.StitchError):
        stitch_mod.stitch([a], work_dir=tmp_path / "v")
    assert calls["n"] == 2     # tried copy, then re-encode, then gave up


@pytest.mark.unit
def test_stitch_empty_raises(tmp_path):
    from composition.stitch import StitchError, stitch
    with pytest.raises(StitchError):
        stitch([], work_dir=tmp_path)
