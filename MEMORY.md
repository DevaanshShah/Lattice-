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

### 2026-10-09 — Hardening plan Phase 1: correctness fixes (no model calls)
- Proof (`verification/visual_plan_validation._proves`) now looks at what every action of the beat did to the objects the claim names (plus the array under a named pointer); citations no longer matter, a change to an unrelated object no longer counts, and planner-added tidy-up hides (`clear_finished_steps`, `hide_final_*`) are excluded. The evidence kind must still match the requirement.
- A carryover object missing from the previous scene is reported before the replay, so a cut or reordered chain fails with a reason instead of a `KeyError`. `web/engine.Engine.check_build` validates the approved scenes before a job is queued and the build endpoint answers 400 with the reason; cutting still works when the remaining scenes validate. The outline screen hides "Add a scene" for learning-video projects.
- Step dimming applies only to flow layouts, never to a scene with an array or chart. Planner calls use three transport attempts (`planner.lesson_plan.TRANSPORT_ATTEMPTS`).
- Regression threshold tightened to 0.9999: unchanged code scores exactly 1.0 and the dimming fix only moved one case to 0.9989.
- Gate: 561 unit tests pass; all 15 saved attempts keep their verdict; only `binary_search` frames changed, as intended, and its baseline was updated. Next is Phase 2 (original card look, no model calls).

### 2026-10-10 — Hardening plan Phase 2: the look (no model calls); owner approval pending
- Message, tool, document, card, node, gate and group objects on the semantic stage are drawn with the original card styles (`.node`, `.kind-*`, `.role-*`) with their payload values inside; decision diamonds and role colours come with them. Arrays, counters, charts, formulas and images are unchanged; code in a flow gets a thin panel.
- Every object a scene ever shows has a fixed slot (`_shown_in_scene`); one not yet visible is rendered with `is-hidden` (opacity 0), so nothing moves when another appears. Flows wrap after four columns and the wrap connector runs through the gap between rows. `window.fitFlow` sizes the stage content to the frame (flows up to 1.3x).
- Arrow labels sit in the gap on at most two lines (`_label_lines`); the gap is sized from the longest line; layout QA allows no overlap between a label and a card. The latest action's targets glow, untouched objects dim to 62%, cleared objects are never lit.
- Frames are captured with software rasterising (`CAPTURE_ARGS = ["--disable-gpu"]`) and stage CSS transitions are off: with scaled cards the GPU path made one shadow pixel differ by one level between browser processes (2/14 runs vs 0/38).
- Correction to earlier notes: the two edits interrupted on 2026-09-29 (wider arrow gap, cleared boxes not counted as active) were in the file all along and part of the checkpoint commit.
- 572 unit tests pass. Regression: all seven cases pass, zero compact fallbacks; `legacy_cards`, Manim, stills and chart identical; `tool_flow`, `structured_args` changed as intended, `binary_search` only in its fade-in; two runs of the new code match at SSIM 1.0. Baseline NOT updated yet: review material is in `out/video_regression/phase2_review/`. Next is Phase 3 (lesson step and prompts, live).
- 2026-10-10: the owner approved the Phase 2 look; the regression baseline was updated for `tool_flow`, `structured_args` and `binary_search`. The owner also asked whether videos are limited to boxes and arrows and named 3Blue1Brown as the bar: concept visuals (graphs, transforming equations, geometry) are not built and are not in Phases 3 or 4 of the hardening plan.
- 2026-10-10: the owner set the TARGET STYLE with seven frames of a "System Design for Beginners" explainer (kept locally in `out/reference/system-design-style-2026-10-10/`, not in git): one map for the whole lesson built piece by piece, icon pieces with one or two words, a simple palette on black, a small ball that moves to each step as it is spoken, panels for related pieces. The hardening plan was rewritten from Phase 3 on: Phase 3 = map pieces in the renderer (no model calls, proven on a hand-written `system_design_map` fixture), Phase 4 = the lesson step plans one map (live), Phase 5 = acceptance and merge. Mathematics visuals moved to the later list.

### 2026-10-10 — Hardening plan Phase 3: map board and code-and-picture board (no model calls); owner review pending
- Scenes are now thought of as a fixed set of board types, built in an order the owner approved: map, code and picture, ideas beside the map (with a ring), compare. The first two are done.
- Map board (`system_map` fixture, our own ride-request example): toned icon pieces, panels holding member pieces, load bar, dashed placeholder, takeaway caption, resting ball, self-drawing arrows, one layout shared by two scenes (`layout_ids`). Arrows between two pieces of one panel are straight. A piece with several arrows out sends a stepped arrow from its top or bottom instead of through the shared gap, where it crossed another arrow's label.
- Code-and-picture board (`code_and_picture` fixture, binary search with our own code): a code object beside other objects in a non-flow scene is pinned left (`.semantic-split`); `active_lines` (1-based, in `set_state`) lights lines and dims the rest; a moved highlight counts as a visible change and its text as visible to the validator.
- 581 unit tests pass (`tests/test_boards.py` is new). Regression: all nine cases pass with zero compact fallbacks; `legacy_cards` and Manim identical; the other browser cases differ from the Phase 2 baseline because of the black palette. Baseline NOT updated: videos wait for the owner in `out/video_regression/phase3_review/`.
- Open in Phase 3: ideas-beside-the-map board with a ring, compare board, a heading that changes colour, card with a small figure, and three more hand-written test boards (problem-and-fix, code-into-system, recap).
- 2026-10-10, after the owner watched both videos: the ball is now a `trace` action (a connect only draws the arrow; the diagram is built first, then the flow is traced; `count` gives a stream, `tone` a colour); motion is eased and brisk instead of linear over the whole narration window; code on the code-and-picture board is 30px; nearly level arrows are drawn level and a panel leaves room for arrows between its pieces. The owner asked for formulas and graphs through Manim (added to the board list) and for a standing no-patchwork rule (now in `AGENTS.md`). 583 tests pass. Baseline still not accepted.

### 2026-10-10 — Hardening plan Phase 4, first part: a system lesson is planned in one model call
- The recipe decides the board (`board` in `prompts/product_video_recipes.json`): `architecture_explainer`, `workflow_explainer` and `before_after` are taught on one map; the rest keep the model-written visual step. The model no longer chooses, and each board has its own lesson prompt (`prompts/lesson-plan-map.md`, `prompts/lesson-plan-v2.md`).
- A map lesson is the map (icon pieces, panels, meters, arrows) plus, per beat, a sentence and one move from seven: introduce, send, trouble, fix, measure, point, remove. `planner/lesson_map.py` fills in ids, claims, proof kinds and anchors, and compiles every scene's objects, actions, timing and evidence. The visual step makes no model call for these lessons. The compiled scenes go through the same validator, and a failure is sent back to the one lesson call.
- Code handles what models repeatedly got wrong instead of rejecting it: a second (reply) arrow between two pieces is folded into the first; a path that skips a piece is routed along the arrows; the ball travels an arrow in either direction; a fix heals every red piece; trouble on something already red becomes a pointing beat; an opening scene may only introduce pieces.
- Validator: a relationship claim now needs the beat to show the arrow (connect, trace, or an end revealed), not merely an arrow that exists; a piece may only be recoloured red or back to its own colour. Layout check: two arrow labels on one spot is a defect; a stepped arrow turns just outside its source's column and carries its label on its last run.
- Planning calls ask for JSON mode and for reasoning off: `deepseek-v4.1-flash` otherwise spent all 4,096 output tokens thinking and returned nothing, at four times the cost. A cut-off blank answer is no longer retried blindly. The narration pace is 2.8 words per second, measured on two rendered lessons.
- Live results (system topic and agent-harness topic, three runs each, final code): `deepseek/deepseek-v4.1-flash` planned 6 of 6, average 1.7 calls and $0.0013 per lesson; `z-ai/glm-4.7-flash` planned 2 of 6 (it writes about 10% over the length limit). Earlier the same day, with the model also writing each scene's actions: `gpt-4o-mini` 0 of 4, `gpt-4o` 1 of 4 at about $0.07 per plan. Spend for the day about $1.00.
- Two AI-planned videos rendered for review (local only): `out/phase4_review/food_delivery_deepseek_v41_flash/` and `out/phase4_review/agent_harness_deepseek_v41_flash/`. The agent-harness topic is the one that failed on 2026-09-29.
- An outside audit (Codex) of `docs/learning-video-system-flow.md` found the tree half-changed and two lenient checks; both are fixed and the document was corrected. `python -m scripts.prompt_doc` regenerates `docs/learning-video-prompts.md` from the prompt files.
- 616 unit tests pass. Open: `.env` still names `gpt-4o-mini` (the owner's file); lessons that are not on a map (algorithm, funnel, metric) still use the model-written visual step, which failed on every model tried; nothing checks that a sentence matches its move; the menu has seven moves.

### 2026-10-10 — Teaching plan written; Phase A (the teaching brief) built, live gate still open
- The owner found the one-call videos read as one fixed template, and an outside review agreed: they show a system and do not teach. Cause: the map prompt dictated the plot (introduce, follow, break, fix) and carried one worked example that every model copied. The new plan is `docs/learning-video-teaching-plan-2026-10-10.md`: topic, then a teaching brief the teacher approves, then the video. Phases: A brief, B playbooks, C algorithm playbook, D teaching moves, E teacher approval, F syllabus, G acceptance and merge.
- Phase A, in the code: a lesson on a map now starts with a brief (`LessonBrief`: learner, what they will be able to do, their question, a concrete problem, the naive attempt, the turning point, a check question and answer), written in the same model call as the lesson. `prompts/lesson-plan-map.md` was rewritten around it: no dictated plot, no worked example, principles in their place. `craft_problems` checks craft and not shape (a brief exists, the first scene asks a question, no beat brings on more than three new pieces, every piece and every meter is used). The battery reports each lesson's plot and how alike the plots are.
- The requested length is now also given to the model as a number of beats and scenes; the fixed "three to five scenes of three or four beats" in the prompt had made a 60-second lesson come out at 220 to 290 words. A scene may consist only of pointing (an opening, a recap); a lesson where fewer than a third of the beats show something travelling or changing is refused. The brief supplies the objective and audience the model leaves out. Each raw lesson answer is saved beside the plan.
- Map layout, three rules found from an AI-drawn backpropagation map that failed the layout check: a piece that only feeds later pieces sits in the column before the first of them; an arrow between pieces with other columns between them runs along a lane outside the row; a stepped arrow carries its label beside its upright stroke. The layout check now also fails an arrow that crosses a piece it does not join, and holds icon pieces to the same no-overlap rule as cards. Nine AI-planned maps from the day pass it.
- Live, on `deepseek/deepseek-v4.1-flash`: the first two runs planned 1 of 6 each (causes were the prompt omitting a required field, a rule that fought the new prompt, and length), the third planned 2 of 3 before the owner's new key ran out of credit (OpenRouter 402) with three runs unstarted. The lessons that planned read as teaching: a named person's failed order and why switching network did not fix it; a network that calls an apple an orange. Two are rendered for review in `out/phase4_review/brief_food_delivery/` and `out/phase4_review/brief_backpropagation/`.
- Cleanup: `BeatMove` and its field were defined twice in `core/schemas/lesson_plan.py` since commit `716db18` (an interrupted patch applied twice); the duplicate is removed.
- 626 unit tests pass; the two Manim tests could not run because Docker Desktop was off. Not committed for that reason. Open: the Phase A gate (5 of 6 planned, and the owner confirming the videos no longer share a plot) needs credit on the key.
- 2026-10-11, after the owner said the brief-led videos looked the same as before in still frames (true: Phase A changed the narration, not the picture): the question is now on screen. Two new moves, `ask` and `answer`, show a line of text under the map: a question in large white type with a yellow mark, an answer with a tick. An `ask` with no text shows the brief's question; the craft check for the opening is now "the first scene has an ask move", which needs no matching of words. The check question and its answer are appended after the model's last beat by code, from the brief, and the picture holds for 1.6 s between them (`pause_after` on a visual beat; the beat's audio is padded so sound and picture stay the same length). A scene has at most one question and one answer, and one that ends on an answer shows no takeaway. A line of text never dims. Piece ids the model writes loosely (`order-service`) are tidied by code wherever they are used.
- New fixture `taught_map` (our own example: why one crashed server takes a site down): a hand-written lesson in the model's own format, compiled by `plan_map_scenes`, so the regression set now renders the compiled path, questions and pause included; a test fails if the stored plan differs from what the compiler writes. With voice: `out/phase4_review/taught_map_with_question/`.
- 642 unit tests pass, Manim included. The live check of this (six lessons, one request at a time) was cut short when the machine slept with the run in progress; one lesson had been attempted. (It was then reported as a network outage. That was wrong: the `curl` in Git Bash on this machine fails on some hosts, OpenRouter and GitHub among them, with its own error 43, while Python and git connect normally. Check reachability with Python or git, not with that curl.)

### 2026-10-11 — Teaching plan Phases B and C: playbooks, and the algorithm playbook (code beside data); live check still owed
- Playbooks are now a registry (`planner/playbooks.py`): each is a lesson prompt, a menu of moves, a compiler and craft checks. The recipe's `board` names the playbook: `map` (systems), `trace` (algorithms, new), anything else keeps the model-written visual step. The planners go through the registry; what compilers share (the lines of text, the brief's share of a lesson, timing, the record of a beat) is in `planner/lesson_shared.py`.
- The trace playbook (`planner/lesson_trace.py`, prompt `prompts/lesson-plan-trace.md`): the model writes the brief, the code (at most 14 lines) and the data (arrays, a table that starts empty, pointers, a fixed value, counters), and one move per beat: show, run, look, compare, discard, fill, count, clear, plus ask and answer. Any move can light lines of code. Code does the rest, and in particular the parts a model gets wrong: a compare is decided by the values on screen; a filled cell is worked out by code from the cells it names (`sum`, `min`, `max`, plus a constant) and the working is shown; a counter tied to a pointer counts that pointer's checks by itself; each beat's anchors are read off the state its move produced.
- Renderer: an array can be a table (empty cells, the cells a value is read from, the cell just written). A trace scene reserves places only for what it shows, so data does not sit beside an empty hole before the code is introduced.
- The fill step numbers every beat even when its move is wrong, so a move from the wrong menu is reported as that and not as a missing id.
- Fixtures `taught_search` (binary search: six checks one by one, then two) and `taught_stairs` (climbing stairs: a table filled from the two cells before) are hand-written lessons in the model's format, compiled by the playbook; tests fail if a stored plan differs from what the compiler writes. `algorithm_explainer` now uses the trace playbook, with more keywords (dynamic programming, recursion, memoization).
- First live runs, `deepseek/deepseek-v4.1-flash`, one request at a time. Before any fix the trace prompt planned 0 of 2 (the prompt showed `lines` in no move format, so the code was never lit; six data items was too few for two attempts' pointers and counters; a 60-second lesson got eight beats, not enough to fill a table). After the fixes (lines in every move format; room by kind: two arrays, four pointers, two values, three counters; a run of fills in one beat; thirteen words a beat for traces) it planned 2 of 2: binary search in 2 calls ($0.0018), climbing stairs in 3 ($0.0034). The map prompt with the ask move planned 2 of 2 in the same run (food delivery first call, backpropagation in 2).
- What reading those lessons showed, and what was done: the model added `count` moves on a counter that already counts a pointer's checks, which would have shown 7 for six checks, so on such a counter a count move now only points at the total; it gave two counters the same label, so labels of data items must differ. Not fixed: with no way to draw a recursion tree, the model acted out the naive attempt at climbing stairs with comparisons that mean nothing, against the prompt's instruction; and a sentence can still say "three checks" over a counter that reads two.
- For review (local): `out/phase4_review/ai_binary_search/` is the AI-written binary-search lesson; `dsa_binary_search/` and `dsa_climbing_stairs/` are the hand-written fixtures with voice.
- Not done: topic routing is still keyword matching; the recursion tree, compare board and zoom of Phase D; a lesson cannot yet switch playbooks between scenes; more live runs before any pass rate is quoted.
- 2026-10-11, the recursion tree (teaching plan Phase D item 2), built because the AI-written climbing-stairs lesson had no honest way to show the naive attempt: a trace can hold a `tree`, described by three numbers (`start`, `steps`, `stop`); `core/call_tree.py` works out every call from them, so the picture cannot show a call the recursion would not make. Moves: `grow` reveals it level by level, `spot` turns every call for one value red and writes "3 is worked out 2 times" under the tree (refused for a value called once), `remove` takes any item off the screen. A counter with `counts` naming the tree always reads the calls shown. Fixture `taught_recursion`: fifteen calls for five stairs, the repeats picked out, then the tree removed and a six-box table filled.
- Found on the way: a `remove` move had never been able to pass the validator, on the map either, because an object hidden by a beat's only step is not counted as shown in that beat. No lesson had used it. It now lights the item once and then hides it, and both playbooks have a test of the path that succeeds.
- 2026-10-11, a lesson that planned and was wrong: with the tree in the prompt, three live DSA lessons planned out of three, and the climbing-stairs one taught a wrong answer. The model started the bottom stair at 0, so the table on screen ended at 5 while its narration said eight ways. The picture was computed honestly from what the model gave; nothing tied the sentence to it. Now a fill that works a value out carries `expect`, the number the lesson says it comes to (a list for a run), and a count on a self-counting counter carries the total it expects; code compares them with what the table and the counter really hold and sends a mismatch back with the working ("you expect cell 2 to hold 2, but the table gives Ways[2] = 1 + 0 = 1"). A table that is filled in must start empty, and one declared a cell too short is sized to the cells it fills.
- Live after that check, same model: climbing stairs twice and Fibonacci once planned 1 of 3, and the one that planned is right (1, 1, 2, 3, 5, 8). The two rejected had real faults (a fill from an empty cell after a table one cell short, since made a fix in code; a counter expected to read 15 that was never tied to the tree). So the pass rate fell and nothing wrong got through. Rendered for review: `out/phase4_review/ai_climbing_stairs/` (AI-written, correct) and `dsa_recursion_tree/` (hand-written).
- 697 unit tests pass. Still open on a trace: a spoken number that no move states (a sentence can still say "three checks" over a compare beat); whether the moves follow the code shown beside them.
- 2026-10-11, after the stricter checks cut the pass rate to 1 of 6: reading the rejected answers showed that several were correct lessons refused by faults in the compiler, not by the model. Fixed: an item taken off screen and brought back in a later scene lost its state, because the replay forgets what is off screen at a scene's end (the compiler now keeps each item's state across scenes and restores it before the item is seen again); a `clear` with nothing to wipe cited the pointers it had just hidden as evidence; `lines` written beside a move is put into it; an item no move uses is no longer a fault, since it is never drawn. Added because lessons asked for it: a counter can count the cells filled in a table; a tree and an array may not share the screen (the lesson is told to remove the tree first); a wrong total now says why (the tree has 15 calls and 13 are shown; or the counter is tied to nothing). A lesson with a playbook gets five tries, each with its reason. `scratchpad/replay_attempts.py` replays saved answers through the current checks with no API call; the saved answers are in `out/domains/*/lesson_attempts/`.
- Final live numbers of the day on `deepseek/deepseek-v4.1-flash`, final code, five tries: binary search planned in 2 calls, Fibonacci in 5, climbing stairs failed after 5 (the model kept working a cell out from an empty one, then got a value wrong). A fourth run was stopped by OpenRouter error 402: the owner's key has no credit left ($0.13 used). So for algorithm lessons: correct when they plan, about two in three planned on this small sample, and the hardest case for this model is keeping a table's starting cells straight. 705 unit tests pass.

### 2026-10-11 — The table rule: a table states its rule once and code fills every cell (not yet run live)

- Commit `0d024b1` (pushed) holds the recursion tree, the `expect` check, state kept across scenes and five tries. Regression on it: 13 of 13 cases pass, zero compact fallbacks, Manim identical.
- Built after it, to remove the last thing the cheap model kept getting wrong on algorithm lessons (which cells of a table start filled, with what, and in which order the rest are worked out). An empty table now carries `"rule": {"start", "back", "op", "plus"}`; `table_by_rule` in `planner/lesson_trace.py` works the whole table out; a fill is `{"do":"fill","array","cell","expect"}` (or `cells` with one `expect` each) and fills every empty cell before the one it names, in order. A cell already full is pointed at again, not rewritten or counted twice. A step that would read before cell 0 is skipped (coin change). A table with no rule still takes `{"cell","value"}`, unchecked.
- Removed, not kept beside it: `from_cells`, `back`, `op`, `plus` on a move. Saved lessons had to be re-saved without those fields (`taught_search`, `taught_stairs`, `taught_recursion`); their compiled visual plans are byte for byte the same. New fixture `taught_coins` (fewest coins of 1, 3, 4 for 6; biggest-first gives three, the table gives two).
- A rejected number now quotes the start values and the whole table the rule gives, counted from cell 0, so an off-by-one in the start is visible in one message.
- 715 unit tests pass. Regression: 14 of 14 cases pass, zero compact fallbacks, Manim identical, and every earlier case has the same length and the same frame scores as the run before the change. The coin lesson is rendered with voice in `out/phase4_review/dsa_coin_change/`. Not known: whether this raises the live pass rate. The owner's OpenRouter key has no credit (error 402), so nothing has been run live on it. Not covered by a rule: a per-cell addend (cost of each stair), a second array read alongside (house robber), two-dimensional tables (LCS, knapsack).
- First live run of the table rule, 2026-10-11, `deepseek/deepseek-v4.1-flash`, new key, five tries allowed, one run per topic: climbing stairs planned in 4 calls, Fibonacci in 4, coin change in 2, binary search in 2. Four of four, 12 calls, $0.012 in all. Every table on screen is right. The stairs lesson, which failed five tries before the rule, was sent back once for a table number, with the whole table quoted, and fixed it on the next try. Four runs are not a pass rate. Answers are saved in `out/domains/live6_*`, videos in `out/phase4_review/live6_*`.
- What those four lessons still get wrong, none of it caught by a check: (1) binary search used one pointer and one counter for both attempts, so the counter reads 8 on screen while the sentence says "two checks, not six"; (2) coin change acted out biggest-first with compare moves, which draw a cross on each coin, and said "then it picks three", which is false (it is 4, 1, 1); (3) climbing stairs says "cell 1" to "cell 5" while the screen numbers the cells 0 to 4; (4) Fibonacci filled the whole table in one beat and said "five additions", a number no move states. Tries were also lost to bookkeeping: an id written in camelCase, a table used but never declared, a total stated before the tree was fully grown.

### 2026-10-12 — Independent review of the four AI-written algorithm lessons: none is fit to publish

- The owner asked for an unbiased review of concept, storyline, flow and whether a new learner would understand, not only of frames. Four reviewers, one per lesson (`live6_stairs`, `live6_coins`, `live6_fib`, `live6_search`), each given the prompt, the accepted plan, the answers sent back, a storyboard and two frames per beat, and not given the builders' list of faults. Full reports: `out/phase4_review/independent_review_2026-10-12.md` (local, not in git). The reviewers are AI, saw no motion and heard no audio.
- Verdict, all four: a new learner would understand partly, and a teacher would not publish it. Overall 3.5 to 4 out of 10. Every number code works out is right; the teaching is not.
- Found in all four: (1) the voice and the screen disagree somewhere; (2) the repair loop made the lesson worse, because a retry passes when the model changes the checked number or adds a step and leaves the sentence (search: expect 2 became 8; coins: a false "then it picks three" added so a counter reads 3; stairs: the table's start shifted so values match and cell numbers do not; Fibonacci: a good sentence replaced by a stage direction); (3) the idea is shown and never explained, and the brief's turning point is usually not spoken; (4) about 200 words a minute with no gaps, the core in 3 to 10 seconds, and the model writes fewer words than allowed; (5) leftovers of the first attempt stay on screen, and the layout resizes between scenes; (6) the code lit is not the code being run; (7) sentences read as stage directions; (8) the check question asks for recall, the pause is about two seconds, and the last scene's takeaway is dropped by `closes_on_a_takeaway`; (9) terms and the topic's own name are never introduced.
- What they said to keep: code-computed numbers, the checks that caught real errors, the lesson skeleton, the fill picture with its working line, the fade when half a list is ruled out, the clean look.
- First round of repairs, done in code with no live run: a counter belongs to one attempt; a `take` move (a cell's number taken out of a value, checked); `first: 1` numbers an array's cells from 1; item ids tidied; an ask beat speaks the question it shows; a run of fills only after the rule is seen once; a breath after every sentence (0.4 s, 0.9 s as a scene closes, 3 s to think); `min_seconds` on a beat so steps get the time they need; a fill shows its working before the number; leftovers of a finished attempt are retired (at `clear`, and at a table's first fill unless used later); a `count` shows every counted counter; a closing scene shows its takeaway before the check question; an item that has left for good gives up its room (non-flow scenes); algorithm lessons are not asked for under 90 seconds. Fixtures `taught_search`, `taught_stairs`, `taught_recursion`, `taught_coins`, `taught_map` regenerated. 733 unit tests pass. Regression: 14 of 14 pass, zero compact fallbacks, Manim identical, and the seven cases that are not compiled lessons have the same length and frame scores as before; the compiled lessons are 7 to 12 seconds longer from the pauses.
- Round two (same day): an independent reviewer of the prompt scored it 5 of 10 (full findings in this session's notes; the ranked list is reflected in DECISIONS.md). Built from it: a `turn` move (the brief's turning point shown and spoken; a trace lesson without one is sent back; the beat after it retires the first attempt and its tree); `why` on a beat; beats sized at 15 words and the recipe outline no longer sent for trace lessons; table lessons teach the rule first, their first attempt a hand list of cases as short strings; the answer cell in a fill of its own (craft); a compare writes "17 < 30" under the data; a lit line goes out when its step is over; think pause 4 s; repairs carry every fault of the moves at once, named by beat, plus `trace_facts` (tables cell by cell, tree calls), with only the latest answer resent and a stronger instruction when a fault repeats; bookkeeping done for the model (a beat written flat, `index` on a fill, a count naming the counted item). 738 unit tests pass; regression 14 of 14, Manim identical (run before the last planner-only edits, which do not touch rendering).
- Live after round two, `deepseek/deepseek-v4.1-flash`, 90-second target: climbing stairs failed three runs of five tries while faults in the new prompt were found and fixed (beats written flat; labels; a `run` with no lines; no move for "list by hand"), then planned in 5 calls; binary search 2 calls; binary search for an absent number (new topic) 4; Fibonacci 3; coin change failed (rule written with one step back, not the coin values). Tribonacci with a table (new) was routed to the map playbook by the keyword router. $0.075 in all. Answers in `out/domains/live7_*`, videos in `out/phase4_review/live7_*`.
- Open after round two: nothing checks that a sentence agrees with the picture; the router is keyword matching; coin-change style rules; a two-call plan (trace first, then sentences written with the computed numbers in hand) is the candidate next step for numbers.
- Outside review and steps after it (2026-10-12): two GPT reviews of our issue list agreed the root cause is one call carrying story, sentences and moves at once, and that the fix is a story contract first, narration built from events, and visual moves that can show an insight. Step 1, a story-first A/B, was cut short by OpenRouter error 402 (account out of credit after about $0.12): the contract variant (GPT-4.1 writes the contract, the cheap model the lesson) planned stairs in 6 calls and failed binary search; the stronger-model single call never ran. The contract's "what must be seen" was only "the table fills", because the video could not group items. Step 2, first part, built: a `group` move colours cells that belong together and names them under the array with their count (stairs: "end in a 1-step: 5", "end in a 2-step: 3"). 739 unit tests pass; regression 14 of 14, Manim identical. Not built yet: the tree-and-table hand-over; numbers in sentences from code.
- Step 3 built (2026-10-12): a sentence names what it means as `{id}` (a counter, a value, the cell under a pointer, the calls shown of a tree) or `{id[n]}` (a table cell), and the compiler writes in what the picture holds once the beat's move is done; a count beat on a self-counting counter must say its total that way; an unknown item or a cell still empty is refused; ids tidied in sentences too. Spoken sentences only, not takeaways. 740 unit tests pass; regression 14 of 14, Manim identical. Not run live (no credit). Still open: code-line highlights are still line numbers the model picks.

### 2026-10-15 — A staged planner for table lessons (pilot), and Jev routing measured

- Why: on 2026-10-12 the single-call trace lesson planned 1 of 4 on the cheap model and GPT-4.1 did no better (1 of 2, ten times the cost): one call was designing the teaching, declaring the data, picking every move and obeying about forty rules. Both outside reviews said split it.
- `planner/lesson_recurrence.py` (pilot, nothing routes to it yet): a model returns the brief and a small concept spec (the table's rule, the cases of the instance and how they end); code checks it against itself (last cell = answer = number of cases; each group of cases as large as the earlier cell it stands for; which cases are in a group is worked out by code from how they end); code builds every step; a model writes one sentence per step with the numbers in hand. Prompts `recurrence-concept.md`, `recurrence-narration.md`.
- Live, DeepSeek V4.1 Flash: 2 to 4 calls, about $0.001 a lesson; 11 of 13 runs planned across six table topics. Independent review of the rendered videos: 4.5 to 5 out of 10 (the single-call videos were 3.5 to 5): numbers right, the reason now said and grouped on screen, but still "said, not shown" (no picture of removing the last step), groups not linked to their table cells, only one cell worked out, the check question sometimes a lookup.
- Also: a `reveal` move and `shown_at_first` hold cases back until after the question; group colours stay through the table fill; a hand-listed case may be nine characters.
- Jev topic routing (`planner/jev_router.py`, written in another session on 2026-10-12, now enabled in `.env`): on 15 fixed topics keyword routing was right 6 times, Jev 13 when its answer is taken; its confidence runs low on right answers, so the cut-off is 0.30. Calls take about 0.3 s; it falls back to keywords on any failure.
- Jev as a sentence judge, measured offline on four lessons with known-bad copies: "says only what the step shows" at a 0.4 cut-off catches 65% of bad sentences and flags 6% of good ones; "gives the reason" at 0.3 catches 83% and flags 15%. Being built in a worktree as a soft gate (one rewrite, never blocks).

### 2026-10-15 — Staged table lessons: the reason shown, the cost shown, cases listed by code; handoff written

- Commits `649fb5f`, `ee36d7f`, `c963242`, `23d1024`, `6644206`, `4a89de8` (see `docs/handoff-2026-10-15.md` for the list). The staged planner now: strikes the last step off each grouped case and colours the table cells the answer reads in their group's colours; shows the cost of listing on a bigger case worked out by code ("Cases for 20 stairs: 10946" against 21 boxes); refuses a split whose ending does not leave exactly the smaller problem's cases; and lists every case itself from the model's description of the parts, the join, the total and any forbidden pattern.
- Live after it: all five table topics planned (binary strings, domino tilings, stairs, steps of 1 to 3, coins), 4 to 6 calls, under half a cent each. Reviews of the staged videos: 5 to 6 out of 10, best 6 (stairs).
- Next step and the rules that bite: `docs/handoff-2026-10-15.md`.
