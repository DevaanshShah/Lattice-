"""Reusable, pre-tested Manim components, prepended to generated scenes so the model can't draw
common figures wrong (Code2Video's component idea, but lightweight: a few free helpers, no grid
base-class). `COMPONENTS_SRC` is prepended before the generated `GeneratedScene`; the codegen prompt
tells the model these are available. Each helper is self-laying-out and frame-safe by construction:

- `fitted_title`        — a title that ALWAYS fits the frame width (kills the oversized-title overflow).
- `circle_with_radius`  — circle + center + radius, label ABOVE the radius (never on the line).
- `circumference_unroll`— a circle + its circumference unrolled into a BOUNDED 2*pi*r segment with end
                          ticks (clamped so it can't run off-frame) — the clean version of the broken scene.
"""
from __future__ import annotations

COMPONENTS_SRC = r'''
from manim import *
import numpy as np

def fitted_title(text, font_size=44, max_width=12.0):
    """Scene title that ALWAYS fits the frame width. Use for EVERY scene title."""
    t = Text(str(text), font_size=font_size, weight=BOLD).to_edge(UP, buff=0.4)
    if t.width > max_width:
        t.scale_to_fit_width(max_width)
    return t

def circle_with_radius(radius=2.0, label="r", color=BLUE, accent=YELLOW):
    """Circle + center dot + a radius line whose label sits just ABOVE it (never on the line)."""
    circ = Circle(radius=radius, color=color)
    dot = Dot(circ.get_center(), color=color)
    rad = Line(circ.get_center(), circ.get_center() + RIGHT * radius, color=accent)
    lbl = MathTex(str(label), color=accent).scale(0.9).next_to(rad, UP, buff=0.1)
    return VGroup(circ, dot, rad, lbl)

def circumference_unroll(radius=1.0, color=BLUE, accent=RED, max_len=7.0):
    """A circle and, to its right, its circumference unrolled into a STRAIGHT bounded segment of
    length 2*pi*r (clamped to max_len) with end ticks and a '2 pi r' label. The whole group is
    CENTERED at the origin so it stays on-frame wherever the caller places it."""
    circ = Circle(radius=radius, color=color)
    seg_len = min(2 * PI * radius, max_len)
    start = circ.get_right() + RIGHT * 0.6
    end = start + RIGHT * seg_len
    seg = Line(start, end, color=accent)
    t1 = Line(start + DOWN * 0.12, start + UP * 0.12, color=accent)
    t2 = Line(end + DOWN * 0.12, end + UP * 0.12, color=accent)
    lbl = MathTex(r"2\pi r", color=accent).next_to(seg, UP, buff=0.12)
    return VGroup(circ, seg, t1, t2, lbl).move_to(ORIGIN)

def labeled_box(text, width=2.2, height=1.0, color=BLUE, text_color=WHITE):
    """A rounded box with a centered, auto-fitted text label — for documents, terms, table cells,
    or any named entity. The label can never overflow the box."""
    box = RoundedRectangle(width=width, height=height, corner_radius=0.12, color=color)
    lbl = Text(str(text), font_size=24, color=text_color)
    if lbl.width > width - 0.3:
        lbl.scale_to_fit_width(width - 0.3)
    return VGroup(box, lbl.move_to(box.get_center()))

def formula_block(tex, color=WHITE, scale=1.2, max_width=11.0):
    """A centered MathTex formula scaled to fit the frame width. Pass LaTeX WITHOUT the $ signs."""
    f = MathTex(str(tex), color=color).scale(scale)
    if f.width > max_width:
        f.scale_to_fit_width(max_width)
    return f
'''

# Prompt addendum: tell the generator the helpers exist and when to use them.
COMPONENTS_PROMPT = """
You also have these PRE-DEFINED, pre-tested helper functions available (do NOT redefine them; just call them):
- `fitted_title(text)` -> a Text title that always fits the frame. Use it for the scene title instead of raw Text(...).to_edge(UP).
- `circle_with_radius(radius=2.0, label="r")` -> a VGroup(circle, center dot, radius line, label). Use for any "circle with a radius" figure.
- `circumference_unroll(radius=1.0)` -> a VGroup showing a circle next to its circumference unrolled as a bounded straight 2*pi*r segment. Use whenever you must show circumference/perimeter being unrolled — do NOT hand-draw a flattened ellipse.
- `labeled_box(text, width=2.2)` -> a rounded box with a fitted label. Use for documents, terms, table cells, or any named entity — do NOT hand-draw boxes with text that overflows.
- `formula_block(tex)` -> a centered formula scaled to fit the frame. Use for equations (pass LaTeX without $). Do NOT write equations that run off the edge.
Prefer these helpers over hand-drawing the same figures; they are frame-safe and correctly laid out.
Always set a dark background at the start: self.camera.background_color = "#101015".
"""
