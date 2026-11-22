"""Deterministic error->fix fast-path for the compile-repair loop (the safe core of "error memory").

Many render failures are MECHANICAL — an invented color name, a stale (pre-CE) API call — and have
a known, exact fix that needs no model. compile_repair tries this table BEFORE spending an LLM repair
call: a free, instant fix for the common cases, falling back to the generator only for real errors.
Pure + table-driven, so it's fully unit-testable without Docker or a model.
"""
from __future__ import annotations

import re

# Invented colors the model reaches for that don't exist in Manim CE (NameError at render). Map each
# to a real, close equivalent (a hex string or an existing constant) so the fix is exact.
_INVENTED_COLORS: dict[str, str] = {
    "CYAN": '"#00BCD4"',
    "MAGENTA": '"#E91E63"',
    "LIGHTBLUE": '"#64B5F6"',
    "DARKBLUE": '"#1565C0"',
    "LIGHTGREEN": '"#81C784"',
    "DARKGREEN": '"#2E7D32"',
    "LIGHTRED": '"#E57373"',
    "DARKRED": '"#C62828"',
    "VIOLET": "PURPLE",
    "INDIGO": '"#3F51B5"',
    "LIGHTGRAY": "GREY_B",
    "LIGHTGREY": "GREY_B",
    "DARKGRAY": "GREY_E",
    "DARKGREY": "GREY_E",
    "SILVER": "GREY_B",
}

# Stale (ManimGL / pre-CE) names -> their Manim CE replacement (exact, context-free substitutions).
_STALE_API: dict[str, str] = {
    "ShowCreation": "Create",
    "TextMobject": "Text",
    "TexMobject": "MathTex",
    "ShowCreationThenFadeOut": "Create",
    "DrawBorderThenFill": "Create",
}

_NAME_ERROR = re.compile(r"NameError: name '(\w+)' is not defined")
_ATTR_ERROR = re.compile(r"(?:module 'manim' has no attribute|has no attribute) '(\w+)'")


def try_deterministic_fix(code: str, error: str | None) -> str | None:
    """Return code with a known, exact fix applied, or None if no rule matches (-> use the LLM fixer).

    Only ever substitutes when the ERROR names the offending symbol AND the substitution actually
    changes the code — so it never mangles unrelated, working code.
    """
    err = error or ""

    # 1) invented color -> real color, keyed off the NameError/AttributeError that named it
    m = _NAME_ERROR.search(err) or _ATTR_ERROR.search(err)
    if m:
        name = m.group(1)
        if name in _INVENTED_COLORS:
            fixed = re.sub(rf"\b{re.escape(name)}\b", _INVENTED_COLORS[name], code)
            if fixed != code:
                return fixed

    # 2) stale pre-CE API -> CE equivalent (apply if the error mentions it and it's in the code)
    for old, new in _STALE_API.items():
        if old in err and re.search(rf"\b{re.escape(old)}\b", code):
            fixed = re.sub(rf"\b{re.escape(old)}\b", new, code)
            if fixed != code:
                return fixed

    return None
