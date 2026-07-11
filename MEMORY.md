# MEMORY.md — Lattice project handoff log

Running memory of this project's state and progress, maintained **across Claude Code sessions**.
Updated on **phase / milestone changes only** — not on individual file edits.

- Each session, Claude reads this at the start of substantive work and appends a dated entry to the **Phase log** when a phase/milestone/task completes.
- Companion docs: `RESUME.md` (one-page build handoff), `MILESTONES.md` (M0→M8 roadmap + DoD), `AGENT_TICKETS.md` (tickets).

---

## Current state (snapshot)

| Milestone | What | State |
|---|---|---|
| M0 | Env spike + Docker render sandbox | ✅ shipped |
| M1 | Scene spec → Manim code + guardrails | ✅ shipped |
| M2 | Verification: compile-repair + vision critic + best-of-N | ✅ shipped |
| M3 | CLI + eval harness + content-hash cache | ✅ shipped |
| M4 | Narrated scene (TTS + sync + captions) | ✅ shipped |
| M5 | Multi-scene video + consistency (**v1 demo**) | ✅ shipped |
| M6 | Editing & human control | ✅ shipped |
| M7 | Web UI + hardened infra | 🧪 code complete — unit gate green; live browser check pending |
| M8 | Polish, moat & V2 | planned |

**Active pipeline:** the web path runs the newer **decoupled + structural** pipeline
(`composition/decoupled.py`, LatticeScene grid scaffold), not the older `composition/video.py`.

**Run it:** `python -m scripts.serve` → http://127.0.0.1:8080 (default port changed from 8000).
Needs Docker Desktop + `lattice-render:0.1` image + `.env` with `LATTICE_LLM_API_KEY`.

---

## Phase log

<!-- Newest first. Append a dated entry when a phase/milestone/task completes. Format: ### YYYY-MM-DD — what changed and why -->

### 2026-07-11 — Seed inputs, code-walkthrough scaffold, Kokoro TTS, deterministic off-frame guards
- **Image + code-snippet inputs** (`be8f57e`): new front doors — image→vision→topic (`web/seed.py`); code→segment-by-segment walkthrough. Both land on the existing `/api/projects` outline gate. Frontend gained Describe/Image/Code tabs.
- **Code-walkthrough deterministic scaffold** (`e65e1b1`): full code stays on screen, the active line highlights, an arrow points to a caption, per-line narration. `generation/code_scaffold.py` + `composition/walkthrough.py` + `planner/code_walkthrough.py` (manifest). Layout fixed in code → reliable on cheap v3, no re-rolls.
- **Kokoro local TTS** (`9fd623f`): `LATTICE_TTS_ENGINE=kokoro` — free/offline neural voice behind the `narration/tts.py` seam; model files in repo root (gitignored). gTTS still the fallback.
- **Off-frame guards** (`c7ed304`, `cca2a72`): `self.graph()` auto-fits y-range so function plots can't overflow; `fit_content()` now SHRINKS any oversized/off-frame content (universal, not just graphs). Off-frame class now solved by construction.
- **Model verdict:** `deepseek-v4-pro` (reasoning, ~4× cost) rendered the SAME scene WORSE than a `v3-0324` re-roll — freeform layout quality is model-INDEPENDENT variance. Keep v3-0324; do NOT use v4-pro. The fix is deterministic scaffolds, not a bigger model or more re-rolls.
- **Next:** comparison-table archetype (`self.table()`) for dense box diagrams + the "weak/sparse scene" mode — the last freeform failure class.

### 2026-07-10 — Established this MEMORY.md handoff log
- Added repo-root `MEMORY.md` as a cross-session memory of project state, updated on phase/milestone changes only.
- Wired a `SessionStart` hook in `.claude/settings.json` so every future Claude session is reminded to read this file and append phase-change entries.
- Changed the web UI default port 8000 → 8080 (`scripts/serve.py`).
