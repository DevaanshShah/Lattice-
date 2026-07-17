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
.foot{position:absolute;bottom:26px;left:0;right:0;text-align:center;font-size:12.5px;color:var(--faint);}
"""

_COLORS = ("blue", "purple", "green", "amber", "cyan", "red")


def _c(name: str, i: int = 0) -> str:
    n = (name or "").strip().lower()
    return n if n in _COLORS else _COLORS[i % len(_COLORS)]


@dataclass
class Slide:
    kind: str                       # title | cards | chips | bullets
    title: str = ""
    subtitle: str = ""
    cards: list = field(default_factory=list)      # [{label, sub, color}]
    subboxes: list = field(default_factory=list)   # [{a, b}] under the cards
    lead: str = ""
    chips: list = field(default_factory=list)      # ["I","love",...]
    ids: list = field(default_factory=list)        # ["7","3245",...]
    note: str = ""
    bullets: list = field(default_factory=list)    # [{label, text, color}]
    kicker: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Slide":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _cards_html(s: Slide) -> str:
    parts = []
    for i, c in enumerate(s.cards):
        col = _c(str(c.get("color", "")), i)
        parts.append(f'<div class="card" style="--c:var(--{col})">'
                     f'<div class="t">{escape(str(c.get("label", "")))}</div>'
                     f'<div class="s">{escape(str(c.get("sub", "")))}</div></div>')
    row = f'<span class="arrow">&#8594;</span>'.join(parts)
    out = f'<div class="row">{row}</div>'
    if s.subboxes:
        subs = "".join(f'<div class="subbox"><div class="a">{escape(str(b.get("a", "")))}</div>'
                       f'<div class="b">{escape(str(b.get("b", "")))}</div></div>' for b in s.subboxes)
        out += f'<div class="row" style="gap:16px;margin-top:-16px;">{subs}</div>'
    return out


def _chips_html(s: Slide) -> str:
    out = ""
    if s.lead:
        out += f'<div class="lead">{escape(s.lead)}</div>'
    if s.chips:
        out += '<div class="row" style="gap:12px;">' + "".join(
            f'<div class="chip">{escape(str(t))}</div>' for t in s.chips) + "</div>"
    if s.ids:
        out += '<div class="row" style="gap:12px;"><span class="tick">&#8595;</span></div>'
        out += '<div class="row" style="gap:12px;">' + "".join(
            f'<div class="idchip">{escape(str(t))}</div>' for t in s.ids) + "</div>"
    if s.note:
        out += f'<div class="note">{escape(s.note)}</div>'
    return out


def _bullets_html(s: Slide) -> str:
    lis = "".join(
        f'<li><span class="dot">&#8226;</span><span class="lab" style="color:var(--{_c(str(b.get("color", "")), i)})">'
        f'{escape(str(b.get("label", "")))}:</span> {escape(str(b.get("text", "")))}</li>'
        for i, b in enumerate(s.bullets))
    out = f'<ul class="bul">{lis}</ul>'
    if s.kicker:
        out += f'<div class="kicker">{escape(s.kicker)}</div>'
    return out


def slide_html(s: Slide) -> str:
    """The inner markup for one slide (no <html>/<style>)."""
    if s.kind == "title":
        body = f'<h1 class="hero">{escape(s.title)}</h1>'
        if s.subtitle:
            body += f'<div class="sub">{escape(s.subtitle)}</div>'
        return f'<div class="slide">{body}</div>'
    head = f'<h2>{escape(s.title)}</h2>' if s.title else ""
    if s.kind == "cards":
        inner = _cards_html(s)
    elif s.kind == "chips":
        inner = _chips_html(s)
    else:
        inner = _bullets_html(s)
    return f'<div class="slide">{head}{inner}</div>'


def page_html(s: Slide, footer: str = "") -> str:
    """A standalone 1200x675 page for headless Chrome to screenshot."""
    foot = f'<div class="foot">{escape(footer)}</div>' if footer else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body>{slide_html(s)}{foot}</body></html>')
