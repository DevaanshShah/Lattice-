"""Topic -> a designed slide DECK spec (content only). ADDITIVE: parallel to planner.outline.

The LLM writes only what the slides SAY (titles, card labels, bullet text) and which slide KIND fits.
Layout, colours, spacing and typography are fixed in generation.slide_deck — which is why this path
needs no compile-repair, no layout lint, and no vision critic: there is no generated layout to get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.llm import LLMClient, get_client
from core.textutil import extract_json
from generation.slide_deck import Slide
from prompts.loader import load

_KINDS = {"title", "cards", "chips", "bullets"}


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
