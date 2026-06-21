# PRD — Phase 1: One Non-Broken Scene

**Goal:** Given a natural-language prompt for a *single* scene, reliably produce a clean animated scene where objects don't overlap, nothing runs off-screen, and the result actually reflects the prompt. This is the most important phase in the project — the entire product's quality is won here, in the two verification loops.

> Context: see `PRD-00-overview.md` for vocabulary (scene, scene spec, vision critic, best-of-N) and the FR catalog. Depends on Phase 0's working render environment.

**Headline demo:** `generate-scene "explain a hash map collision"` → a clean, non-broken animated scene, no human touch-up.

---

## In scope (FRs)

### FR-1 — NL prompt → scene spec
Generate a structured (JSON) **scene spec** from the prompt *before* generating any code: objects present, rough layout intent, the single narration line (placeholder for now — full narration is Phase 2), and the animation beats.
- *Acceptance:* the same prompt yields a valid scene spec conforming to a locked JSON schema; invalid model output is rejected and regenerated, not passed downstream.

### FR-2 — Scene spec → Manim code
Generate Manim CE code from the scene spec.
- *Acceptance:* for a battery of ≥10 varied test prompts, generated code targets the pinned Manim version and produces a render after the repair loop (FR-5) on every one.

### FR-5 — Compile-check + auto-repair loop
Render the generated code; on failure, feed the traceback back to the model and retry.
- *Acceptance:* a deliberately-broken generation (e.g. undefined mobject) is recovered automatically within the retry cap; the loop logs each attempt.

### FR-6 — Vision-critic loop *(the load-bearing feature)*
Render a keyframe (or a few), pass the PNG(s) to a vision model, and check for: overlapping elements, off-screen elements, and mismatch with the prompt's intent. Feed concrete fixes back into generation and re-render.
- *Acceptance:* a scene that compiles but is visually broken (two labels stacked on top of each other, or an object pushed off-frame) is detected and corrected without a human flagging it. Critic output is structured (issue type + location + suggested fix), not free prose.

### FR-7 — Retry/step caps + graceful failure
Hard caps on repair attempts and critic iterations; never hang or loop forever.
- *Acceptance:* when a scene can't be fixed within caps, the system fails cleanly with a useful error and the best attempt so far — it does not spin.

### FR-8 — Manim API guardrails
Constrain generation to Manim CE conventions: no CE/GL mixing, no deprecated calls, house conventions for positioning.
- *Acceptance:* generated code never imports/uses the GL/OpenGL renderer path; deprecated-API usage is caught (lint or prompt-level) before render.

### FR-22 — Local render worker
A single local process that renders a scene to MP4 + a keyframe PNG.
- *Acceptance:* callable as a function the loops above can invoke repeatedly within one run.

### FR-27 — CLI core
The engine, driven from the command line: `generate-scene "<prompt>"` → MP4.
- *Acceptance:* one command runs the full pipeline (spec → code → render → repair → critic → final MP4) and writes the output path.

### Best-of-N (optional within this phase)
If budget (**Q1**) allows, generate N candidate scenes, run each through FR-5/FR-6, and keep the highest-scoring.
- *Acceptance:* with N>1, the kept scene is measurably at least as good (fewer critic-flagged issues) as N=1 on the test battery.

---

## Out of scope

- Narration/TTS/subtitles (Phase 2).
- Multi-scene, planner, style spec (Phase 3).
- Editing, persistence, web UI (Phases 4–5).
- Best-of-N is allowed but not required; don't let it block the core loop.

## Dependencies

- Phase 0 render environment (Manim + LaTeX + FFmpeg, keyframe-PNG export).
- Decisions: **Q1** (model + budget — gates best-of-N and critic re-render width), **Q2** (Manim version).

## Definition of Done

Running `generate-scene "<prompt>"` on the ≥10-prompt test battery produces, for every prompt, a single MP4 that compiles, has no vision-critic-flagged overlap/off-screen issues, and visibly matches the prompt — with zero manual intervention. The scene spec JSON schema is locked and documented. The repair and critic loops both respect their caps and fail gracefully.

## Risks & notes

- **The vision critic is the whole differentiator.** Existing open-source text→Manim tools skip it and that's exactly why they look like demos. Budget real iteration time here; this is the moat.
- **The model is animating blind** — it writes positioning code with no eyes. The critic is what gives it eyes. Don't expect good layout from prompt-engineering alone.
- **Lock the scene spec schema in this phase.** Everything downstream (regeneration, style spec, persistence) keys off it. Changing it later is expensive.
- Keep the critic's output *structured*. Free-text critiques are hard to feed back reliably; typed issues (overlap / off-screen / intent-mismatch + location) close the loop cleanly.
