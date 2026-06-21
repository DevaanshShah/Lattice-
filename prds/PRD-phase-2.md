# PRD — Phase 2: Narrated Scene

**Goal:** Make a single scene explain itself out loud, with the animation synced to the narration. The key architectural move is **narration-first**: generate the script for a scene, then generate animation that syncs to it — the script becomes the backbone the visuals hang off.

> Context: see `PRD-00-overview.md`. Builds directly on the Phase 1 single-scene pipeline. Good news up front: sync is a *solved* library problem (`manim-voiceover`), so this phase is smaller than it looks.

**Headline demo:** the Phase 1 scene now explains itself out loud, perfectly synced, with captions.

---

## In scope (FRs)

### FR-9 — Narration-first script generation
Generate the narration script for a scene *before* the animation, then generate animation that syncs to it via voiceover bookmarks. This flips the Phase 1 ordering so the script drives the visuals.
- *Acceptance:* the scene spec now carries a real narration script; the generated Manim code wraps animations in `with self.voiceover(...)` blocks whose beats correspond to the script. The script is purposeful (drives what's shown), not a caption bolted on after.

### FR-10 — TTS integration
Integrate text-to-speech. Start with free **gTTS**; make the engine swappable so OpenAI/Azure can be plugged in for quality. (Default engine resolves **Q3**.)
- *Acceptance:* the same narration script renders to audio via the configured engine; switching engines is a config change, not a code rewrite.

### FR-11 — Auto-synced narration
Use `manim-voiceover` with-blocks so each animation's duration is taken from its audio segment and synced automatically.
- *Acceptance:* in the output MP4, animation beats line up with the spoken words — no manual timing. Re-rendering with a different voice/engine re-syncs automatically (you never hand-tune timings).

### FR-12 — Auto subtitles/captions
Auto-generate captions from the narration.
- *Acceptance:* the pipeline can emit a subtitle track / burned-in captions matching the spoken narration for the scene.

---

## Out of scope

- Per-word / bookmark-level fine timing (a `manim-voiceover` capability, but **[Later]** — deferred to V2).
- Swapping in a *recorded human* voice (FR-33, Phase 6).
- Multi-language (FR-34, Phase 6).
- Anything multi-scene — still one scene here.

## Dependencies

- Phase 1 pipeline (scene spec → code → verified render).
- External: `manim-voiceover`, a TTS engine (gTTS to start).
- Decision: **Q3** (default TTS engine).

## Definition of Done

`generate-scene "<prompt>"` now produces a scene that speaks its own narration with the animation synced automatically and captions available. Swapping the TTS engine is a one-line config change and does not require re-timing the animation. The narration-first ordering is the default generation path.

## Risks & notes

- **You're worried about the wrong thing — voiceover is basically free.** Sync, the genuinely hard part, is handled by `manim-voiceover`'s with-block model. Don't over-engineer it.
- **Narration-first has two big downstream payoffs:** (1) the script makes the visuals more purposeful, and (2) it *shrinks the future editor* — if every scene carries its own synced audio, Phase 4's "editor" is mostly reorder + regenerate + concatenate, not a real NLE.
- Develop with the cheap AI voice so you never re-sync during iteration; the human-recording swap is a few-line change saved for V2 (FR-33).
- Keep the engine abstraction clean now — it's the seam FR-33 and FR-34 plug into later.
