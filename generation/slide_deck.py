"""HTML/CSS designed-slide renderer — an ADDITIVE alternative to the Manim scene path.

Why this exists: Manim is a math-ANIMATION engine; its native output is flat Rectangles + plain Text,
so card/flow/diagram slides top out at "clean but amateur" no matter how much reliability scaffolding
we add. The same slide in CSS gets border-radius + gradients + glow + real typography in ~3 lines, and
flexbox CANNOT put a card off-frame or overlap two labels — so the whole compile-repair / layout-lint /
vision-critic / re-roll apparatus the Manim path needs is simply not required here.

Contract: the LLM supplies CONTENT ONLY (title, card labels, bullet text). Layout + styling live here,
fixed, so every slide in every deck is consistent. Nothing in this module imports or changes the Manim
path — it is a parallel renderer.

`page_html(slide)` -> a standalone 1200x675 page for headless Chrome to screenshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any

W, H = 1280, 720   # 16:9 and BOTH EVEN — libx264/yuv420p rejects odd dimensions (1200x675 failed)

# --- the design system (one palette + type scale reused by every slide) ----------------------
CSS = """
:root{
  --bg:#0d0d12; --ink:#e9e7e2; --muted:#8b8b96; --faint:#5c5c68; --line:#24242e; --panel:#16161d;
  --blue:#5b9bd5; --purple:#c07fd6; --green:#5fbf87; --amber:#e0a33c; --red:#e0574a; --cyan:#4fb6c4;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{width:1280px;height:720px;background:var(--bg);color:var(--ink);overflow:hidden;
     font-family:"Segoe UI",system-ui,-apple-system,sans-serif;}
.slide{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;
       justify-content:center;gap:34px;padding:56px 64px;text-align:center;}
h1.hero{font-family:Georgia,"Times New Roman",serif;font-size:52px;font-weight:600;
        line-height:1.12;letter-spacing:-.5px;color:var(--blue);}
h2{font-family:Georgia,"Times New Roman",serif;font-size:33px;font-weight:600;letter-spacing:.2px;}
.sub{font-family:Georgia,serif;font-size:17px;color:var(--muted);letter-spacing:.4px;}
.note{font-size:13px;color:var(--green);letter-spacing:.3px;}
.lead{font-family:Georgia,serif;font-size:22px;color:var(--amber);}
.row{display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap;}
.arrow{color:var(--faint);font-size:22px;line-height:1;}
/* the card: radius + gradient + colored border + outer glow — the whole aesthetic, 4 lines */
.card{border-radius:12px;padding:18px 26px;min-width:206px;
      border:1px solid color-mix(in srgb, var(--c) 45%, transparent);
      background:linear-gradient(160deg, color-mix(in srgb, var(--c) 16%, transparent), transparent 70%);
      box-shadow:0 0 28px -6px color-mix(in srgb, var(--c) 40%, transparent);}
.card .t{font-size:20px;font-weight:700;color:var(--c);margin-bottom:5px;}
.card .s{font-family:Georgia,serif;font-size:12.5px;color:var(--muted);letter-spacing:.3px;}
.subbox{min-width:206px;border-radius:8px;padding:9px 10px;background:var(--panel);
        border:1px solid var(--line);}
.subbox .a{font-size:13px;} .subbox .b{font-size:11px;color:var(--faint);}
.chip{border-radius:7px;padding:9px 15px;background:#1c1c26;border:1px solid #2c2c38;font-size:15px;}
.idchip{border-radius:7px;padding:7px 15px;background:#15202e;border:1px solid #24384f;
        font-size:13px;color:var(--blue);}
.tick{color:var(--faint);font-size:14px;line-height:1;}
ul.bul{list-style:none;display:flex;flex-direction:column;gap:16px;text-align:left;}
ul.bul li{font-size:17px;color:var(--muted);line-height:1.5;}
ul.bul .lab{font-weight:700;}
ul.bul .dot{color:var(--faint);margin-right:9px;}
.kicker{font-family:Georgia,serif;font-size:19px;color:var(--amber);font-weight:600;}
/* the Lattice mark — baked into the screenshot, so it costs nothing: no overlay pass, no re-encode */
.foot{position:absolute;bottom:22px;right:26px;display:flex;align-items:center;gap:7px;opacity:.5;}
.foot .glyph{width:15px;height:15px;position:relative;border:1.2px solid var(--amber);border-radius:2px;}
.foot .glyph i{position:absolute;background:var(--amber);}
.foot .glyph i.v{top:0;bottom:0;width:1px;} .foot .glyph i.h{left:0;right:0;height:1px;}
.foot .word{font-size:12px;font-weight:700;color:var(--amber);letter-spacing:.02em;}
/* focus states: the element being SPOKEN lights up, everything else recedes. One frame per narration
   beat, held for that beat's measured audio length -> the highlight tracks the voice exactly. */
.dim{opacity:.3;filter:saturate(.3);}
.card.on{transform:translateY(-3px) scale(1.035);
         border-color:color-mix(in srgb, var(--c) 85%, transparent);
         box-shadow:0 0 46px -4px color-mix(in srgb, var(--c) 72%, transparent);}
.chip.on,.idchip.on{background:#26263a;border-color:#4a4a68;transform:scale(1.06);}
ul.bul li.on{color:var(--ink);}
ul.bul li.on .dot{color:var(--amber);}
"""

_COLORS = ("blue", "purple", "green", "amber", "cyan", "red")


def _c(name: str, i: int = 0) -> str:
    n = (name or "").strip().lower()
    return n if n in _COLORS else _COLORS[i % len(_COLORS)]


@dataclass
class Slide:
    kind: str                       # title | cards | chips | bullets | math (math routes to Manim)
    title: str = ""
    # --- math-slide fields (kind="math"): rendered by generation.math_scene, NOT by this HTML path ---
    fn: str = ""                    # f(x) expression, e.g. "0.5*(x-1)**2 + 1"
    x_range: list = field(default_factory=list)   # [x_min, x_max]
    dots: list = field(default_factory=list)      # x values to mark on the curve
    x_label: str = ""
    y_label: str = ""
    subtitle: str = ""
    cards: list = field(default_factory=list)      # [{label, sub, color}]
    subboxes: list = field(default_factory=list)   # [{a, b}] under the cards
    lead: str = ""
    chips: list = field(default_factory=list)      # ["I","love",...]
    ids: list = field(default_factory=list)        # ["7","3245",...]
    note: str = ""
    bullets: list = field(default_factory=list)    # [{label, text, color}]
    kicker: str = ""
    # narration split into beats: [{"say": "<one spoken sentence>", "focus": <element index|-1>}].
    # One rendered frame per beat, held for that beat's measured TTS duration.
    beats: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Slide":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def script(self) -> str:
        """The slide's narration as one string (used for the math scene, which has no beat frames)."""
        return " ".join(str(b.get("say", "")).strip() for b in self.beats).strip()


def _fx(i: int, focus: int) -> str:
    """Class for element `i` given the focused index: lit, dimmed, or neutral (focus < 0)."""
    if focus < 0:
        return ""
    return " on" if i == focus else " dim"


def _cards_html(s: Slide, focus: int = -1) -> str:
    parts = []
    for i, c in enumerate(s.cards):
        col = _c(str(c.get("color", "")), i)
        parts.append(f'<div class="card{_fx(i, focus)}" style="--c:var(--{col})">'
                     f'<div class="t">{escape(str(c.get("label", "")))}</div>'
                     f'<div class="s">{escape(str(c.get("sub", "")))}</div></div>')
    row = f'<span class="arrow">&#8594;</span>'.join(parts)
    out = f'<div class="row">{row}</div>'
    if s.subboxes:
        subs = "".join(f'<div class="subbox{_fx(i, focus)}"><div class="a">{escape(str(b.get("a", "")))}</div>'
                       f'<div class="b">{escape(str(b.get("b", "")))}</div></div>'
                       for i, b in enumerate(s.subboxes))
        out += f'<div class="row" style="gap:16px;margin-top:-16px;">{subs}</div>'
    return out


def _chips_html(s: Slide, focus: int = -1) -> str:
    out = ""
    if s.lead:
        out += f'<div class="lead">{escape(s.lead)}</div>'
    if s.chips:
        out += '<div class="row" style="gap:12px;">' + "".join(
            f'<div class="chip{_fx(i, focus)}">{escape(str(t))}</div>'
            for i, t in enumerate(s.chips)) + "</div>"
    if s.ids:
        out += '<div class="row" style="gap:12px;"><span class="tick">&#8595;</span></div>'
        out += '<div class="row" style="gap:12px;">' + "".join(
            f'<div class="idchip{_fx(i, focus)}">{escape(str(t))}</div>'
            for i, t in enumerate(s.ids)) + "</div>"
    if s.note:
        out += f'<div class="note">{escape(s.note)}</div>'
    return out


def _bullets_html(s: Slide, focus: int = -1) -> str:
    lis = "".join(
        f'<li class="{_fx(i, focus).strip()}"><span class="dot">&#8226;</span>'
        f'<span class="lab" style="color:var(--{_c(str(b.get("color", "")), i)})">'
        f'{escape(str(b.get("label", "")))}:</span> {escape(str(b.get("text", "")))}</li>'
        for i, b in enumerate(s.bullets))
    out = f'<ul class="bul">{lis}</ul>'
    if s.kicker:
        out += f'<div class="kicker">{escape(s.kicker)}</div>'
    return out


def slide_html(s: Slide, focus: int = -1) -> str:
    """The inner markup for one slide (no <html>/<style>). `focus` is the index of the element the
    narrator is speaking about right now — it lights up and the rest dim. -1 = no highlight.
    `math` slides never reach here — the deck builder routes them to generation.math_scene."""
    if s.kind == "math":
        raise ValueError("math slides render via generation.math_scene, not HTML")
    if s.kind == "title":
        body = f'<h1 class="hero">{escape(s.title)}</h1>'
        if s.subtitle:
            body += f'<div class="sub">{escape(s.subtitle)}</div>'
        return f'<div class="slide">{body}</div>'
    head = f'<h2>{escape(s.title)}</h2>' if s.title else ""
    if s.kind == "cards":
        inner = _cards_html(s, focus)
    elif s.kind == "chips":
        inner = _chips_html(s, focus)
    else:
        inner = _bullets_html(s, focus)
    return f'<div class="slide">{head}{inner}</div>'


def brand_html(word: str = "Lattice") -> str:
    """The Lattice mark: the grid glyph + wordmark, in CSS. Free — it lands in the screenshot Chrome
    is already taking, so there is no overlay filter and no extra encode anywhere in the deck path."""
    rules = ('<i class="v" style="left:33%"></i><i class="v" style="left:66%"></i>'
             '<i class="h" style="top:33%"></i><i class="h" style="top:66%"></i>')
    return (f'<div class="foot"><div class="glyph">{rules}</div>'
            f'<div class="word">{escape(word)}</div></div>')


def page_html(s: Slide, footer: str = "", focus: int = -1) -> str:
    """A standalone 1280x720 page for headless Chrome to screenshot."""
    foot = brand_html(footer) if footer else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body>{slide_html(s, focus)}{foot}</body></html>')
