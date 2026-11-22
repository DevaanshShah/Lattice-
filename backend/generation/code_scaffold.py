"""Deterministic code-walkthrough scene codegen.

Emits a standalone Manim `GeneratedScene` that renders the FULL snippet on the left (dim), brightens
the active line(s), and points an arrow to a short caption on the right. The layout is fixed in code
(no LLM, no free-hand placement), so it is reliable regardless of model — the planner only supplies
which line to highlight and what to say. See out/walkthrough_preview/scaffold_proto for the prototype.

Contract with the render pipeline: the scene class is named `GeneratedScene` (SCENE_CLASS) and is
self-contained (`from manim import *`), so verification.compile_repair renders it as-is.
"""
from __future__ import annotations

# Fixed body: helpers + the scene. Plain string (NOT an f-string) so Manim's own braces stay literal.
_PRELUDE = '''from manim import *
import re as _re

BG = "#101015"
ACCENT = "#F2B441"
KEYWORD = "#FFD43B"
COMMENT = "#6A9955"
DIM = 0.28
FS = 24
KW = ["def", "return", "print", "sum", "for", "in", "if", "elif", "else", "while", "import",
      "from", "class", "lambda", "and", "or", "not", "None", "True", "False", "with", "as",
      "try", "except", "yield", "pass", "break", "continue", "range", "len", "int", "str"]
'''

_BODY = '''

def build_line(text):
    # Pango strips leading whitespace, so we render the un-indented text and re-apply indentation as a
    # measured horizontal offset in construct() (deterministic, font-independent).
    text = text.lstrip(" ")
    if text.startswith("#"):
        return Text(text, font="Monospace", font_size=FS, color=COMMENT)
    t2c = {}
    for k in KW:
        if _re.search(r"\\b" + _re.escape(k) + r"\\b", text):
            t2c[k] = KEYWORD
    return Text(text, font="Monospace", font_size=FS, t2c=t2c)


def wrap(s, n=26):
    words, out, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= n:
            cur = (cur + " " + w).strip()
        else:
            out.append(cur); cur = w
    if cur:
        out.append(cur)
    return "\\n".join(out)


class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = BG
        title = Text(TITLE, font_size=30, weight=BOLD).to_edge(UP, buff=0.32)
        if title.width > 12.5:
            title.scale_to_fit_width(12.5)

        LINE_H = 0.44
        space_w = (Text("x x", font="Monospace", font_size=FS).width
                   - Text("xx", font="Monospace", font_size=FS).width)   # one monospace space, measured
        items, mobs, rows = [], {}, []
        for i, raw in enumerate(LINES):
            if not raw.strip():
                continue
            m = build_line(raw)
            m.move_to([0, -i * LINE_H, 0])
            items.append(m); mobs[i] = m
            rows.append((m, len(raw) - len(raw.lstrip(" "))))
        for m, indent in rows:
            m.set_x(m.get_x() - m.get_left()[0] + indent * space_w)   # left-align + preserve indentation
        code = VGroup(*items)
        if code.width > 6.3:
            code.scale_to_fit_width(6.3)
        if code.height > 6.4:
            code.scale_to_fit_height(6.4)
        code.to_edge(LEFT, buff=0.5)
        code.set_y(-0.35)

        active_mobs = [mobs[i] for i in ACTIVE if i in mobs]
        base_op = 1.0 if not active_mobs else DIM      # overview (no active line) shows full code bright
        for m in items:
            m.set_opacity(base_op)

        self.add(title, code)
        self.wait(0.3)

        show = [m.animate.set_opacity(1.0) for m in active_mobs]
        grp = None
        if CAPTION:
            gx = code.get_right()[0] + 0.3
            cx = (gx + 6.9) / 2.0
            ay = float(active_mobs[0].get_y()) if active_mobs else 0.0
            cy = max(-2.5, min(2.6, ay))
            cap = Text(wrap(CAPTION), font_size=25, line_spacing=0.8).set_color(WHITE).move_to([cx, cy, 0])
            if cap.width > 6.6:
                cap.scale_to_fit_width(6.6)
            parts = [cap]
            if active_mobs:
                arrow = Arrow([gx, ay, 0], cap.get_left() + LEFT * 0.12, buff=0.1, color=ACCENT,
                              stroke_width=3, max_tip_length_to_length_ratio=0.18)
                parts.insert(0, arrow)
            grp = VGroup(*parts)
            show.append(FadeIn(grp, shift=RIGHT * 0.15))
        if show:
            self.play(*show, run_time=0.5)
        self.wait(max(1.6, HOLD - 0.8))
'''


def render_scene_code(lines: list[str], active: list[int], caption: str, title: str,
                      seconds: float) -> str:
    """Return a self-contained Manim `GeneratedScene` for one walkthrough step.

    lines: the full snippet (one str per source line, blanks kept for spacing).
    active: indices (into `lines`) to highlight; [] renders the whole code as an intro/overview.
    caption: the short right-panel explanation. title: the persistent scene title.
    seconds: how long to hold the frame (paced to narration length by the caller).
    """
    header = (
        "LINES = " + repr(list(lines)) + "\n"
        "ACTIVE = " + repr([int(i) for i in active]) + "\n"
        "CAPTION = " + repr(str(caption or "")) + "\n"
        "TITLE = " + repr(str(title or "")) + "\n"
        "HOLD = " + repr(float(seconds)) + "\n"
    )
    return _PRELUDE + header + _BODY
