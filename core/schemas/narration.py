"""Narration script schema (M4). One spoken line per animation beat — narration-first."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NarrationScript(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lines: list[str] = Field(..., min_length=1, description="one spoken sentence per beat, in order")

    @property
    def full_text(self) -> str:
        return " ".join(self.lines)
