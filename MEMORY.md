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

### 2026-09-04 — Two parallel sessions reconciled on main; Learn takes attachments
- **Merged `phase-ab-reliability` into main** (Phase A+B reliability + the Learn/Teach split)
  alongside the admin-console / usage-ledger / R2 / Learn-wiring work that a second session had
  been doing in the same checkout. That work was committed as-is first (`bfbf160`) so a merge
  could not lose it. Six conflicts, all additive on both sides, nothing dropped. The two that
  needed a real decision: `cancel.carry(usage.carry(...))` on the scene fan-out (both thread-locals
  must survive the hop), and in `jobs._run` **`usage.bind` outside, `cancel.scope` inside** — a
  stop unwinds the work but must NOT skip the durable job-ledger line. A cancelled job is now
  recorded too: a stop that already cost four minutes of renders is what those numbers are for.
- **Teach's front door is Describe + Code; Image moved to Learn.** The doors were split by SEED
  when the real difference is the OUTPUT CONTRACT — Teach returns a rendered artifact through the
  review gate, Learn returns an answer now with a video only when earned. A learner photographing
  a homework problem on the Teach door was starting a 4-minute build to be told what the picture
  shows. Code STAYS in Teach: its walkthrough scaffold is deterministic, which makes it the most
  reliable video the pipeline makes. `web/seed.describe()` (vision on the CRITIC client — the
  generator can't see) turns an attachment into text; the thread keeps a `has_image` flag and
  drops the base64.
- **Deleted the old Learn screen** (95 lines in app.js), dead since the chat rewrite and dangerous:
  it auto-approved every scene and built with no review gate.
- **Gate: 404 passing** (365 unit + 39 admin/storage). Server boots; a Learn thread with an image
  answers as text. `python -m scripts.merge_check <other-checkout>` now answers "does this merge?"
  with an exit code. NOT done: Phases C and D, and no live end-to-end video run yet.

### 2026-09-04 — Cloudflare R2 for finished videos (chosen over "send users to their own Drive")

- **The bug it fixes is not "we need a CDN": a PaaS disk is ephemeral.** Every redeploy wipes `out/`
  and every video the product ever made. Locally invisible, fatal in production.
- **R2 over S3** for one reason that dominates when the artifact is a streamed video: **zero egress**
  ($0.015/GB-month storage; 1,000 videos ~= 10 GB ~= $0.15/month — cheaper than making one deck).
- **Rejected: redirecting users to their own Google Drive.** It is an export feature, not a storage
  backend. It needs Google OAuth per user, which means building accounts first (users are anonymous
  cookie ids), and it takes the file OUT of the product: no in-app playback, gallery, re-export to
  Reel/YouTube, thumbnails, or admin visibility — and it asks for authorization at the exact moment
  the video is ready. Worth adding later as a "save a copy" button, on TOP of R2.
- **`core/storage.py`** is the seam: keys are DERIVED from ids (`videos/<pid>/final.mp4`), so no
  project/deck/thread schema changed to adopt it. Uploads happen after each build in all three paths
  (video, deck, learn) and are best-effort — an R2 outage logs and leaves the local file, never
  loses a render. Serving prefers local and 307s to a presigned URL when the disk was wiped;
  `engine.ensure_final()` pulls the file back for export/reframe/burn-in.
- **Inert until configured**: with the R2_* settings empty, `enabled()` is False and every call is a
  no-op, so this was safe to merge before the bucket existed.
- **`python -m scripts.r2 check|push|list|backup|pull`** — `check` round-trips a real object so bad
  credentials fail loudly at setup instead of silently swallowing uploads mid-render. `backup`
  snapshots the admin ledger, which is on the same ephemeral disk. Setup: `docs/r2-setup.md`.
- Private bucket + presigned URLs is the default; `LATTICE_R2_PUBLIC_BASE` switches to permanent
  public links, which is a product decision (anyone with the link can watch, forever).

### 2026-09-04 — Admin console: who uses Lattice, what they built, what it cost

- **The gap this closed.** There was no way to see usage at all: `core/llm.py` counted tokens in
  ONE process-wide accumulator that evals reset and a restart wiped, with no idea which user or
  project spent them — and the product has no accounts, so "per user" had nothing to group by.
- **Two new primitives, then a page on top.** `core/usage.py` is an append-only attributed ledger
  (`out/admin/usage.jsonl`): every model call, every created project/deck/thread, every finished
  job, each tagged with user + project + kind + surface. `web/users.py` mints an anonymous
  first-party cookie id per browser — explicitly NOT auth, just an attribution key, with
  `dependency()` as the single seam to swap when real accounts land.
- **Attribution rides a ContextVar, re-bound at every thread hop.** A request binds it once; the
  job queue captures it at submit (in the request thread) and `usage.carry()` re-binds it inside
  `composition/pool.py` and the `decoupled` scene fan-out. Without that, every scene's model calls
  land unattributed, because a worker thread starts with an EMPTY context. A test pins this.
- **Cost is honest about what it doesn't know.** Provider-reported `usage.cost` wins over the local
  price table; a model missing from `MODEL_PRICES` with no reported cost is flagged `priced:false`
  and the dashboard says the total is a floor. `/api/admin/*` also shows the real OpenRouter
  account + key balance beside our own number, so the gap is visible.
- **`/admin`** (vanilla, polls every 5s): user/spend/build tiles, live jobs with progress bars,
  14-day spend chart, per-user table + drawer (their projects, models, events, editable label),
  everything-built table with per-project progress, cost by model and by surface, raw ledger feed.
- **Gate: `LATTICE_ADMIN_TOKEN`, else loopback only** — a public deploy fails closed instead of
  publishing every user's activity. The page shell stays open so there is somewhere to type it.
- **Found by running it:** the test suite was writing itself into the REAL ledger (35 fake users,
  110 fake jobs on first look). `tests/conftest.py` now redirects `settings.out_dir` for the whole
  session. Also fixed: `Request`/`Response` imported inside the dependency factory resolved to
  nothing under `from __future__ import annotations`, so FastAPI treated them as query params.
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

### 2026-09-29 — Structured payload fields made visible so software-flow claims can be proven
- Diagnosis (live-acceptance-harness-20260926): message/card/document/tool objects rendered only their label; payload (`order_id: 42`) and `set_state` changes were invisible, so the planner could only appear/highlight boxes and the `sequence` proof correctly failed.
- `core/visual_state.displayed_fields` now drives both renderer (`key: value` rows) and validator anchor text; `set_state` that changes nothing drawn is rejected (validator stricter, not weaker). Prompt + repair teach "prove a step by changing a drawn field, then show the next message".
- Follow-ups from live GPT-4o runs (attempt-04..07, resumed from saved valid scenes, ~$0.21 total): first scene now drops forward `carryover_ids`; drawn message/document fields count as `value` proof; `set_state` must change a drawn value vs. the current screen (no-op "proofs" rejected, error names the value already shown); missing-anchor repair names the exact `key: value` to draw.
- Then replaced those patches with one rule: the validator replays every action and judges proof only from visible screen effects (revealed/changed/removed via `core/visual_state.action_effect`), never from the plan's self-declared evidence; anchors match facts (value under a compatible field name) at any moment in the beat; planner derives `closing_visible_ids` from executed actions (`derive_closing`). 529 tests pass.
- Offline replay of attempts 03-07: every scene has one honest plan that passes; every fake (highlight-only, appear-only, no-op correction) is rejected. First complete agent-harness video rendered offline from saved plans with zero LLM calls: `out/live-acceptance-harness-20260926/attempt-08-offline/browser-video.mp4` (16.7s).
- Known defects in that video: lesson too short (~41 words vs ~90 asked, no grounded answer); scene 3 reuses the original request so it shows `order_id: missing` with `validated: ✓` and the old `shipped` response stays on screen (meaning-level inconsistency the validator cannot see); tall single-column layout with small text and a confusing error loop arrow.

### 2026-10-09 — Full audit of the semantic (v2) video path (no code changed)
- Wiring: the web UI on branch `codex/learning-video-continuity-20260922` always plans `browser_v2` + schema v2; `main` has none of it (6 commits + all 2026-09-29 work live only on this branch, the latter uncommitted). CLI needs `--renderer browser_v2 --semantic-visuals`; `scripts.selftest` and image upload still drive the legacy path.
- Confirmed by offline experiment: cutting/reordering an outline scene crashes a v2 build (raw `KeyError` or carryover error); `target_seconds` never reaches the lesson planner and `max_scenes` truncates the finished lesson; an unrelated object's change still passes as proof; a lesson that marks every claim `label` bypasses proof entirely; the saved 2026-09-23 binary-search plan now fails validation (true catch: hidden counter increment, re-check of an already marked cell) so older v2 drafts may need re-planning; step dimming dims the array in browser-mode array scenes; flows over 3 linked boxes need the compact retry and 7+ fail.
- Unverified: whether the web default model (`gpt-4o-mini`) can pass the new checker; every passing scene so far came from `gpt-4o`.
- Open design decision unchanged: render message/tool/document objects with the original card renderer (2026-09-20 look) and put payload fields inside, instead of the bare semantic column/flow layout.
- Measured prompt budget of the v2 path (offline replay, ~4 chars/token, within ~10% of billed usage): lesson call ≈ 875 tokens in / 760 out; each scene call ≈ 3,300–3,600 in / 550–1,000 out, of which the fixed planner prompt is 2,452 (about 70%) and over half of that prompt is array/pointer/binary-search rules. Best case for a 3-scene video = 4 calls ≈ 11k in / 3k out (≈ $0.06 on gpt-4o, ≈ $0.003 on gpt-4o-mini); a scene that needs all 3 tries costs ≈ 11.9k in by itself. Rendering makes no LLM calls.
- Planner calls use `attempts=1` and sit outside the repair `try`, so one timeout/429/5xx aborts the whole plan (app default is 6 transport attempts).
- Plan for the remaining work: `docs/learning-video-hardening-plan-2026-10-09.md` (proposed, not started). Phase 0 checkpoint + offline regression harness, Phase 1 correctness fixes, Phase 2 original card look, Phase 3 lesson step and prompts against a live baseline, Phase 4 acceptance and merge. Research behind the "keep the architecture" call: `reports/Explainer video generation architectures.md`. Decisions logged in `DECISIONS.md` (2026-10-09, 2026-09-29).

### 2026-10-09 — Hardening plan Phase 0: checkpoint and offline regression harness
- Checkpoint of the 2026-09-29 work committed and pushed on `codex/learning-video-continuity-20260922` (`04e6d3a` code, `4f23b88` docs). Commits carry only the owner's name.
- `python -m scripts.video_regression`: re-renders seven saved plans in `tests/fixtures/video_golden/` through `browser_video.build` with silent fixed-length narration, checks validity, build, compact-layout fallbacks and length, compares every frame (FFmpeg SSIM) with the approved videos in `out/video_regression/baseline/` (local, not in git) and writes a contact sheet per case. About five minutes; all seven pass, zero fallbacks, and repeat runs match at SSIM 1.0000. `--accept-last` approves a reviewed run.
- `python -m scripts.selftest --renderer browser_v2` drives the new path through the web engine (live). `python -m scripts.plan_battery` plans three fixed topics and scores plan rate and first-try scene rate against a baseline (live, call cap; scoring in `eval/plan_score.py`). Neither has been run live yet: the first battery run is the Phase 3 baseline.
- The Docker image `lattice-render:0.2` had been deleted from this machine; rebuilt with `python -m scripts.setup_env`. Unit tests: 552 pass, including the two that need Docker.
- Gate still open: the owner looks at the starting contact sheets. Next is Phase 1 (correctness fixes, no model calls).
