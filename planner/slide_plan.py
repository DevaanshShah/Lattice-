"""Topic -> a designed slide DECK spec (content only). ADDITIVE: parallel to planner.outline.

The LLM writes only what the slides SAY (titles, card labels, bullet text) and which slide KIND fits.
Layout, colours, spacing and typography are fixed in generation.slide_deck — which is why this path
needs no compile-repair, no layout lint, and no vision critic: there is no generated layout to get wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.llm import LLMClient, get_client
from core.textutil import extract_json
from generation.slide_deck import Slide
from prompts.loader import load

_KINDS = {"title", "cards", "chips", "bullets", "math"}

# --- script lint: the filler ban, enforced deterministically ---------------------------------
# The prompt asks for no filler; a prompt alone drifts. These are free, text-only checks whose error
# feeds straight back into the plan retry loop — the same "system owns quality" move as layout_lint,
# except it costs nothing and never gives a false positive on a real sentence.
_FILLER = re.compile(
    r"\b(in this (slide|video|section)|let'?s (take a look|dive|move on|explore|begin|start)"
    r"|as you can see|as we can see|it'?s important to note|in today'?s video|welcome back"
    r"|first,? we have|simply put|at the end of the day|that'?s where \w+ comes in"
    r"|stay tuned|without further ado|hope you (enjoyed|liked)|don'?t forget to"
    r"|amazing|revolutionary|game[- ]chang\w*|incredibly powerful)\b", re.I)

_MAX_WORDS = 32          # a beat longer than this is a paragraph, not a spoken line
_NORM = re.compile(r"[^a-z0-9 ]+")


def _norm(s: str) -> str:
    return " ".join(_NORM.sub(" ", str(s).lower()).split())


def _elements(sd: dict) -> list[str]:
    """The slide's focusable elements, as the text a beat would be restating."""
    kind = sd.get("kind")
    if kind == "cards":
        return [f"{c.get('label','')} {c.get('sub','')}" for c in sd.get("cards") or []]
    if kind == "chips":
        return [str(c) for c in sd.get("chips") or []]
    if kind == "bullets":
        return [f"{b.get('label','')} {b.get('text','')}" for b in sd.get("bullets") or []]
    return []


def _lint_beats(sd: dict, i: int) -> None:
    """Reject filler, over-long beats, out-of-range focus, and narration that just reads the slide."""
    beats = sd.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ValueError(f"slide {i}: 'beats' is required — every slide needs narration")
    els = _elements(sd)
    for j, b in enumerate(beats):
        if not isinstance(b, dict):
            raise ValueError(f"slide {i} beat {j}: must be an object with 'say' and 'focus'")
        say = str(b.get("say", "")).strip()
        if not say:
            raise ValueError(f"slide {i} beat {j}: 'say' is empty")
        hit = _FILLER.search(say)
        if hit:
            raise ValueError(f"slide {i} beat {j}: banned filler phrase {hit.group(0)!r} in "
                             f"{say!r} — say a fact about the topic instead")
        if len(say.split()) > _MAX_WORDS:
            raise ValueError(f"slide {i} beat {j}: {len(say.split())} words (max {_MAX_WORDS}) — "
                             f"split it into separate beats")
        try:
            foc = int(b.get("focus", -1))
        except (TypeError, ValueError):
            raise ValueError(f"slide {i} beat {j}: 'focus' must be an integer index or -1")
        if foc >= len(els):
            raise ValueError(f"slide {i} beat {j}: focus {foc} but the slide has {len(els)} "
                             f"focusable elements (use 0..{len(els)-1}, or -1)")
        b["focus"] = foc
        if foc >= 0 and _norm(say) == _norm(els[foc]):     # narration must ADD to the slide, not read it
            raise ValueError(f"slide {i} beat {j}: {say!r} just restates the element it points at — "
                             f"say why it matters or what breaks without it")
    # Every element must get spoken about, or it sits dimmed for the whole slide with nothing said
    # about it — the model reliably forgets this on `bullets`, so it is enforced here, not asked for.
    missing = [k for k in range(len(els)) if k not in {int(b.get("focus", -1)) for b in beats}]
    if missing:
        raise ValueError(f"slide {i}: elements {missing} are never focused by any beat — give each "
                         f"one its own beat with \"focus\" set to its index, in order")


class SlidePlanError(RuntimeError):
    pass


@dataclass
class Deck:
    title: str
    slides: list[Slide] = field(default_factory=list)


def _validate(data: dict) -> Deck:
    """Structural checks the design system relies on (counts must pair up, kinds must exist)."""
    slides_raw = data.get("slides")
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ValueError("no slides")
    slides: list[Slide] = []
    for i, sd in enumerate(slides_raw):
        if not isinstance(sd, dict):
            raise ValueError(f"slide {i} is not an object")
        kind = str(sd.get("kind", "")).strip().lower()
        if kind not in _KINDS:
            raise ValueError(f"slide {i}: unknown kind {kind!r} (use {sorted(_KINDS)})")
        sd["kind"] = kind
        if kind == "cards":
            if not sd.get("cards"):
                raise ValueError(f"slide {i}: 'cards' needs at least one card")
            if sd.get("subboxes") and len(sd["subboxes"]) != len(sd["cards"]):
                sd.pop("subboxes")            # mismatched captions would misalign -> drop, don't fail
        if kind == "chips":
            if not sd.get("chips"):
                raise ValueError(f"slide {i}: 'chips' needs at least one chip")
            if sd.get("ids") and len(sd["ids"]) != len(sd["chips"]):
                sd.pop("ids")
        if kind == "bullets" and not sd.get("bullets"):
            raise ValueError(f"slide {i}: 'bullets' needs at least one bullet")
        if kind == "math":
            from generation.math_scene import MathSceneError, safe_expr
            xr = sd.get("x_range")
            if not (isinstance(xr, list) and len(xr) >= 2):
                raise ValueError(f"slide {i}: 'math' needs x_range [min, max]")
            try:                                   # reject anything but a plain f(x) expression
                safe_expr(str(sd.get("fn", "")))
            except MathSceneError as e:
                raise ValueError(f"slide {i}: bad fn — {e}")
        _lint_beats(sd, i)
        slides.append(Slide.from_dict(sd))
    return Deck(title=str(data.get("title") or slides[0].title or "Untitled"), slides=slides)


def plan_deck(topic: str, *, client: LLMClient | None = None, attempts: int = 3) -> Deck:
    """Topic -> Deck. Retries with the validation error fed back, like planner.outline."""
    topic = (topic or "").strip()
    if not topic:
        raise SlidePlanError("topic is empty")
    client = client or get_client()
    messages = [
        {"role": "system", "content": load("slide-deck")},
        {"role": "user", "content": f"Topic: {topic}\n\nReturn the deck JSON now."},
    ]
    last: Exception | None = None
    for _ in range(attempts):
        raw = client.chat(messages)
        try:
            return _validate(extract_json(raw))
        except ValueError as e:
            last = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f"That was invalid ({e}). Return ONLY the deck JSON matching the documented slide "
                "kinds and field names.")})
    raise SlidePlanError(f"slide deck invalid after {attempts} attempts: {last}")
