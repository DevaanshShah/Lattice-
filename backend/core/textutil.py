"""Robust extraction of JSON / code from model output.

Provider-agnostic: we do NOT rely on OpenAI's `response_format=json_object` (Claude and
others via OpenRouter don't all honor it). Instead we ask for raw JSON/code and parse
defensively here — stripping markdown fences and, as a last resort, slicing the outermost
braces.
"""
from __future__ import annotations

import json
import re


_CODE_START = re.compile(r"^[ \t]*(from\s+\w[\w.]*\s+import|import\s+\w)", re.MULTILINE)


def strip_code_fences(text: str) -> str:
    """Extract Python from a model reply, tolerating fences AND leading/trailing prose.

    Weak models often wrap code as "Here is the file:\\n```python\\n...\\n```" or leak a sentence
    before the import. We (1) take the contents of the first fenced block if any fence exists
    anywhere, then (2) drop any leading prose before the first real `import`/`from ... import`.
    """
    t = text.strip()
    fenced = re.search(r"```[a-zA-Z0-9_+-]*[ \t]*\r?\n(.*?)```", t, re.DOTALL)
    if fenced:
        t = fenced.group(1).strip()
    else:
        t = re.sub(r"\n?```[ \t]*$", "", re.sub(r"^```[a-zA-Z0-9_+-]*[ \t]*\n?", "", t)).strip()
    m = _CODE_START.search(t)          # slice off any leading prose before the code actually starts
    if m and m.start() > 0:
        t = t[m.start():]
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
