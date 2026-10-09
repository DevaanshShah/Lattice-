"""Resolve curated local visual assets without allowing arbitrary renderer file access."""
from __future__ import annotations

import base64
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


def asset_inventory() -> dict[str, list[str]]:
    icons = sorted(path.stem for path in (ASSET_ROOT / "icons").glob("*.svg"))
    images = sorted(path.name for path in (ASSET_ROOT / "images").glob("*")
                    if path.suffix.lower() in _MIME)
    return {"icons": icons, "images": images}
