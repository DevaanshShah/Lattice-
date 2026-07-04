"""M7 — free deterministic OFF-FRAME layout lint. Unit-level covers everything that doesn't need
Docker: the pure geometry predicate, graceful degradation on probe failure, and the vision_critic
splice (lint issues fix FREE without a vision call; vision runs only once layout is clean). The
in-container probe itself is a live check (needs Docker)."""
from pathlib import Path

import pytest

from verification import layout_lint
from verification.vision_critic import CritiqueIssue, CritiqueReport

FRAME = [7.11, 4.0]


def _facts(items):
    return {"ok": True, "frame": FRAME, "items": items}


# --- pure geometry: issues_from_facts ------------------------------------------------------

@pytest.mark.unit
def test_offframe_flagged_inside_left_alone():
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "Sigmoid", "x": [6.0, 8.3], "y": [-0.5, 0.5]},  # past right
        {"i": 1, "kind": "Circle", "label": "", "x": [-1.0, 1.0], "y": [-1.0, 1.0]},        # inside
    ])
    issues = layout_lint.issues_from_facts(facts)
    assert len(issues) == 1
    assert issues[0].type == "off_frame" and "right" in issues[0].description
    assert "Sigmoid" in issues[0].location


@pytest.mark.unit
def test_each_edge_detected():
    items = [
        {"i": 0, "kind": "Text", "label": "L", "x": [-9.0, -7.5], "y": [0, 1]},
        {"i": 1, "kind": "Text", "label": "T", "x": [0, 1], "y": [4.5, 6.0]},
        {"i": 2, "kind": "Text", "label": "B", "x": [0, 1], "y": [-6.0, -4.5]},
    ]
    sides = {i.location: i.description for i in layout_lint.issues_from_facts(_facts(items))}
    assert any("left" in d for d in sides.values())
    assert any("top" in d for d in sides.values())
    assert any("bottom" in d for d in sides.values())


@pytest.mark.unit
def test_flush_to_edge_within_margin_not_flagged():
    # right edge at 7.11; bbox to 7.2 is within the 0.15 margin -> not flagged
    facts = _facts([{"i": 0, "kind": "Text", "label": "x", "x": [6.0, 7.2], "y": [0, 1]}])
    assert layout_lint.issues_from_facts(facts) == []


@pytest.mark.unit
def test_issue_count_capped():
    items = [{"i": i, "kind": "Text", "label": f"t{i}", "x": [8.0, 9.0], "y": [0, 1]} for i in range(20)]
    assert len(layout_lint.issues_from_facts(_facts(items))) == layout_lint._MAX_ISSUES


# --- lint() degradation (never blocks a renderable scene) ----------------------------------

@pytest.mark.unit
def test_lint_degrades_to_ok_on_probe_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(layout_lint, "_run_probe", lambda wd: None)
    r = layout_lint.lint(tmp_path)
    assert r.ok and not r.issues

    monkeypatch.setattr(layout_lint, "_run_probe", lambda wd: {"ok": False, "error": "boom"})
    r = layout_lint.lint(tmp_path)
    assert r.ok and not r.issues


@pytest.mark.unit
def test_lint_reports_offframe_from_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(layout_lint, "_run_probe",
                        lambda wd: _facts([{"i": 0, "kind": "Text", "label": "y", "x": [6, 9], "y": [0, 1]}]))
    r = layout_lint.lint(tmp_path)
    assert not r.ok and r.n_issues == 1


@pytest.mark.unit
def test_run_probe_short_circuits_without_scene_py(tmp_path):
    # no scene.py present -> probe returns None WITHOUT shelling out to Docker (keeps unit tests clean)
    assert layout_lint._run_probe(tmp_path) is None


# --- overlap detection (Phase 3) -----------------------------------------------------------

@pytest.mark.unit
def test_overlapping_top_level_texts_flagged():
    facts = _facts([
        {"i": 0, "kind": "MathTex", "label": "w_2", "x": [0.0, 0.5], "y": [0.0, 0.3]},
        {"i": 1, "kind": "MathTex", "label": "w_3", "x": [0.1, 0.6], "y": [0.05, 0.35]},  # overlaps w_2
    ])
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1 and "w_2" in ov[0].location and "w_3" in ov[0].location


@pytest.mark.unit
def test_distant_texts_not_flagged():
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "a", "x": [-5, -4], "y": [1, 1.4]},
        {"i": 1, "kind": "Text", "label": "b", "x": [4, 5], "y": [1, 1.4]},
    ])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_text_over_shape_not_flagged():
    # a label sitting on a box is INTENDED; only text-vs-text counts (avoids the false-positive trap)
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "lbl", "x": [0, 0.5], "y": [0, 0.3]},
        {"i": 1, "kind": "Rectangle", "label": "", "x": [-0.2, 0.7], "y": [-0.2, 0.5]},
    ])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_overlap_issues_combined_and_capped():
    items = [{"i": k, "kind": "Text", "label": f"t{k}", "x": [0, 1], "y": [0, 1]} for k in range(8)]
    issues = layout_lint.issues_from_facts(_facts(items))   # all mutually overlap
    assert len(issues) <= layout_lint._MAX_ISSUES
    assert any(i.type == "overlap" for i in issues)


@pytest.mark.unit
def test_transient_overlap_in_snapshot_flagged():
    # the scene-4 defect: two labels COLLIDE mid-animation (a per-play snapshot), then a later play
    # moves/merges them so the FINAL frame is clean. The still-final probe missed it; snapshots catch it.
    final = [{"top": 0, "kind": "Text", "label": "HTML", "x": [-5, -4], "y": [1, 1.4]},
             {"top": 1, "kind": "Text", "label": "CSS", "x": [4, 5], "y": [1, 1.4]}]   # apart at the end
    snap = [{"top": 0, "kind": "Text", "label": "HTML", "x": [0.0, 0.5], "y": [0.0, 0.3]},
            {"top": 1, "kind": "Text", "label": "CSS", "x": [0.1, 0.6], "y": [0.05, 0.35]}]  # same cell
    facts = {"ok": True, "frame": FRAME, "items": [], "texts": final, "snapshots": [snap]}
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1 and "HTML" in ov[0].location and "CSS" in ov[0].location


@pytest.mark.unit
def test_transient_overlap_reported_once_across_snapshots():
    snap = [{"top": 0, "kind": "Text", "label": "A", "x": [0, 0.5], "y": [0, 0.3]},
            {"top": 1, "kind": "Text", "label": "B", "x": [0.1, 0.6], "y": [0.05, 0.35]}]
    facts = {"ok": True, "frame": FRAME, "items": [], "texts": [], "snapshots": [snap, snap, snap]}
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1   # the same colliding pair over many snapshots is ONE issue, not three


@pytest.mark.unit
def test_no_snapshots_key_behaves_as_before():
    # backward-compat: facts without "snapshots" lints exactly as the old single-frame path
    facts = _facts([{"i": 0, "kind": "Text", "label": "x", "x": [0, 0.5], "y": [0, 0.3]},
                    {"i": 1, "kind": "Text", "label": "y", "x": [0.1, 0.6], "y": [0.05, 0.35]}])
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1


# --- distance-based clearance + tiny font (Tier 1) -----------------------------------------

@pytest.mark.unit
def test_near_touch_texts_flagged():
    # aligned on y, 0.05 horizontal gap: no area overlap (IoU ~0) but visually cramped -> flagged
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "a", "x": [0.0, 1.0], "y": [0.0, 0.3]},
        {"i": 1, "kind": "Text", "label": "b", "x": [1.05, 2.05], "y": [0.0, 0.3]},
    ])
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1 and "nearly touch" in ov[0].description


@pytest.mark.unit
def test_diagonal_near_texts_not_flagged():
    # small gap on BOTH axes (corner-to-corner) is not cramped -> not flagged
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "a", "x": [0.0, 1.0], "y": [0.0, 0.3]},
        {"i": 1, "kind": "Text", "label": "b", "x": [1.05, 2.05], "y": [0.4, 0.7]},
    ])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_clearance_beyond_threshold_not_flagged():
    facts = _facts([
        {"i": 0, "kind": "Text", "label": "a", "x": [0.0, 1.0], "y": [0.0, 0.3]},
        {"i": 1, "kind": "Text", "label": "b", "x": [1.15, 2.15], "y": [0.0, 0.3]},  # 0.15 gap > 0.12
    ])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_tiny_single_line_text_flagged():
    facts = _facts([{"i": 0, "kind": "Text", "label": "tiny", "x": [0.0, 0.5], "y": [0.0, 0.1],
                     "fs": 8.0, "nl": False}])   # height 0.1 < 0.18
    tf = [i for i in layout_lint.issues_from_facts(facts) if i.type == "tiny_font"]
    assert len(tf) == 1 and "tiny" in tf[0].location


@pytest.mark.unit
def test_tiny_multiline_text_not_flagged():
    # multi-line height isn't a per-line legibility proxy -> skipped
    facts = _facts([{"i": 0, "kind": "Text", "label": "two\nlines", "x": [0.0, 2.0], "y": [0.0, 0.1],
                     "fs": 24.0, "nl": True}])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "tiny_font"] == []


@pytest.mark.unit
def test_readable_text_not_flagged_tiny():
    facts = _facts([{"i": 0, "kind": "Text", "label": "ok", "x": [0.0, 1.0], "y": [0.0, 0.4],
                     "fs": 28.0, "nl": False}])   # height 0.4 >= 0.18
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "tiny_font"] == []


# --- WIDENED lint: cross-group label overlap + shape-over-text (the classes v1 missed) ------
# The narrow v1 only compared TOP-LEVEL text, so a label buried in a labeled_box VGroup and a shape
# drawn on top of a label both slipped (web "how tcp works": arrow-through-box, timer-circle-on-box).

def _facts2(items, texts):
    return {"ok": True, "frame": FRAME, "items": items, "texts": texts}


@pytest.mark.unit
def test_cross_group_labels_overlap_flagged():
    # scene-0 box-jam: two labels from DIFFERENT boxes (top 0 vs 1) whose boxes overlap
    facts = _facts2([], [
        {"top": 0, "kind": "Text", "label": "Hi", "x": [0.0, 0.6], "y": [0.0, 0.3]},
        {"top": 1, "kind": "Text", "label": "Computer B", "x": [0.3, 1.5], "y": [0.0, 0.3]},
    ])
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert ov and "Hi" in ov[0].location


@pytest.mark.unit
def test_same_group_labels_not_flagged():
    # two texts in the SAME component (same top) overlapping is intended -> never a defect
    facts = _facts2([], [
        {"top": 0, "kind": "Text", "label": "a", "x": [0.0, 0.6], "y": [0.0, 0.3]},
        {"top": 0, "kind": "Text", "label": "b", "x": [0.1, 0.7], "y": [0.05, 0.35]},
    ])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_circle_over_label_flagged():
    # scene-3: a FREE Circle drawn on top of a box's label -> occlusion defect
    facts = _facts2(
        [{"i": 5, "kind": "Circle", "label": "", "x": [0.0, 0.8], "y": [0.0, 0.8]}],
        [{"top": 1, "kind": "Text", "label": "Packet 3", "x": [0.1, 0.7], "y": [0.2, 0.6]}],
    )
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert ov and "Packet 3" in ov[0].location and "Circle" in ov[0].location


@pytest.mark.unit
def test_rectangle_over_label_not_flagged():
    # a Rectangle over a label is the intended labeled_box CONTAINER -> NOT flagged (the v1 false-positive dodge)
    facts = _facts2(
        [{"i": 2, "kind": "Rectangle", "label": "", "x": [-0.2, 1.0], "y": [-0.2, 0.6]}],
        [{"top": 3, "kind": "Text", "label": "lbl", "x": [0.0, 0.6], "y": [0.0, 0.3]}],
    )
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_shape_barely_touching_label_not_flagged():
    # a Circle clipping just a corner of a label (<35% covered) is not occlusion -> conservative, no FP
    facts = _facts2(
        [{"i": 5, "kind": "Circle", "label": "", "x": [0.6, 1.4], "y": [0.2, 1.0]}],
        [{"top": 1, "kind": "Text", "label": "x", "x": [0.0, 0.7], "y": [0.0, 0.4]}],
    )
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"] == []


@pytest.mark.unit
def test_backward_compat_top_level_items_still_work():
    # old callers pass only `items` (no `texts`): top-level text overlap must behave exactly as before
    facts = _facts([
        {"i": 0, "kind": "MathTex", "label": "w_2", "x": [0.0, 0.5], "y": [0.0, 0.3]},
        {"i": 1, "kind": "MathTex", "label": "w_3", "x": [0.1, 0.6], "y": [0.05, 0.35]},
    ])
    ov = [i for i in layout_lint.issues_from_facts(facts) if i.type == "overlap"]
    assert len(ov) == 1


# --- low-contrast text (legibility) --------------------------------------------------------

def _facts_c(bg, items, texts):
    return {"ok": True, "frame": FRAME, "bg": bg, "items": items, "texts": texts}


@pytest.mark.unit
def test_dark_text_on_dark_bg_flagged():
    # the scene-1 "height" defect: dark navy label on the dark scene bg -> ~invisible
    facts = _facts_c("#101015", [],
                     [{"top": 0, "kind": "Text", "label": "height", "x": [0, 1], "y": [0, 0.3], "color": "#1b2a4a"}])
    lc = [i for i in layout_lint.issues_from_facts(facts) if i.type == "low_contrast"]
    assert lc and "height" in lc[0].location


@pytest.mark.unit
def test_white_text_on_dark_bg_not_flagged():
    facts = _facts_c("#101015", [],
                     [{"top": 0, "kind": "Text", "label": "ok", "x": [0, 1], "y": [0, 0.3], "color": "#ffffff"}])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "low_contrast"] == []


@pytest.mark.unit
def test_dark_text_on_light_box_not_flagged():
    # dark text INSIDE a light filled box reads fine -> the box (not the scene bg) is its background
    facts = _facts_c("#101015",
                     [{"i": 1, "kind": "Rectangle", "label": "", "x": [-0.2, 1.2], "y": [-0.2, 0.5], "fill": "#e8e8e8"}],
                     [{"top": 2, "kind": "Text", "label": "lbl", "x": [0, 1], "y": [0, 0.3], "color": "#111111"}])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "low_contrast"] == []


@pytest.mark.unit
def test_text_without_color_not_flagged_contrast():
    # backward-compat: old probe facts (no color / no bg) -> the contrast check simply skips
    facts = _facts([{"i": 0, "kind": "Text", "label": "x", "x": [0, 1], "y": [0, 0.3]}])
    assert [i for i in layout_lint.issues_from_facts(facts) if i.type == "low_contrast"] == []


# --- the vision_critic splice: free lint gates the paid vision call -------------------------

def _ok_render(mp4, png):
    from render.worker import WorkerResult
    return lambda code, wd: WorkerResult(True, 0, "", "", mp4, [png], [])


@pytest.mark.unit
def test_lint_issue_fixed_free_then_vision_confirms(monkeypatch, tmp_path):
    from verification import vision_critic
    from verification.caps import Caps

    mp4 = tmp_path / "v.mp4"; mp4.write_bytes(b"x")
    png = tmp_path / "f.png"; png.write_bytes(b"x")
    calls = {"lint": 0, "critic": 0, "fix": 0}

    def fake_lint(wd):
        calls["lint"] += 1
        if calls["lint"] == 1:
            return CritiqueReport(ok=False, issues=[CritiqueIssue(type="off_frame", description="x off right")])
        return CritiqueReport(ok=True, issues=[])

    monkeypatch.setattr(vision_critic.settings, "layout_lint_enabled", True)
    monkeypatch.setattr(vision_critic.settings, "vision_confirm", True)
    monkeypatch.setattr("verification.layout_lint.lint", fake_lint)

    def critic_fn(frames):
        calls["critic"] += 1
        return CritiqueReport(ok=True, issues=[])

    def issue_regen_fn(code, report):
        calls["fix"] += 1
        return code + " #fixed"

    res = vision_critic.run("code", tmp_path, None, render_fn=_ok_render(mp4, png),
                            critic_fn=critic_fn, issue_regen_fn=issue_regen_fn,
                            caps=Caps(max_critic_iters=3))
    # iter1: lint dirty -> free fix, NO vision call. iter2: lint clean -> vision confirms -> done.
    assert calls["lint"] == 2
    assert calls["fix"] == 1          # the free, lint-driven fix
    assert calls["critic"] == 1       # vision spent ONLY after lint went clean
    assert res.passed


@pytest.mark.unit
def test_vision_confirm_off_spends_zero_vision_when_layout_clean(monkeypatch, tmp_path):
    from verification import vision_critic
    from verification.caps import Caps

    mp4 = tmp_path / "v.mp4"; mp4.write_bytes(b"x")
    png = tmp_path / "f.png"; png.write_bytes(b"x")
    calls = {"critic": 0}

    monkeypatch.setattr(vision_critic.settings, "layout_lint_enabled", True)
    monkeypatch.setattr(vision_critic.settings, "vision_confirm", False)
    monkeypatch.setattr("verification.layout_lint.lint",
                        lambda wd: CritiqueReport(ok=True, issues=[]))

    def critic_fn(frames):
        calls["critic"] += 1
        return CritiqueReport(ok=True, issues=[])

    res = vision_critic.run("code", tmp_path, None, render_fn=_ok_render(mp4, png),
                            critic_fn=critic_fn, issue_regen_fn=lambda c, r: c,
                            caps=Caps(max_critic_iters=3))
    assert calls["critic"] == 0       # lint-only mode never pays for vision
    assert res.passed                 # clean layout + no vision required = pass
