"""Central, env-overridable settings. Pinned versions live here (Q2)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LATTICE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Manim / render image (Q2: pinned here, referenced everywhere) ---
    manim_version: str = "0.18.1"
    manim_base_image: str = "manimcommunity/manim:v0.18.1"
    render_image: str = "lattice-render:0.1"
    render_network: bool = False  # sandbox: NO network unless explicitly enabled (Q5)
    render_timeout_s: int = 600

    # quality presets -> manim CLI flags. preview = fast/low-res, final = slow/high-res.
    quality_preview_flag: str = "-ql"  # 480p15
    quality_final_flag: str = "-qh"    # 1080p60

    # --- loop caps (M2: never hang) ---
    max_repair_attempts: int = 4   # compile-repair retries per render
    max_critic_iters: int = 3      # vision-critic <-> fix iterations before best-of-N fallback
    best_of_n: int = 2             # candidates generated when the critic loop doesn't converge
    concurrency_cap: int = 4

    # --- vision critic (M2) ---
    critic_frames: int = 3         # keyframes sampled per render for the critic

    # --- LLM (OpenAI-compatible, swappable; NOT called in M0) ---
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "anthropic/claude-sonnet-4.5"   # generator (strong coder)
    critic_model: str = "openai/gpt-4o-mini"          # vision critic (cheap, swappable)

    # --- TTS (Q3; from M4) ---
    tts_engine: str = "gtts"

    # --- paths ---
    out_dir: Path = Field(default=PROJECT_ROOT / "out")

    def quality_flag(self, quality: str) -> str:
        """Map a quality name to the Manim flag. Anything not 'final' is preview."""
        return self.quality_final_flag if quality == "final" else self.quality_preview_flag


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
