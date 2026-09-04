# Decision log

Why the code is the way it is. Newest first. One entry per decision that a future reader could
reasonably second-guess — the alternative that was rejected matters more than the choice that was
made. Format: `### YYYY-MM-DD — decision` with **Context / Decision / Why not the alternative /
Consequence**.

Companion docs: `MEMORY.md` (phase log — what happened when), `PHASE_AB_STATUS.md` (the Phase A+B
handoff), `CLAUDE_CODE_HANDOFF.md` (the engineering brief this work answers).

---

### 2026-09-04 — `scripts/merge_check.py` instead of eyeballing the two trees

**Context.** The reconciliation question is "does this branch merge into the other checkout", but
the other side's work is uncommitted and on no branch, so `git merge` and `git diff <branch>` have
nothing to compare against.

**Decision.** A small tool that runs the same three-way merge git would (`git merge-file --diff3`)
per tracked file — merge base as base, this branch as ours, the other tree's working copy as theirs
— and exits with the number of conflicting files.

**Why not the alternative.** Reading both diffs by hand scales badly and is wrong quietly. The first
manual attempt reported *every* file as conflicting because the repo is `core.autocrlf=true` and a
blob (LF) never matches a working file (CRLF); the tool normalises line endings, which is exactly
the kind of detail a human check forgets on the second run.

**Consequence.** "Check for conflicts" is now a command with an exit code, so it can gate a merge.
It compares working copies, so its answer is a snapshot — re-run it before actually merging.

### 2026-09-04 — Phase A+B lives on a branch in a separate worktree, not in the main checkout

**Context.** A second agent session was writing to `C:\Users\Dev\Desktop\Franko` at the same time
(the admin-console / usage-ledger feature). Files changed underneath a read: `web/jobs.py::_run`
gained `usage.bind(...)` and the scene fan-out gained `usage.carry(...)` between two reads of the
same region, minutes apart.

**Decision.** Move the reliability work to `C:\Users\Dev\Desktop\Franko-phaseab`, branch
`phase-ab-reliability`, based on `1dcc164`; revert every edit made to the live tree so it holds only
the other session's work.

**Why not the alternative.** Continuing in the shared tree with exact-match anchors fails loudly on
a changed region — but only for *edits*. A whole-file write from the other side lands silently and
takes the other party's work with it, and neither session notices until tests fail for a reason
neither can explain.

**Consequence.** Two trees to reconcile, and the branch's `web/static/app.js` is based on the
COMMITTED file rather than the uncommitted UI work in the live tree. A three-way merge test
(recorded in `PHASE_AB_STATUS.md` §5) says the reconciliation is four conflicts, all additive on
both sides, all with union resolutions.

---

### 2026-09-04 — `Cancelled` derives from `BaseException`, not `Exception`

**Context.** The pipeline is deliberately full of `except Exception` handlers that retry a scene,
degrade to a silent clip, or skip a nice-to-have step. There are 30+ of them between `composition/`,
`verification/`, `narration/` and `web/`.

**Decision.** `core.cancel.Cancelled(BaseException)`, matching `asyncio.CancelledError`. Code that
must observe a stop (`JobQueue._run`, `_build_with_retry`) catches it explicitly by name.

**Why not the alternative.** Subclassing `Exception` means every one of those handlers swallows a
stop request and keeps spending money — the retry loop would treat "the user pressed Stop" as "the
provider hiccupped" and try again. Auditing and special-casing 30 handlers is a change that silently
rots the first time someone adds handler 31.

**Consequence.** A bare `except Exception` will not catch cancellation, which is the point; anything
that genuinely needs to clean up on cancel must use `finally` or catch `cancel.Cancelled` by name.

---

### 2026-09-04 — The cancel token is ambient (thread-local), not a `cancel=` parameter

**Context.** The stop switch has to be visible at every checkpoint: model call, compile repair,
critic round, render, scene scheduling. Threading a parameter there means touching ~12 signatures
across four packages, and every one of them then knows the web layer exists.

**Decision.** `web.jobs.JobQueue._run` installs the token for the job's thread; deep modules call
`cancel.check()` with no arguments; `cancel.carry(fn)` re-installs it across the hop into the scene
pool, mirroring the existing `usage.carry` idiom in this codebase.

**Why not the alternative.** Explicit parameters are easier to trace, but the diff would be large,
would collide with the other session's work in exactly those signatures, and would make every future
call site remember to forward `cancel=`. Forgetting is silent: the step simply becomes unstoppable.

**Consequence.** With no token installed (CLI, evals, tests) every check is a no-op, so nothing
outside the web path changes behaviour. The cost is that "who can be cancelled" is not visible from
a signature — `cancel.check()` call sites are the map.

---

### 2026-09-04 — Cancellation is cooperative; it does not kill the render container

**Decision.** A stop takes effect at the next checkpoint. Worst case that is one in-flight render,
bounded by `render_timeout_s` (600s default).

**Why not the alternative.** `docker kill` on the running container would stop it inside a second,
but it strands half-written media files and a partially-populated work dir that the recovery path
would then have to distinguish from a genuine crash. Not worth it for the first cut.

**Consequence.** The UI says "Stopping…" and waits for the job's own terminal status, rather than
claiming the job ended when it hasn't. Tightening this is a known follow-up.

---

### 2026-09-04 — The current step is derived from the pipeline's log narration

**Context.** The UI knew only "Thinking… / Scene k / Merging". The pipeline already narrates itself
in detail (`[compile] attempt 2/4`, `[critic] iter 1/3`, devtrace's `[llm#3] codegen · …`,
`-> stitching`), and `web/devtrace.py` already labels every model call.

**Decision.** `web/phases.py` classifies those existing lines into a named vocabulary; `Job.log()`
applies it. No phase callback is threaded through the pipeline.

**Why not the alternative.** An explicit `on_phase(...)` callback is type-safe and would not break
if a log line is reworded — but it means editing every module in the build path (again, in the
regions the other session is editing) and teaching `composition/` and `verification/` about a web
concept. The classifier keeps that knowledge in one file, in the layer that needs it.

**Consequence.** The coupling is to log strings. It is pinned by unit tests asserting on 13 literal
lines copied from the source, so rewording a log line fails a test instead of silently blanking the
UI. `classify()` returns `None` for unrecognised lines and the step persists, so an unclassified
line is never worse than the status quo.

---

### 2026-09-04 — `max_retries=0` on the OpenAI client; `_create` is the only retry loop

**Context.** `LLMClient._create` retries transient errors up to six times. The OpenAI SDK also
retries by default (2), and with no `timeout=` set it waits on its own 10-minute default first.

**Decision.** `OpenAI(..., timeout=settings.llm_timeout_s, max_retries=0)`.

**Why not the alternative.** Leaving the SDK's retries on gives up to 18 attempts per logical call,
none of them visible in our telemetry, each potentially waiting ten minutes. That is a large part of
what "the job looks hung" actually was.

**Consequence.** Worst case per call is now `llm_attempts × llm_timeout_s` and both are in `.env`.
If a provider needs longer than 120s for a legitimate response, raise `LATTICE_LLM_TIMEOUT_S`
rather than restoring SDK retries.

---

### 2026-09-04 — Deadlines end a job; caps only bound repetition

**Decision.** Two new bounds — `job_deadline_s` (3600) and `scene_deadline_s` (900, per thread) —
trip the same cancel token as a user Stop.

**Why not the alternative.** The existing caps (`max_repair_attempts`, `max_critic_iters`,
`scene_retries`) bound how many times a step repeats, not how long the whole thing takes; multiplied
together they permit a job to run for hours while looking identical to a hang. A deadline converts
that into an ended job with a stated reason.

**Consequence.** A legitimately slow build can now be killed by its own deadline. Both default
generously and `0` disables either.

---

### 2026-09-04 — Settings resolve inside `build_video`, not at the call site

**Decision.** `workers`/`retries` default to `None` and are resolved from `settings` inside
`build_video`; an explicit argument still wins.

**Why not the alternative.** Passing `settings.scene_workers` from `web/engine.py` fixes the web
path only and leaves the CLI, evals and `scripts.selftest` on the literals — the same class of bug
one layer up.

**Consequence.** `.env` is the single control for every caller, and evals can still pin a value for
one run.

---

### 2026-09-04 — A stopped build does not stitch, and does not delete

**Decision.** On cancel, `build_video` raises instead of stitching. Scene clips already rendered
stay on disk in the project workspace, and finished scenes stay visible in `job.scenes`.

**Why not the alternative.** Stitching anyway produces a video the user cancelled and did not ask
for; deleting the clips throws away work already paid for. Doing neither leaves the boot-time
recovery path (which already stitches half-built projects) able to salvage them.

**Consequence.** After a stop there is no `final.mp4` until something stitches the survivors. That
is a deliberate gap, not an oversight.

---

### 2026-09-04 — This file exists

**Context.** The user asked for a decision record to be maintained as work proceeds.

**Decision.** `DECISIONS.md` at the repo root, appended whenever a choice is made that a reader
could reasonably second-guess. `MEMORY.md` stays the dated phase log (what happened);
`DECISIONS.md` holds the reasoning (why it was done that way, and what was rejected).

**Consequence.** Two files to keep current. The split is deliberate: a phase log read in order tells
the story, a decision log read by lookup answers "why is this like this".
