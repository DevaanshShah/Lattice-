"""FREE deterministic OFF-FRAME lint — moves the one defect class geometry detects RELIABLY
out of the paid vision critic.

The generator animates blind, so it can place an object past the frame edge (the "Sigmoid box
ran off the right edge" defect). That is pure geometry: Manim knows every mobject's bounding box.
So instead of paying the vision model to notice it across several iterations, a tiny probe runs
the scene HEADLESS inside the same pinned sandbox container, applies each animation's END state
(so final positions are correct — not the pre-move positions a naive snapshot would read), walks
the resulting mobjects, and reports anything whose bounding box leaves the frame.

Two defect classes, both deterministic: OFF-FRAME (a box past the edge) and OVERLAP (Phase 3 — two
TOP-LEVEL text mobjects whose boxes intersect, the w2/w3-merge defect). The probe walks only
TOP-LEVEL `self.mobjects` (never flattens), so a single MathTex's internal glyphs are not separate
items — no glyph false positives — and overlap is restricted to text-vs-text so intended
label-inside-box / arrow-over-content isn't flagged.

Invariants: runs only AFTER compile-repair succeeds (the scene already renders); degrades to
ok=True / no issues on ANY probe failure, so it never blocks a renderable scene or hangs the loop.
Issues are emitted in the EXISTING CritiqueIssue/CritiqueReport shape, so the existing fixer
consumes them unchanged (and narration add_sound sync is preserved by that same fixer).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import settings
from render import sandbox
from verification.vision_critic import CritiqueIssue, CritiqueReport

# Off-frame margin (Manim units): only flag a bbox that clears the true frame edge by this much,
# so a mobject sitting flush against the edge isn't nagged. The suggested fix asks for a larger
# safe margin (the generator should pull WELL inside, not just barely on-screen).
_OFF_FRAME_MARGIN = 0.15
_MAX_ISSUES = 6  # keep the fix prompt small — the fix call is the expensive one

# Overlap (Phase 3): flag TWO TOP-LEVEL TEXT mobjects whose boxes intersect. Top-level only (the probe
# never flattens), so a single MathTex's internal glyphs are NOT separate items — no glyph false
# positives. Restricting to text-vs-text avoids flagging intended label-inside-box / arrow-over-content.
_TEXT_KINDS = {"Text", "MarkupText", "Tex", "MathTex", "SingleStringMathTex", "Paragraph", "Title"}
_OVERLAP_MIN_FRAC = 0.25  # min intersection as a fraction of the SMALLER box's area to call it overlap
_MAX_OVERLAP_ISSUES = 4

# The in-container probe. Runs scene.py headless, applies animation END states, prints one JSON
# line of top-level mobject bounding boxes. Self-contained (no project imports) — it executes in
# the render image where only `manim` + stdlib are guaranteed.
PROBE_SRC = r'''
import json, warnings
warnings.filterwarnings("ignore")
from manim import Scene, config
try:
    from manim.animation.animation import prepare_animation
except Exception:
    prepare_animation = None


def _apply_end_state(scene, anim):
    """Apply one animation's FINAL state to its mobject (no rendering)."""
    # flatten AnimationGroup / Succession / LaggedStart
    subs = getattr(anim, "animations", None)
    if subs:
        for s in subs:
            _apply_end_state(scene, s)
        return
    try:
        m = getattr(anim, "mobject", None)
        if m is not None:
            scene.add(m)            # ensure present, then move it to its end state
        anim.begin(); anim.interpolate(1); anim.finish()
        anim.clean_up_from_scene(scene)   # removes FadeOut/Uncreate targets, etc.
    except Exception:
        pass


def _play(self, *anims, **kw):
    for raw in anims:
        a = raw
        if prepare_animation is not None:
            try:
                a = prepare_animation(raw)     # converts x.animate.foo() builders -> Animation
            except Exception:
                a = raw
        _apply_end_state(self, a)


Scene.play = _play
Scene.wait = lambda self, *a, **k: None
Scene.add_sound = lambda self, *a, **k: None     # narration calls are harmless no-ops here

from manim import UP, DOWN, LEFT, RIGHT


def _kind(m):
    return type(m).__name__


def _label(m):
    t = getattr(m, "text", None)
    if t is None:
        t = getattr(m, "tex_string", None)
    return (str(t)[:48] if t else "")


def _bbox(m):
    ul = m.get_corner(UP + LEFT); dr = m.get_corner(DOWN + RIGHT)
    return [float(ul[0]), float(dr[0])], [float(dr[1]), float(ul[1])]   # x[left,right], y[bottom,top]


try:
    import scene as _mod
    S = _mod.GeneratedScene()
    S.construct()
    items = []
    for i, m in enumerate(S.mobjects):     # top-level mobjects only (a group's bbox covers its parts)
        try:
            x, y = _bbox(m)
            items.append({"i": i, "kind": _kind(m), "label": _label(m), "x": x, "y": y})
        except Exception:
            pass
    print(json.dumps({"ok": True,
                      "frame": [float(config.frame_x_radius), float(config.frame_y_radius)],
                      "items": items}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(type(e).__name__) + ": " + str(e)[:200]}))
'''


def _run_probe(work_dir: Path) -> dict | None:
    """Write _probe.py next to scene.py, run it in the pinned container. None on hard failure."""
    if not (work_dir / "scene.py").exists():
        return None
    probe = work_dir / "_layout_probe.py"
    probe.write_text(PROBE_SRC, encoding="utf-8")
    res = sandbox.run_python_file(probe, timeout=min(90, settings.render_timeout_s))
    if res.returncode != 0 or not (res.stdout or "").strip():
        return None
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])  # probe prints one JSON line last
    except (ValueError, IndexError):
        return None


def _overlap_frac(a: dict, b: dict) -> float:
    """Intersection area of two bboxes as a fraction of the smaller box's area (0 if disjoint)."""
    ox = max(0.0, min(a["x"][1], b["x"][1]) - max(a["x"][0], b["x"][0]))
    oy = max(0.0, min(a["y"][1], b["y"][1]) - max(a["y"][0], b["y"][0]))
    inter = ox * oy
    if inter <= 0:
        return 0.0
    area_a = (a["x"][1] - a["x"][0]) * (a["y"][1] - a["y"][0])
    area_b = (b["x"][1] - b["x"][0]) * (b["y"][1] - b["y"][0])
    smaller = min(area_a, area_b)
    return (inter / smaller) if smaller > 0 else 0.0


def _overlap_issues(items: list[dict]) -> list[CritiqueIssue]:
    """Flag pairs of top-level TEXT mobjects whose boxes intersect (the w2/w3-merge defect class)."""
    texts = [it for it in items if it["kind"] in _TEXT_KINDS and it.get("label")]
    pairs = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            frac = _overlap_frac(texts[i], texts[j])
            if frac >= _OVERLAP_MIN_FRAC:
                pairs.append((frac, texts[i], texts[j]))
    issues: list[CritiqueIssue] = []
    for _, a, b in sorted(pairs, key=lambda p: -p[0])[:_MAX_OVERLAP_ISSUES]:
        la, lb = a["label"], b["label"]
        issues.append(CritiqueIssue(
            type="overlap",
            location=f"'{la}' & '{lb}'",
            description=f"Text '{la}' and '{lb}' overlap — their bounding boxes intersect.",
            suggested_fix=(f"Separate '{la}' and '{lb}': place them in different regions / cells, or "
                           f"use next_to(..., buff>=0.3) so the labels don't sit on top of each other."),
        ))
    return issues


def issues_from_facts(facts: dict) -> list[CritiqueIssue]:
    """Pure: probe geometry facts -> OFF-FRAME + OVERLAP CritiqueIssues. Unit-testable without Docker."""
    fx, fy = facts["frame"]
    issues: list[CritiqueIssue] = []
    for it in facts.get("items", []):
        sides = []
        if it["x"][0] < -fx - _OFF_FRAME_MARGIN:
            sides.append("left")
        if it["x"][1] > fx + _OFF_FRAME_MARGIN:
            sides.append("right")
        if it["y"][0] < -fy - _OFF_FRAME_MARGIN:
            sides.append("bottom")
        if it["y"][1] > fy + _OFF_FRAME_MARGIN:
            sides.append("top")
        if sides:
            tag = it["label"] or it["kind"]
            issues.append(CritiqueIssue(
                type="off_frame",
                location=f"{it['kind']} '{tag}'" if it["label"] else it["kind"],
                description=(f"'{tag}' extends past the {', '.join(sides)} frame edge "
                            f"(x={[round(v, 2) for v in it['x']]}, y={[round(v, 2) for v in it['y']]})."),
                suggested_fix=(f"Move/scale '{tag}' so its whole bounding box sits inside "
                               f"x in [-{fx - 0.5:.1f}, {fx - 0.5:.1f}], y in [-{fy - 0.5:.1f}, {fy - 0.5:.1f}] "
                               f"(keep a ~0.5 safe margin; scale_to_fit_width or next_to/shift it inward)."),
            ))
    issues.extend(_overlap_issues(facts.get("items", [])))   # text-vs-text overlap (Phase 3)
    return issues[:_MAX_ISSUES]


def lint(work_dir: str | Path) -> CritiqueReport:
    """Geometric OFF-FRAME lint of the already-rendered scene in work_dir.

    Returns a CritiqueReport (existing type) whose issues are off_frame. Degrades to ok=True with
    no issues on probe failure, so it NEVER gates a renderable scene and never hangs.
    """
    facts = _run_probe(Path(work_dir))
    if not facts or not facts.get("ok"):
        return CritiqueReport(ok=True, score=None, issues=[])  # probe hiccup -> defer to vision
    issues = issues_from_facts(facts)
    return CritiqueReport(ok=not issues, score=(100 if not issues else None), issues=issues)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from core.console import enable_utf8
    enable_utf8()
    ap = argparse.ArgumentParser(description="Free off-frame layout lint of a rendered scene dir.")
    ap.add_argument("work_dir", help="dir containing the rendered scene.py")
    args = ap.parse_args(argv)

    report = lint(args.work_dir)
    print(f"off-frame issues: {report.n_issues}")
    for i in report.issues:
        print(f"  - [{i.type}] {i.location}: {i.description}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
