"""Outline schema (M5) — the planner's output, human-editable BEFORE any scene renders."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OutlineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=1, description="what this scene should show / explain")


class Outline(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str
    items: list[OutlineItem] = Field(..., min_length=1)

    def titles(self) -> list[str]:
        return [i.title for i in self.items]
