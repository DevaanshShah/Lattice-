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
_MAX_ISSUES = 8  # keep the fix prompt small — the fix call is the expensive one

# Overlap (Phase 3): flag TWO TOP-LEVEL TEXT mobjects whose boxes intersect. Top-level only (the probe
# never flattens), so a single MathTex's internal glyphs are NOT separate items — no glyph false
# positives. Restricting to text-vs-text avoids flagging intended label-inside-box / arrow-over-content.
_TEXT_KINDS = {"Text", "MarkupText", "Tex", "MathTex", "SingleStringMathTex", "Paragraph", "Title",
               "DecimalNumber", "Integer", "Variable"}
_OVERLAP_MIN_FRAC = 0.25  # min intersection as a fraction of the SMALLER box's area to call it overlap
_MAX_OVERLAP_ISSUES = 4

# Clearance (Tier 1 / GPT #6): two labels touching by a few px have ~0 intersection-area but still read
# as cramped. Distance metrics catch that where IoU/area-fraction can't. Flag a text pair that is ALIGNED
# on one axis (gap 0) and separated by a tiny positive gap (< this) on the other — i.e. adjacent + cramped.
_MIN_CLEARANCE = 0.12
# Tiny-font (Tier 1): a SINGLE LINE of text shorter than this (Manim units) is ~unreadable on an
# 8-unit-tall frame — usually the place_in_area auto-scale-to-fit shrinking content into a cramped region.
_MIN_TEXT_HEIGHT = 0.18
_MAX_TINY_FONT_ISSUES = 4

# Shape-over-text (widening — the class the narrow v1 missed): a FREE round/linear shape (a timer
# circle drawn on a box, an arrow struck THROUGH a label) covering a text from a DIFFERENT group is
# almost always an occlusion defect. We DELIBERATELY EXCLUDE Rectangle/Square/Polygon — those are
# commonly the intended label CONTAINER (labeled_box), so flagging text-inside-its-box would
# false-positive (exactly the trap the v1 dodged). Only cross-group occlusion by a non-box shape.
_OCCLUDER_KINDS = {"Circle", "Ellipse", "Arc", "Annulus", "Dot", "AnnotationDot", "Arrow", "Line",
                   "DashedLine", "Vector", "DoubleArrow", "CurvedArrow", "Arrow3D", "Sector"}
_COVER_FRAC = 0.35        # a shape covering >= this fraction of a text's OWN area occludes it
_MAX_COVERED_ISSUES = 4

# Low-contrast text (legibility): dark text on a dark fill is ~invisible (a real defect — a dark-on-dark
# "height" label). Flag only NEAR-invisible cases (WCAG contrast ratio below this) so a merely-muted
# label isn't nagged. Each text is compared to the fill it sits on, else the scene background.
_MIN_CONTRAST = 1.8       # WCAG-style ratio; 1.0 == identical, 21 == black-on-white. <1.8 == unreadable.
_MAX_CONTRAST_ISSUES = 3

# Top-heavy layout (canvas usage): the blind model clusters content in the top rows (A/B) and leaves the
# lower half empty (the recurring "empty frame" defect). Flag only CLEARLY top-heavy scenes — content
# whose vertical CENTER sits above this y — so a legitimately centered single element isn't nagged.
_TOP_HEAVY_CY = 1.2       # Manim units; rows A~2.3, B~1.2, C~0.05 -> content centered on B/A trips, C-spread doesn't
_TITLE_BAND = 1.0         # exclude items within this of the top edge (the scaffold title lives there)

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


_SNAP = []   # a text-bbox snapshot AFTER each play() -> catches TRANSIENT overlaps (a moved label that
             # collides during the animation, before a LATER play removes/merges it — the still-final
             # frame the probe otherwise reads misses these). Capped so a long scene can't blow up output.


def _play(self, *anims, **kw):
    for raw in anims:
        a = raw
        if prepare_animation is not None:
            try:
                a = prepare_animation(raw)     # converts x.animate.foo() builders -> Animation
            except Exception:
                a = raw
        _apply_end_state(self, a)
    try:
        if len(_SNAP) < 80:
            snap = []
            for i, m in enumerate(self.mobjects):   # _collect_texts is defined below; resolved at call time
                _collect_texts(i, m, snap)
            if snap:
                _SNAP.append(snap)
    except Exception:
        pass


Scene.play = _play
Scene.wait = lambda self, *a, **k: None
Scene.add_sound = lambda self, *a, **k: None     # narration calls are harmless no-ops here

from manim import UP, DOWN, LEFT, RIGHT


def _kind(m):
    return type(m).__name__


def _rawtext(m):
    t = getattr(m, "text", None)
    if t is None:
        t = getattr(m, "tex_string", None)
    return str(t) if t else ""


def _label(m):
    return _rawtext(m)[:48]


def _fontsize(m):
    try:
        return float(getattr(m, "font_size", 0) or 0)
    except Exception:
        return 0.0


def _bbox(m):
    ul = m.get_corner(UP + LEFT); dr = m.get_corner(DOWN + RIGHT)
    return [float(ul[0]), float(dr[0])], [float(dr[1]), float(ul[1])]   # x[left,right], y[bottom,top]


def _hexcolor(m):
    """Rendered hex color of a mobject (fill first, then stroke) -> for the contrast check. None on failure.
    Reads from the first LEAF submobject with points: a parent Text/Tex VMobject often reports the DEFAULT
    black (#000000) while its glyphs are actually white — that misread produced 3 phantom low_contrast
    flags per scene, burning the fixer's budget on fakes while real overlaps shipped."""
    targets = []
    try:
        fam = m.family_members_with_points()
        if fam:
            targets.append(fam[0])
    except Exception:
        pass
    targets.append(m)
    for t in targets:
        for getter in ("get_fill_color", "get_color", "get_stroke_color"):
            try:
                c = getattr(t, getter)()
                if c is not None:
                    h = c.to_hex() if hasattr(c, "to_hex") else str(c)
                    if h and h.lower() not in ("#000000", "#000"):
                        return h
            except Exception:
                pass
    return None


def _fillop(m):
    try:
        return float(m.get_fill_opacity())
    except Exception:
        return 0.0


_TEXT_KINDS = {"Text", "MarkupText", "Tex", "MathTex", "SingleStringMathTex", "Paragraph", "Title",
               "DecimalNumber", "Integer", "Variable"}


def _collect_texts(top, m, out):
    """Collect text mobjects at ANY depth, each tagged with `top` = its top-level ancestor index, so a
    label buried in a labeled_box VGroup is comparable. Stop at the text (don't descend into its glyphs
    / SingleStringMathTex children) -> no glyph double-count and no false positives."""
    try:
        if _kind(m) in _TEXT_KINDS:
            x, y = _bbox(m)
            out.append({"top": top, "kind": _kind(m), "label": _label(m), "x": x, "y": y,
                        "fs": _fontsize(m), "nl": ("\n" in _rawtext(m)), "color": _hexcolor(m)})
            return
        for s in getattr(m, "submobjects", []):
            _collect_texts(top, s, out)
    except Exception:
        pass


try:
    import scene as _mod
    S = _mod.GeneratedScene()
    S.construct()
    try:
        _bg = S.camera.background_color
        _bg = _bg.to_hex() if hasattr(_bg, "to_hex") else str(_bg)
    except Exception:
        _bg = "#000000"
    items, texts = [], []
    for i, m in enumerate(S.mobjects):     # top-level mobjects (a group's bbox covers its parts)
        try:
            x, y = _bbox(m)
            items.append({"i": i, "kind": _kind(m), "label": _label(m), "x": x, "y": y,
                          "fs": _fontsize(m), "nl": ("\n" in _rawtext(m)),
                          "fill": (_hexcolor(m) if _fillop(m) > 0.1 else None)})
        except Exception:
            pass
        _collect_texts(i, m, texts)        # text labels at any depth, tagged with this top index
    print(json.dumps({"ok": True,
                      "frame": [float(config.frame_x_radius), float(config.frame_y_radius)],
                      "bg": _bg, "items": items, "texts": texts, "snapshots": _SNAP}))
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


def _edge_gap(a: dict, b: dict) -> tuple[float, float]:
    """(gap_x, gap_y) between two axis-aligned boxes; 0 on an axis where they overlap/touch."""
    gap_x = max(0.0, max(a["x"][0], b["x"][0]) - min(a["x"][1], b["x"][1]))
    gap_y = max(0.0, max(a["y"][0], b["y"][0]) - min(a["y"][1], b["y"][1]))
    return gap_x, gap_y


def _overlap_issues(text_frames: list) -> list[CritiqueIssue]:
    """Flag TEXT pairs (labels at ANY depth) that OVERLAP (boxes intersect) OR NEARLY TOUCH (distance-
    based clearance). Pairs from the SAME top-level group are skipped (a component's own parts are
    intended); CROSS-group text collision — a moved box's label landing on another box's label — is the
    class the narrow top-level-only v1 missed.

    `text_frames` may be a SINGLE frame (list of text dicts) or MANY frames (list of such lists — the
    per-play snapshots). Scanning every snapshot, not just the final frame, catches a TRANSIENT collision
    (two labels sliding onto the same cell before a later play merges/removes them — the scene-4 defect).
    A pair is reported ONCE, at its worst-observed severity."""
    if text_frames and isinstance(text_frames[0], dict):
        text_frames = [text_frames]                       # backward-compat: a single frame was passed
    worst: dict = {}  # frozenset(labels) -> (severity, kind, a, b), keeping the highest severity seen
    for texts in text_frames:
        texts = [t for t in (texts or []) if t.get("label")]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b = texts[i], texts[j]
                if a.get("top") is not None and a.get("top") == b.get("top"):
                    continue  # same container (e.g. one component's parts) -> intended, not a defect
                sev = kind = None
                frac = _overlap_frac(a, b)
                if frac >= _OVERLAP_MIN_FRAC:
                    sev, kind = 1.0 + frac, "overlap"
                else:
                    gx, gy = _edge_gap(a, b)
                    gap = None  # near-touch only when ALIGNED on one axis (gap 0) and cramped on the other
                    if gx == 0.0 and 0.0 < gy < _MIN_CLEARANCE:
                        gap = gy
                    elif gy == 0.0 and 0.0 < gx < _MIN_CLEARANCE:
                        gap = gx
                    if gap is not None:
                        sev, kind = 1.0 - gap, "touch"
                if kind is None:
                    continue
                key = frozenset((a["label"], b["label"]))
                if key not in worst or sev > worst[key][0]:
                    worst[key] = (sev, kind, a, b)
    issues: list[CritiqueIssue] = []
    for _, kind, a, b in sorted(worst.values(), key=lambda p: -p[0])[:_MAX_OVERLAP_ISSUES]:
        la, lb = a["label"], b["label"]
        desc = (f"Text '{la}' and '{lb}' overlap — their bounding boxes intersect." if kind == "overlap"
                else f"Text '{la}' and '{lb}' nearly touch — the gap between them is tiny (cramped).")
        issues.append(CritiqueIssue(
            type="overlap",
            location=f"'{la}' & '{lb}'",
            description=desc,
            suggested_fix=(f"Separate '{la}' and '{lb}': place them in different regions / cells, or "
                           f"use next_to(..., buff>=0.3) so the labels aren't cramped."),
        ))
    return issues


def _covered_issues(items: list[dict], texts: list[dict]) -> list[CritiqueIssue]:
    """Flag a text label substantially COVERED by a FREE round/linear shape from a DIFFERENT group — a
    timer circle drawn on a box, an arrow struck through a label (scenes 0 & 3). Box shapes are excluded
    (they're the intended label container), and a shape covering its OWN group's label is skipped, so
    intended label-inside-box never trips."""
    shapes = [it for it in items if it["kind"] in _OCCLUDER_KINDS]
    texts = [t for t in texts if t.get("label")]
    if not shapes or not texts:
        return []
    flagged = []  # (cover_frac, text, shape)
    for t in texts:
        area_t = (t["x"][1] - t["x"][0]) * (t["y"][1] - t["y"][0])
        if area_t <= 0:
            continue
        for s in shapes:
            if s.get("i") == t.get("top"):
                continue  # the shape IS this text's own top-level container -> intended
            ox = max(0.0, min(t["x"][1], s["x"][1]) - max(t["x"][0], s["x"][0]))
            oy = max(0.0, min(t["y"][1], s["y"][1]) - max(t["y"][0], s["y"][0]))
            cover = (ox * oy) / area_t
            if cover >= _COVER_FRAC:
                flagged.append((cover, t, s))
                break
    issues: list[CritiqueIssue] = []
    for cover, t, s in sorted(flagged, key=lambda p: -p[0])[:_MAX_COVERED_ISSUES]:
        lbl = t["label"]
        issues.append(CritiqueIssue(
            type="overlap",
            location=f"{s['kind']} over '{lbl}'",
            description=(f"A {s['kind']} is drawn on top of the text '{lbl}' (covers ~{cover * 100:.0f}% "
                        f"of it) — the shape occludes the label."),
            suggested_fix=(f"Move the {s['kind']} off '{lbl}' (place it in a different cell, or next_to "
                           f"with buff>=0.3), or move the label — a shape must not sit on top of text."),
        ))
    return issues


def _tiny_font_issues(texts: list[dict]) -> list[CritiqueIssue]:
    """Flag SINGLE-LINE text (at any depth) rendered too small to read — usually auto-scaled to fit a
    cramped region (the place_in_area tradeoff). Multi-line text is skipped (height isn't a per-line proxy)."""
    small = []
    for it in texts:
        if not it.get("label") or it.get("nl"):
            continue
        h = it["y"][1] - it["y"][0]
        if 0.0 < h < _MIN_TEXT_HEIGHT:
            small.append((h, it))
    issues: list[CritiqueIssue] = []
    for h, it in sorted(small, key=lambda p: p[0])[:_MAX_TINY_FONT_ISSUES]:
        tag = it["label"]
        fs = it.get("fs") or 0
        fs_hint = f", font_size~{fs:.0f}" if fs else ""
        issues.append(CritiqueIssue(
            type="tiny_font",
            location=f"{it['kind']} '{tag}'",
            description=f"Text '{tag}' renders very small (height {h:.2f}u{fs_hint}) — likely unreadable.",
            suggested_fix=(f"Give it more room or a larger font — it was likely auto-scaled to fit a cramped "
                           f"region. Use fewer elements per row / a wider region / a bigger cell so its "
                           f"rendered height is >= {_MIN_TEXT_HEIGHT}u."),
        ))
    return issues


def _rel_lum(hexcol: str) -> float | None:
    """WCAG relative luminance of a #rrggbb color (0=black, 1=white). None if unparseable."""
    if not hexcol:
        return None
    h = hexcol.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return None
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(c1: str, c2: str) -> float | None:
    l1, l2 = _rel_lum(c1), _rel_lum(c2)
    if l1 is None or l2 is None:
        return None
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _contrast_issues(texts: list[dict], items: list[dict], bg: str) -> list[CritiqueIssue]:
    """Flag text that is NEAR-INVISIBLE against its background (dark-on-dark). Each text is compared to
    the fill of the SMALLEST filled shape it sits inside (its box), else the scene background. Only
    ratios below _MIN_CONTRAST are flagged, so a merely-muted label isn't nagged."""
    # a text is never its own background: exclude TEXT-kind items (their white glyph fill would compare a
    # title against ITSELF -> phantom 1.0:1), and below, a text's own top-level ancestor container.
    filled = [it for it in items if it.get("fill") and it["kind"] not in _TEXT_KINDS]
    flagged = []
    for t in texts:
        tc = t.get("color")
        if not tc or not t.get("label"):
            continue
        cx = (t["x"][0] + t["x"][1]) / 2.0
        cy = (t["y"][0] + t["y"][1]) / 2.0
        bg_col, best_area = bg, None                 # default: the scene background
        for s in filled:                              # the box the text sits in wins (smallest containing)
            if s.get("i") == t.get("top"):
                continue                              # the text's own container/group -> not a background
            if s["x"][0] <= cx <= s["x"][1] and s["y"][0] <= cy <= s["y"][1]:
                area = (s["x"][1] - s["x"][0]) * (s["y"][1] - s["y"][0])
                if best_area is None or area < best_area:
                    best_area, bg_col = area, s["fill"]
        cr = _contrast_ratio(tc, bg_col)
        if cr is not None and cr < _MIN_CONTRAST:
            flagged.append((cr, t, bg_col))
    issues: list[CritiqueIssue] = []
    for cr, t, bg_col in sorted(flagged, key=lambda p: p[0])[:_MAX_CONTRAST_ISSUES]:
        lbl = t["label"]
        issues.append(CritiqueIssue(
            type="low_contrast",
            location=f"'{lbl}'",
            description=(f"Text '{lbl}' ({t['color']}) is nearly invisible on its background ({bg_col}) "
                        f"— contrast only {cr:.1f}:1."),
            suggested_fix=(f"Give '{lbl}' a contrasting color (on the dark theme, WHITE or a light accent), "
                           f"or a lighter background — aim for a contrast ratio of at least 4:1."),
        ))
    return issues


def _centering_issue(items: list[dict], frame: list) -> list[CritiqueIssue]:
    """Flag a CLEARLY top-heavy scene — content clustered in the top rows with the lower half empty (the
    recurring 'empty frame' defect). Excludes the title band (always at the top) and only fires when the
    content's vertical center sits above _TOP_HEAVY_CY, so a centered single element / normal layout isn't
    nagged. One issue per scene (it's a whole-scene property)."""
    fx, fy = frame
    content = [it for it in items
               if (it["y"][0] + it["y"][1]) / 2.0 <= fy - _TITLE_BAND    # drop the title strip
               and (it["x"][1] - it["x"][0]) > 0 and (it["y"][1] - it["y"][0]) > 0]
    if not content:
        return []
    top = max(it["y"][1] for it in content)
    bot = min(it["y"][0] for it in content)
    cy = (top + bot) / 2.0
    if cy <= _TOP_HEAVY_CY:
        return []
    return [CritiqueIssue(
        type="layout",
        location="whole scene",
        description=(f"The content is clustered high in the frame (vertical center y={cy:.1f}); the lower "
                     f"half of the canvas is empty."),
        suggested_fix=("Center the content vertically — shift the whole group toward the middle (around "
                       "row C / y=0) or spread elements down into rows C, D, E, so the frame is used evenly "
                       "instead of clustered at the top. The title stays at the top; content fills below it."),
    )]


def _texts_of(facts: dict) -> list[dict]:
    """The text mobjects to compare. New probe emits `texts` (labels at any depth, each tagged with its
    top-level ancestor `top`). Backward-compat: if absent, derive from top-level text `items`, each its
    own group — so old callers / unit tests that pass only `items` behave exactly as before."""
    if "texts" in facts:
        return [t for t in facts["texts"] if t.get("label")]
    return [{**it, "top": it["i"]} for it in facts.get("items", [])
            if it["kind"] in _TEXT_KINDS and it.get("label")]


def issues_from_facts(facts: dict) -> list[CritiqueIssue]:
    """Pure: probe geometry facts -> OFF-FRAME + OVERLAP + SHAPE-OVER-TEXT + TINY-FONT CritiqueIssues.
    Unit-testable without Docker."""
    fx, fy = facts["frame"]
    texts = _texts_of(facts)
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
    # scan the final frame AND every per-play snapshot -> catches transient collisions (scene-4 defect)
    issues.extend(_overlap_issues([texts, *facts.get("snapshots", [])]))
    issues.extend(_covered_issues(facts.get("items", []), texts))  # a shape drawn on top of a label
    issues.extend(_tiny_font_issues(texts))                        # unreadable tiny text
    issues.extend(_contrast_issues(texts, facts.get("items", []),  # near-invisible dark-on-dark text
                                   facts.get("bg", "#000000")))
    issues.extend(_centering_issue(facts.get("items", []), [fx, fy]))  # top-heavy / empty-frame layout
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
