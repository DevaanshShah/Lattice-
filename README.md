# Lattice

*An AI platform that turns a natural-language prompt into a narrated, multi-scene educational explainer video, using **Manim CE** as the deterministic rendering engine.* (Working title in the PRDs: "Manimate".)

Type a topic → a planner breaks it into short scenes → you approve the outline → each scene is generated **narration-first**, compiled, render-checked, and **vision-verified** before you ever see it → a shared **style spec** keeps every scene looking like one film → finished scenes are FFmpeg-stitched into one continuous narrated explainer.

## Why this is tractable (the core bets)
- **Manim is a deterministic compiler** — code renders or crashes, a free correctness signal, no reward model needed.
- **Videos decompose into 5–10s independent scenes** — every generation stays small, fast, cheap, isolated, parallelizable. Scene 7 breaking never touches scenes 1–6.
- **The unsolved part isn't codegen** (commoditized) — it's making output reliably *not look broken* and wrapping it in a coherent multi-scene product. The **vision critic** and the **style spec** are the two load-bearing features.

## The two non-negotiable invariants
1. **Verification is two-layered and never conflated.** A free, deterministic *compile check* gates every paid *vision-critic* call — "it compiles" is never "it looks right." No scene is surfaced without passing both (or a logged best-of-N fallback). Every loop respects hard caps and never hangs.
2. **Idempotent by content hash; structure approved before spend.** Same `(scene spec + style spec + model)` ⇒ reuse the cached render. The outline is approved before any scene renders.

## Repository layout

```
lattice/
├── README.md            ← you are here
├── MILESTONES.md        ← curated roadmap (M0→M8), DoD + verify per milestone
├── AGENT_TICKETS.md     ← GitHub-ready tickets T-0…T-34
├── BUILD_PLAN.md        ← the v2 build plan (cost/latency engineering, bottlenecks)
│
├── prds/                ← locked product requirement docs (build one phase at a time)
├── reference/           ← source/background material (sas.pdf)
│
├── core/                ← LLM client, config, schemas, content-hash cache  [M0–M1]
├── planner/             ← topic→outline, approval gate, spec expansion       [M5 · FR-3]
├── generation/          ← scene spec→Manim code, style spec, guardrails      [M1/M5 · FR-1,2,4,8]
├── verification/        ← compile-repair, vision critic, best-of-N  (moat)   [M2 · FR-5,6,7]
├── narration/           ← TTS, voiceover sync, captions                      [M4 · FR-9–12]
├── render/              ← render worker, sandbox, cache, quality             [M0/M2/M3/M7 · FR-22,23,25,26]
├── composition/         ← scene DAG, parallel pool, FFmpeg stitch, regen     [M5 · FR-13–16]
├── editing/             ← reorder/add/delete, narration edit, persistence    [M6 · FR-17–21]
├── cli/                 ← CLI engine: generate-scene / generate-video        [M3 · FR-27]
├── web/                 ← thin UI, job queue, streaming, export              [M7 · FR-28,24,29,30]
├── eval/                ← fixed prompt battery + regression harness          [M3]
├── prompts/             ← versioned system prompts (loaded, not inlined)
├── scripts/             ← operator scripts (setup_env, render_sample, run_eval, smoke)
└── tests/               ← pytest harness (unit / integration / llm markers)
```

Each source folder has a `README.md` describing its role, FRs, and milestone. **No product code exists yet** — this is the documented skeleton the build fills in, one milestone at a time.

## Where to start
1. Read `prds/PRD-00-overview.md` (vocabulary, the 36-FR catalog, non-goals, open questions Q1–Q6).
2. Read `MILESTONES.md` for the sequenced roadmap and per-milestone Definition of Done.
3. Pick up **T-0** in `AGENT_TICKETS.md` (the environment spike) — it blocks everything else.

## Status
Planning complete; build not started. See the status table in `MILESTONES.md`.

**v1 is demo-ready** when M0–M5 are green: *type a topic, approve the outline, get a narrated multi-scene explainer.* M6–M8 turn the demo into a product.
