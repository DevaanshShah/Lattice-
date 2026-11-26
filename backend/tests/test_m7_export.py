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


@pytest.mark.unit
def test_export_unknown_format_rejected(tmp_path):
    from composition.scene_dag import VideoProject
    proj = VideoProject(topic="x")
    with pytest.raises(ValueError):
        export.export(proj, out_dir=tmp_path, fmt="imax")


# --- format reframe (FR-30) — the -vf chain is pure, the encode itself is integration ----------

@pytest.mark.unit
def test_youtube_needs_no_video_pass():
    # the 16:9 render already IS the deliverable — an empty chain is what skips the re-encode
    assert export.build_filters("youtube") == ""


@pytest.mark.unit
def test_reel_scales_to_phone_width_then_pads_to_9_16():
    vf = export.build_filters("reel")
    assert vf.startswith(f"scale={export.REEL_W}:-2,")     # -2 = keep aspect, force an even height
    assert f"pad={export.REEL_W}:{export.REEL_H}:" in vf   # 1080x1920
    assert "(ow-iw)/2:(oh-ih)/2" in vf                     # centred, so no edge is favoured


@pytest.mark.unit
def test_reel_pads_with_the_sampled_color_not_the_nominal_one():
    """The seam guard. The scenes are painted #101015, but h264's limited-range encode makes that
    decode ~#090A0F — padding with the nominal constant leaves a visibly lighter band (measured
    7/255). Sampling the real frame closed it to 1/255, so the sampled colour MUST win."""
    vf = export.build_filters("reel", bg="0x090A0F")
    assert "color=0x090A0F" in vf
    assert "color=0x101015" not in vf


@pytest.mark.unit
def test_reel_pad_falls_back_to_the_nominal_background():
    from composition import decoupled
    assert export.nominal_bg() == "0x" + decoupled.BG_COLOR.lstrip("#").upper()
    assert f"color={export.nominal_bg()}" in export.build_filters("reel")   # bg=None -> fallback


@pytest.mark.unit
def test_sample_bg_falls_back_instead_of_raising(tmp_path, monkeypatch):
    # a failed probe must degrade to a faint seam, never to a failed export
    def boom(*a, **k):
        raise OSError("no docker")
    monkeypatch.setattr(export.subprocess, "run", boom)
    assert export.sample_bg(tmp_path, "missing.mp4") == export.nominal_bg()


@pytest.mark.unit
def test_sample_bg_averages_the_corner_patch_to_a_hex_color(tmp_path, monkeypatch):
    class Proc:
        returncode = 0
        stdout = bytes([9, 10, 15] * 256)   # a 16x16 rgb24 patch of the real decoded background
    monkeypatch.setattr(export.subprocess, "run", lambda *a, **k: Proc())
    assert export.sample_bg(tmp_path, "in.mp4") == "0x090A0F"


@pytest.mark.unit
def test_reel_pads_before_burning_so_captions_land_on_the_tall_frame():
    vf = export.build_filters("reel", srt_rel="c.srt")
    assert vf.index("pad=") < vf.index("subtitles=")   # order is the whole point
    assert "force_style" in vf                          # captions restyled for the 9:16 canvas


@pytest.mark.unit
def test_youtube_burn_chain_is_unchanged_by_the_format_work():
    # the pre-existing 16:9 burn must stay byte-identical — no force_style, no scaling
    assert export.build_filters("youtube", srt_rel="subs.srt") == "subtitles=subs.srt"


@pytest.mark.unit
def test_build_filters_rejects_unknown_format():
    with pytest.raises(ValueError):
        export.build_filters("imax")


@pytest.mark.unit
def test_build_export_command_is_hardened_and_copies_audio(tmp_path):
    cmd = export.build_export_command(tmp_path, "in.mp4", "out.mp4", vf="scale=1080:-2", name="lattice-e")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd
    assert cmd[cmd.index("-vf") + 1] == "scale=1080:-2"
    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_script_srt_splits_duration_by_line_length():
    srt = export.script_srt(["Short.", "A much longer second line here."], 10.0)
    cues = export._shift_block(srt.split("\n\n")[0], 0) + export._shift_block(srt.split("\n\n")[1], 0)
    assert [c[2] for c in cues] == ["Short.", "A much longer second line here."]
    assert cues[0][0] == 0.0 and abs(cues[1][1] - 10.0) < 0.01
    assert cues[0][1] < 3.0 < cues[1][1]           # the short line gets the smaller share


def test_script_srt_empty_without_lines_or_duration():
    assert export.script_srt([], 5.0) == ""
    assert export.script_srt(["hi"], 0.0) == ""


def test_merged_captions_falls_back_to_the_narration_script(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(export, "_probe_duration", lambda _p: 4.0)
    proj = SimpleNamespace(scenes=[SimpleNamespace(srt=None, mp4="a.mp4", script=["One line."]),
                                   SimpleNamespace(srt=None, mp4="b.mp4", script=["Two."])])
    merged = export.merged_captions(proj)
    assert "One line." in merged and "Two." in merged
    assert "00:00:04,000 --> 00:00:08,000" in merged   # second scene offset by the first's length


def test_burn_with_no_captions_fails_plainly(tmp_path, monkeypatch):
    from types import SimpleNamespace
    final = tmp_path / "final.mp4"; final.write_bytes(b"x")
    monkeypatch.setattr(export, "merged_captions", lambda _p: "")
    proj = SimpleNamespace(final_mp4=str(final), scenes=[])
    with pytest.raises(ValueError, match="no narration"):
        export.export(proj, out_dir=tmp_path / "out", subtitles="burn")


def test_reel_caption_style_stays_inside_the_frame():
    style = dict(kv.split("=") for kv in export._REEL_SUB_STYLE.split(","))
    margin, size = int(style["MarginV"]), int(style["FontSize"])
    # units are libass's 288-tall reference canvas; the letterboxed 16:9 video ends at
    # 50% + half its height of the frame, and the captions must sit in the band below it
    video_bottom = export.REEL_SUB_PLAYRES_Y * (0.5 + (export.REEL_W * 9 / 16) / export.REEL_H / 2)
    assert 0 < margin < export.REEL_SUB_PLAYRES_Y - video_bottom    # bottom edge sits inside the band
    assert export.REEL_SUB_PLAYRES_Y - margin - 2 * size * 1.2 > video_bottom  # two lines fit below the video
