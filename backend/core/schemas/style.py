"""Style spec (M5, FR-4) — one small design system injected into EVERY scene's generation,
so 20 independent scenes read as one coherent film. Generated once per video."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StyleSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    palette: dict[str, str] = Field(default_factory=dict)        # name -> hex, e.g. {"primary": "#3498db"}
    fonts: str = ""                                              # font/sizing guidance
    object_styles: dict[str, str] = Field(default_factory=dict)  # "box" -> "rounded, primary stroke"
    layout_rules: list[str] = Field(default_factory=list)

    def as_prompt(self) -> str:
        """Render to a directive block injected into every scene's codegen prompt."""
        parts = ["STYLE SPEC — apply consistently to EVERY scene so they look like one film:"]
        if self.palette:
            parts.append("Palette: " + ", ".join(f"{k}={v}" for k, v in self.palette.items()))
        if self.fonts:
            parts.append("Fonts: " + self.fonts)
        if self.object_styles:
            parts.append("Object styles: " + "; ".join(f"{k} -> {v}" for k, v in self.object_styles.items()))
        if self.layout_rules:
            parts.append("Layout rules:\n" + "\n".join(f"- {r}" for r in self.layout_rules))
        return "\n".join(parts)
