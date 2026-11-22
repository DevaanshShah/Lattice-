"""Optional, bounded Jev decision for auto-routing a lesson topic.

Jev only chooses from the existing recipe ids (or ``unsupported``). It is deliberately
outside planning and rendering: an unavailable or uncertain decision falls back to the
deterministic keyword picker.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen


UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RouteDecision:
    recipe_id: str
    confidence: float


def route(topic: str, criteria: dict[str, str], *, api_key: str, base_url: str,
          model: str, timeout: float, open_url: Callable = urlopen) -> RouteDecision | None:
    """Return one validated Jev choice, or ``None`` when it is unusable.

    Routing is an optimization. Network, provider, shape, and confidence failures must never
    prevent the established keyword router from planning a lesson.
    """
    choices = {**criteria, UNSUPPORTED: "The current lesson boards cannot clearly teach this topic."}
    body = json.dumps({
        "model": model,
        "state": {"topic": topic},
        "questions": {
            "recipe": {
                "type": "choice",
                "instructions": (
                    "Choose the one existing lesson recipe that can teach this topic clearly. "
                    "Choose unsupported when none of the supplied boards fits."),
                "criteria": choices,
            },
        },
    }).encode("utf-8")
    request = Request(base_url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with open_url(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        answer = data["answers"]["recipe"]
        recipe_id, confidence = answer["choice"], float(answer["confidence"])
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(recipe_id, str) or recipe_id not in choices or not 0.0 <= confidence <= 1.0:
        return None
    return RouteDecision(recipe_id=recipe_id, confidence=confidence)
