# RESUME.md — Lattice build state & how to continue

One-page handoff. Read this first in any new chat to continue the build without re-deriving anything.
Keep the "Current state" table updated as milestones ship.

---

## ▶️ To continue in a NEW chat (reduce context), paste this:

> This is the **Lattice** project at `c:\Users\Dev\Desktop\Franko` (AI that turns a prompt into a
> narrated multi-scene Manim explainer video). Read `RESUME.md`, `MILESTONES.md`, and
> `AGENT_TICKETS.md`. M0–M5 are already shipped and verified (v1 demo works) — **do not rebuild them**.
> Build the **next milestone** following the same rhythm: write the code, run
> `python -m pytest -m unit -q`, then give me a live check-step and pause for me to confirm.

That's it — the new session has full context from the repo.

---

## Current state

| Milestone | What | State |
|---|---|---|
| M0 | Env spike + Docker render sandbox | ✅ shipped (verified live) |
| M1 | Scene spec → Manim code + guardrails | ✅ shipped (verified live) |
| M2 | Verification loops: compile-repair + vision critic + best-of-N | ✅ shipped (verified live) |
| M3 | CLI + eval harness + content-hash cache | ✅ shipped (verified live) |
| M4 | Narrated scene (TTS + sync + captions) | ✅ shipped (verified live) |
| M5 | Multi-scene video + consistency (**demo**) | ✅ shipped — **v1 demo works** |
| **M6** | **Editing & human control** | ⏭️ **NEXT** |
| M7 | Web UI + hardened infra | planned |
| M8 | Polish, moat & V2 | planned |

**Build order is sequential — do not skip.** M0 → M1 → **M2** → M3 → M4 → M5 (demo) → M6 → M7 → M8.
e.g. M3 (CLI/eval/cache) wraps M2's loops, so M2 must be done before M3.

---

## Environment (already set up on this machine)

- **Python 3.10** (global) already has: pydantic, pydantic-settings, openai, python-dotenv, pytest, gtts, mutagen
  (M4 TTS runs host-side; `pip install -r requirements.txt` on a fresh machine).
- **Docker Desktop** running + image **`lattice-render:0.1`** built (Manim CE v0.18.1 + LaTeX + FFmpeg).
- **`.env`** holds the OpenRouter key (gitignored, local only). Generator = `anthropic/claude-sonnet-4.5`,
  critic = `openai/gpt-4o-mini`. If `.env` is missing (fresh clone), copy `.env.example` → `.env` and paste a key.
- **GitHub:** https://github.com/DevaanshShah/Lattice- (branch `main`).

> On a **fresh machine / clone**: run `python -m scripts.setup_env` to build the Docker image, and
> recreate `.env` from `.env.example` with your key. Everything else is in the repo.

---

## Key commands

| Do | Command |
|---|---|
| Unit gate (must be green to commit) | `python -m pytest -m unit -q` |
| Build/refresh Docker image | `python -m scripts.setup_env` |
| M0 render check | `python -m scripts.render_sample` |
| M1 generate (prompt → spec → code → render) | `python -m scripts.gen_scene "<prompt>" --render` |
| M2 verify (prompt → spec → compile-repair → vision critic) | `python -m verification.run "<prompt>" [--best-of N]` |
| M3 CLI (prompt → verified MP4, cached) | `python -m cli "<prompt>" [--quality final] [--no-cache]` |
| M3 eval battery + regression check | `python -m scripts.run_eval [--limit N] [--set-baseline]` |
| M4 narrate (prompt → spoken, synced, captioned scene) | `python -m scripts.narrate "<prompt>"` |
| M5 generate-video (topic → outline → multi-scene film) | `python -m scripts.generate_video "<topic>" [--yes] [--max-scenes N]` |
| M5 regenerate one scene + re-stitch | `python -m scripts.regen_scene <index>` |
| Quick key test | see "Cheap test" in chat history (gpt-4o-mini, max_tokens=5) |

## See results
- M1 AI video: `out\m1\media\videos\scene\480p15\GeneratedScene.mp4`
- M1 plan + code: `out\m1\spec.json`, `out\m1\scene.py`
- M0 sample video: `out\render\media\videos\scene\1080p60\SampleScene.mp4`

## Push to GitHub
```
git add . && git commit -m "Mx: <summary>" && git push
```

---

## Invariants (hold in every milestone)
1. **Verification two-layered, never conflated** — free compile check gates every paid vision call; nothing hangs (hard caps).
2. **Idempotent by content hash; outline approved before spend** (cache from M3; outline gate from M5).

## Conventions
- Top-level packages at repo root (`core/`, `render/`, `generation/`, …); run from root with `python -m ...`.
- Prompts live in `prompts/*.md` (loaded, not inlined). Pinned versions in `core/config.py`.
- Tests: `unit` (no net/docker/model), `integration` (needs docker), `llm` (needs key) — unit is the commit gate.
