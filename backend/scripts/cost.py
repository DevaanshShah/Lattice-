"""Show OpenRouter spend for the configured key (uses LATTICE_LLM_API_KEY from .env).

    python -m scripts.cost

Account-level credits/usage + this key's usage and limit. Handy after a big generate-video run.
Only works for OpenRouter base_url; other providers track cost on their own dashboards.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from core.config import settings
from core.console import enable_utf8


def _get(path: str) -> dict:
    req = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + path,
        headers={"Authorization": "Bearer " + settings.llm_api_key},
    )
    return json.load(urllib.request.urlopen(req, timeout=20))


def main() -> int:
    enable_utf8()
    if "openrouter" not in settings.llm_base_url:
        print(f"cost tracking here is OpenRouter-only; your base_url is {settings.llm_base_url}")
        return 0
    if not settings.llm_api_key:
        print("[X] no LATTICE_LLM_API_KEY set in .env")
        return 1

    try:
        c = _get("/credits")["data"]
        purchased, used = c.get("total_credits", 0.0), c.get("total_usage", 0.0)
        print("Account:")
        print(f"  purchased: ${purchased:.2f}")
        print(f"  used:      ${used:.4f}")
        print(f"  remaining: ${purchased - used:.2f}")
    except Exception as e:
        print("  (account credits unavailable:", e, ")")

    try:
        k = _get("/auth/key")["data"]
        usage, limit = k.get("usage", 0.0), k.get("limit")
        print("This key:")
        print(f"  used:  ${usage:.4f}")
        print(f"  limit: {('$%.2f' % limit) if limit is not None else 'none'}")
        if limit is not None:
            left = limit - usage
            flag = "  <-- LOW, raise the key limit at openrouter.ai/settings/keys" if left < 1 else ""
            print(f"  left:  ${left:.2f}{flag}")
    except Exception as e:
        print("  (key info unavailable:", e, ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
