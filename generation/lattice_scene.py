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

# Grid geometry — MUST stay in sync with the constants inside LATTICE_SCENE_SRC below.
GRID_COLS = 8                 # columns 1..8, left -> right
GRID_ROWS = "ABCDE"           # rows A(top) .. E(bottom)
_MAIN_X = (-6.0, 6.0)         # main-area x span (frame is ~14.2 wide; this leaves margin)
_MAIN_Y = (2.3, -3.0)         # main-area y span (sits BELOW the title band)


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


LATTICE_SCENE_SRC = '''from manim import *
import numpy as np


class LatticeScene(Scene):
    """Structural layout base: a named grid + mandatory title so placement can't free-hand into
    overlap. Use self.place(obj, "C4") / self.place_in_area(...) / the components; avoid raw
    .move_to([x,y,0]) for layout. The whole frame is available (narration is audio, not on-screen)."""
    GRID_COLS = 8
    GRID_ROWS = "ABCDE"
    MAIN_X = (-6.0, 6.0)
    MAIN_Y = (2.3, -3.0)

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
        s = str(text)
        if "$" in s or "_" in s or "^" in s or chr(92) in s:
            try:
                return MathTex(s.strip("$"), font_size=font_size)
            except Exception:
                return Text(s, font_size=font_size)
        return Text(s, font_size=font_size)

    # --- starter components: self-laying-out, own their labels (no sibling collisions) ---
    def labeled_box(self, text, color=BLUE, w=1.6, h=1.0):
        box = Rectangle(width=w, height=h, color=color)
        lbl = self._label(text, 24).move_to(box.get_center())
        if lbl.width > w - 0.2:
            lbl.scale_to_fit_width(w - 0.2)
        return VGroup(box, lbl)

    def node(self, label, color=BLUE, r=0.35):
        c = Circle(radius=r, color=color)
        lbl = self._label(label, 22).move_to(c.get_center())
        if lbl.width > 2 * r - 0.1:
            lbl.scale_to_fit_width(2 * r - 0.1)
        return VGroup(c, lbl)

    def connect(self, a, b, color=GREY, buff=0.1):
        return Arrow(a.get_center(), b.get_center(), buff=buff, color=color, stroke_width=3)
'''
