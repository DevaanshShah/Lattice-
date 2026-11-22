"""FR-25 — content-hash cache. Never re-render or re-spend on unchanged work.

Two keys, both deterministic:
- `spec_key(prompt, model)`   — caches the generated scene spec, so the SAME PROMPT is
  idempotent end-to-end: a re-run makes ZERO LLM/render calls (this is the cost win).
- `render_key(spec, model, quality)` — the build-plan key (scene spec + model + quality; the
  style spec joins it in M5). Any meaningful spec change busts it; a no-op reuses the render.

A `Cache` is a directory of `<key>/manifest.json` (+ any copied artifacts like the MP4).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.config import settings


def content_hash(*parts: str, length: int = 16) -> str:
    """Stable hash of the given parts (order-sensitive, NUL-separated to avoid collisions)."""
    h = hashlib.sha256()
    for p in parts:
        h.update(b"\x00")
        h.update(p.encode("utf-8"))
    return h.hexdigest()[:length]


def spec_key(prompt: str, *, model: str) -> str:
    return content_hash("spec-v1", prompt.strip(), model)


def _canonical_json(spec_json: str) -> str:
    """Normalize JSON so trivial key reordering / whitespace doesn't bust the cache."""
    try:
        return json.dumps(json.loads(spec_json), sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError):
        return spec_json


def render_key(spec_json: str, *, model: str, quality: str) -> str:
    return content_hash("render-v1", _canonical_json(spec_json), model, quality)


@dataclass
class Cache:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def dir_for(self, key: str) -> Path:
        return self.root / key

    def _manifest_path(self, key: str) -> Path:
        return self.dir_for(key) / "manifest.json"

    def has(self, key: str) -> bool:
        return self._manifest_path(key).exists()

    def load(self, key: str) -> dict | None:
        m = self._manifest_path(key)
        return json.loads(m.read_text(encoding="utf-8")) if m.exists() else None

    def save(self, key: str, manifest: dict, *, copy: dict[str, Path] | None = None) -> dict:
        """Write the manifest under `key`, copying any `copy={name: src}` artifacts in.

        For each copied file the returned/stored manifest's `name` points at the cached copy,
        so callers always get a stable path inside the cache.
        """
        d = self.dir_for(key)
        d.mkdir(parents=True, exist_ok=True)
        stored = dict(manifest)
        for name, src in (copy or {}).items():
            if src and Path(src).exists():
                dst = d / Path(src).name
                shutil.copy2(src, dst)
                stored[name] = str(dst)
        self._manifest_path(key).write_text(json.dumps(stored, indent=2), encoding="utf-8")
        return stored


def default_cache() -> Cache:
    return Cache(settings.out_dir / "cache")
