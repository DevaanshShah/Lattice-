# AGENT_TICKETS.md — Lattice v1

GitHub-ready tickets for **Lattice** (NL prompt → narrated multi-scene Manim explainer). Each ticket is self-contained: paste the body into a GitHub issue, apply the labels, link the milestone. Ordered by the build sequence in `MILESTONES.md` (**M0 → M8**, PRD phases 0 → 6).

**How to use:** build one ticket at a time, satisfy only its acceptance criteria, run its Verify block, then the milestone Test & Ship Gate. Do not start a ticket whose dependencies are unchecked.

**Two invariants gate every ticket:**
1. **Verification two-layered, never conflated** — free compile check gates every paid vision call; no scene surfaced without passing both (or a logged best-of-N fallback); every loop respects a hard cap and never hangs.
2. **Idempotent by content hash; structure approved before spend** — same `(scene spec + style spec + model)` ⇒ reuse cached render; outline approved before any scene renders.

**Label legend:** `milestone:M*` · `phase:*` · `area:*` (generation / verification / narration / render / composition / editing / web / cli / eval / infra) · `priority:p0|p1|p2` · `type:feat|infra|test|docs`

---

## Milestone M0 — Environment Spike & Sandbox  ·  Phase 0

### T-0 — Reproducible sandboxed Manim render environment + LLM client stub
**Labels:** `milestone:M0` `phase:0` `area:infra` `priority:p0` `type:infra`
**FRs:** substrate for FR-2, FR-22, FR-26 · seed of FR-6, FR-23 · resolves **Q2**, **Q5**
**Depends on:** —

**Context.** Every downstream phase assumes "given Manim code, we can render an MP4." The real early risk is the toolchain (Manim CE + LaTeX + FFmpeg), not the AI. Pay this once, in isolation. Code is throwaway.

**Scope / files.** `scripts/setup_env.sh`, `Dockerfile`, a checked-in sample scene `render/sample_scene.py` (shapes + `MathTex`), `scripts/render_sample.py`, `render/sandbox` (no-net, non-root), `core/llm` client stub (swappable `base_url`/`api_key`/`model`, **not yet called**), `core/config` (pinned Manim version), `tests/conftest.py` + markers, decision note `prds/decisions/Q2-Q5.md`.

**Acceptance criteria.**
- [ ] One documented command builds a working env from clean; re-running on a fresh machine/container succeeds with no manual fixes.
- [ ] Sample scene renders to a **playable MP4 with both a shape animation and a `MathTex` expression** (proves LaTeX).
- [ ] Same scene renders at **preview (low-res, fast)** and **final (high-res, slow)** via a documented flag.
- [ ] **One keyframe exports as a PNG.**
- [ ] Model-written code runs in a **container with no network, as non-root.**
- [ ] **Q2** (Manim CE version, pinned in `core/config`) and **Q5** (local vs container) written down with rationale.
- [ ] `tests/` harness exists; `pytest -m unit` green.

**Verify.**
```bash
bash scripts/setup_env.sh
python -m scripts.render_sample --quality preview && python -m scripts.render_sample --quality final
ls out/keyframe.png && ffprobe out/sample_final.mp4
docker run --network=none --user 1000 lattice-render python -c "import socket" ; echo $?
pytest -m unit
```
**Effort:** ~1 week.

---

## Milestone M1 — Scene Spec → Manim Code  ·  Phase 1

### T-1 — NL prompt → scene spec (locked JSON IR)
**Labels:** `milestone:M1` `phase:1` `area:generation` `priority:p0` `type:feat`
**FRs:** FR-1 · **Depends on:** T-0

**Context.** Generate the structured intermediate representation *before* any code — objects, layout intent, a placeholder narration line, animation beats. Lock the schema here; everything downstream (regeneration, style spec, persistence) keys off it.

**Scope / files.** `core/schemas/scene_spec.py` (locked), `generation/scene_spec.py`, `prompts/scene-spec.md`.

**Acceptance criteria.**
- [ ] Same prompt → **valid scene spec conforming to the locked schema.**
- [ ] Invalid model output is **rejected and regenerated, not passed downstream.**
- [ ] The schema is **documented** and version-stamped.

**Verify.**
```bash
python -m lattice.generation.scene_spec "explain a hash map collision" | python -m json.tool
python -c "from core.schemas import SceneSpec; SceneSpec.model_validate_json(open('out/spec.json').read()); print('schema OK')"
pytest -m unit
```
**Effort:** ~2 days.

### T-2 — Scene spec → Manim code + API guardrails
**Labels:** `milestone:M1` `phase:1` `area:generation` `priority:p0` `type:feat`
**FRs:** FR-2, FR-8 · **Depends on:** T-1

**Context.** Compile the scene spec to Manim CE code targeting the pinned version, constrained to CE conventions (no CE/GL mixing, no deprecated calls).

**Scope / files.** `generation/codegen.py`, `generation/guardrails.py`, `prompts/codegen.md`, `prompts/manim-conventions.md`.

**Acceptance criteria.**
- [ ] Codegen targets the **pinned Manim version** for a given scene spec.
- [ ] Generated code **never imports/uses the GL/OpenGL path.**
- [ ] Deprecated-API usage is **caught (lint or prompt-level) before render.**

**Verify.**
```bash
python -m lattice.generation.codegen out/spec.json > out/scene.py
grep -E "opengl|OpenGL|ManimGL|\.gl\b" out/scene.py && echo "GUARDRAIL FAIL" || echo "guardrail OK"
pytest -m unit
```
**Effort:** ~2 days.

---

## Milestone M2 — Verification Loops (the moat)  ·  Phase 1

### T-3 — Local render worker (MP4 + keyframe PNGs)
**Labels:** `milestone:M2` `phase:1` `area:render` `priority:p0` `type:feat`
**FRs:** FR-22 · **Depends on:** T-0, T-2

**Context.** A single local process that renders a scene to MP4 + keyframe PNG(s), callable as a function the verification loops invoke repeatedly within one run.

**Scope / files.** `render/worker.py`.

**Acceptance criteria.**
- [ ] Callable function: Manim code path → MP4 + one or more keyframe PNGs.
- [ ] Invokable repeatedly in a single run without leaking state.
- [ ] Honors preview/final quality from `core/config`.

**Verify.**
```bash
python -m lattice.render.worker out/scene.py    # writes out/scene.mp4 + frame_*.png
pytest -m unit
```
**Effort:** ~2 days.

### T-4 — Compile-check + auto-repair loop
**Labels:** `milestone:M2` `phase:1` `area:verification` `priority:p0` `type:feat`
**FRs:** FR-5, FR-7 · **Depends on:** T-3

**Context.** The free, deterministic correctness signal. On render crash, feed the **trimmed** traceback back and retry up to N times — don't resend everything (cost control).

**Scope / files.** `verification/compile_repair.py`, `verification/caps.py`.

**Acceptance criteria.**
- [ ] A deliberately-broken generation (e.g. undefined mobject) is **recovered automatically within the retry cap.**
- [ ] Each attempt is **logged**; the traceback fed back is **trimmed.**
- [ ] On non-recovery within caps, returns the **best attempt + a useful error** — never spins.

**Verify.**
```bash
python -m lattice.verification.compile_repair out/broken_scene.py   # recovers, logs attempts
pytest -m unit    # cap + graceful-failure behaviour
```
**Effort:** ~3 days.

### T-5 — Vision-critic loop (multi-frame, structured) + best-of-N
**Labels:** `milestone:M2` `phase:1` `area:verification` `priority:p0` `type:feat`
**FRs:** FR-6, FR-7 · **Depends on:** T-4

**Context.** The load-bearing feature — gives the blind generator eyes. Sample **multiple** rendered frames, have a (cheaper, swappable) vision model check overlap / off-screen / intent, feed structured fixes back. On non-convergence, fall back to best-of-N.

**Scope / files.** `verification/vision_critic.py`, `verification/best_of_n.py`, `prompts/vision-critic.md`.

**Acceptance criteria.**
- [ ] A scene that **compiles but is visually broken** (stacked labels / off-frame object) is **detected and corrected without a human flagging it.**
- [ ] Critic output is **structured** (issue type + location + suggested fix), never free prose.
- [ ] Critic samples **multiple frames**, not one.
- [ ] On non-convergence, **best-of-N** generates N candidates, renders, keeps the highest-scoring.
- [ ] **Invariant:** the free compile check runs **before** any vision call; compile-score and vision-score are tracked separately and never conflated. Hard caps respected; never hangs.

**Verify.**
```bash
python -m lattice.verification.vision_critic out/scene.py --json     # typed, multi-frame
python -m lattice.verification.run --best-of 3 "two labels that overlap"
LATTICE_TEST_LLM=1 pytest -m llm    # optional: real critic on a known-broken fixture
pytest -m unit
```
**Effort:** ~1 week.

---

## Milestone M3 — CLI + Eval Harness + Cache  ·  Phase 1

### T-6 — CLI core: `generate-scene`
**Labels:** `milestone:M3` `phase:1` `area:cli` `priority:p0` `type:feat`
**FRs:** FR-27 · **Depends on:** T-5

**Context.** The engine, driven from one command. Full pipeline: spec → code → render → repair → critic → final MP4, writes the output path.

**Scope / files.** `cli/__main__.py` (`generate-scene`).

**Acceptance criteria.**
- [ ] `generate-scene "<prompt>"` runs the **full pipeline in one command** and writes the final MP4 path.
- [ ] Exit code reflects success/graceful-failure.

**Verify.**
```bash
lattice generate-scene "explain a hash map collision"   # → writes out/<hash>.mp4
pytest -m unit
```
**Effort:** ~1 day.

### T-7 — Eval / regression harness
**Labels:** `milestone:M3` `phase:1` `area:eval` `priority:p0` `type:test`
**FRs:** supports FR-1/FR-2/FR-6 · **Depends on:** T-6

**Context.** A small fixed prompt battery with expected outcomes, re-run on every prompt/model change. Without it you tune blind.

**Scope / files.** `eval/battery.py` (≥10 varied prompts), `eval/score.py`, `scripts/run_eval.py`.

**Acceptance criteria.**
- [ ] ≥10 varied prompts each produce an MP4 that compiles, has **no critic-flagged issues**, and visibly matches — **zero manual intervention.**
- [ ] Harness prints a **score table** (compile success + critic flag count) and a regression verdict vs the last run.
- [ ] A change can be shown to **help** (fewer flagged issues), not merely run.

**Verify.**
```bash
python -m scripts.run_eval     # score table, no regressions
pytest -m unit
```
**Effort:** ~1.5 days.

### T-8 — Content-hash render cache
**Labels:** `milestone:M3` `phase:1` `area:render` `priority:p0` `type:feat`
**FRs:** FR-25 · **Depends on:** T-3

**Context.** Never re-render or re-generate unchanged work. Key = `hash(scene spec + style spec + model)`. TTS audio cached separately (M4).

**Scope / files.** `core/cache.py`, `render/cache.py`.

**Acceptance criteria.**
- [ ] Re-running `generate-scene` with the same prompt/spec/model **reuses the existing render** (no re-render).
- [ ] Any meaningful spec/style change **busts the key**; a no-op reuses it.
- [ ] Cache-key function is **deterministic** (unit-tested).

**Verify.**
```bash
lattice generate-scene "explain a hash map collision"   # miss → render
lattice generate-scene "explain a hash map collision"   # hit → no re-render
python -c "from core.cache import key; assert key(s,st,m)==key(s,st,m); print('stable')"
pytest -m unit
```
**Effort:** ~1 day.

---

## Milestone M4 — Narrated Scene  ·  Phase 2

### T-9 — Narration-first script + `manim-voiceover` sync
**Labels:** `milestone:M4` `phase:2` `area:narration` `priority:p0` `type:feat`
**FRs:** FR-9, FR-11 · **Depends on:** T-6

**Context.** Flip the ordering: write the script first, then generate animation that syncs to it via `with self.voiceover(...)` blocks. Sync is a solved library problem — don't over-engineer.

**Scope / files.** `narration/script.py`, `narration/sync.py`, `prompts/narration.md`, scene-spec gains a real `narration` field.

**Acceptance criteria.**
- [ ] Scene spec carries a **real narration script**; generated code wraps animations in voiceover blocks whose beats correspond to it.
- [ ] **Narration-first is the default** generation path.
- [ ] Animation beats **line up with spoken words with no manual timing**; a voice/engine change **re-syncs automatically.**

**Verify.**
```bash
lattice generate-scene "explain a hash map collision"   # MP4 speaks + synced
pytest -m unit
```
**Effort:** ~3 days.

### T-10 — TTS integration (swappable) + audio cache
**Labels:** `milestone:M4` `phase:2` `area:narration` `priority:p0` `type:feat`
**FRs:** FR-10 · resolves **Q3** · **Depends on:** T-9

**Context.** gTTS free to start; engine swappable to OpenAI/Azure for quality. Keep the seam clean — FR-33 (voice swap) and FR-34 (multi-language) plug in here later.

**Scope / files.** `narration/tts.py` (engine abstraction), audio cache in `core/cache`.

**Acceptance criteria.**
- [ ] Same script renders to audio via the configured engine; switching engines is a **one-line config change**, not a rewrite.
- [ ] Generated audio is **cached** (separate key from renders).
- [ ] **Q3** default engine documented.

**Verify.**
```bash
LATTICE_TTS=gtts  lattice generate-scene "..."
LATTICE_TTS=openai lattice generate-scene "..."   # config-only swap
pytest -m unit
```
**Effort:** ~2 days.

### T-11 — Auto subtitles / captions
**Labels:** `milestone:M4` `phase:2` `area:narration` `priority:p1` `type:feat`
**FRs:** FR-12 · **Depends on:** T-9

**Acceptance criteria.**
- [ ] Pipeline emits a **subtitle track / burned-in captions** matching the spoken narration.
- [ ] Captions update when narration changes.

**Verify.**
```bash
lattice generate-scene "..." && ls out/captions.srt
pytest -m unit
```
**Effort:** ~1 day.

---

## Milestone M5 — Multi-Scene Video + Consistency  ·  Phase 3

### T-12 — Planner (topic → outline → specs) + outline-approval gate
**Labels:** `milestone:M5` `phase:3` `area:generation` `priority:p0` `type:feat`
**FRs:** FR-3 · resolves **Q4**, **Q6** · **Depends on:** T-9

**Context.** Turn a topic into an ordered outline, **let the user edit/reorder/cut before any scene renders**, then expand each item into a full scene spec. The outline is a single point of failure — the approval gate is the guard.

**Scope / files.** `planner/outline.py`, `planner/approval.py`, `planner/expand.py`, `prompts/planner.md`.

**Acceptance criteria.**
- [ ] Topic → **sensible ordered outline within the scene cap (Q4)**, inspectable as an artifact.
- [ ] **Outline-approval gate** shows the list and accepts edit/reorder/cut **before any render.**
- [ ] Each approved item expands into a valid scene spec the M1–M4 pipeline builds.

**Verify.**
```bash
lattice generate-video "how TCP works"    # shows outline for approval before rendering
pytest -m unit
```
**Effort:** ~3 days.

### T-13 — Shared style spec (cross-scene consistency)
**Labels:** `milestone:M5` `phase:3` `area:generation` `priority:p0` `type:feat`
**FRs:** FR-4 · **Depends on:** T-12

**Context.** A compact JSON design system (palette, fonts, object shapes, layout rules) generated once per video and injected into every scene's prompt — what makes 20 independent generations read as one film.

**Scope / files.** `generation/style.py`, `prompts/style-spec.md`, scene cache key includes the style spec.

**Acceptance criteria.**
- [ ] Across all scenes, **colors/fonts/recurring object styles are visibly consistent** (a "packet" matches in scene 2 and scene 6).
- [ ] The style spec is a **single artifact reused by every scene's generation.**

**Verify.**
```bash
lattice generate-video "how TCP works" && open out/<project>/final.mp4   # visual consistency
pytest -m unit
```
**Effort:** ~3 days.

### T-14 — Scene-DAG project model
**Labels:** `milestone:M5` `phase:3` `area:composition` `priority:p0` `type:feat`
**FRs:** FR-13 · **Depends on:** T-12

**Acceptance criteria.**
- [ ] A video is a single structure enumerating its scenes **in order**; individual scenes are **addressable** (needed for FR-16).
- [ ] Room for per-scene version history (filled in M6).

**Verify.** `pytest -m unit`  **Effort:** ~2 days.

### T-15 — Bounded parallel scene rendering
**Labels:** `milestone:M5` `phase:3` `area:composition` `priority:p0` `type:feat`
**FRs:** FR-14 · **Depends on:** T-14, T-3

**Context.** Scenes are independent — render in parallel, but **through a worker pool with a sane concurrency cap** (avoid rate limits + cost spikes).

**Acceptance criteria.**
- [ ] N-scene video renders **meaningfully faster than N sequential renders.**
- [ ] One scene failing (after its caps) **doesn't abort the others.**
- [ ] Concurrency is **bounded** by a configurable cap.

**Verify.** `pytest -m unit`  **Effort:** ~2 days.

### T-16 — FFmpeg stitching / concatenation
**Labels:** `milestone:M5` `phase:3` `area:composition` `priority:p0` `type:feat`
**FRs:** FR-15 · **Depends on:** T-14

**Acceptance criteria.**
- [ ] Final output is a **single MP4 that plays start-to-finish with narration intact across boundaries**, no audible/visual seam glitches.

**Verify.**
```bash
ls out/<project>/final.mp4 && ffprobe out/<project>/final.mp4
pytest -m unit
```
**Effort:** ~1.5 days.

### T-17 — Regenerate a single scene in isolation
**Labels:** `milestone:M5` `phase:3` `area:composition` `priority:p0` `type:feat`
**FRs:** FR-16 · **Depends on:** T-14, T-16, T-8

**Context.** The seam Phase 4's entire editing story builds on. Re-run generation for one scene without touching the others, reuse everything else from cache, re-stitch.

**Acceptance criteria.**
- [ ] Regenerating scene *k* leaves scenes ≠ *k* **byte-for-byte unchanged (or cache-reused)** and produces an updated final video.

**Verify.**
```bash
lattice regenerate-scene <project> 3   # only scene 3 changes
pytest -m unit
```
**Effort:** ~2 days.

---

## Milestone M6 — Editing & Human Control  ·  Phase 4

> **Discipline against N1:** every feature operates on *scenes*, not frames or clips. Isolation is the whole game — each op touches only the affected scene(s) and reuses everything else.

### T-18 — Reorder / add / delete scenes
**Labels:** `milestone:M6` `phase:4` `area:editing` `priority:p0` `type:feat`
**FRs:** FR-17 · **Depends on:** T-17

**Acceptance criteria.**
- [ ] Reorder re-stitches in new order **without re-rendering unchanged scenes.**
- [ ] Insert generates **only** the new scene (inheriting the style spec).
- [ ] Delete removes + re-stitches; the scene DAG stays consistent.

**Verify.** `lattice reorder <project> 7 2 ; pytest -m unit`  **Effort:** ~3 days.

### T-19 — Edit narration text + re-time
**Labels:** `milestone:M6` `phase:4` `area:editing` `priority:p0` `type:feat`
**FRs:** FR-18 · **Depends on:** T-9, T-17

**Acceptance criteria.**
- [ ] Editing scene *k*'s narration **re-runs TTS + sync for that scene only**; final video + captions update; other scenes untouched.

**Verify.** `lattice edit-narration <project> 4 "new script" ; pytest -m unit`  **Effort:** ~2 days.

### T-20 — Per-scene tweak prompts
**Labels:** `milestone:M6` `phase:4` `area:editing` `priority:p1` `type:feat`
**FRs:** FR-19 · **Depends on:** T-17

**Acceptance criteria.**
- [ ] A tweak ("move the cache box left", "slow this down") produces a revised scene that **passes the same verification loops (FR-5/FR-6)** and re-stitches — affecting no other scene.

**Verify.** `lattice tweak <project> 5 "move the cache box left" ; pytest -m unit`  **Effort:** ~2 days.

### T-21 — Project save / load / persistence
**Labels:** `milestone:M6` `phase:4` `area:editing` `priority:p0` `type:feat`
**FRs:** FR-20 · **Depends on:** T-14

**Context.** First phase where state survives between runs. A video = scene DAG + specs + style spec + cached renders. Version the saved-project format so future schema changes don't orphan old projects.

**Acceptance criteria.**
- [ ] A saved project **reopens with all scenes, specs, narration, style spec, and renders intact** — resume exactly where you left off.
- [ ] Saved-project format is **versioned.**

**Verify.** `lattice save <project> && lattice open <project> ; pytest -m unit`  **Effort:** ~2 days.

### T-22 — Per-scene version history + rollback
**Labels:** `milestone:M6` `phase:4` `area:editing` `priority:p1` `type:feat`
**FRs:** FR-21 · **Depends on:** T-21

**Acceptance criteria.**
- [ ] After regen/tweak, the **previous version is recoverable**; selecting it re-stitches using that earlier render.
- [ ] History is **per-scene, not global.**

**Verify.** `lattice rollback <project> 5 ; pytest -m unit`  **Effort:** ~2 days.

---

## Milestone M7 — Web UI + Hardened Infra  ·  Phase 5

> **FR-23 is the one that bites if skipped** — never run model-written Python unsandboxed in multi-user. Keep the UI a thin layer over the M6 engine API.

### T-23 — Thin web UI (prompt → outline → scene list → preview → regenerate)
**Labels:** `milestone:M7` `phase:5` `area:web` `priority:p0` `type:feat`
**FRs:** FR-28 · **Depends on:** T-18, T-19, T-20

**Acceptance criteria.**
- [ ] From the browser alone: enter a topic, see scenes on a timeline, preview each, regenerate/tweak/edit-narration/reorder/add/delete, render a high-res final, **download the MP4 — no CLI.**
- [ ] Frontend re-implements **no** scene logic (thin layer over the engine API).

**Verify.** manual browser flow + `curl -s localhost:8000/health` + `pytest -m unit`  **Effort:** ~1.5 weeks.

### T-24 — Hardened sandbox (resource caps, ephemeral FS)
**Labels:** `milestone:M7` `phase:5` `area:infra` `priority:p0` `type:infra`
**FRs:** FR-23 · **Depends on:** T-0

**Acceptance criteria.**
- [ ] A render job **cannot reach the network**, exceeds neither CPU/memory nor wall-clock caps (**killed** if it does), runs **non-root**, leaves **no persistent FS state** between jobs.
- [ ] A hostile snippet (network egress / fork bomb) is **contained.**

**Verify.**
```bash
lattice render-sandbox tests/fixtures/fork_bomb.py ; echo "exit=$?"
lattice render-sandbox tests/fixtures/net_egress.py ; echo "exit=$?"
pytest -m unit
```
**Effort:** ~3 days.

### T-25 — Job queue + async status
**Labels:** `milestone:M7` `phase:5` `area:web` `priority:p0` `type:feat`
**FRs:** FR-24 · **Depends on:** T-23

**Acceptance criteria.**
- [ ] Submitting queues a job; UI reflects **queued → rendering → done/failed per scene**; users don't block each other.

**Verify.** `pytest -m unit`  **Effort:** ~2 days.

### T-26 — Streaming progress
**Labels:** `milestone:M7` `phase:5` `area:web` `priority:p1` `type:feat`
**FRs:** FR-29 · **Depends on:** T-25

**Acceptance criteria.**
- [ ] User sees **live per-scene progress** (reviews scene 1 while scene 8 renders) — not a frozen spinner.

**Verify.** manual + `pytest -m unit`  **Effort:** ~1.5 days.

### T-27 — Quality / resolution settings
**Labels:** `milestone:M7` `phase:5` `area:render` `priority:p1` `type:feat`
**FRs:** FR-26 · **Depends on:** T-3, T-23

**Acceptance criteria.**
- [ ] UI offers a **fast low-res preview** vs **high-res final**, clearly labeled; preview is materially faster.

**Verify.** `pytest -m unit`  **Effort:** ~1 day.

### T-28 — Export / download
**Labels:** `milestone:M7` `phase:5` `area:web` `priority:p1` `type:feat`
**FRs:** FR-30 · **Depends on:** T-16, T-23

**Acceptance criteria.**
- [ ] Final MP4 downloads, with an option for **burned-in subtitles vs a separate track.**

**Verify.** manual + `pytest -m unit`  **Effort:** ~1 day.

---

## Milestone M8 — Polish, Moat & V2  ·  Phase 6 (ongoing)

> Each ticket is independently shippable against its own FR acceptance criteria (`prds/PRD-phase-6.md`). None block each other. Don't start M8 to avoid finishing M7.

### T-29 — Domain templates / themes
**Labels:** `milestone:M8` `phase:6` `area:generation` `priority:p2` `type:feat` · **FRs:** FR-31 · **Depends on:** T-13
- [ ] Selecting a domain template (CS / ML / math / systems) **seeds the style spec + prompts** so output matches that domain out of the box.

### T-30 — Reusable component / asset library
**Labels:** `milestone:M8` `phase:6` `area:generation` `priority:p2` `type:feat` · **FRs:** FR-32 · **Depends on:** T-13
- [ ] A user drops a library component (a "server" box, a "packet", a stack frame) into a scene and it renders consistently; the library is extensible.

### T-31 — Voice swap / cloning
**Labels:** `milestone:M8` `phase:6` `area:narration` `priority:p2` `type:feat` · **FRs:** FR-33 · **Depends on:** T-10
- [ ] A user replaces generated narration with their own recording (`manim-voiceover` human-recording path + Whisper timing) **without re-authoring scenes** — a few-step change, not a rebuild.

### T-32 — Multi-language
**Labels:** `milestone:M8` `phase:6` `area:narration` `priority:p2` `type:feat` · **FRs:** FR-34 · **Depends on:** T-10
- [ ] A finished video regenerates in another language — narration translated, TTS localized, captions updated — **reusing the existing scene DAG + style spec.**

### T-33 — RAG over curated Manim examples
**Labels:** `milestone:M8` `phase:6` `area:eval` `priority:p2` `type:feat` · **FRs:** FR-35 (only place N3 relaxes) · **Depends on:** T-7
- [ ] Generation grounded in retrieved known-good snippets produces **fewer compile-repair iterations and/or lower token cost** on the eval battery, at equal-or-better visual quality. (Fine-tune only after usage data — never speculatively.)

### T-34 — Sharing / gallery / collaboration
**Labels:** `milestone:M8` `phase:6` `area:web` `priority:p2` `type:feat` · **FRs:** FR-36 · **Depends on:** T-28
- [ ] A user shares a finished video via a link and/or publishes it to a gallery; collaboration scope specified per-feature when prioritized.

---

## Ticket index

| Ticket | Title | Milestone | FRs |
|---|---|---|---|
| T-0 | Sandboxed Manim env + LLM client stub | M0 | FR-2/22/26, Q2/Q5 |
| T-1 | NL prompt → scene spec (locked IR) | M1 | FR-1 |
| T-2 | Scene spec → Manim code + guardrails | M1 | FR-2, FR-8 |
| T-3 | Local render worker | M2 | FR-22 |
| T-4 | Compile-check + auto-repair loop | M2 | FR-5, FR-7 |
| T-5 | Vision-critic + best-of-N | M2 | FR-6, FR-7 |
| T-6 | CLI core `generate-scene` | M3 | FR-27 |
| T-7 | Eval / regression harness | M3 | (reliability) |
| T-8 | Content-hash render cache | M3 | FR-25 |
| T-9 | Narration-first + sync | M4 | FR-9, FR-11 |
| T-10 | TTS integration + audio cache | M4 | FR-10, Q3 |
| T-11 | Auto subtitles / captions | M4 | FR-12 |
| T-12 | Planner + outline-approval gate | M5 | FR-3, Q4/Q6 |
| T-13 | Shared style spec | M5 | FR-4 |
| T-14 | Scene-DAG project model | M5 | FR-13 |
| T-15 | Bounded parallel rendering | M5 | FR-14 |
| T-16 | FFmpeg stitching | M5 | FR-15 |
| T-17 | Isolated single-scene regen | M5 | FR-16 |
| T-18 | Reorder / add / delete scenes | M6 | FR-17 |
| T-19 | Edit narration + re-time | M6 | FR-18 |
| T-20 | Per-scene tweak prompts | M6 | FR-19 |
| T-21 | Project save / load / persistence | M6 | FR-20 |
| T-22 | Per-scene version history + rollback | M6 | FR-21 |
| T-23 | Thin web UI | M7 | FR-28 |
| T-24 | Hardened sandbox | M7 | FR-23 |
| T-25 | Job queue + async status | M7 | FR-24 |
| T-26 | Streaming progress | M7 | FR-29 |
| T-27 | Quality / resolution settings | M7 | FR-26 |
| T-28 | Export / download | M7 | FR-30 |
| T-29 | Domain templates / themes | M8 | FR-31 |
| T-30 | Reusable component library | M8 | FR-32 |
| T-31 | Voice swap / cloning | M8 | FR-33 |
| T-32 | Multi-language | M8 | FR-34 |
| T-33 | RAG over curated Manim examples | M8 | FR-35 |
| T-34 | Sharing / gallery / collaboration | M8 | FR-36 |
