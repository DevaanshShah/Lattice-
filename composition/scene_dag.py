"""FR-13 — the scene-DAG project model.

A video = an ORDERED collection of scenes (spec + code + render) + the shared style, plus the
final stitched MP4. Scenes are individually addressable (needed for isolated regeneration,
FR-16) and the whole thing persists to/from JSON (the seam M6's save/load builds on).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.outline import Outline
from core.schemas.scene_spec import SceneSpec
from core.schemas.style import StyleSpec


class SceneNode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int
    title: str
    intent: str
    spec: SceneSpec | None = None
    code: str | None = None
    mp4: str | None = None        # path to this scene's rendered (narrated) clip
    srt: str | None = None
    compiled: bool = False
    score: int = -1               # critic score if verified; -1 otherwise


class VideoProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
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

    def ordered_mp4s(self) -> list[str]:
        """Rendered clip paths in scene order (only scenes that have one) — input to stitching."""
        return [s.mp4 for s in self.scenes if s.mp4]

    def all_ready(self) -> bool:
        return bool(self.scenes) and all(s.mp4 for s in self.scenes)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "VideoProject":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
