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

    # --- sandbox hardening (M7 / FR-23): bound model-written code, contain hostile snippets ---
    # These ride on top of the day-one guarantees (--network=none + image's non-root user + --rm).
    render_memory: str = "2g"          # hard RAM cap (container OOM-killed past it)
    render_cpus: str = "2.0"           # CPU quota (no host CPU monopoly)
    render_pids_limit: int = 512       # cap live processes -> contains fork bombs
    render_read_only: bool = False     # read-only root FS (writable: the mounted /manim + tmpfs)
    render_tmpfs_size: str = "512m"    # size of the ephemeral /tmp tmpfs when read_only is on
    render_user: str = ""              # explicit --user (uid[:gid]); empty = the image's non-root default

    # quality presets -> manim CLI flags. preview = fast/low-res, final = slow/high-res.
    quality_preview_flag: str = "-ql"  # 480p15
    quality_final_flag: str = "-qh"    # 1080p60

    # --- loop caps (M2: never hang) ---
    max_repair_attempts: int = 4   # compile-repair retries per render
    max_critic_iters: int = 3      # vision-critic <-> fix iterations before best-of-N fallback
    best_of_n: int = 2             # candidates generated when the critic loop doesn't converge
    concurrency_cap: int = 4

    # --- vision critic (M2) ---
    critic_frames: int = 2            # keyframes per critique (fewer frames = fewer image tokens)
    critic_image_detail: str = "low"  # "low" ~= 85 vision tokens/frame vs ~765 for "high" — big cut
    video_critic_enabled: bool = True  # M7: run the vision critic in the multi-scene video path too
                                       # (catches overlap/off-screen/blank per scene). Off = cheaper, blind.
    layout_lint_enabled: bool = True   # FREE deterministic off-frame lint BEFORE the paid vision call:
                                       # geometry catches off-frame exactly, so the generator fixes it
                                       # in one pass instead of the critic flailing across iterations.
    vision_confirm: bool = True        # paid vision critic as a confirmation pass (defects geometry
                                       # can't see: merged glyphs, crowding, color). Default for the
                                       # SINGLE-scene generate-scene moat. The multi-scene VIDEO path
                                       # overrides this with video_vision_confirm (below).
    video_vision_confirm: bool = False  # MULTI-scene video: paid vision OFF by default — across 8 scenes
                                        # it adds up, and the free off-frame lint + codegen guardrails carry
                                        # most of the value. Set LATTICE_VIDEO_VISION_CONFIRM=1 to re-enable.

    # --- token budget (cost control) ---
    # caps output per call: bounds output-token cost (the dominant cost) AND the upfront credit
    # reservation providers require (this is what 402'd Sonnet at 64000 on the capped key).
    max_output_tokens: int = 8192

    # --- multi-scene (M5) ---
    scene_cap: int = 8             # Q4: hard cap on scenes per video (planner output + cost)

    # --- LLM (OpenAI-compatible, swappable; NOT called in M0) ---
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-4o-mini"            # generator (cheap; ~20x less than sonnet)
    critic_model: str = "openai/gpt-4o-mini"          # vision critic (cheap, swappable)
    critic_base_url: str = ""                         # optional: critic on a DIFFERENT provider (e.g. Groq gen + Gemini critic). empty = same as generator
    critic_api_key: str = ""                          # empty = reuse llm_api_key
    prompt_cache_enabled: bool = True                 # mark static system prompt cacheable (Anthropic cache_control)

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
