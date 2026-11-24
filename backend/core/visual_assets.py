"""Resolve curated local visual assets without allowing arbitrary renderer file access."""
from __future__ import annotations

import base64
from functools import lru_cache
import json
from pathlib import Path
import re


ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"
_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_./-]*\Z")
_MIME = {".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def resolve_asset(kind: str, asset_id: str) -> Path:
    if not _SAFE_ID.fullmatch(asset_id) or ".." in Path(asset_id).parts:
        raise ValueError(f"unsafe visual asset id: {asset_id!r}")
    relative = f"icons/{asset_id}.svg" if kind == "icon" else f"images/{asset_id}"
    path = (ASSET_ROOT / relative).resolve()
    if not path.is_relative_to(ASSET_ROOT.resolve()) or path.suffix.lower() not in _MIME:
        raise ValueError(f"unsupported visual asset: {asset_id!r}")
    if not path.is_file():
        raise ValueError(f"visual asset not found: {asset_id!r}")
    return path


def asset_data_uri(kind: str, asset_id: str) -> str:
    path = resolve_asset(kind, asset_id)
    return f"data:{_MIME[path.suffix.lower()]};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def icon_svg(asset_id: str) -> str:
    """The icon's SVG markup for inlining, so it takes the colour of the piece it is drawn in."""
    text = resolve_asset("icon", asset_id).read_text(encoding="utf-8")
    return text[text.index("<svg"):].strip()


# The whiteboard style draws from Fluent Emoji (about 1,600 colour icons: people in jobs, bodies,
# things, places, symbols; MIT, assets/icons/fluent). The model is never shown all of them: code
# shortlists the ones a topic's words match, beside a fixed set that most explainers need.
_UNIVERSAL = ("woman-technologist man-technologist woman-office-worker man-office-worker student teacher "
              "health-worker person-in-tuxedo busts-in-silhouette speech-balloon thought-balloon "
              "check-mark-button cross-mark warning locked unlocked key clock-face-three-o-clock hourglass-not-done "
              "light-bulb gear wrench magnifying-glass-tilted-left bar-chart chart-increasing chart-decreasing "
              "laptop desktop-computer mobile-phone television headphone telephone-receiver envelope package "
              "credit-card money-bag shopping-cart house office-building globe-showing-europe-africa "
              "books open-book memo clipboard file-folder trash-can bell fire high-voltage "
              "brain anatomical-heart lungs bone skull dna microscope test-tube").split()
_COLOURS = set("red orange yellow green blue purple pink brown black white grey gray light dark".split())
_STOP = set("a an and the of to in on for with how what why when does do is are it its this that "
            "explained explain work works make makes use using about from into by as at be can".split())


@lru_cache(maxsize=1)
def fluent_index() -> list[dict]:
    path = ASSET_ROOT / "icons" / "fluent" / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def icon_choices(topic: str, limit: int = 40) -> list[str]:
    """Fluent icon ids ("fluent/skull") for a topic: the best matches for its words, then the
    universal set. An icon scores 3 for a word in its name, 2 for one of its keywords."""
    index = fluent_index()
    if not index:
        return []
    words = {_stem(word) for word in re.findall(r"[a-z]+", topic.lower()) if word not in _STOP and len(word) > 2}
    scored = []
    for row in index:
        name = {_stem(word) for word in re.split(r"[-\s]+", row["id"])}
        keys = {_stem(word) for key in row.get("keywords", []) for word in re.findall(r"[a-z]+", key.lower())}
        score = 3 * len(words & name) + 2 * len(words & keys)
        if score:
            scored.append((-score, len(row["id"]), row["id"]))
    have = {row["id"] for row in index}
    chosen: list[str] = []
    for _, _, name in sorted(scored):      # one icon of each kind: not fourteen hearts, one per colour
        kind = " ".join(word for word in name.split("-") if word not in _COLOURS or word in words)
        if kind in {" ".join(w for w in c.split("-") if w not in _COLOURS or w in words) for c in chosen}:
            continue
        chosen.append(name)
        if len(chosen) == limit:
            break
    chosen += [name for name in _UNIVERSAL if name in have and name not in chosen]
    return [f"fluent/{name}" for name in chosen]


def asset_inventory() -> dict[str, list[str]]:
    icons = sorted(path.stem for path in (ASSET_ROOT / "icons").glob("*.svg"))
    images = sorted(path.name for path in (ASSET_ROOT / "images").glob("*")
                    if path.suffix.lower() in _MIME)
    return {"icons": icons, "images": images}
