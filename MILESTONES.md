# MILESTONES.md — Lattice v1 Roadmap

This roadmap sequences the build of **Lattice** *(working title in the PRDs: "Manimate")* — an AI platform that turns a natural-language prompt into a narrated, multi-scene educational explainer video, using **Manim CE** as the deterministic rendering engine. It follows the locked PRD build order: **0 → 1 → 2 → 3 → 4 → 5 → 6**, with the dense Phase 1 split into three shippable milestones (M1/M2/M3). Each milestone names its goal, the tickets it contains, the make-or-break exit criteria (Definition of Done), the commands to verify it, and a rough effort estimate.

Build **one milestone at a time.** Hand the implementer the matching `prds/PRD-phase-N.md` plus `prds/PRD-00-overview.md`, satisfy only that milestone's FRs, and check against its DoD before moving on. Handing over the whole product at once is the fastest way to a half-built timeline editor in week one.

Two invariants run through every milestone and are non-negotiable acceptance gates:

- **Verification is two-layered and never conflated.** The *compile check* is a free, deterministic crash signal and **gates** every paid *vision-critic* call — "it compiles" is never treated as "it looks right." No scene is surfaced to the user without passing both layers (or a logged best-of-N fallback). Every loop (repair, critic, best-of-N) respects a hard iteration cap and on non-convergence returns the best attempt with a useful error — it **never hangs or loops forever**.
- **Idempotent by content hash; structure approved before spend.** Every render is keyed by `hash(scene spec + style spec + model)` — unchanged work is never redone and re-runs change nothing. The scene **outline is human-approved before any scene renders**, so wrong scenes are never paid for. TTS audio is cached separately on the same principle.

---

## Status

| Milestone | Phase | Tickets | State |
|---|---|---|---|
| M0 — Environment spike & sandbox | 0 | T-0 | ✅ shipped — verified e2e (preview+final MP4 + keyframe; LaTeX OK; sandbox no-net proven; 9/9 unit) |
| M1 — Scene spec → Manim code | 1 | T-1, T-2 | ✅ shipped — verified live (prompt→spec→clean-guarded code, rendered first try); 19/19 unit |
| M2 — Verification loops (the moat) | 1 | T-3, T-4, T-5 | ✅ shipped — verified live (compile-repair + structured multi-frame vision critic + fix loop + best-of-N, caps respected); 39/39 unit |
| M3 — CLI + eval harness + cache | 1 | T-6, T-7, T-8 | ✅ shipped — verified live (generate-scene + cache hit = no re-spend; eval battery + score table + baseline); 54/54 unit |
| M4 — Narrated scene | 2 | T-9, T-10, T-11 | ✅ shipped — verified live (narration-first + host-side gTTS + add_sound sync + SRT; MP4 has h264+aac; render stayed no-net); 69/69 unit |
| M5 — Multi-scene video + consistency | 3 | T-12 … T-17 | ✅ shipped — **v1 demo!** verified live (outline+gate → style → 3 scenes parallel → stitched 95.5s narrated film h264+aac; a scene self-healed via compile-repair); 100/100 unit |
| M6 — Editing & human control | 4 | T-18 … T-22 | 🔲 planned |
| M7 — Web UI + hardened infra | 5 | T-23 … T-28 | 🔲 planned |
| M8 — Polish, moat & V2 | 6 | T-29 … T-34 | 🔲 ongoing |

**Reality check:** M0–M5 (~6 weeks part-time) already give the portfolio milestone — *type a topic, approve the outline, get a narrated multi-scene video.* M6–M8 turn that demo into a product.

---

## Test & Ship Gate (every milestone — M0…M8)

Each milestone ends with the **same gate**:

1. Write/extend that milestone's pytest tests (mapped to its DoD) under `tests/`.
2. `pytest -m unit` — **hard gate, must be green to commit** (no network, no model calls). When a render container is available: `LATTICE_TEST_INTEGRATION=1 pytest -m "integration and not llm"`. **LLM/vision tests are DEFERRED** (run only with `LATTICE_TEST_LLM=1`); nothing calls a paid model by default.
3. Re-run the eval battery from M3 onward (`python -m scripts.run_eval`) and confirm **no regression** before committing a prompt/model change.
4. Commit and push to the working branch (`main` or a milestone branch), one commit per milestone: `M<n>: <summary>`.

The M0 milestone also lands the `tests/` harness itself (conftest, markers, baseline unit tests) and the eval harness skeleton.

---

## Foundation — decisions to lock before/while building

Nothing is built yet. The substrate every milestone stands on is the **open decisions (Q1–Q6)** from `prds/PRD-00-overview.md` and the **pinned dependency stack**. Lock these early; an unpinned Manim version silently breaks codegen prompts you tune later.

- **Q1** — generation model + monthly budget ceiling. Gates best-of-N width and vision re-render aggressiveness. *(Generator and critic are different, swappable models: strong coder writes; cheap vision model checks.)*
- **Q2** — pinned Manim CE version. **Locked in M0 and referenced everywhere after.**
- **Q3** — default MVP TTS engine (free gTTS vs paid OpenAI/Azure). Locked by M4.
- **Q4** — hard cap on scenes per video. Caps planner output + worst-case cost. Locked by M5.
- **Q5** — local single-process vs containerized render. **Decided & documented in M0** (the PRD pushes containerized-from-day-one for the free no-net/non-root sandbox).
- **Q6** — the one canonical demo workflow that defines "done" for the multi-scene phase (e.g. `"how TCP works"`). Pick it now; it's the M5 acceptance fixture.

**Dependency stack (pin all):** Manim CE (Q2), `manim-voiceover`, FFmpeg, a LaTeX subset (for `Tex`/`MathTex`), a vision-capable model (critic), any OpenAI-compatible model (generator).

---

## M0 — Environment Spike & Sandbox

**Goal:** de-risk the substrate before any product code. The hard part at the start is **not** the AI — it's getting Manim CE + LaTeX + FFmpeg to render reliably. Prove that path end-to-end, in a sandboxed container, with a swappable LLM client wired but unused. Code here is deliberately throwaway.

**Tickets:** T-0

**Scope:** `scripts/setup_env` (one documented command → working env from clean); a checked-in hand-written sample scene (shapes + `MathTex`); `scripts/render_sample` (preview + final quality, export one keyframe PNG); `render/sandbox` (no-network, non-root container — free from day one); `core/llm` client stub (swappable via `base_url`/`api_key`/`model`, **not yet called**); `core/config` with the pinned Manim version. Decide **Q2** and **Q5** in writing.

**Exit / DoD (make-or-break):**
- One documented command produces a working environment from clean; re-running on a fresh machine/container succeeds with no manual fixes.
- The checked-in sample scene renders to a **playable MP4 containing both a shape animation and a `MathTex` expression** (proves LaTeX works — the #1 breakage; a scene that renders shapes but chokes on equations *looks* fine and isn't).
- The same scene renders at **preview (fast, low-res)** and **final (slow, high-res)** via a documented flag.
- **One keyframe exports as a PNG** (the hook the vision critic will use — prove it's mechanically possible now).
- Model-written code runs in a **container with no network, as non-root** (basic sandbox, costs nothing).
- **Q2** (Manim version) and **Q5** (local vs container) are written down with rationale; the Manim version is pinned in `core/config`.
- `pytest -m unit` green; the `tests/` harness (conftest, markers) exists.

**Verify:**
```bash
bash scripts/setup_env.sh                      # clean env from one command
python -m scripts.render_sample --quality preview   # fast MP4
python -m scripts.render_sample --quality final     # high-res MP4 + keyframe.png
ls out/keyframe.png && ffprobe out/sample_final.mp4 # PNG exists, MP4 plays
docker run --network=none --user 1000 lattice-render python -c "import socket"  # no net
pytest -m unit
```

**Effort:** ~1 week. *(Hard prerequisite for everything — blocks M1–M8.)*

---

## M1 — Scene Spec → Manim Code

**Goal:** given a single NL prompt, produce a valid **scene spec** (locked JSON IR) and compile it to Manim CE code that targets the pinned version and obeys the API guardrails. This is the codegen spine; reliability comes in M2.

**Tickets:** T-1 (scene spec), T-2 (codegen + guardrails)

**Scope:** `core/schemas` scene-spec model (objects, layout intent, placeholder narration line, animation beats) — **locked here**; `generation/scene_spec` (NL → spec, validate-or-regenerate); `generation/codegen` (spec → Manim code); `generation/guardrails` (no CE/GL mixing, no deprecated calls); `prompts/{scene-spec,codegen,manim-conventions}`.

**Exit / DoD (make-or-break):**
- The same prompt yields a **valid scene spec conforming to the locked JSON schema**; invalid model output is **rejected and regenerated, not passed downstream** (FR-1).
- Codegen produces Manim code **targeting the pinned version** for the scene spec (FR-2).
- Generated code **never imports/uses the GL/OpenGL renderer path**; deprecated-API usage is caught (lint or prompt-level) before render (FR-8).
- The scene-spec JSON schema is **locked and documented** — everything downstream (regeneration, style spec, persistence) keys off it.
- `pytest -m unit` green (schema validation + guardrail checks are unit-testable without rendering).

**Verify:**
```bash
python -m lattice.generation.scene_spec "explain a hash map collision" | python -m json.tool   # valid spec
python -c "from core.schemas import SceneSpec; SceneSpec.model_validate_json(open('out/spec.json').read()); print('schema OK')"
python -m lattice.generation.codegen out/spec.json > out/scene.py
grep -E "opengl|OpenGL|ManimGL|\.gl\b" out/scene.py && echo "GUARDRAIL FAIL" || echo "guardrail OK"
pytest -m unit
```

**Effort:** ~3–4 days (locking the schema right is the keystone; changing it later is expensive).

---

## M2 — Verification Loops *(the moat)*

**Goal:** make generated scenes reliably **not look broken** — the one thing the existing text→Manim tools skip and the reason they look like demos. Render worker + compile-repair + vision critic + best-of-N fallback, all under hard caps.

**Tickets:** T-3 (render worker), T-4 (compile-repair), T-5 (vision critic + best-of-N)

**Scope:** `render/worker` (Manim code → MP4 + keyframe PNGs, callable repeatedly); `verification/compile_repair` (trimmed-traceback retry, capped); `verification/vision_critic` (multi-frame sampling → structured issues → fix); `verification/best_of_n`; `verification/caps`; `prompts/vision-critic`. The generator/critic are **different swappable models**.

**Exit / DoD (make-or-break):**
- A deliberately-broken generation (e.g. undefined mobject) is **recovered automatically within the retry cap**; the loop logs each attempt and feeds back the **trimmed** traceback (not the whole thing — cost control) (FR-5).
- A scene that **compiles but is visually broken** (two labels stacked, an object off-frame) is **detected and corrected without a human flagging it** (FR-6).
- Critic output is **structured** (issue type + location + suggested fix), never free prose.
- The critic samples **multiple frames**, not one (catches mid-animation problems).
- On critic non-convergence, **best-of-N** generates N candidates, renders, keeps the highest-scoring (FR-6 fallback).
- When a scene can't be fixed within caps, the system **fails cleanly with a useful error and the best attempt so far** — it does not spin (FR-7).
- **Invariant proof:** the free compile check runs **before** any vision call on every path; "compiles" and "looks right" are tracked as two distinct scores.

**Verify:**
```bash
python -m lattice.render.worker out/scene.py            # MP4 + frame_*.png
python -m lattice.verification.compile_repair out/broken_scene.py   # recovers within cap, logs attempts
python -m lattice.verification.vision_critic out/scene.py --json     # typed issues, multi-frame
python -m lattice.verification.run --best-of 3 "two labels that overlap"  # picks cleanest; never hangs
pytest -m unit          # cap behaviour + structured-issue parsing
LATTICE_TEST_LLM=1 pytest -m llm   # (optional) real critic on a known-broken fixture
```

**Effort:** ~1.5 weeks (the differentiator — budget real iteration time; the model animates blind, the critic gives it eyes).

---

## M3 — CLI + Eval Harness + Content-Hash Cache

**Goal:** wrap M1+M2 in `generate-scene`, make quality **provable** with a regression harness, and stop redoing unchanged work with a content-hash cache. After this, a single scene is a finished, repeatable product.

**Tickets:** T-6 (CLI core), T-7 (eval/regression harness), T-8 (content-hash cache)

**Scope:** `cli/generate-scene` (full pipeline: spec → code → render → repair → critic → final MP4, writes the output path) (FR-27); `eval/` (fixed ≥10-prompt battery + scoring + regression gate); `core/cache` + `render/cache` (key = hash(scene spec + style spec + model); TTS cached separately later).

**Exit / DoD (make-or-break):**
- `generate-scene "<prompt>"` runs the **full pipeline in one command** and writes the final MP4 path (FR-27).
- On the **≥10-prompt battery**, every prompt yields a single MP4 that compiles, has **no critic-flagged overlap/off-screen issues**, and visibly matches the prompt — **zero manual intervention** (Phase 1 DoD).
- The eval harness **re-runs on demand and reports a score table**; a prompt/model change can be shown to *help* (fewer flagged issues), not merely *run* — without it you tune blind.
- **Cache is idempotent:** re-running `generate-scene` with the same prompt/spec/model **reuses the existing render** (no re-render); any meaningful spec change busts the key.
- `pytest -m unit` green (cache-key determinism is unit-tested).

**Verify:**
```bash
lattice generate-scene "explain a hash map collision"    # → writes out/<hash>.mp4
python -m scripts.run_eval                                # score table over the battery, no regressions
lattice generate-scene "explain a hash map collision"    # 2nd run: cache hit, no re-render
python -c "from core.cache import key; assert key(spec, style, model)==key(spec, style, model); print('cache key stable')"
pytest -m unit
```

**Effort:** ~3 days. **(End of Phase 1 — single-scene quality is now won and measurable.)**

---

## M4 — Narrated Scene

**Goal:** make a single scene explain itself out loud, animation synced to the script. The architectural move is **narration-first**: write the script, then generate animation that syncs to it. Good news — sync is a solved library problem (`manim-voiceover`), so this phase is smaller than it looks.

**Tickets:** T-9 (narration-first + sync), T-10 (TTS + audio cache), T-11 (captions)

**Scope:** `narration/script` (narration-first generation, scene spec carries a real script) (FR-9); `narration/sync` (`with self.voiceover(...)` blocks; durations from audio segments) (FR-11); `narration/tts` (gTTS default, swappable to OpenAI/Azure — resolves **Q3**; audio cached) (FR-10); `narration/captions` (FR-12); `prompts/narration`.

**Exit / DoD (make-or-break):**
- The scene spec now carries a **real narration script**, and generated code wraps animations in `with self.voiceover(...)` blocks whose beats correspond to the script — narration-first is the **default** generation path (FR-9).
- In the output MP4, **animation beats line up with the spoken words with no manual timing**; re-rendering with a different voice/engine **re-syncs automatically** (FR-11).
- Swapping the TTS engine is a **one-line config change**, not a code rewrite (FR-10); generated audio is cached.
- The pipeline emits a **caption track / burned-in captions** matching the narration (FR-12).
- **Known coupling acknowledged:** editing narration text re-renders that scene (timing derives from audio duration) — made cheap by TTS + render caching, not engineered away.

**Verify:**
```bash
lattice generate-scene "explain a hash map collision"    # MP4 now speaks + synced + captions
# swap engine via config only, re-render — beats re-sync automatically:
LATTICE_TTS=openai lattice generate-scene "explain a hash map collision"
ls out/captions.srt
pytest -m unit
```

**Effort:** ~1 week (don't over-engineer sync — `manim-voiceover` handles the hard part; keep the TTS engine seam clean for FR-33/FR-34 later).

---

## M5 — Multi-Scene Video + Consistency *(the portfolio demo)*

**Goal:** go from one narrated scene to a full coherent explainer — type a topic, **approve the outline**, get an ordered set of scenes that look like one film and stitch into a single continuous narrated video. This is the demo you show people.

**Tickets:** T-12 (planner + outline-approval gate), T-13 (style spec), T-14 (scene-DAG), T-15 (bounded parallel render), T-16 (FFmpeg stitch), T-17 (isolated regen)

**Scope:** `planner/{outline,approval,expand}` (FR-3); `generation/style` style spec (FR-4); `composition/scene_dag` (FR-13); `composition/pool` bounded parallel (FR-14); `composition/stitch` (FR-15); `composition/regen` (FR-16). Resolves **Q4** (scene cap) and **Q6** (canonical workflow).

**Exit / DoD (make-or-break):**
- A topic produces a **sensible ordered outline within the scene cap (Q4)**, inspectable as an artifact; each item expands into a valid scene spec the M1–M4 pipeline builds (FR-3).
- The **outline-approval gate** shows the scene list and lets the user edit/reorder/cut **before any scene renders** (no paying to render 20 wrong scenes).
- Across all scenes in one video, **colors/fonts/recurring object styles are visibly consistent** (a "packet" looks the same in scene 2 and scene 6) via a single reused **style spec** (FR-4).
- An N-scene video renders **meaningfully faster than N sequential renders** through a **bounded** worker pool; one scene failing (after its caps) doesn't abort the others (FR-14).
- FFmpeg concatenation yields **one MP4 that plays start-to-finish with narration intact across boundaries**, no seam glitches (FR-15).
- **Regenerating scene *k* leaves scenes ≠ *k* byte-for-byte unchanged** (or cache-reused) and produces an updated final video (FR-16) — the seam Phase 4 builds on.
- The Q6 workflow (e.g. `"how TCP works"`) is the standing acceptance fixture.

**Verify:**
```bash
lattice generate-video "how TCP works"          # → outline shown for approval
# edit/approve the outline, then it renders in parallel + stitches:
ls out/<project>/final.mp4                       # single continuous narrated MP4
lattice regenerate-scene <project> 3             # only scene 3 changes; others reused
python -c "import hashlib,glob; print('scene-DAG addressable + cache reuse OK')"
pytest -m unit
```

**Effort:** ~2 weeks (the style spec + bounded parallelism + clean isolated regen are the load-bearing parts; spend polish budget on stitch seams and consistency).

---

## M6 — Editing & Human Control

**Goal:** give the human real scene-level control without it becoming a video editor — **a list with a stitch button, not Premiere** (non-goal N1). Because every scene already carries its own synced audio (M4), editing stays at the scene level: regenerate, reorder, tweak, roll back, save.

**Tickets:** T-18 (reorder/add/delete), T-19 (narration edit + re-time), T-20 (tweak prompts), T-21 (persistence), T-22 (version history + rollback)

**Scope:** `editing/arrange` (FR-17), `editing/narration_edit` (FR-18), `editing/tweak` (FR-19), `editing/persistence` (FR-20), `editing/history` (FR-21). Exposed via CLI/engine first (the web UI wraps them in M7).

**Exit / DoD (make-or-break):**
- Reorder re-stitches in the new order **without re-rendering unchanged scenes**; insert generates **only** the new scene (inheriting the style spec); delete removes + re-stitches; the scene DAG stays consistent (FR-17).
- Editing scene *k*'s narration **re-runs TTS + sync for that scene only**, updates the final video and captions; other scenes untouched (FR-18).
- A tweak prompt ("move the cache box left", "slow this down") produces a revised scene that **passes the same verification loops** and re-stitches, affecting no other scene (FR-19).
- A **saved project reopens** with all scenes, specs, narration, style spec, and existing renders intact — resume exactly where you left off (FR-20). *First phase where state survives between runs.*
- After regen/tweak, the **previous version is recoverable** and selecting it re-stitches using that earlier render; history is **per-scene, not global** (FR-21).
- **Invariant proof — isolation:** every operation touches only the affected scene(s) and reuses everything else from cache; no operation forces a full re-render.

**Verify:**
```bash
lattice reorder <project> 7 2          # scene 7 → position 2, others reused, re-stitched
lattice edit-narration <project> 4 "new script"   # only scene 4 re-times; captions update
lattice tweak <project> 5 "move the cache box left"
lattice save <project> && lattice open <project>  # full state restored
lattice rollback <project> 5           # previous good render restored + re-stitch
pytest -m unit
```

**Effort:** ~2–3 weeks (stay disciplined against N1; isolation is the whole game — if editing one scene forces a full re-render, the UX and render budget collapse).

---

## M7 — Web UI + Hardened Infra

**Goal:** put the engine behind a browser so a non-coder produces a narrated explainer end-to-end without seeing Python. This forces the first hard infra requirement: the moment strangers submit prompts, you are executing model-written Python for them — **sandboxing stops being optional.** Ship a **thin cut first** so momentum doesn't die in a timeline-editor swamp.

**Tickets:** T-23 (thin web UI), T-24 (hardened sandbox), T-25 (job queue + async status), T-26 (streaming progress), T-27 (quality settings), T-28 (export/download)

**Scope:** `web/ui` (prompt → editable outline → linear scene list → preview + regenerate + narration editor) (FR-28); `render/sandbox` hardened (resource caps, ephemeral FS, kill on overrun) (FR-23); `web/queue` (FR-24); `web/streaming` (FR-29); `render/quality` exposed (FR-26); `web/export` (FR-30). The UI is a **thin layer** over the M6 engine API.

**Exit / DoD (make-or-break):**
- From the browser alone a user enters a topic, sees scenes on a timeline, previews each, regenerates/tweaks/edits narration/reorders/adds/deletes, renders a high-res final, and **downloads the MP4 — no CLI** (FR-28).
- A render job **cannot reach the network**, exceeds neither CPU/memory nor wall-clock caps (killed if it does), runs **non-root**, and **leaves no persistent FS state** between jobs; a deliberately hostile snippet (network egress / fork bomb) is **contained** (FR-23).
- Submitting queues a job; the UI reflects **queued → rendering → done/failed per scene**; users don't block each other (FR-24).
- The user sees **live per-scene progress**, reviewing scene 1 while scene 8 renders — not a frozen spinner (FR-29).
- A **fast low-res preview** vs **high-res final** is offered and labeled; preview is materially faster (FR-26).
- Final MP4 downloads, with an option for **burned-in subtitles vs a separate track** (FR-30).

**Verify:**
```bash
# browser flow (manual): topic → approve outline → previews stream → final → download
curl -s localhost:8000/health
# hostile-snippet containment (must be killed/blocked, exit non-zero):
lattice render-sandbox tests/fixtures/fork_bomb.py ; echo "exit=$?"
lattice render-sandbox tests/fixtures/net_egress.py ; echo "exit=$?"
pytest -m unit
```

**Effort:** ~3–4 weeks (FR-23 is the one that bites if skipped — never run model-written Python unsandboxed in multi-user; keep the UI thin over the engine API).

---

## M8 — Polish, Moat & V2 *(ongoing)*

**Goal:** turn a working product into a defensible one. Unlike M0–M7 this is an **ongoing roadmap**, not one tight build — each item is independently shippable; sequence by your own priorities; none block each other.

**Tickets:** T-29 (domain templates), T-30 (component library), T-31 (voice swap/cloning), T-32 (multi-language), T-33 (RAG over curated Manim examples), T-34 (sharing/gallery/collaboration)

**Scope (each a mini-project against its own FR):** `generation/style` templates (FR-31); a reusable component/asset library (FR-32); `narration/tts` human-recording + cloning path (FR-33); multi-language translate + localized TTS (FR-34); `eval`/`generation` RAG over curated good Manim snippets (FR-35 — the only place N3 relaxes); `web` sharing/gallery (FR-36).

**Exit / DoD:** there is no single DoD — each ticket is done against its own FR's acceptance criteria (see `prds/PRD-phase-6.md`). Treat each as a mini-project pulled off the backlog with its own scope.

**Notes / guardrails:**
- **Don't start M8 to avoid finishing M7.** The moat is the reliability layer (vision critic + style spec) plus a product that works — not a long feature list.
- FR-33/FR-34 are cheap **because** of the narration-first decision in M4 and the clean TTS seam; if they feel hard, revisit that abstraction.
- FR-35 is where fine-tuning finally becomes reasonable — but only after real usage data shows where ungrounded generation fails. Don't fine-tune speculatively.

**Effort:** ongoing / per-feature.

---

## Definition of Done for v1

Lattice **v1** is the portfolio milestone — done when all of the following hold simultaneously on a running stack:

1. **The environment is reproducible and sandboxed.** One documented command builds a working Manim CE + LaTeX + FFmpeg env; the sample scene (shapes + `MathTex`) renders to a playable MP4 at preview and final quality with a keyframe PNG; model-written code runs no-network / non-root. (M0)

2. **A single scene is reliably non-broken.** `generate-scene "<prompt>"` over the ≥10-prompt battery produces, for every prompt, a single MP4 that compiles, has no critic-flagged overlap/off-screen issues, and visibly matches the prompt — zero manual intervention. The compile check gates every vision call; every loop respects its caps and fails gracefully. The eval harness can prove a change helped. (M1–M3)

3. **The scene speaks itself.** `generate-scene` produces narration-first audio synced via `manim-voiceover` with captions; swapping the TTS engine is one config line and re-syncs automatically. (M4)

4. **A topic becomes a coherent multi-scene film.** `generate-video "<topic>"` (the Q6 workflow) shows an editable outline, renders the approved scenes in parallel through a bounded pool, keeps them visibly consistent via one style spec, and FFmpeg-stitches them into a single seamless narrated MP4; regenerating any one scene updates the final video without disturbing the rest. (M5)

5. **Both invariants are provably upheld.** Verification is two-layered and never conflated (free compile gates paid vision; no scene surfaced without passing both or a logged best-of-N fallback; nothing hangs); every render is idempotent by content hash and the outline is approved before any spend.

6. **No environment regressions.** The sandbox contains a hostile snippet; the pinned Manim version is honored everywhere; the system runs from the CLI with no web/UI dependency.

When items 1–6 are green, **v1 is demo-ready** — *type a topic, approve the outline, get a narrated multi-scene explainer.* M6–M8 turn it into a product.
