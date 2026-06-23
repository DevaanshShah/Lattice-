"""M7 / FR-30 — export. Unit-level: the per-scene caption offset math and the burn-in ffmpeg
argv are pure. The actual mux/burn pass is integration (needs the container)."""
import pytest

from composition import export

SRT0 = "1\n00:00:00,000 --> 00:00:02,000\nhello\n"
SRT1 = "1\n00:00:00,500 --> 00:00:01,500\nworld\n"
SRT_MULTI = (
    "1\n00:00:00,000 --> 00:00:01,000\nline one\n\n"
    "2\n00:00:01,000 --> 00:00:02,000\nline two\nwrapped\n"
)


@pytest.mark.unit
def test_merge_srt_offsets_later_scenes_by_cumulative_duration():
    merged = export.merge_srt([(SRT0, 5.0), (SRT1, 3.0)])
    # scene 0 stays at 0; scene 1's 0.5–1.5 shifts by 5.0 -> 5.5–6.5
    assert "00:00:00,000 --> 00:00:02,000" in merged
    assert "00:00:05,500 --> 00:00:06,500" in merged
    # renumbered continuously 1,2 (not 1,1)
    assert merged.splitlines()[0] == "1"
    assert "world" in merged and "hello" in merged
    assert "\n2\n" in "\n" + merged


@pytest.mark.unit
def test_merge_srt_empty_scene_still_advances_offset():
    # a silent scene 0 (no captions) of 4s pushes scene 1's cue to 4.5–5.5
    merged = export.merge_srt([("", 4.0), (SRT1, 3.0)])
    assert "00:00:04,500 --> 00:00:05,500" in merged
    assert merged.splitlines()[0] == "1"  # numbering starts at 1 despite the empty first scene


@pytest.mark.unit
def test_merge_srt_preserves_multiline_cues_and_renumbers():
    merged = export.merge_srt([(SRT_MULTI, 2.0)])
    assert "line one" in merged
    assert "line two\nwrapped" in merged          # multi-line body intact
    blocks = [b for b in merged.split("\n\n") if b.strip()]
    assert blocks[0].startswith("1") and blocks[1].startswith("2")


@pytest.mark.unit
def test_build_burn_command_is_hardened_subtitles_pass(tmp_path):
    cmd = export.build_burn_command(tmp_path, "in.mp4", "subs.srt", "out.mp4", name="lattice-e")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd                 # shares the sandbox hardening
    assert "ffmpeg" in cmd
    assert "subtitles=subs.srt" in cmd and "out.mp4" in cmd
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"   # video re-encoded, audio copied


@pytest.mark.unit
def test_export_unknown_subtitle_mode_rejected(tmp_path):
    from composition.scene_dag import VideoProject
    proj = VideoProject(topic="x")
    with pytest.raises(ValueError):
        export.export(proj, out_dir=tmp_path, subtitles="rainbow")
