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

### 2026-07-10 — Established this MEMORY.md handoff log
- Added repo-root `MEMORY.md` as a cross-session memory of project state, updated on phase/milestone changes only.
- Wired a `SessionStart` hook in `.claude/settings.json` so every future Claude session is reminded to read this file and append phase-change entries.
- Changed the web UI default port 8000 → 8080 (`scripts/serve.py`).
