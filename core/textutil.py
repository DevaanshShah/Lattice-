"""Robust extraction of JSON / code from model output.

Provider-agnostic: we do NOT rely on OpenAI's `response_format=json_object` (Claude and
others via OpenRouter don't all honor it). Instead we ask for raw JSON/code and parse
defensively here — stripping markdown fences and, as a last resort, slicing the outermost
braces.
"""
from __future__ import annotations

import json
import re


def strip_code_fences(text: str) -> str:
    """Remove a leading ```lang fence and a trailing ``` fence, if present."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_+-]*[ \t]*\n?", "", t)
        t = re.sub(r"\n?```[ \t]*$", "", t)
    return t.strip()


def extract_json(text: str) -> dict:
    """Parse a JSON object out of model output. Raises ValueError if none is found."""
    t = strip_code_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(t[start:end + 1])  # may raise JSONDecodeError -> surfaced below
    raise ValueError("no JSON object found in model output")
