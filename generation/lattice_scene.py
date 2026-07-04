"""Structural layout scaffold (Phase 2 / FR-32) — a `LatticeScene` base class prepended to
generated code so the model places objects into a NAMED GRID + components instead of free-handing
coordinates (the way Code2Video does). Overlap/off-frame become hard *by construction*, and the
**title is always rendered** (fixes the dropped-title defect). Gated by `settings.structural_layout`
so it is A/B-measurable against the free-hand baseline.

`LATTICE_SCENE_SRC` is a self-contained source string prepended before the generated `GeneratedScene`
(which subclasses `LatticeScene`). `grid_cells()` is a pure host-side mirror of the in-container grid,
so the geometry is unit-testable without Manim/Docker.
"""
from __future__ import annotations

from pathlib import Path

# Grid geometry — MUST stay in sync with the constants inside LATTICE_SCENE_SRC below.
GRID_COLS = 8                 # columns 1..8, left -> right
GRID_ROWS = "ABCDE"           # rows A(top) .. E(bottom)
_MAIN_X = (-6.0, 6.0)         # main-area x span (frame is ~14.2 wide; this leaves margin)
_MAIN_Y = (2.3, -3.0)         # main-area y span (sits BELOW the title band)

# Curated Lucide (ISC) line-icons, baked into the render image at /opt/icons/<slug>.svg (Dockerfile).
# AUTO-DERIVED from the bundled files so adding an icon = drop the SVG in assets/icons/ + rebuild the
# image — no code edit, no hardcoded list to drift. Feeds the codegen prompt (icon_catalog_prompt); the
# in-container self.icon() is file-driven + falls back, so it needs no copy of this list.
_ICON_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
ICON_NAMES: list[str] = sorted(p.stem for p in _ICON_ASSET_DIR.glob("*.svg"))


def grid_cells() -> dict[str, tuple[float, float]]:
    """Pure mirror of the in-container grid: cell name (e.g. 'C4') -> (x, y) center."""
    cells: dict[str, tuple[float, float]] = {}
    for ri, row in enumerate(GRID_ROWS):
        ty = ri / (len(GRID_ROWS) - 1)
        y = _MAIN_Y[0] + (_MAIN_Y[1] - _MAIN_Y[0]) * ty
        for col in range(1, GRID_COLS + 1):
            tx = (col - 1) / (GRID_COLS - 1)
            x = _MAIN_X[0] + (_MAIN_X[1] - _MAIN_X[0]) * tx
            cells[f"{row}{col}"] = (x, y)
    return cells


def square_corners_away_from(
    p1: tuple[float, float], p2: tuple[float, float], away_from: tuple[float, float],
) -> list[tuple[float, float]]:
    """Pure 2D mirror of `LatticeScene.square_on_segment`'s orientation math (no Manim/Docker needed):
    the 4 corners of a square flush on segment p1->p2, picked to extend AWAY from `away_from` via a
    dot-product side test. z is dropped (always 0 for our 2D constructions) -- this mirrors the
    in-container method's logic exactly, just without the Manim Polygon/np.ndarray wrapping."""
    ax, ay = p1[0], p1[1]
    bx, by = p2[0], p2[1]
    ex, ey = bx - ax, by - ay
    px, py = -ey, ex   # rotate +90 deg; |perp| == |edge| => a square
    rx, ry = away_from[0], away_from[1]
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    if px * (rx - mx) + py * (ry - my) > 0:   # perp points TOWARD the reference -> flip
        px, py = -px, -py
    return [(ax, ay), (bx, by), (bx + px, by + py), (ax + px, ay + py)]


def icon_catalog_prompt() -> str:
    """A system-prompt addendum listing the bundled icon names, so the codegen model knows exactly which
    `self.icon("name")` calls resolve (an unknown name silently falls back to a labeled box). Kept here so
    the list lives in ONE place (ICON_NAMES) and the .md prompt never hardcodes / drifts from the shipped set."""
    return ("\n\nAVAILABLE ICONS — for a RECOGNIZABLE real-world entity, use `self.icon(\"name\")` instead "
            "of a plain box/circle (a server, a database, a user, a cat, ...). Names that resolve:\n"
            + ", ".join(ICON_NAMES)
            + "\nPlace and connect an icon exactly like a node. Only use names from this list; any other "
            "name falls back to a labeled box.")


def scaffold_methods() -> list[str]:
    """The public method signatures LatticeScene actually provides, PARSED from LATTICE_SCENE_SRC so the
    list can never drift from the real code. Feeds the 'these are the only methods' prompt block below."""
    import re
    seen: list[str] = []
    for m in re.finditer(r"\n    def (\w+)\(self,?\s*(.*?)\):", LATTICE_SCENE_SRC, re.DOTALL):
        name, params = m.group(1), " ".join(m.group(2).split())
        if name.startswith("_"):
            continue                                  # skip private/dunder helpers
        sig = f"self.{name}({params})" if params else f"self.{name}()"
        if sig not in seen:
            seen.append(sig)
    return seen


def scaffold_api_prompt() -> str:
    """Authoritative list of the ONLY methods LatticeScene exposes — stops the model inventing scaffold
    methods that don't exist (a real failure: a scene called `self.get_cell_center(...)`, which isn't a
    method, and died through 3 compile-repair round-trips). Reaches codegen AND both fixers via
    structural_system_prompt, so this class of hallucination self-heals instead of burning the scene."""
    methods = "\n".join(f"  - {s}" for s in scaffold_methods())
    return ("\n\nSCAFFOLD METHODS — these are the ONLY methods LatticeScene provides. Call the layout/"
            "component helpers by these EXACT names; do NOT invent scaffold methods. In particular the "
            "cell centre is `self.cell(\"B2\")` (there is NO get_cell_center / cell_center / get_cell):\n"
            + methods
            + "\nEverything else is ordinary Manim. For positions use self.cell(name) / self.place(obj, "
            "name) / self.place_in_area(...); never guess a self.<name> that isn't listed above.")


def structural_system_prompt(*, narrated: bool = False) -> str:
    """The full structural codegen system prompt (house conventions + lattice prompt + scaffold-API list
    + icon catalog), assembled in ONE place instead of duplicated across the codegen/fix/repair sites."""
    from prompts.loader import load   # function-local: keep this module import-light for the compile test
    base = load("manim-conventions") + "\n\n---\n\n" + load(
        "lattice-codegen-narrated" if narrated else "lattice-codegen")
    return base + scaffold_api_prompt() + icon_catalog_prompt()


LATTICE_SCENE_SRC = '''from manim import *
import numpy as np
import os
import re
import shutil


class LatticeScene(Scene):
    """Structural layout base: a named grid + mandatory title so placement can't free-hand into
    overlap. Use self.place(obj, "C4") / self.place_in_area(...) / the components; avoid raw
    .move_to([x,y,0]) for layout. The whole frame is available (narration is audio, not on-screen)."""
    GRID_COLS = 8
    GRID_ROWS = "ABCDE"
    MAIN_X = (-6.0, 6.0)
    MAIN_Y = (2.3, -3.0)
    ICON_DIR = "/opt/icons"        # curated line-icons baked into the render image (see assets/icons/)

    def setup_scene(self, title):
        """MUST be the first call in construct(). Renders the title (always, fit to frame) + builds the grid."""
        self.camera.background_color = "#101015"
        self.scene_title = Text(str(title), font_size=34, weight=BOLD).to_edge(UP, buff=0.35)
        if self.scene_title.width > 12.5:
            self.scene_title.scale_to_fit_width(12.5)
        self.add(self.scene_title)
        self.grid = {}
        rows, cols = self.GRID_ROWS, self.GRID_COLS
        for ri, row in enumerate(rows):
            ty = ri / (len(rows) - 1)
            y = self.MAIN_Y[0] + (self.MAIN_Y[1] - self.MAIN_Y[0]) * ty
            for col in range(1, cols + 1):
                tx = (col - 1) / (cols - 1)
                x = self.MAIN_X[0] + (self.MAIN_X[1] - self.MAIN_X[0]) * tx
                self.grid[f"{row}{col}"] = np.array([x, y, 0.0])

    def cell(self, name):
        return self.grid[name]

    def place(self, mob, name, scale=1.0):
        if scale != 1.0:
            mob.scale(scale)
        mob.move_to(self.grid[name])
        return mob

    def place_in_area(self, mob, top_left, bottom_right):
        tl, br = self.grid[top_left], self.grid[bottom_right]
        center = (tl + br) / 2
        w = abs(br[0] - tl[0]) + 1.2
        h = abs(tl[1] - br[1]) + 1.2
        if mob.width > w:
            mob.scale_to_fit_width(w)
        if mob.height > h:
            mob.scale_to_fit_height(h)
        mob.move_to(center)
        return mob

    def _label(self, text, font_size=24):
        # Math labels (x_1, w^2, \\sigma, $...$) render as MathTex; plain words as Text. Without
        # this, "x_1"/"$x_1$" show as LITERAL text instead of a subscript (the structural-A/B bug).
        if isinstance(text, Mobject):
            return text  # model passed a ready MathTex/Text (natural idiom) — use it, don't str() its repr
        s = str(text)
        if "$" in s or "_" in s or "^" in s or chr(92) in s:
            try:
                return MathTex(s.strip("$"), font_size=font_size)
            except Exception:
                return Text(s, font_size=font_size)
        return Text(s, font_size=font_size)

    # --- starter components: self-laying-out, own their labels (no sibling collisions) ---
    def _style_kw(self, style, extra=()):
        # The model naturally passes Manim styling kwargs (fill_color, stroke_color, ...) to these
        # components; accept the safe ones and DROP anything unknown so a stray kwarg can never raise a
        # TypeError that kills the render (a real failure: labeled_box("x", corner_radius=..) crashed a scene).
        ok = ("fill_color", "fill_opacity", "stroke_color", "stroke_width", "stroke_opacity", "color") + tuple(extra)
        return {k: v for k, v in style.items() if k in ok}

    def labeled_box(self, text, color=BLUE, w=1.6, h=1.0, **style):
        cr = style.pop("corner_radius", 0.0)   # tolerate corner_radius via RoundedRectangle (0 == sharp)
        kw = self._style_kw(style); kw.setdefault("color", color)
        box = RoundedRectangle(width=w, height=h, corner_radius=cr, **kw)
        lbl = self._label(text, 24).move_to(box.get_center())
        if lbl.width > w - 0.2:
            lbl.scale_to_fit_width(w - 0.2)
        return VGroup(box, lbl)

    def node(self, label, color=BLUE, r=0.35, **style):
        style.pop("corner_radius", None)       # circles have no corners -> drop it silently
        kw = self._style_kw(style); kw.setdefault("color", color)
        c = Circle(radius=r, **kw)
        lbl = self._label(label, 22).move_to(c.get_center())
        if lbl.width > 2 * r - 0.1:
            lbl.scale_to_fit_width(2 * r - 0.1)
        return VGroup(c, lbl)

    def connect(self, a, b, color=GREY, buff=0.1, **style):
        kw = {"buff": buff, "color": color, "stroke_width": 3}
        kw.update(self._style_kw(style, extra=("max_tip_length_to_length_ratio", "tip_length")))
        return Arrow(a.get_center(), b.get_center(), **kw)

    def icon(self, name, color=WHITE, width=1.0):
        """A recognizable line-icon Mobject for a REAL-WORLD entity (server, database, router, cloud,
        user, laptop, cat, car, ...), tinted `color` and fit to `width`. Use it wherever a node/box
        would be a meaningless blob for a concrete thing, then place + connect it like a node. Does NOT
        place itself (caller uses self.place / self.place_in_area). ROBUST: an unknown/missing/unparseable
        name falls back to labeled_box(name), so a bad icon never crashes the render."""
        slug = re.sub(r"[^a-z0-9_-]", "", str(name).lower())   # traversal-safe + case-normalized
        src = os.path.join(self.ICON_DIR, slug + ".svg")
        try:
            if slug and os.path.exists(src):
                # SVGMobject writes a derived "<slug>_.svg" NEXT TO the source; /opt/icons is read-only
                # to the render user, so load from the writable work dir (CWD) instead.
                local = slug + ".svg"
                if not os.path.exists(local):
                    shutil.copyfile(src, local)
                svg = SVGMobject(local)
                if len(svg.submobjects) or svg.width > 0:      # guard SVGMobject's silent empty-parse
                    svg.set_stroke(color); svg.set_fill(color)  # line icons: fill=none stays invisible
                    svg.scale_to_fit_width(width)
                    return svg
        except Exception:
            pass
        return self.labeled_box(name, color=color)              # unknown/missing -> readable box label

    # --- geometry primitives: correctness-by-construction for the math the model reasons badly blind ---
    def square_on_segment(self, p1, p2, away_from=None, color=BLUE, fill_opacity=0.25, outward=True):
        """A square built FLUSH on segment p1->p2 (side length = |p1 p2|), extending to ONE side.
        Removes the hard math of placing a square on a triangle's edge (the model gets this wrong
        free-hand). Already positioned relative to p1/p2 -- do NOT self.place() it.

        ALWAYS pass `away_from` (a third reference point the square must extend away from, e.g. the
        triangle's third vertex or `triangle.get_center()`) -- the side is then picked by a dot-product
        test, so it is correct for ANY vertex order/winding, not a guess. Without `away_from`, the
        legacy `outward` bool picks a side by a fixed rotation sign, which can be the WRONG side
        depending on winding (this caused a real overlap bug) -- only rely on it if you truly have no
        reference point available.
        """
        a = np.array(p1, dtype=float); b = np.array(p2, dtype=float)
        edge = b - a
        perp = np.array([-edge[1], edge[0], 0.0])   # rotate +90 deg in-plane; |perp| == |edge| => a square
        if away_from is not None:
            ref = np.array(away_from, dtype=float)
            mid = (a + b) / 2.0
            if np.dot(perp, ref - mid) > 0:   # perp points TOWARD the reference -> flip to point away
                perp = -perp
        elif not outward:
            perp = -perp
        return Polygon(a, b, b + perp, a + perp, color=color,
                       fill_color=color, fill_opacity=fill_opacity, stroke_width=2)

    def braced(self, mob, text, direction=DOWN, color=GREY):
        """A Brace on `mob` in `direction` with its label just beyond it. Returns VGroup(brace, label)."""
        br = Brace(mob, direction=direction, color=color)
        lbl = self._label(text, 24).next_to(br, direction, buff=0.1)
        return VGroup(br, lbl)
'''
