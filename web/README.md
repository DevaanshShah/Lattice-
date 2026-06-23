# web/

The browser skin over the engine, so a non-coder never sees Python. Built in **M7** (Phase 5). **Stays a thin layer** over the Phase 4 engine API — no scene logic re-implemented in the frontend; every endpoint delegates to `web/engine.py`, which delegates to the M1–M6 modules.

**Owns**
- `engine.py` — the facade the HTTP layer talks to. Adds only MULTI-PROJECT workspaces (`out/web/<pid>/`); everything else delegates to planner / `composition.video` / `composition.regen` / `editing.*` / `composition.export`.
- `app.py` — FastAPI app (`create_app(engine, queue)` is injectable for tests). Prompt → outline-approval gate → async build → per-scene preview/regenerate/tweak/narration/reorder/insert/delete → download (**FR-28**). Quality toggle preview|final on every render endpoint (**FR-26**).
- `jobs.py` — `JobQueue`: render jobs are async on a bounded thread pool, status queued → running → done/failed with per-scene state; users don't block each other (**FR-24**). Append-only event log + replay cursor backs SSE streaming so the user reviews scene 1 while scene 8 renders (**FR-29**).
- `static/` — the thin frontend (`index.html` + `app.js` + `style.css`).
- `export` — `composition/export.py`: download the final MP4, with merged captions as a burned-in track or a separate `.srt` (**FR-30**).

Pairs with `render/sandbox` hardening (**FR-23**): resource caps (`--memory`/`--cpus`/`--pids-limit`), wall-clock container kill, opt-in read-only root FS + tmpfs, all on top of the day-one no-network + non-root + `--rm` guarantees. Containment harness: `lattice render-sandbox <file.py>`.

**Run:** `python -m scripts.serve` (or `lattice serve`) → http://127.0.0.1:8000. The HTTP layer is unit-tested with fakes (`tests/test_m7_*`); live browser flow needs the LLM key + Docker.

**Maps to:** Phase 5 / M7. **FRs:** FR-28, FR-24, FR-29, FR-30, FR-26 (+ FR-23 hardening).
