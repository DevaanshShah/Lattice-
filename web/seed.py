"""Image seed: a user-uploaded image -> the topic-description string the existing pipeline consumes.

A thin preprocessing step in front of Engine.plan. It mirrors verification.vision_critic's vision call
(base64 data-URL packed as an image_url content block, sent through the shared LLMClient on the cheap
vision-capable critic model) but its job is INPUT understanding, not output critique: it returns a short
plain-text topic that Engine.plan_from_image feeds straight into planner.outline.generate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.config import settings
from core.llm import LLMClient, get_critic_client
from prompts.loader import load

# ~8 MB of data-URL chars ≈ a ~5.5 MB image after base64 — a cheap len() guard before the vision call.
MAX_IMAGE_CHARS = 8_000_000
DERIVE_MAX_TOKENS = 400  # the topic is 1-3 sentences; cap output cost + reservation
_DATA_URL = re.compile(r"^data:image/(png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+$", re.IGNORECASE)


class SeedError(ValueError):
    """A bad/unsupported input (not a bug) — the API surfaces this as a 422."""


@dataclass(frozen=True)
class SeedResult:
    topic: str
    kind: str                                  # "image"
    meta: dict[str, Any] = field(default_factory=dict)


def _clean(raw: str) -> str:
    """Tidy the model reply into a bare topic string. Deliberately NOT core.textutil.strip_code_fences —
    its `_CODE_START` regex would slice a topic that happens to begin with a word like 'import'."""
    t = (raw or "").strip()
    if t.startswith("```"):                    # strip a stray accidental fence, keep the prose
        t = t.strip("`").strip()
    if not t:
        raise SeedError("could not derive a topic from the image")
    return t


def validate(data_url: str) -> str:
    """Cheap guards before any paid vision call: right shape, not absurdly large."""
    data_url = (data_url or "").strip()
    if not _DATA_URL.match(data_url):
        raise SeedError("image must be a png/jpeg/webp data URL (data:image/...;base64,...)")
    if len(data_url) > MAX_IMAGE_CHARS:
        raise SeedError("image too large (max ~5 MB)")
    return data_url


DESCRIBE_MAX_TOKENS = 700   # a paragraph of what's in the image, not an essay


def describe(data_url: str, question: str = "", *, client: LLMClient | None = None) -> str:
    """What is IN this image, in plain text, read with the learner's question in mind.

    The sibling of from_image() and deliberately not the same thing: from_image() returns a TOPIC
    for the video planner, this returns a DESCRIPTION for a chat answer. A learner photographing a
    homework problem wants it read and answered, not turned into a lesson title.

    The description is what gets folded into the chat turn, so the generator model never has to be
    vision-capable (the live one, deepseek, isn't) and the thread stores text rather than megabytes
    of base64.
    """
    data_url = validate(data_url)
    ask = (question or "").strip()
    prompt = ("Describe what this image shows, in enough detail that someone who cannot see it "
              "could answer questions about it. Transcribe any text, code, equations, labels or "
              "numbers exactly. Do not answer the question yourself — just describe.")
    if ask:
        prompt += f"\n\nThe person asked: {ask!r} — make sure the parts relevant to that are covered."
    client = client or get_critic_client()   # vision runs on the critic model, like from_image
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url, "detail": settings.critic_image_detail}},
    ]
    out = (client.chat([{"role": "user", "content": content}],
                       max_tokens=DESCRIBE_MAX_TOKENS) or "").strip()
    if not out:
        raise SeedError("could not read that image")
    return out


def from_image(data_url: str, *, client: LLMClient | None = None) -> SeedResult:
    """Derive a 1-3 sentence explainer topic from an image data-URL. Raises SeedError on a bad input
    or an empty model reply."""
    data_url = validate(data_url)

    # vision needs the CRITIC client — the default generator (deepseek) isn't vision-capable, and the
    # critic may live on its own provider (settings.critic_base_url). Tests inject their own client.
    client = client or get_critic_client()
    content: list[dict] = [
        {"type": "text", "text": "Give the explainer-video topic for this image."},
        {"type": "image_url", "image_url": {"url": data_url, "detail": settings.critic_image_detail}},
    ]
    messages = [{"role": "system", "content": load("seed-image")},
                {"role": "user", "content": content}]
    # cheap, vision-capable critic model (gpt-4o-mini by default); same provider fallbacks as the critic
    raw = client.chat(messages, model=settings.critic_model, max_tokens=DERIVE_MAX_TOKENS)
    return SeedResult(_clean(raw), "image")
