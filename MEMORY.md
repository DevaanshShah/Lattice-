# MEMORY.md — Lattice project handoff log

Running memory of this project's state and progress, maintained **across Claude Code sessions**.
Updated on **phase / milestone changes only** — not on individual file edits.

- Each session, Claude reads this at the start of substantive work and appends a dated entry to the **Phase log** when a phase/milestone/task completes.
- Companion docs: `RESUME.md` (one-page build handoff), `MILESTONES.md` (M0→M8 roadmap + DoD), `AGENT_TICKETS.md` (tickets).

---

## Current state (snapshot)

| Milestone | What | State |
|---|---|---|
| M0 | Env spike + Docker render sandbox | ✅ shipped |
| M1 | Scene spec → Manim code + guardrails | ✅ shipped |
| M2 | Verification: compile-repair + vision critic + best-of-N | ✅ shipped |
| M3 | CLI + eval harness + content-hash cache | ✅ shipped |
| M4 | Narrated scene (TTS + sync + captions) | ✅ shipped |
| M5 | Multi-scene video + consistency (**v1 demo**) | ✅ shipped |
| M6 | Editing & human control | ✅ shipped |
| M7 | Web UI + hardened infra | 🧪 code complete — unit gate green; live browser check pending |
| M8 | Polish, moat & V2 | planned |

**Active pipeline:** the web path runs the newer **decoupled + structural** pipeline
(`composition/decoupled.py`, LatticeScene grid scaffold), not the older `composition/video.py`.

**Run it:** `python -m scripts.serve` → http://127.0.0.1:8080 (default port changed from 8000).
Needs Docker Desktop + `lattice-render:0.1` image + `.env` with `LATTICE_LLM_API_KEY`.

---

## Phase log

<!-- Newest first. Append a dated entry when a phase/milestone/task completes. Format: ### YYYY-MM-DD — what changed and why -->

### 2026-09-04 — Reliability/speed Phase A+B: configured limits made real, plus stop + named steps
- **Branch `phase-ab-reliability` (worktree `..\Franko-phaseab`), uncommitted. See `PHASE_AB_STATUS.md`.**
  Done on a branch because a second session was writing to the main checkout at the same time (the
  admin-console / usage-ledger work); every edit made to that tree was reverted, and it is back to
  its own state with `313 passed`.
- **Phase B — the .env knobs were wired to nothing.** `JobQueue(workers=2)` and
  `build_video(workers=3, retries=3)` were literals; `settings.job_workers` / `scene_workers`
  existed but were referenced nowhere. Now resolved from settings (explicit args still override).
  Added `scene_retries`, `scene_retry_backoff_s`, `llm_timeout_s`, `llm_attempts`, `job_deadline_s`,
  `scene_deadline_s`. **The real find: the OpenAI SDK was retrying on top of our 6-attempt loop with
  no timeout set** — up to 18 hidden attempts, each waiting on the SDK's 10-minute default before our
  retry policy ran. `OpenAI(..., timeout=…, max_retries=0)` makes `_create` the single retry
  authority. Defaults unchanged, so behaviour only moves when a knob does.
- **Phase A — a build that is retrying no longer looks hung.** `core/cancel.py`: an AMBIENT
  (thread-local) cancel token, carried into the scene pool the same way `usage.carry` carries
  attribution, checked before every model call / repair attempt / critic round / render / scene.
  `Cancelled` subclasses **BaseException** on purpose — the pipeline's many `except Exception`
  handlers would otherwise swallow a stop and keep spending. Deadlines (job + per-scene) trip the
  same token, so running out of time ends with a reason instead of a mystery timeout.
- **Named steps without touching the pipeline.** `web/phases.py` derives the current step
  (planning/codegen/render/lint/vision/narration/stitch/retrying/…) from the log narration the
  pipeline ALREADY emits, so `composition/` and `verification/` stay web-agnostic; unit-tested
  against 13 literal log strings so a reworded line fails a test instead of silently blanking the UI.
  Job state gained step/attempt/elapsed + a `cancelled` terminal state (a stop is not a failure);
  `POST /api/jobs/{id}/cancel`; UI shows "Rendering · attempt 2/4 · 3:41" and a Stop button.
- **Gate: 358 passed** (313 base + 45 new). NOT done: a live end-to-end run, Phases C and D, and
  cancellation is cooperative — worst case it waits out one in-flight render.

### 2026-07-17 — Direct export presets: YouTube (16:9) + Reel (9:16), reframed at export
- **Two delivery formats from ONE build.** `GET /api/projects/{pid}/download?format=youtube|reel`
  (+ the existing `subtitles=none|burn`). "youtube" = the finished `final.mp4` handed back untouched,
  **no re-encode**; "reel" = one ffmpeg pass → 1080x1920. UI: a format segmented control in the
  download dropdown (`app.js` `studio()`, `state.format`).
- **Reframe, NOT a native vertical render — deliberate.** A portrait Manim frame would mean redoing
  every landscape constant in the grid scaffold (`_MAIN_X/_MAIN_Y`, the 12.4x5.8 `fit_content` safe
  area, title caps, the `11.5` width-cap regex, the prompt's "8 cols / rows A–E" rules), would
  re-open the layout failure class this project has spent months closing by construction, AND would
  cost a second LLM build per format. It would also trip `sandbox._RES_BY_FLAG` (maps `-qh` →
  literal `"1080p60"` to FIND the output; passing `-r` makes Manim write elsewhere → silent
  no-output). Padding costs one ffmpeg pass, zero tokens, and cannot regress a scene that rendered
  correctly. Trade: the diagram is a centre band; the freed space is where burned captions go.
- **Seam bug found by looking at the rendered frame, not the code** (exactly the `judge-by-rendered-frames`
  lesson). Padding with the nominal `#101015` produced a visibly LIGHTER band: h264's limited-range
  encode makes that constant *decode* as ~`#090A0F` (7/255 off). Forcing `in_range/out_range=tv` did
  nothing (the mismatch is on source decode, not pad conversion); a blurred-cover bg was still 3/255
  off at ~3x CPU. Fix = `export.sample_bg()` samples the video's OWN corner and pads with that →
  **seam 7/255 → 1/255**. Self-corrects for future/per-project backgrounds; falls back to nominal.
- `build_filters()` / `build_export_command()` are pure + unit-tested (16 tests); `build_burn_command`
  now delegates and the 16:9 burn chain is asserted byte-identical. `decoupled._BG_COLOR` → public
  `BG_COLOR` (single source, aliased for back-compat). Verified live on a real 264s build: 1920x1080
  → 1080x1920, duration preserved, youtube path returns `final.mp4` itself.

### 2026-07-12 — Autonomous self-test harness (run-once, no human in the loop)
- **`python -m scripts.selftest ["<topic>"]`** drives the REAL user path via `web.engine.Engine`
  (plan → auto-approve the theme/outline gate → build → stitch), then GRADES the rendered output —
  it does not re-implement the pipeline. Preflight (key/docker/render-image/TTS) fails fast before spend.
  CRITICAL checks (exit≠0 on fail): project persisted · final.mp4 non-trivial · every scene rendered ·
  final duration>0. WARN checks: clip length · stitch≈Σscenes · narration present · **no chat/meta leaked
  into narration** (reuses `decoupled._NARRATION_META`) · word budget · theme applied. Writes
  `out/selftest/<topic>/report.md` + keeps the workspace. Default = cheap 2-scene preview smoke.
- **First live run PASSED clean**: binary-search topic, 2/2 scenes, 33.9s, 0 critical / 0 warnings; the
  build even self-healed (compile-fix + critic-fix recovered scene 0). This replaces the old
  `scripts.test_video` (which used the LEGACY `composition.video` path and graded nothing).
- Gap surfaced (not new): cost meter still reports **$0.0000** for `deepseek-chat-v3-0324` — not in
  `core/llm.py::MODEL_PRICES`, so token counts are real but the dollar figure isn't.

### 2026-07-12 — Web editor upgrade, per-video cost fixes, theme-review gate
- **Video-editor edit panel** (web): per-scene editor is now a tabbed **Frames · Sound · Motion** control (`web/static/app.js` `editorPanel`/`editTabBar`), mapping to the existing tweak / narration / regenerate endpoints. Utility actions (insert/history/delete) moved to a footer.
- **Cost fixes** (per-video spend spiked from calls×tokens/scene, NOT model price): **A** — `llm_provider_pin` (`.env` `LATTICE_LLM_PROVIDER_PIN=DeepSeek`) keeps DeepSeek's prefix cache warm instead of `sort:throughput` scattering providers; **B** — paid vision critic now gated to `quality in ("high","final")` in `composition/decoupled.py`, so Draft builds are lint-only. Measured a 2-scene Draft at **$0.0074, 0 vision calls**. Deferred: lower critic/repair caps, add v3-0324 to `MODEL_PRICES` (cost meter reports $0 for the live model).
- **Theme review gate**: the visual THEME (StyleSpec) is now generated at PLAN time and shown on the outline-review screen ("Step 2 · Review theme & storyboard") so the user checks palette/fonts BEFORE building; `build()` threads the approved theme into `build_video(style=...)` instead of rolling a fresh one. (`web/engine.py`, `composition/decoupled.py`, `themePanel()` in app.js.)
- Not committed yet at time of writing.

### 2026-07-11 — Seed inputs, code-walkthrough scaffold, Kokoro TTS, deterministic off-frame guards
- **Image + code-snippet inputs** (`be8f57e`): new front doors — image→vision→topic (`web/seed.py`); code→segment-by-segment walkthrough. Both land on the existing `/api/projects` outline gate. Frontend gained Describe/Image/Code tabs.
- **Code-walkthrough deterministic scaffold** (`e65e1b1`): full code stays on screen, the active line highlights, an arrow points to a caption, per-line narration. `generation/code_scaffold.py` + `composition/walkthrough.py` + `planner/code_walkthrough.py` (manifest). Layout fixed in code → reliable on cheap v3, no re-rolls.
- **Kokoro local TTS** (`9fd623f`): `LATTICE_TTS_ENGINE=kokoro` — free/offline neural voice behind the `narration/tts.py` seam; model files in repo root (gitignored). gTTS still the fallback.
- **Off-frame guards** (`c7ed304`, `cca2a72`): `self.graph()` auto-fits y-range so function plots can't overflow; `fit_content()` now SHRINKS any oversized/off-frame content (universal, not just graphs). Off-frame class now solved by construction.
- **Model verdict:** `deepseek-v4-pro` (reasoning, ~4× cost) rendered the SAME scene WORSE than a `v3-0324` re-roll — freeform layout quality is model-INDEPENDENT variance. Keep v3-0324; do NOT use v4-pro. The fix is deterministic scaffolds, not a bigger model or more re-rolls.
- **Next:** comparison-table archetype (`self.table()`) for dense box diagrams + the "weak/sparse scene" mode — the last freeform failure class.

### 2026-07-10 — Established this MEMORY.md handoff log
- Added repo-root `MEMORY.md` as a cross-session memory of project state, updated on phase/milestone changes only.
- Wired a `SessionStart` hook in `.claude/settings.json` so every future Claude session is reminded to read this file and append phase-change entries.
- Changed the web UI default port 8000 → 8080 (`scripts/serve.py`).
