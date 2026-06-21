# PRD — Phase 3: Multi-Scene Video + Consistency

**Goal:** Go from one narrated scene to a full coherent explainer: type a topic, get an ordered set of scenes that look like one film and stitch into a single continuous narrated video. This is the **portfolio/demo milestone** — the thing that proves the concept.

> Context: see `PRD-00-overview.md` for vocabulary (outline, scene DAG, style spec). Builds on the Phase 2 narrated-scene pipeline by wrapping it in a planner and a consistency layer, then composing the outputs.

**Headline demo:** `generate-video "how TCP works"` → a coherent, narrated, multi-scene explainer. (Pick this canonical workflow now — resolves **Q6**.)

---

## In scope (FRs)

### FR-3 — Planner (topic → outline → scene specs)
Turn a topic into an **outline** (ordered scene titles/intents), then expand each into a full scene spec.
- *Acceptance:* a single topic produces a sensible ordered outline within the scene cap (**Q4**), and each outline item expands into a valid scene spec that the Phase 1–2 pipeline can build. The outline is inspectable as an intermediate artifact.

### FR-4 — Shared style spec *(consistency = the other load-bearing feature)*
A small JSON design system — palette, fonts, object shapes, layout rules — generated once per video and injected into every scene's generation prompt so scenes stay visually consistent.
- *Acceptance:* across all scenes in one video, colors/fonts/recurring object styles are visibly consistent (e.g. a "packet" looks the same in scene 2 and scene 6). The style spec is a single artifact reused by every scene's generation.

### FR-13 — Scene-DAG project model
Represent a video as an ordered collection of scene specs + their renders (and room for the version history added in Phase 4).
- *Acceptance:* a video is a single in-memory/on-disk structure enumerating its scenes in order; individual scenes are addressable (needed for FR-16).

### FR-14 — Parallel scene rendering
Scenes are independent — render them in parallel.
- *Acceptance:* an N-scene video renders meaningfully faster than N sequential renders; a failure in one scene (after its repair/critic caps) doesn't abort the others.

### FR-15 — FFmpeg stitching/concatenation
Concatenate the per-scene MP4s (each already carrying synced narration from Phase 2) into one continuous video.
- *Acceptance:* the final output is a single MP4 that plays start-to-finish with narration intact across scene boundaries and no audible/visual seam glitches.

### FR-16 — Regenerate a single scene in isolation
Re-run generation for one scene without touching the others, then re-stitch.
- *Acceptance:* regenerating scene *k* leaves scenes ≠ *k* byte-for-byte unchanged (or reused from cache) and produces an updated final video. This is the seam Phase 4's editing features build on.

---

## Out of scope

- Reorder/add/delete, narration editing, tweak prompts, persistence-across-runs, version history (all Phase 4).
- Web UI, job queue, sandboxing, caching-as-a-feature (Phase 5).
- Domain templates / RAG (Phase 6). The style spec here is generated per-video, not drawn from a curated library yet.

## Dependencies

- Phase 2 narrated-scene pipeline.
- Decisions: **Q4** (max scenes — caps planner output and worst-case cost), **Q6** (the canonical validation workflow).

## Definition of Done

`generate-video "how TCP works"` (the Q6 workflow) produces a single narrated MP4 of multiple scenes that (a) covers the topic in a sensible order, (b) is visibly consistent in style across scenes thanks to the style spec, and (c) plays seamlessly after FFmpeg stitching. Regenerating any one scene updates the final video without disturbing the rest. Scenes render in parallel.

## Risks & notes

- **The style spec is what makes 20 independent generations read as one coherent film** — it's exactly the thing the one-prompt-one-animation tools don't bother with because they're not thinking in *courses*. Protect it; it's a moat feature alongside the vision critic.
- **Exploit independence.** The scene decomposition is the single strongest argument that this is *more* tractable than monolithic codegen tools — each generation stays small and isolated. Parallelism here is nearly free architecturally.
- Get FR-16 (isolated regeneration) genuinely clean now. Phase 4's entire editing story assumes you can touch one scene without re-rendering the world.
- This phase is the demo you show people. Spend a little polish budget on the stitch seams and the consistency — it's the difference between "impressive" and "looks broken."
