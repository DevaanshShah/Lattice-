# PRD — Phase 4: Editing & Human Control

**Goal:** Give the human real control over a generated video without it becoming a video editor. Because every scene already carries its own synced audio (Phase 2), "editing" stays at the scene level: regenerate, reorder, tweak, roll back. **This is a list with a stitch button, not Premiere** (non-goal **N1**).

> Context: see `PRD-00-overview.md`. Builds on the Phase 3 scene-DAG and isolated single-scene regeneration (FR-16).

**Headline demo:** fix scene 7, re-stitch, ship — without rebuilding the other scenes.

---

## In scope (FRs — all [Later] features, now being built)

### FR-17 — Reorder / add / delete scenes
Change the scene order, insert a new scene at a position, or remove one.
- *Acceptance:* reordering re-stitches in the new order without re-rendering unchanged scenes; inserting generates only the new scene (inheriting the video's style spec); deleting removes it and re-stitches. The scene DAG stays consistent throughout.

### FR-18 — Edit narration text + re-time
Let the user edit a scene's narration script; regenerate audio and re-sync.
- *Acceptance:* editing the narration for scene *k* re-runs TTS + `manim-voiceover` sync for that scene only and updates the final video; other scenes are untouched. Captions (FR-12) update to match.

### FR-19 — Per-scene tweak prompts
Natural-language nudges to a single scene ("move the cache box left", "slow this down") that re-generate just that scene.
- *Acceptance:* a tweak prompt produces a revised scene reflecting the instruction, passes the same verification loops (FR-5/FR-6), and re-stitches — without affecting other scenes.

### FR-20 — Project save/load/persistence
A video = its scene DAG + specs + style spec + renders, saved and reloadable across runs.
- *Acceptance:* a saved project reopens with all scenes, their specs, narration, the style spec, and existing renders intact; you can resume editing exactly where you left off. (This is the first phase where state survives between runs — Phases 0–3 were ephemeral.)

### FR-21 — Per-scene version history + rollback
Keep prior good renders/specs per scene; roll back to a previous version.
- *Acceptance:* after regenerating or tweaking scene *k*, the previous version is recoverable and selecting it re-stitches the video using that earlier render. History is per-scene, not global.

---

## Out of scope

- Web UI for any of this (Phase 5) — these are exposed via the CLI/engine first.
- Job queue, sandboxing, render caching as infrastructure (Phase 5). *Note:* FR-17/FR-20 benefit hugely from reusing prior renders; do reuse them, but the formal caching feature (FR-25) is Phase 5.
- Voice swap, multi-language, templates (Phase 6).

## Dependencies

- Phase 3: scene-DAG model (FR-13), isolated regeneration (FR-16), style spec (FR-4) so inserted scenes match.
- Phase 2: narration-first + sync (FR-9/FR-11) so narration edits re-time cleanly.

## Definition of Done

A user can take a Phase 3 video and, entirely at the scene level: reorder/add/delete scenes, edit a scene's narration and have it re-time, nudge a scene with a tweak prompt, save the project and reopen it later, and roll any scene back to a previous version — each operation re-stitching the final video while leaving untouched scenes untouched. No frame-level editing exists, by design.

## Risks & notes

- **Stay disciplined against N1.** The gravitational pull here is toward building a timeline/NLE. Every feature in this phase operates on *scenes*, not frames or clips. If a request implies frame-level editing, it's out of scope.
- **Isolation is the whole game.** Each operation must touch only the affected scene(s) and reuse everything else. If editing one scene forces a full re-render, the UX (and your render budget) collapses.
- Persistence (FR-20) is what makes the tool feel real rather than a one-shot generator — but it also means schema stability matters. Lean on the scene spec schema locked in Phase 1; version your saved-project format so future changes don't orphan old projects.
- These scene-level primitives are exactly what Phase 5's web UI will wrap — design the engine API for them cleanly now so the UI is a thin layer.
