# Decision log

Why the code is the way it is. Newest first. One entry per decision that a future reader could
reasonably second-guess — the alternative that was rejected matters more than the choice that was
made. Format: `### YYYY-MM-DD — decision` with **Context / Decision / Why not the alternative /
Consequence**.

Companion docs: `MEMORY.md` (phase log — what happened when), `PHASE_AB_STATUS.md` (the Phase A+B
handoff), `CLAUDE_CODE_HANDOFF.md` (the engineering brief this work answers).

---

### 2026-10-09 — The video regression compares against local videos rendered with silent narration

**Context.** Nothing checked how a learning video looks; the 2026-09-23 renderer change passed
every test and made videos worse. A check has to be free to run, repeatable, and able to tell
"the code changed the picture" from noise.

**Decision.** `scripts/video_regression.py` re-renders plans kept in git
(`tests/fixtures/video_golden/`) with silent audio whose length comes from each beat's word count,
and compares every frame with FFmpeg's SSIM filter against approved videos stored under
`out/video_regression/baseline/`, which is not in git. A changed frame is reported for a person to
judge on a contact sheet; it is not a failure by itself.

**Why not the alternative.** Real narration: the voice engine decides beat length, so frames move
when the voice changes and a diff means nothing. Baseline videos in git: tens of megabytes of
binaries that depend on this machine's fonts and Chrome. A vision model as judge: the research
found such judges rate visibly broken layouts as fine. Pillow or another image library: a new
dependency for something FFmpeg already does.

**Consequence.** A fresh clone has no baseline until the regression is run once and accepted, so
the first run on a new machine cannot detect a change. Two runs of the same code match at SSIM
1.0000 on this machine, so the threshold of 0.995 flags real differences only.

---

### 2026-10-09 — Keep the structured-plan architecture; work in gated phases behind a harness

**Context.** After two sessions of fixing the new learning-video path one failure at a time, the
owner asked whether the approach itself was right. A full audit found twelve problems, five
serious, and no test of how a new-path video looks. A web research pass compared this design with
model-written Manim code, slide systems, video frameworks and generative video.

**Decision.** Keep "the model writes a typed plan, fixed code draws it, rules check it". Do the
remaining work as the phases in `docs/learning-video-hardening-plan-2026-10-09.md`: a checkpoint
and regression harness first, then offline correctness and look fixes, then prompt changes
measured against a live baseline. Each phase has a gate and is reverted if the gate fails.

**Why not the alternative.** Model-written animation code: in the one direct published test a
typed plan rendered 99.8% of the time against 82.5%, and layout is that family's weakest part.
Slides: as reliable, but static. Generative video: the best model gets a quarter of on-screen
words wrong. Continuing without a harness: the 2026-09-23 renderer change made videos look worse
while every test passed. A layout engine now: it adds a dependency the original plan forbids and
is untested in video, so it is a later side experiment.

**Consequence.** No published study compares these designs on the same topics, so "best" is an
inference. Nobody can yet check automatically that a picture teaches the spoken claim; acceptance
keeps a person in the loop for that.

### 2026-10-09 — The look comes from the original card renderer, not a new layout

**Context.** The semantic renderer added on 2026-09-23 draws message, tool and document objects as
plain text in a column. The 2026-09-20 and 2026-09-21 videos looked better because the original
renderer in the same file has card styles per object kind, a glow for the current step and
pattern layouts. On 2026-09-29 a left-to-right layout and step dimming were rebuilt inside the
semantic renderer.

**Decision.** Phase 2 draws those object kinds with the original card styles, with their payload
values inside the card, and keeps the semantic drawing for arrays, counters, charts, formulas,
code and images.

**Why not the alternative.** Extending the 2026-09-29 layout code would re-create styling that
already exists and was already tuned against real output.

**Consequence.** The 2026-09-29 dimming and flow CSS is partly replaced. Old-format plans keep
using the original renderer unchanged, and one of them is in the fixed regression set.

### 2026-09-29 — Proof is judged from replayed screen effects, not from the plan's own evidence

**Context.** The agent-harness lesson failed at visual planning in every run. The validator
accepted a claim when the actions the plan cited had approved names (`move`, `set_state`, ...). A
highlight failed, a `set_state` to the value already shown passed, and an honest document showing
`status: shipped` failed because of its object kind.

**Decision.** `verification/visual_plan_validation.py` replays every action through
`core/visual_state.action_effect` and records what was revealed, changed or removed on screen.
`state_change` and `sequence` proof are decided from those effects. Anchors match the fact (the
value under a compatible field name) at any moment in the beat.

**Why not the alternative.** Special cases were tried first on the same day: a no-op check, a
value-proof exception for documents, a repair hint for anchors. Each closed one way of gaming the
form and left the next one open.

**Consequence.** The checker is stricter, so a saved version-2 plan from before this date can fail
at build time; the 2026-09-23 binary-search plan does, correctly (a counter increments while
hidden). Proof still depends on which actions the plan cites and is not tied to the claimed
objects; both are Phase 1 items in the hardening plan.

---

### 2026-09-04 — Deploy-readiness before a platform, and a preflight that fails loudly

**Context.** Every way this app breaks in production breaks *quietly*: a missing render image looks
like a broken scene, missing Kokoro files ship a silent video, an unset admin token makes the console
answer only to loopback (on a server: to nobody), and the default concurrency knobs permit six
concurrent renders at 2 GB each — 12 GB — on a box you would size at 4.

**Decision.** `python -m scripts.preflight`: one command, checks as pure functions over `settings`,
exit code = number of failures, and every finding names the env var to change. It runs at container
start before the server.

**Why not the alternative.** Documenting the requirements in a runbook only helps the person who
reads it on the day. The memory arithmetic in particular (`JOB_WORKERS × SCENE_WORKERS ×
RENDER_MEMORY` against the cgroup limit) is not something anyone recomputes after changing one knob.

**Consequence.** It found two real defects the moment it ran: `kokoro-onnx` was missing from
`requirements.txt` (so any rebuilt environment silently loses the voice — this machine had already
lost it), and building the image showed `COPY . .` was baking `.env` — the model key, admin token and
R2 credentials — into the image layers. Both fixed.

### 2026-09-04 — One app Dockerfile with a swappable base, not two

**Decision.** `Dockerfile.app` takes `ARG BASE`. Default `python:3.11-slim` gives a ~2 GB app image
that shells out to the pinned render sandbox (docker mode). `--build-arg BASE=manimcommunity/manim:v0.18.1`
gives a self-contained image for PaaS platforms with no daemon (local mode).

**Why not the alternative.** Two Dockerfiles drift: the dependency list, the Kokoro copy and the
entrypoint would be duplicated, and the one nobody builds locally is the one that breaks. The two
modes already exist in `render/exec.py`; the image should mirror that seam rather than invent a
second one.

**Consequence.** On a VPS, run the app **on the host**, not in this image — containerising it in
docker mode would mean mounting `/var/run/docker.sock`, which hands the app container root-equivalent
control of the host. The image is for the PaaS paths and for local parity testing.

---

### 2026-09-04 — In `jobs._run`, attribution wraps cancellation (and a cancelled job is still recorded)

**Context.** Merging the two sessions' work put two context managers on the same block: the other
session's `usage.bind(...)` (so every model call inside is billed to the right user) and this
session's `cancel.scope(job.token)` (so the work is stoppable).

**Decision.** `usage.bind` outermost, `cancel.scope` inside it, and `usage.record("job", ...)`
stays at the end of the `usage.bind` block — where a `Cancelled` unwind still reaches it.

**Why not the alternative.** The other order would let a stop unwind past the ledger write, so
exactly the jobs worth measuring — the ones somebody killed after four minutes of renders — would
be the ones missing from the numbers. Cancellation has to be visible in the spend record, not a
hole in it.

**Consequence.** `usage.record` now sees `status="cancelled"` as well as done/failed; anything
reading the ledger should expect that third value.

### 2026-09-04 — Image leaves the Teach front door; Code stays. Learn answers both in text

**Context.** Teach step 1 offered three doors: Describe, Image, Code. The question was whether
Image and Code are student gestures that belong in Learn.

**Decision.** Image moves to the Learn chat composer (attach a photo, get a text answer). Code
stays in Teach *and* gains a "send as code" affordance in Learn.

**Why not the alternative.** Moving both would make Teach a single clean box, but it would cost the
code-walkthrough video — the most *reliable* artifact this pipeline makes, because its scaffold is
deterministic (full snippet on screen, active line highlighted, per-line narration) rather than
dependent on the model getting layout right. "Make a video explaining this function" is normal
lesson prep, not a student gesture.

The real line is not *who pastes what* — students and teachers both paste code. It is the **output
contract**: Teach returns a rendered artifact through the review gate; Learn returns an answer now,
with a video only when it is earned. A learner photographing a homework problem on the Teach door
was starting a four-minute build to be told what the picture shows.

**Consequence.** `/api/projects/from-image` is now unreferenced by the UI. It is left in place —
removing a working endpoint is a separate decision — but it is dead weight to revisit.

### 2026-09-04 — Learn describes an attached image, and stores the description, not the image

**Decision.** `web/seed.describe()` (sibling of `from_image`, which returns a video *topic*) turns
the attachment into plain text on the vision-capable **critic** client; `web/learn.py` folds that
into the ordinary chat turn. The thread keeps the learner's own words plus a `has_image` flag; the
base64 is dropped after the call.

**Why not the alternative.** Passing the image straight to the chat model does not work — the live
generator (deepseek) is not vision-capable, and the critic model is the one already configured for
vision. Storing the payload would add megabytes per message to a thread JSON that no later turn
re-reads. Letting vision *answer* the question (rather than describe) would hand the chat model a
conclusion it cannot check, and the learner a reasoning step they cannot see.

**Consequence.** One extra paid vision call per attached image, bounded at 700 output tokens; if it
fails, the turn still answers, with a note that the image could not be read.

### 2026-09-04 — The Learn composer wires itself, with no new DOM id

**Context.** `learn.js` normally relies on `app.js` to wire its inputs — but `app.js` differs
between the two checkouts, and the obvious id (`learn-file`) is already taken there by the old,
now-unrouted Learn screen.

**Decision.** The attach button builds its own `<input type="file">` in JS. `learn.js` gains no new
externally-wired id, so the file merges into either checkout untouched.

**Consequence.** `learn.js` — the one file in this feature that neither session was editing —
stayed conflict-free. `app.js` did not.

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
