# Lattice / Franko — Engineering Handoff

**Repository:** `C:\Users\Dev\Desktop\Franko`  
**Branch:** `main`  
**Prepared:** 2026-09-04  
**Purpose:** Give Claude Code the verified system map, current state, risks, and a safe implementation plan for improving video-generation speed, reliability, and cost.

## 1. Read this before changing anything

- The checkout contains **user-owned, uncommitted work**. Do not reset, checkout, clean, or overwrite it.
- Do not commit, push, deploy, change production credentials, or run broad live generation tests unless explicitly asked.
- The root `README.md` is stale: it says the product code does not exist. Treat the implementation and tests as the source of truth.
- On this Windows machine, use the project interpreter: `./.venv/Scripts/python.exe`.
- Git inspection may require: `git -c safe.directory='C:/Users/Dev/Desktop/Franko' ...`. Do not weaken Git safety globally.

### Current uncommitted files (preserve)

```text
M  prompts/style-spec.md
M  web/app.py
M  web/static/app.js
M  web/static/index.html
?? .codex/
?? index.html
?? intro.js
?? web/static/fourier-poster.jpg
?? web/static/intro.js
```

Latest commit seen: `1dcc164` (2026-07-17), `feat(learn): chat-shaped Learn — text by default...`.

## 2. What the product is

Lattice is an AI educational-explainer video application. It turns a prompt into a structured multi-scene video, with deterministic rendering and quality checks rather than trusting model output directly.

It has three user-facing paths:

1. **Video generation:** prompt → plan → Manim scenes → narration → stitched MP4.
2. **Slides:** content-first HTML/CSS deck rendering plus FFmpeg composition.
3. **Learn:** chat-first learning interaction; a video/deck is generated only when it is justified.

The codebase is materially implemented, despite the stale root README.

## 3. End-to-end video pipeline

```text
User prompt
  → outline generation
  → visual style generation
  → one structured scene specification per scene
  → Manim/Python code generation
  → sandboxed render (Docker image by default)
  → compile repair + deterministic layout lint
  → optional image/vision confirmation
  → scene narration generation
  → local Kokoro text-to-speech
  → FFmpeg mux per scene
  → FFmpeg stitch into final MP4
```

Key implementation locations:

| Concern | Primary files |
|---|---|
| Runtime settings | `core/config.py` |
| OpenAI-compatible client, retry and token accounting | `core/llm.py` |
| Main multi-scene build orchestration | `composition/decoupled.py` |
| Structural named-grid Manim scaffold | `generation/lattice_scene.py` |
| Deterministic geometry/layout checks | `verification/layout_lint.py` |
| Web app and job queue wiring | `web/app.py`, `web/jobs.py` |
| Web build orchestration and project state | `web/engine.py` |
| Slide and Learn paths | `web/decks.py`, `web/learn.py` |

### Important design boundary

`LatticeScene` gives generated Manim code a named-grid structural scaffold. Layout lint is deterministic and free; visual confirmation is optional and paid. Preserve this ordering: **lint before vision**. It keeps the expensive reviewer focused on defects geometry cannot detect (bad typography, crowding, colors, etc.).

## 4. Verified current configuration

Loaded from the local `.env` using the `LATTICE_` prefix. Credentials were not exposed.

```text
LLM base URL:              https://openrouter.ai/api/v1
Generator:                 deepseek/deepseek-chat-v3-0324
Vision critic:             openai/gpt-4o-mini
Generator provider pin:    DeepSeek
Separate critic key:       configured
Scene workers:             3
Web job workers:           2
Max compile-repair tries:  4
Max critic iterations:     3
Render timeout:            600 seconds
Video vision confirmation: enabled
Maximum output tokens:     8192
TTS:                       Kokoro (local)
```

### Account availability was verified, not assumed

The configured OpenRouter account lists these relevant IDs:

```text
openai/gpt-5.6-terra
openai/gpt-4o-mini
deepseek/deepseek-chat-v3-0324
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-flash-0731
deepseek/deepseek-v4-flash-vision-exp
deepseek/deepseek-v4-pro
deepseek/deepseek-v4-pro-0813
```

`openai/gpt-5.6-terra` was also exercised through the **existing Lattice OpenRouter client** with a minimal live request and returned `OK`. There is no configured direct OpenAI API route, but none is required for Terra through this OpenRouter account.

## 5. What is already verified

- Unit gate run on 2026-09-04: **313 passed in 4.44s**.
- Project-local `.venv` is functioning.
- Docker Desktop and `lattice-render:0.2` were confirmed in prior validation.
- A historical real self-test passed for a 2-scene binary-search video (33.9-second MP4). It is evidence that the path has worked, **not proof of current end-to-end quality after the uncommitted UI changes**.
- A previous local server check returned HTTP 200 at `http://127.0.0.1:8080/`. It is **not running at the moment this handoff was prepared**.

Run the local app explicitly with:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve --host 127.0.0.1 --port 8080
```

Then open `http://127.0.0.1:8080/`.

## 6. Why a single video can be slow or appear stuck

This is primarily a retry/render orchestration problem, not just a "pick a faster model" problem.

### Current multiplicative work

- A video can build up to 8 scenes.
- `composition/decoupled.py::build_video()` fans scenes out with `workers=3` by default.
- Each scene can retry the whole scene build up to 3 times.
- A render can attempt compile repair up to 4 times.
- The critic can iterate up to 3 times and may trigger additional renders/fixes.
- Each render may wait as long as 600 seconds.
- `core/llm.py` retries a transient/empty model response up to 6 times, with increasing sleeps.
- The web process concurrently accepts 2 build jobs (`web/app.py` currently hard-codes `JobQueue(workers=2)`).

So a transient provider failure, weak generated code, or a slow render can look like a hung job while it is actually repeatedly regenerating, rendering, and repairing.

### Confirmed observability gap

The UI exposes coarse progress such as planning, scene number, and merging. Detailed LLM call labels/durations are recorded by `web/devtrace.py`, but there is no strong user-facing phase timeline, per-phase deadline, cancellation, or durable job persistence.

## 7. Cost findings

An earlier successful two-scene run consumed about 62,274 input tokens and 6,343 output tokens across pipeline calls. Using provider list prices at the time of analysis, estimated **text-model-only** cost was:

| Generator used for all text calls | Approx. cost / two-scene video | Relative to current V3 |
|---|---:|---:|
| Current V3-0324 | $0.0207 | baseline |
| DeepSeek V4 Flash | $0.0053 | ~74% cheaper |
| DeepSeek V4 Pro | $0.0472 | ~2.3× more |
| GPT-5.6 Terra | $0.2007 | ~9.7× more |

These are estimates, not guaranteed invoices. Image-token vision review, retries, provider routing, and prefix caching change actual spend. Kokoro incurs no per-request model fee because it runs locally.

### Cost-accounting bug/gap to fix

`core/llm.py::MODEL_PRICES` is a hand-maintained price table. It does **not** contain V4 Flash or Terra, and its V3/V4 Pro values may not match the current OpenRouter route. An unknown model reports `$0` while still recording tokens. Do not use the displayed cost metric as billing truth until this is fixed.

## 8. Recommended model policy

Do not route every call through Terra. It is confirmed compatible but should be a rare premium fallback.

```text
Normal pipeline (fast + inexpensive)
  generator / JSON / code / narration / first repair:  deepseek/deepseek-v4-flash
  normal visual critic:                                openai/gpt-4o-mini
  speech:                                              local Kokoro

Escalation only after an actual failure
  one final repair attempt:                            deepseek/deepseek-v4-pro

Premium only for a user-selected final review or a scene that remains ambiguous
  visual/code review fallback:                         openai/gpt-5.6-terra
```

Before changing the default globally, run a fixed evaluation battery (15–20 representative prompts) and compare:

1. first-try compile success rate;
2. number of repair loops and renders per scene;
3. deterministic lint violations;
4. visual defects found by the critic;
5. wall-clock time to a usable preview and final video;
6. input, output, image-token, and retry cost per completed video.

## 9. Recommended implementation order (do not patch randomly)

### Phase A — make failures visible and bounded

1. Add explicit phases to the job state: `planning`, `style`, `scene_spec`, `codegen`, `render`, `lint`, `vision`, `narration`, `mux`, `stitch`, `retrying`, `failed`, `complete`.
2. Stream the phase, attempt count, elapsed time, and useful failure message to the UI.
3. Add a cancellation flag checked between model calls, repair attempts, render calls, and scene scheduling.
4. Add phase-level deadlines. A job should terminate with an actionable error instead of retrying invisibly for many minutes.

**Acceptance test:** intentionally make a scene fail; the UI must name the failing phase, show bounded retries, allow cancellation, and preserve any successful earlier scene clips.

### Phase B — make configured limits real

1. Pass `settings.scene_workers` into `build_video()` rather than relying on its literal default.
2. Replace `JobQueue(workers=2)` in `web/app.py` with `JobQueue(workers=settings.job_workers)`.
3. Centralize retry limits: remove competing magic defaults where possible and report all attempts in job telemetry.
4. Add a real client timeout to the OpenAI-compatible client; currently a provider call can wait until the underlying library/network timeout before the retry policy takes effect.

**Acceptance test:** changing `LATTICE_SCENE_WORKERS`, `LATTICE_JOB_WORKERS`, and timeout/retry settings alters a controlled test run without source changes.

### Phase C — split Draft from Final

1. **Draft:** preview resolution, no paid vision call, small output limits, short deadline, maximum one repair.
2. **Final:** current structural lint and paid vision confirmation, with bounded escalation.
3. Cache stable artifacts: approved outline, style, scene specs, code, rendered clips, narration, and audio using content/model/quality keys.

**Acceptance test:** a repeat build of unchanged approved scenes performs no new model/render work; a draft reaches a playable video predictably before final quality processing.

### Phase D — install the model ladder safely

1. Add named settings for primary generator, repair fallback, normal critic, and premium critic; do not scatter model strings through call sites.
2. Route to V4 Pro only after defined evidence of failure, not simply because a response took longer than expected.
3. Permit Terra only via an explicit per-job quality option or a narrowly defined fallback.
4. Update `MODEL_PRICES` and report cost by model, input/output tokens, image inputs, and retry number.

**Acceptance test:** test doubles prove correct model routing, no silent Terra use, and correct cost aggregation for every configured model.

## 10. Non-negotiable safety and quality rules

- Keep Docker/Manim sandboxing (`network=none` by default, pinned render image, resource limits).
- Do not remove deterministic lint in favor of an LLM/vision judge.
- Do not run elevated and non-elevated full self-tests concurrently against the same output folder; it duplicates model spend and corrupts conclusions.
- Preserve partial successful scene clips when another scene fails.
- Keep OpenRouter keys out of logs, commits, issue comments, screenshots, and generated reports.
- Do not claim deployment or production verification. Current evidence is local-only.

## 11. Useful commands

```powershell
# Unit gate
.\.venv\Scripts\python.exe -m pytest -m unit -q

# Local server
.\.venv\Scripts\python.exe -m scripts.serve --host 127.0.0.1 --port 8080

# Controlled real generation / self-test (only when authorized; consumes model credits)
.\.venv\Scripts\python.exe -m scripts.selftest

# Per-key OpenRouter spend report
.\.venv\Scripts\python.exe -m scripts.cost
```

## 12. Definition of done for the reliability/speed work

Do not call this finished merely because models were renamed. It is done when:

- a user sees exactly which phase is running and how long it has taken;
- every model/render/retry has a bounded deadline and meaningful error;
- cancellation works without killing the server;
- Draft reliably gives a quick playable output;
- Final uses the bounded quality ladder;
- model routing comes from config and is covered by tests;
- cost telemetry is accurate enough to compare models and retries;
- the fixed evaluation battery demonstrates better median time and equal-or-better compile/visual quality;
- unit tests pass and one authorized live end-to-end run succeeds.

