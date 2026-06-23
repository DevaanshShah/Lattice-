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
