# PRD — Phase 0: Environment Spike

**Goal:** De-risk the environment before writing any product code. The hard part of this whole project at the start is *not* the AI — it's getting Manim CE + LaTeX + FFmpeg installed and rendering reliably. This phase exists only to prove that path works end-to-end. The code is deliberately throwaway.

> Context: see `PRD-00-overview.md` for vocabulary and the full FR catalog. This phase introduces no product FRs; it validates the substrate that **FR-2** (codegen) and **FR-22** (render worker) will depend on.

---

## Why this phase exists

Every downstream phase assumes "given Manim code, we can render an MP4." If that assumption is shaky, everything built on top inherits flaky renders and you'll waste days debugging the AI when the real problem is a missing LaTeX package or an FFmpeg path issue. Pay this cost once, up front, in isolation.

## In scope

1. **Reproducible install** of Manim CE (pinned version — resolves **Q2**), LaTeX (the subset Manim needs for `Tex`/`MathTex`), and FFmpeg.
   - *Acceptance:* a single documented command/script produces a working environment from clean. Re-running it on a fresh machine/container succeeds without manual fixes.
2. **Render a hand-written scene** end-to-end (no AI involved).
   - *Acceptance:* a checked-in `.py` Manim scene renders to an MP4 that plays, containing both a shape animation and a `MathTex` expression (proves LaTeX works, the most common breakage).
3. **Render in both a fast preview quality and a final quality.**
   - *Acceptance:* the same scene renders at low-res quickly and high-res slowly via a documented flag. (This is the seed of **FR-26**, not the feature itself.)
4. **Capture a single keyframe as a PNG** from a render.
   - *Acceptance:* one frame can be exported as an image. This is the hook the **vision critic** (FR-6) will later use; prove it's mechanically possible now.
5. **Decide and document Q5** for the build's early life: local single-process vs containerized render.
   - *Acceptance:* a one-paragraph written decision with rationale, plus — if containerized — a working Dockerfile that does items 1–4 inside the container.

## Out of scope

- Any LLM/AI integration. (No prompt → code yet.)
- Any CLI or product structure. Throwaway scripts are fine.
- Voiceover, multi-scene, style spec — nothing past "a single scene renders."
- Sandboxing/security (FR-23) — deferred until multi-user (Phase 5).

## Dependencies

- External: Manim CE, a LaTeX distribution, FFmpeg.
- Decisions: **Q2** (Manim version), **Q5** (local vs container).

## Definition of Done

A teammate (or future-you on a clean machine) can run one documented script and, within minutes, render the provided sample scene — shapes + a LaTeX equation — to a playable MP4 at both preview and final quality, and export one frame as a PNG. The local-vs-container decision is written down.

## Risks & notes

- **LaTeX is the #1 source of pain.** Don't install "all of TeX Live" blindly if you can avoid it, but do verify `MathTex` actually compiles — a Manim install that renders shapes but chokes on equations *looks* fine and isn't.
- **Pin the Manim version (Q2) here and everywhere after.** Manim CE's API drifts; an unpinned version will silently break codegen prompts you tune in Phase 1.
- Resist the urge to start building product structure in this phase. Its entire value is being throwaway and fast.
