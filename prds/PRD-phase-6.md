# PRD — Phase 6: Polish, Moat & V2

**Goal:** Turn a working product into a defensible one. Unlike Phases 0–5, this is an **ongoing roadmap**, not a single tight build with one demo — each item is independently shippable. Sequence by your own priorities; none of these block each other.

> Context: see `PRD-00-overview.md`. All items here are **[Later]** and assume the full Phase 5 product exists.

---

## In scope (FRs — pick and sequence as you go)

### FR-31 — Domain templates / themes
Presets and branding for specific domains (CS, ML, math, systems diagrams).
- *Acceptance:* selecting a domain template seeds the style spec and generation prompts so output matches that domain's visual conventions out of the box.

### FR-32 — Reusable component / asset library
A library of recurring objects (a "server" box, a "packet", a stack frame) reusable across videos.
- *Acceptance:* a user can drop a library component into a scene and it renders consistently; the library is extensible.

### FR-33 — Voice swap / cloning
Swap the AI voice for a recorded human voice; optionally clone a voice.
- *Acceptance:* a user replaces the generated narration audio with their own recording (using `manim-voiceover`'s human-recording path, with Whisper-based timing) without re-authoring the scenes; the swap is a few-step change, not a rebuild — exactly as the narration-first design promised.

### FR-34 — Multi-language
Translate narration and re-render with localized TTS.
- *Acceptance:* a finished video can be regenerated in another language — narration translated, TTS localized, captions updated — reusing the existing scene DAG and style spec.

### FR-35 — RAG over curated Manim examples
Retrieve from a curated library of known-good Manim snippets to cut hallucination and token cost; optionally a fine-tuned model later (this is the only place **N3** relaxes).
- *Acceptance:* generation grounded in retrieved examples produces fewer compile-repair iterations and/or lower token cost on the test battery than ungrounded generation, at equal or better visual quality.

### FR-36 — Sharing / gallery / collaboration
Share videos, a public gallery, collaboration/export options.
- *Acceptance:* a user can share a finished video via a link and/or publish it to a gallery; collaboration scope to be specified per-feature when prioritized.

---

## Out of scope

- Anything that contradicts the core non-goals: still no frame-level NLE (**N1**), still 2D educational explainers in Manim CE (**N5**).
- Each item ships independently — avoid bundling them into one mega-release.

## Dependencies

- The complete Phase 5 product (engine + UI + sandboxed infra + persistence).
- FR-33/FR-34 lean on the clean TTS/voiceover engine abstraction built in Phase 2 — that seam is what makes them small changes.
- FR-35 leans on a corpus of good Manim examples you'll need to curate.

## Definition of Done

There isn't a single one — this phase is "done" per feature, against each FR's own acceptance criteria. Treat each as a mini-project with its own scope when you pull it off the backlog.

## Risks & notes

- **Don't start Phase 6 to avoid finishing Phase 5.** These are attractive, visible features; it's tempting to bolt on voice cloning before the core product is solid. Resist — the moat is the reliability layer (vision critic, style spec) plus a product that works, not a long feature list.
- FR-35 is where fine-tuning finally becomes reasonable — but only after you have real usage data showing where ungrounded generation actually fails. Don't fine-tune speculatively.
- The narration-first decision from Phase 2 is what makes FR-33 and FR-34 cheap. If those feel hard here, the engine abstraction from Phase 2 is the thing to revisit.
