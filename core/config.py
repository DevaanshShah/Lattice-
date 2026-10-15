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
    render_image: str = "lattice-render:0.2"   # 0.2 bakes in /opt/icons for self.icon() (see Dockerfile)
    render_network: bool = False  # sandbox: NO network unless explicitly enabled (Q5)
    render_timeout_s: int = 600

    # --- execution mode (PaaS deploy: no docker daemon available) ---
    # "docker" (default): every render/ffmpeg call is `docker run` in the pinned sandbox image.
    # "local": run manim/ffmpeg as direct subprocesses (cwd=work_dir, scrubbed env, rlimits) —
    # for platforms (Railway/Render) that only give you one container, no docker-in-docker.
    exec_mode: str = "docker"

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
    scene_retries: int = 3         # composition.decoupled: whole-scene REBUILDS before a scene is given up
    scene_retry_backoff_s: float = 10.0  # pause between those rebuilds (rides out a provider 500-streak)
    # Deadlines (0 = off). Caps bound how MANY times a step repeats; these bound how LONG the whole
    # thing may take, so a job ends with an actionable error instead of retrying invisibly.
    # Cooperative: enforced at the pipeline's checkpoints (core/cancel.py), so the effective
    # overshoot is at most one in-flight render (render_timeout_s).
    job_deadline_s: int = 3600     # whole build job, wall clock
    scene_deadline_s: int = 900    # one scene INCLUDING its rebuild attempts

    # --- web deploy: concurrency + auth (FR-31, PaaS deploy) ---
    # Admin console (/admin + /api/admin/*): usage, spend and per-user activity — everything a
    # visitor must never see. Set a token in .env for any deployed instance; with it empty the
    # console answers ONLY to loopback, so a public deploy fails closed instead of leaking.
    admin_token: str = ""
    job_workers: int = 2            # web/jobs.py::JobQueue thread pool (concurrent build jobs)
    scene_workers: int = 3          # composition.decoupled.build_video per-build scene fan-out
    web_users: str = ""             # "alice:<sha256hex>,bob:<sha256hex>" — empty = auth OFF (local dev)

    # --- vision critic (M2) ---
    critic_frames: int = 2            # keyframes per critique (fewer frames = fewer image tokens)
    critic_image_detail: str = "low"  # "low" ~= 85 vision tokens/frame vs ~765 for "high" — big cut
    video_critic_enabled: bool = True  # M7: run the vision critic in the multi-scene video path too
                                       # (catches overlap/off-screen/blank per scene). Off = cheaper, blind.
    structural_layout: bool = False    # Global default for the LEGACY main pipeline (generate/generate_narrated).
                                       # The VIDEO path (composition.decoupled.build_video) is FINALIZED on
                                       # structural — it defaults structural=True on its own (validated to render
                                       # cleaner than freehand AND Sonnet-freehand, at ~1/40th Sonnet's cost).
                                       # This flag stays False so the legacy path + its M1/M4/M5 tests are stable.
    layout_lint_enabled: bool = True   # FREE deterministic off-frame lint BEFORE the paid vision call:
                                       # geometry catches off-frame exactly, so the generator fixes it
                                       # in one pass instead of the critic flailing across iterations.
    vision_confirm: bool = True        # paid vision critic as a confirmation pass (defects geometry
                                       # can't see: merged glyphs, crowding, color). Default for the
                                       # SINGLE-scene generate-scene moat. The multi-scene VIDEO path
                                       # overrides this with video_vision_confirm (below).
    video_vision_confirm: bool = True   # MULTI-scene video: paid vision ON — it's the only layer that SEES
                                        # the render (catches text-on-shape overlap, literal labels, color that
                                        # the blind lint misses). Keep it cheap with a fast critic (Groq). Set
                                        # LATTICE_VIDEO_VISION_CONFIRM=0 to go blind/cheaper.

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
    # OpenRouter routing (cost lever): the ~6k static system prompt is re-billed at full input price
    # on every call UNLESS the upstream provider's automatic prefix cache stays warm. `sort:throughput`
    # picks the fastest host per call -> scatters providers -> cache never warms. Pin a provider instead
    # so DeepSeek's context cache hits (~90% off repeated input); fallbacks stay ON for reliability.
    llm_provider_pin: str = ""                         # e.g. "DeepSeek" — prefer this OpenRouter provider (warm cache)
    llm_provider_sort: str = "throughput"              # used only when NOT pinning: throughput|price|latency
    # Retry/timeout budget for ONE model call. Without an explicit timeout the SDK waits on its own
    # default (10 min) before our retry policy ever runs, so a wedged route reads as a hung job.
    # llm_attempts is OUR retry loop; the SDK's internal retries are turned OFF (see core/llm.py) so
    # attempts aren't silently multiplied. Worst case per call ~= llm_attempts * llm_timeout_s.
    llm_timeout_s: float = 120.0                       # per-request client timeout (seconds)
    llm_attempts: int = 6                              # transient-error / empty-response retries

    # --- optional Jev routing gate ---
    # Jev only classifies an auto-routed topic. It never writes a lesson, selects values, or
    # changes a deterministic trace. Empty/disabled means the existing keyword route is exact.
    jev_enabled: bool = False
    jev_api_key: str = ""
    jev_base_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-1.13.0"                     # pin routing behaviour; do not use jev-latest in production
    jev_timeout_s: float = 5.0
    jev_min_confidence: float = 0.30                  # measured 2026-10-15: right answers often come back at 0.4-0.7

    # --- TTS (Q3; from M4) ---
    tts_engine: str = "gtts"                          # "gtts" (free/online) | "kokoro" (free/local)
    kokoro_model: str = "kokoro-v1.0.onnx"            # path to the Kokoro ONNX model
    kokoro_voices: str = "voices-v1.0.bin"            # path to the Kokoro voices bin
    kokoro_voice: str = "af_heart"                    # af_*=female, am_*=male, bf_/bm_=British

    # --- object storage: Cloudflare R2 (S3-compatible) ---
    # A PaaS container's disk is ephemeral, so without this every redeploy destroys every video the
    # product has made. All empty = OFF, and everything keeps working exactly as it does on local
    # disk, so this is safe to leave unset until the bucket exists.
    r2_account_id: str = ""            # Cloudflare account id (the R2 endpoint is derived from it)
    r2_bucket: str = ""
    r2_access_key_id: str = ""         # R2 API token -> Access Key ID
    r2_secret_access_key: str = ""     # R2 API token -> Secret Access Key (shown once)
    r2_endpoint: str = ""              # override the derived endpoint (rarely needed)
    r2_public_base: str = ""           # optional public base (custom domain / r2.dev); empty = presigned URLs
    r2_delete_local: bool = False      # delete the local copy after a successful upload (small-disk deploys)

    # --- paths ---
    out_dir: Path = Field(default=PROJECT_ROOT / "out")

    def quality_flag(self, quality: str) -> str:
        """Map a quality name to the Manim flag. Anything not 'final' is preview."""
        return self.quality_final_flag if quality == "final" else self.quality_preview_flag


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
