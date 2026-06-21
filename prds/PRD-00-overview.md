# Manimate — PRD Index & Shared Context

*An AI platform that turns a natural-language prompt into a narrated, multi-scene educational explainer video, using Manim (Community Edition) as the deterministic rendering engine.*

This file is the shared context for the per-phase PRDs (`PRD-phase-0.md` … `PRD-phase-6.md`). Each phase file is self-contained enough to hand to Claude on its own, but this index holds the vocabulary, the full requirement catalog, the non-goals, and the open decisions so they don't get re-litigated in every file.

---

## How to use these files

Build **one phase at a time.** Hand Claude the relevant `PRD-phase-N.md` plus this overview, ask it to satisfy only the FRs listed for that phase, and check the result against that phase's *Definition of Done* before moving on. Do **not** hand over the whole product at once — that's the fastest way to get scope sprawl and a half-built timeline editor in week one.

---

## The product in one paragraph

The user types a topic. A planner breaks it into an ordered list of short scenes. Each scene is generated independently as a small, structured **scene spec**, compiled to Manim code, render-checked, and visually verified before the user ever sees it. A shared **style spec** keeps all scenes looking like one film. Narration is generated first and the animation syncs to it. Finished scenes are stitched with FFmpeg into one continuous, narrated explainer.

## Why this is tractable (the core bets)

- **Manim is a deterministic compiler**: code either renders or crashes, which gives a free correctness signal — no reward model needed for the compile layer.
- **Videos decompose naturally** into 5–10s independent scenes, so every generation stays small, fast, cheap, isolated, and parallelizable. Scene 7 breaking never touches scenes 1–6.
- **The unsolved part isn't codegen** (commoditized) — it's making output reliably *not look broken* and wrapping it in a coherent multi-scene product. The **vision critic** and the **style spec** are the two load-bearing features that close that gap.

---

## Shared vocabulary

Pin these — agents drift when terms are loose.

- **Scene** — one short (~5–10s) animated unit. The atomic build/regenerate target.
- **Scene spec** — the structured (JSON) intermediate representation of a scene: its objects, layout intent, narration line, and animation beats. Generated *before* code; code is generated *from* it.
- **Scene DAG** — the full project: an ordered set of scene specs + their renders, plus version history. The thing that gets saved/loaded as "a video."
- **Style spec** — a small JSON design system (palette, fonts, object shapes, layout rules) injected into every scene's prompt so scenes stay visually consistent.
- **Outline** — the planner's output: topic → ordered list of scene titles/intents, before specs are fleshed out.
- **Vision critic** — a vision-model pass over a rendered keyframe that checks for overlap, off-screen elements, and intent mismatch, then feeds a fix back into generation.
- **Best-of-N** — generate N candidate scenes, render them, score them (compile + vision critic), keep the best.

---

## Full functional requirement catalog

The per-phase files reference these by number. Tags: **[MVP]** = core experience; **[Later]** = V2+.

### Generation core
- **FR-1** [MVP] — NL prompt → scene spec (structured IR).
- **FR-2** [MVP] — Scene spec → Manim code.
- **FR-3** [MVP] — Topic → outline → ordered scene specs (planner / decomposition).
- **FR-4** [MVP] — Shared style spec injected into every scene's generation.

### Reliability & verification *(the differentiator)*
- **FR-5** [MVP] — Compile-check + auto-repair loop (traceback fed back to the model).
- **FR-6** [MVP] — Vision-critic loop (keyframe render → overlap/off-screen/intent check → fix).
- **FR-7** [MVP] — Retry/step caps + graceful failure (never hang or loop forever).
- **FR-8** [MVP] — Manim API guardrails (CE conventions, no CE/GL mixing, no deprecated calls).

### Audio & narration
- **FR-9** [MVP] — Narration-first script generation (script drives the animation).
- **FR-10** [MVP] — TTS integration (gTTS free → OpenAI/Azure for quality).
- **FR-11** [MVP] — Auto-synced narration (`manim-voiceover` with-blocks).
- **FR-12** [MVP] — Auto subtitles/captions.

### Composition & editing
- **FR-13** [MVP] — Scene-DAG project model.
- **FR-14** [MVP] — Parallel scene rendering.
- **FR-15** [MVP] — FFmpeg stitching/concatenation.
- **FR-16** [MVP] — Regenerate a single scene in isolation.
- **FR-17** [Later] — Reorder / add / delete scenes.
- **FR-18** [Later] — Edit narration text + re-time.
- **FR-19** [Later] — Per-scene tweak prompts ("move left", "slower").
- **FR-20** [Later] — Project save/load/persistence.
- **FR-21** [Later] — Per-scene version history + rollback.

### Rendering & infrastructure
- **FR-22** [MVP] — Local/single render worker.
- **FR-23** [Later] — Sandboxed render workers (no-net, resource caps, non-root, ephemeral FS).
- **FR-24** [Later] — Job queue + async status.
- **FR-25** [Later] — Render caching (skip unchanged scenes).
- **FR-26** [Later] — Quality/resolution settings (low-res preview vs high-res final).

### Interface
- **FR-27** [MVP] — CLI core (the engine everything wraps).
- **FR-28** [Later] — Web UI (prompt, timeline, preview, narration editor).
- **FR-29** [Later] — Streaming progress to the UI.
- **FR-30** [Later] — Export/download (MP4 ± burned-in subtitles).

### Moat / V2
- **FR-31** [Later] — Domain templates/themes (CS, ML, math, systems).
- **FR-32** [Later] — Reusable component/asset library.
- **FR-33** [Later] — Voice swap (AI → recorded human) / voice cloning.
- **FR-34** [Later] — Multi-language (translation + localized TTS).
- **FR-35** [Later] — RAG over a curated library of good Manim examples.
- **FR-36** [Later] — Sharing / gallery / collaboration.

---

## Non-goals (fence these off aggressively)

- **N1** — Not a general-purpose video editor / NLE. No frame-level timeline, keyframing, or transitions library. The "editor" is reorder-regenerate-concatenate.
- **N2** — Not real-time/live animation. Rendering is offline/batch.
- **N3** — Not training a custom model for the MVP. Use an off-the-shelf API; fine-tuning is V2 (FR-35 territory).
- **N4** — Not a multi-tenant SaaS in early phases. Single-user/local through Phase 4; no auth/billing/orgs until they're explicitly needed.
- **N5** — Not arbitrary cinematic or 3D animation. Scope is 2D educational explainers (diagrams, math, systems), Manim CE only — no CE/GL mixing.

---

## Open questions (decide before/while building)

- **Q1** — Which LLM, and what monthly budget ceiling? Shapes best-of-N width and how aggressively the vision critic re-renders.
- **Q2** — Which Manim CE version do we pin? API churn between versions is a real source of broken codegen.
- **Q3** — Default TTS for the MVP: free gTTS, or pay for OpenAI/Azure quality from day one?
- **Q4** — Max scenes per video (hard cap)? Drives worst-case cost and render time.
- **Q5** — Local single-process render, or containerized from the start? Cheaper to defer, but FR-23 becomes mandatory the moment it's multi-user.
- **Q6** — The one canonical demo workflow used to validate Phase 3 (e.g. "how TCP works"). Pick it now so "done" is concrete.

---

## Phase map

| Phase | Theme | Headline demo | FRs |
|---|---|---|---|
| 0 | Environment spike (throwaway) | Any Manim scene renders end-to-end | — |
| 1 | One non-broken scene | `generate-scene "hash map collision"` → clean scene | FR-1,2,5,6,7,8,22,27 |
| 2 | Narrated scene | The scene explains itself, perfectly synced | FR-9,10,11,12 |
| 3 | Multi-scene + consistency | `generate-video "how TCP works"` → coherent explainer | FR-3,4,13,14,15,16 |
| 4 | Editing & human control | Fix scene 7, re-stitch, ship | FR-17,18,19,20,21 |
| 5 | Web UI | Non-coder makes an explainer in the browser | FR-23,24,25,26,28,29,30 |
| 6 | Polish / moat / V2 | Branded, multilingual, shareable, cheaper | FR-31,32,33,34,35,36 |

**Reality check:** Phases 0–3 (~6 weeks part-time) already give you the portfolio milestone — *type a topic, get a narrated multi-scene video.* Phases 4–6 turn that demo into a product.
