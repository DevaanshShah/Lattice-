# Phase A + B — status

**Branch:** `phase-ab-reliability` · **Worktree:** `C:\Users\Dev\Desktop\Franko-phaseab`
**Base:** `1dcc164` (main) · **Date:** 2026-09-04
**Gate:** `358 passed` (was `313` at base — 45 new tests, 0 changed, 0 removed)
**Committed:** yes, on `phase-ab-reliability`. Nothing here is in your main checkout.

Answers section 9 of `CLAUDE_CODE_HANDOFF.md`: Phase B (make configured limits real) and Phase A
(make failures visible and bounded). Phases C and D are untouched.

---

## 1. Why this is on a branch, not in your tree

While I was working, a second session was writing to `C:\Users\Dev\Desktop\Franko` — the admin
console / usage-ledger feature (`core/usage.py`, `web/admin.py`, `web/users.py`,
`web/static/admin.*`, plus edits to `web/app.py`, `web/jobs.py`, `composition/decoupled.py`,
`web/decks.py`, `web/learn.py`, `composition/pool.py`). Files changed underneath me mid-session:
`web/jobs.py::_run` gained a `usage.bind(...)` wrapper and the scene fan-out gained `usage.carry(...)`
between two of my reads.

Two writers on one tree means whoever writes a whole file last wins, silently. So this work moved to
an isolated git worktree, and **every edit I had made to your live tree was reverted** — that tree's
diff against `HEAD` is now purely the other session's work, and its gate is back to `313 passed`.

One correction worth stating plainly: the revert initially dropped a docstring terminator in
`composition/decoupled.py`, which broke collection in the live tree for about a minute. It is fixed,
the file parses, and the 313 gate is green again.

---

## 2. Phase B — the configured limits are now real

The failure this closes: `.env` said `LATTICE_SCENE_WORKERS=6`, the code said `workers=3`, and you
were tuning a knob wired to nothing.

| Change | File |
|---|---|
| `JobQueue(workers=2)` → `workers=settings.job_workers` | `web/app.py` |
| `build_video(workers=3, retries=3)` → `None` defaults resolved from `settings.scene_workers` / `scene_retries` (an explicit argument still overrides, for evals) | `composition/decoupled.py` |
| New `scene_retries`, `scene_retry_backoff_s`, `llm_timeout_s`, `llm_attempts`, `job_deadline_s`, `scene_deadline_s` | `core/config.py` |
| Real client timeout: `OpenAI(..., timeout=settings.llm_timeout_s, max_retries=0)` | `core/llm.py` |
| `_create(attempts=6)` → `settings.llm_attempts` | `core/llm.py` |
| The retry backoff no longer sleeps after the **last** attempt (was 10s of dead time on every failed scene) | `composition/decoupled.py` |
| The build log now prints every bound up front: `caps: compile-repair x4, critic x3, llm x6 @ 120s, render 600s` | `composition/decoupled.py` |

**`max_retries=0` is the important one.** The OpenAI SDK retries transient errors on its own, on top
of our six-attempt loop — up to 18 hidden attempts per call, each waiting on the SDK's 10-minute
default timeout before our policy got a turn. `_create` is now the single retry authority, with a
real per-call deadline.

**Defaults are unchanged** (3 / 2 / 3 / 6), so behaviour is identical until you move a knob.

**Acceptance (handoff §9 Phase B):** verified — env vars alone change the runtime.

```
LATTICE_SCENE_WORKERS=6 LATTICE_JOB_WORKERS=4 LATTICE_LLM_TIMEOUT_S=45 \
LATTICE_LLM_ATTEMPTS=2 LATTICE_SCENE_RETRIES=1  →  6 / 4 / 45.0 / 2 / 1
(no env)                                        →  3 / 2 / 120.0 / 6 / 3
```

Covered by `tests/test_config_budgets.py` (6 tests).

---

## 3. Phase A — failures are visible and bounded

### 3.1 Cooperative cancellation (`core/cancel.py`, new)

A build is minutes of nested loops, so "stop" has to be something the pipeline *asks about* — killing
a worker mid-render would strand a Docker container and half-written files. A `CancelToken` is
installed **ambiently** (thread-local) by the job runner; deep modules just call `cancel.check()`.
No `cancel=` parameter is threaded through a dozen signatures, and no module below `web/` learns
about the web layer.

- `cancel.carry(fn)` moves the token across the thread hop into the scene pool — the same idiom as
  the existing `usage.carry`, and necessary because thread-locals do not inherit.
- `Cancelled` derives from **`BaseException`**, like `asyncio.CancelledError` and for the same
  reason: this pipeline is full of `except Exception` handlers that retry or degrade, and every one
  of them would otherwise swallow a stop request and keep spending.
- With no token installed (CLI, evals, existing tests) every check is a no-op.

Checkpoints, chosen so a stop costs nothing already paid for:

| Where | Effect |
|---|---|
| `core/llm.py::_create`, top of the attempt loop | never spends another model call |
| `verification/compile_repair.py`, each repair attempt | never re-renders |
| `verification/vision_critic.py`, each critic round | never pays for another vision call |
| `render/sandbox.py::render`, before the container starts | never starts a fresh render |
| `composition/decoupled.py`, before each scene attempt + before stitch | a stopped scene is given up, not retried; a stopped build raises instead of stitching |

**Bound, stated honestly:** cancellation is cooperative, so a stop takes effect at the next
checkpoint. Worst case that is one in-flight render (`render_timeout_s`, default 600s). Killing the
container on cancel would tighten this and is not done here.

### 3.2 Deadlines

`job_deadline_s` (3600) bounds the whole job; `scene_deadline_s` (900) bounds one scene including
its rebuilds, and is per-thread so parallel scenes each get their own clock. Both trip the same
token, so a job that runs out of time ends as `cancelled` with *"ran past its time limit — it was
not hung, it was still retrying"* rather than as a mystery `APITimeoutError`. Set either to `0` to
disable.

### 3.3 Named steps (`web/phases.py`, new)

The UI could say "Thinking…", "Scene 2", "Merging" and nothing else. There is now a real vocabulary —
`planning · style · scene_spec · codegen · render · lint · vision · narration · mux · stitch ·
retrying · complete · failed · cancelled` — with user-facing wording per step.

It is derived from the narration the pipeline **already** emits (`[compile] attempt 2/4`,
`[critic] iter 1/3`, devtrace's `[llm#3] codegen · …`, the `-> stitching` say-lines) rather than by
threading a phase callback through every module. That is a deliberate trade: one module owns the
vocabulary and is unit-tested against the literal strings the pipeline emits today (13 of them), and
if a log line is reworded a test fails rather than the UI silently going quiet. `classify()` returns
`None` for detail lines, so the step persists instead of flickering.

`web/devtrace.py` also learned to label the scene-spec call `spec` (it was being reported as
`codegen`/`outline`).

### 3.4 Job state and API (`web/jobs.py`, `web/app.py`)

- `Job` carries `step`, `attempt` ("2/4"), `step_started_at`, and its own `CancelToken`.
- `progress()` adds `step`, `step_label`, `attempt`, `elapsed`, `step_elapsed`, `cancellable`,
  `cancelled` — and keeps every existing key, so the cylinder UI is unaffected. Elapsed is whole
  seconds on purpose: the SSE stream pushes on change, and a float clock would push 4×/second.
- New terminal state `cancelled`, distinct from `failed` — pressing Stop is not a crash.
- `POST /api/jobs/{id}/cancel` → `{accepted, status, progress}`. Idempotent; an already-finished job
  reports `accepted: false` rather than erroring.

### 3.5 UI (`web/static/app.js`)

Under the percentage: `Rendering · attempt 2/4 · 3:41`, plus a **Stop** button that reads
"Stopping…" until the job's own terminal status arrives. A cancelled build returns to the outline
screen instead of alerting "Build failed".

**Caveat:** this was written against the **committed** `app.js`. Your live tree has uncommitted UI
work in that file, so this needs re-applying rather than merging blind. It is four small, clearly
delimited edits (`followJob`, `approveGenerate`, `genInner`, one `wire()` case) — the patch script
is at `scratchpad/patch_appjs.py`. `node --check` passes.

### 3.6 Acceptance (handoff §9 Phase A)

| Criterion | State |
|---|---|
| UI names the failing phase | done — step + attempt + elapsed, streamed |
| bounded retries shown | done — `attempt` surfaced from the pipeline's own counters |
| cancellation | done — endpoint, token, checkpoints, Stop button |
| successful earlier scene clips preserved | done — a stopped build does not stitch, does not delete; finished clips stay on disk in the project workspace and stay visible in `job.scenes` |
| **the same, driven by a real failing scene end to end** | **not done** — needs Docker + a live model, which the handoff says not to run unattended |

---

## 4. Tests

45 new, all `unit` (no network, no Docker, no model):

- `tests/test_config_budgets.py` (6) — every knob moves the runtime; explicit args still override.
- `tests/test_cancel.py` (29) — token semantics, deadlines, `BaseException` behaviour, `carry`
  across a thread hop, each pipeline checkpoint, and the 13 real log lines the classifier reads.
- `tests/test_phase_a_jobs.py` (10) — step tracking, elapsed, cancel of a queued and of a running
  job, deadline wording, partial scenes after a stop, the endpoint.

```powershell
cd C:\Users\Dev\Desktop\Franko-phaseab
C:\Users\Dev\Desktop\Franko\.venv\Scripts\python.exe -m pytest -m unit -q     # 358 passed
```

(The worktree has no `.venv` of its own; the main checkout's interpreter works from this directory.)

---

## 5. Merging this back — measured, not guessed

Run as a real three-way merge (`git merge-file --diff3`) with `HEAD` as the base, this branch as
*ours* and the live tree's current working copy as *theirs*, line endings normalised (the repo is
`core.autocrlf=true`, so an un-normalised compare reports every file as conflicting).

| File | Conflicts |
|---|---|
| `core/config.py` | 0 — clean |
| `core/llm.py` | 0 — clean |
| `web/devtrace.py` | 0 — clean |
| `web/static/app.js` | 0 — clean (my edits and the uncommitted UI work are in different regions) |
| `verification/compile_repair.py`, `verification/vision_critic.py`, `render/sandbox.py` | 0 — clean |
| `core/cancel.py`, `web/phases.py`, `tests/*`, `DECISIONS.md`, `PHASE_AB_STATUS.md` | new files, nothing to merge |
| `composition/decoupled.py` | **1** |
| `web/app.py` | **1** |
| `web/jobs.py` | **2** |
| `MEMORY.md` | **1** |

**All four conflicts are additive-on-additive** — both sides inserted at the same line, neither
deletes the other's code. The union resolution for each:

1. `composition/decoupled.py` — the fan-out wrapper. Both wrap the same lambda. Resolve as
   `build_one = cancel.carry(usage.carry(<lambda>))` and close with three parens. (This is exactly
   what the live tree held before the revert, so it is known to work: 319 passed at the time.)
2. `web/app.py` — the import block. Keep both `from core import usage` and
   `from core.config import settings`.
3. `web/jobs.py` (a) — the import block. Keep `from core import cancel, usage`, plus
   `from core.config import settings` and `from web import phases`.
4. `web/jobs.py` (b) — `_run`. Nest the two: their `with usage.bind(attr or usage.current()):`
   outermost, then my `with cancel.scope(job.token):`, keeping my `except cancel.Cancelled` clause
   ahead of `except Exception` and their `usage.record("job", ...)` line at the end.
5. `MEMORY.md` — both sessions appended a phase-log entry at the same anchor. Keep both, newest first.

Nothing else in either tree is touched by the other side.

---

## 6. Not done, and known limits

- **No live end-to-end run.** Everything above is proven by unit tests and by reading the code. The
  handoff's definition of done also requires one authorized live build; that has not been run.
- **Cancellation granularity** — one in-flight render, as described in 3.2.
- **Phase C (Draft vs Final) and Phase D (model ladder)** — untouched.
- **`MODEL_PRICES` is still missing `deepseek-v4-flash*` and `openai/gpt-5.6-terra`** (Phase D item
  4). Note the handoff is out of date on one point: `deepseek-chat-v3-0324` **is** now in the table
  in both id forms, so the live generator is priced; unknown models still report `$0` while
  recording tokens. Separately, the other session's `_record_usage` now prefers the provider's own
  reported cost when OpenRouter returns one, which makes the table matter less than it did.
- **`_infer_kind` in devtrace is heuristic** — it reads prompt text. It is right for today's
  prompts; reword a system prompt and a call may be labelled with the wrong step.
