"""FR-13 / FR-20 / FR-21 foundation — the scene-DAG project model.

A video = an ORDERED collection of scenes (spec + code + render + per-scene history) + the
shared style, plus the final stitched MP4. Key design points the M6 editing ops depend on:

- STABLE IDENTITY: each SceneNode has an immutable `sid`. Per-scene work dirs are keyed off
  `sid`, so reorder/insert/delete can renumber `index` (via reindex()) without moving or
  colliding rendered artifacts — the root enabler of the isolation invariant.
- VERSIONED PERSISTENCE: `schema_version` + a real `_migrate` so old projects never orphan;
  legacy (M5, pre-sid) dumps are migrated on load. save() stays a plain dump (M5 round-trip
  unaffected).
- PER-SCENE HISTORY: `SceneNode.versions` holds SceneVersion snapshots; rollback is per-scene.
  Defined HERE (not in editing/) so composition never imports editing.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec
from core.schemas.style import StyleSpec

SCHEMA_VERSION = 1


class SceneVersion(BaseModel):
    """A frozen snapshot of one scene for per-scene rollback (FR-21)."""
    model_config = ConfigDict(extra="ignore")
    version: int
    label: str = ""
    spec: SceneSpec | None = None
    code: str | None = None
    script: list[str] = Field(default_factory=list)
    mp4: str | None = None        # path to the FROZEN (immutable) clip copy
    srt: str | None = None
    score: int = -1


class SceneNode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sid: str = Field(default_factory=lambda: uuid4().hex[:12])  # immutable work-dir key
    index: int                                                  # pure presentation order (reindex owns it)
    title: str
    intent: str
    spec: SceneSpec | None = None
    code: str | None = None
    script: list[str] = Field(default_factory=list)             # narration lines (rollback reproducibility)
    mp4: str | None = None
    srt: str | None = None
    compiled: bool = False
    score: int = -1
    versions: list[SceneVersion] = Field(default_factory=list)  # per-scene history (FR-21)


class VideoProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    topic: str
    style: StyleSpec | None = None
    scenes: list[SceneNode] = Field(default_factory=list)
    final_mp4: str | None = None

    @classmethod
    def from_outline(cls, outline: Outline, style: StyleSpec | None = None) -> "VideoProject":
        return cls(
            topic=outline.topic, style=style,
            scenes=[SceneNode(index=i, title=it.title, intent=it.intent)
                    for i, it in enumerate(outline.items)],
        )

    def scene(self, i: int) -> SceneNode:
        return self.scenes[i]

    def scene_by_sid(self, sid: str) -> SceneNode:
        return next(s for s in self.scenes if s.sid == sid)

    def reindex(self) -> None:
        """The single canonical renumber — every structural edit calls this (DAG consistency)."""
        for i, s in enumerate(self.scenes):
            s.index = i

    def ordered_mp4s(self) -> list[str]:
        return [s.mp4 for s in self.scenes if s.mp4]

    def all_ready(self) -> bool:
        return bool(self.scenes) and all(s.mp4 for s in self.scenes)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "VideoProject":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(_migrate(raw))


# --- versioned persistence (FR-20) ---------------------------------------------------------

def _detect_version(raw: dict) -> int:
    return int(raw.get("schema_version", 0))


def _normalize_v0_to_v1(raw: dict) -> dict:
    """Legacy M5 dump (no schema_version, nodes lack sid/script/versions) -> v1.

    Deterministic legacy sids so old per-scene work dirs still resolve.
    """
    raw = dict(raw)
    for i, s in enumerate(raw.get("scenes", [])):
        s.setdefault("sid", f"legacy{i:02d}")
        s.setdefault("script", [])
        s.setdefault("versions", [])
    raw["schema_version"] = 1
    return raw


_MIGRATIONS = {0: _normalize_v0_to_v1}  # every step v -> v+1 MUST be registered here


def _migrate(raw: dict) -> dict:
    v = _detect_version(raw)
    if v > SCHEMA_VERSION:
        raise ValueError(f"project schema_version {v} is newer than supported {SCHEMA_VERSION}; upgrade Lattice")
    while v < SCHEMA_VERSION:
        raw = _MIGRATIONS[v](raw)
        v += 1
    return raw
