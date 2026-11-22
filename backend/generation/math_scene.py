"""Deterministic Manim MATH scene for the hybrid deck — the ~20% a slide cannot do.

Slides (generation.slide_deck) own cards/flows/steps: CSS does those better, free, instantly. But CSS
cannot PLOT a function or roll a dot down a curve. That is Manim's actual home turf, so a deck slide
flagged `kind:"math"` routes here instead of to Chrome.

The LLM supplies CONTENT ONLY (the expression, the x-range, the axis labels) — the layout comes from the
proven self.graph() component (auto-fits y-range, so the curve cannot leave the frame). No LLM writes
Manim code here, so there is nothing to compile-repair or critique.
"""
from __future__ import annotations

import re

from generation.lattice_scene import LATTICE_SCENE_SRC

# The expression is embedded into code that runs in the render sandbox. Keep it to plain math: digits,
# x, operators, parens, and a few whitelisted numpy calls. No names/attrs/calls beyond this survive.
_ALLOWED_CALL = ("np.sin", "np.cos", "np.tan", "np.exp", "np.log", "np.sqrt", "np.abs", "np.pi")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9.]*")


class MathSceneError(ValueError):
    pass


def safe_expr(fn: str) -> str:
    """Validate an LLM-supplied f(x) expression. Raises MathSceneError on anything but plain math."""
    fn = (fn or "").strip()
    if not fn or len(fn) > 200:
        raise MathSceneError("empty or over-long expression")
    if any(bad in fn for bad in ("__", "import", "lambda", ";", "\n", "open", "eval", "exec")):
        raise MathSceneError(f"disallowed construct in {fn!r}")
    for tok in _TOKEN.findall(fn):
        if tok == "x" or tok in _ALLOWED_CALL:
            continue
        raise MathSceneError(f"disallowed name {tok!r} (allowed: x, {', '.join(_ALLOWED_CALL)})")
    return fn


def render_scene_code(fn: str, x_range, *, title: str = "", dots=None, x_label: str = "",
                      y_label: str = "", roll: bool = True, seconds: float = 6.0) -> str:
    """A self-contained Manim scene: plot f(x) via self.graph(), then roll a dot along the curve.

    fn: an f(x) expression (validated). x_range: [x_min, x_max]. dots: x values to mark.
    roll: animate a dot travelling along the plotted curve (the motion CSS can't do)."""
    fn = safe_expr(fn)
    x0, x1 = float(x_range[0]), float(x_range[1])
    dots = [float(d) for d in (dots or [])]
    hold = max(1.0, float(seconds) - 4.0)
    body = f'''

class GeneratedScene(LatticeScene):
    def construct(self):
        self.setup_scene({title!r})
        g = self.graph(lambda x: {fn}, [{x0!r}, {x1!r}], dots={dots!r},
                       x_label={x_label!r}, y_label={y_label!r})
        self.place_in_area(g, "B2", "D5")
        axes, curve = g[0], g[1]
        self.play(Create(g), run_time=1.6)
        self.wait(0.3)
'''
    if roll:
        body += f'''        d = Dot(color=YELLOW, radius=0.10).move_to(curve.get_start())
        self.play(FadeIn(d, scale=1.4), run_time=0.4)
        self.play(MoveAlongPath(d, curve), run_time=2.2, rate_func=rate_functions.ease_in_out_sine)
'''
    body += f'''        self.wait({hold!r})
        self.fit_content()
'''
    return LATTICE_SCENE_SRC + body
