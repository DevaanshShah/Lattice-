# Decision log

Why the code is the way it is. Newest first. One entry per decision that a future reader could
reasonably second-guess — the alternative that was rejected matters more than the choice that was
made. Format: `### YYYY-MM-DD — decision` with **Context / Decision / Why not the alternative /
Consequence**.

Companion docs: `MEMORY.md` (phase log — what happened when), `PHASE_AB_STATUS.md` (the Phase A+B
handoff), `CLAUDE_CODE_HANDOFF.md` (the engineering brief this work answers).

---

### 2026-10-12 — Pacing and a clean stage are code's job; "it planned" is not the test

**Context.** Four lessons planned live for about a third of a cent each, and every number code
worked out in them was right. The owner asked for an independent review of the teaching, not
the frames. Four reviewers, one per lesson, each given the prompt, the plan and the frames and
not our own list of faults, all returned the same verdict: a learner understands partly, and a
teacher would not publish it. Common to all four: sentences running into each other at about
200 words a minute, a table filled in three seconds, crossed-out coins and old pointers sitting
beside the second attempt, a table drawn small beside the hole a removed tree left, and a
closing takeaway that never appeared.

**Decision.** Everything in that list that does not need the model's judgement is now done by
code. A beat is followed by a breath, and lasts at least as long as its steps need to be
followed. A fill shows where its number comes from before the number. When an attempt ends, its
marks, pointers and used-up values leave; a count shows every total; a closing scene shows its
takeaway and then gives way to the check question; an item that has left for good gives up its
room. An algorithm lesson is not asked for in under ninety seconds. Three gaps in the menu that
made lessons act things out wrongly were closed: a `take` move, a counter that belongs to one
attempt, and cells that can be numbered from 1.

**Why not the alternative.** Asking the model for these in the prompt had been tried: the
prompt already said to clear the array, to give each attempt its own counter and to fill the
first cells slowly, and three of four lessons did not. Rejecting a lesson for them costs a try,
and the review showed that tries are not free: in all four lessons the worst fault was made or
sealed by a retry. So what code can do without judging the teaching, it does without asking.

**Consequence.** Lessons run longer than the length asked for, by the pauses and by the time
steps need, and a picture can go on in silence after a short sentence. A lesson that never
clears its first attempt is cleaned anyway, so a lesson cannot keep an old mark on screen by
leaving it there; it has to use it again. Planning a lesson is no longer evidence that it is
fit to publish: the test is a reviewed video. Not done by this change, and the larger half of
the review: a sentence can still contradict the screen, and the reason behind the idea is still
not said.

### 2026-10-11 — A table states its rule once, and code fills every cell

**Context.** A fill move carried its own working: the cells it read, how to combine them, or a
starting value. Code did the arithmetic, but the model still kept the table's books: which
cells start filled, with what, and the order of the rest. On the cheap model that is where
algorithm lessons failed. Climbing stairs was rejected five times in a row for working a cell
out from one still empty, and then for a wrong starting value.

**Decision.** The table carries the rule, once: its first cells, how far back each later cell
reads, and `sum`, `min` or `max` plus a constant. Code works the whole table out from it. A
fill names a cell and the number the lesson expects there, and nothing else; every cell still
empty before it is filled first, in order. Naming a cell that is already full points at it
again and writes nothing. A step that would read before cell 0 is skipped, which is what makes
"fewest coins" one rule. The move forms that carried their own working were removed, not kept
beside the rule.

**Why not the alternative.** Keeping the old forms next to the rule would leave two ways to do
one thing, and the prompt would have to teach both; a model shown both mixes them. Repairing
the order in code while still reading the cells from each move would hide a move that names the
wrong cells. Leaving it to more retries had already been tried: five tries, each with the exact
reason, did not get the stairs lesson through.

**Consequence.** A lesson can no longer fill out of order or read an empty cell, because it no
longer says either. A wrong start value is still possible, and is caught by `expect` with the
whole table quoted back. What a rule cannot say cannot be worked out by code: a cell that adds
a different number each time (the cost of each stair), a second array read alongside, or a
table in two dimensions. Such a table can still be filled with given values, which are not
checked. The saved lessons with tables were rewritten in the new form and compile to the same
pictures. First live run, one per topic on the cheap model: stairs, Fibonacci, coin change and
binary search all planned (12 calls, $0.012), with every table right; the stairs lesson was
sent back once for a table number and fixed it from the quoted table.

### 2026-10-11 — The lesson states the number it expects, and code checks it

**Context.** Code computed every cell of a table from the cells the model named, so the
arithmetic on screen was always right for the starting values given. A live lesson then started
a table from the wrong value: the screen showed five ways to climb the stairs and the narration
said eight. It passed every check, because nothing connected the sentence to the picture.

**Decision.** Wherever code works a number out and the narration is likely to say it, the move
carries the number the lesson expects: `expect` on a computed fill (one per cell of a run) and
on a count that points at a self-counting counter. Code compares it with the real value and
rejects a mismatch, quoting the working.

**Why not the alternative.** Reading numbers out of the narration ("eight", "8 ways") would be
matching words, which breaks on phrasing and languages. Letting the model write the cell values
and dropping the computation would bring back wrong arithmetic on screen. Stating the number
twice, once for the picture's rule and once as the expected result, makes the model's two
accounts check each other, and the structured one is what code compares.

**Consequence.** Fewer lessons plan: in the first run after it, one of three, where before it
three of three planned and one was wrong. A model can still narrate a number it did not put in
`expect`. The check covers tables and counters, not yet comparisons or discarded ranges.

### 2026-10-11 — In an algorithm lesson the model chooses the step and code does the arithmetic

**Context.** Algorithm topics went through the model-written visual step and failed on every
model tried: anchors that were never on screen, counters that started at their final value,
marks that did not match the values. The renderer could already draw code beside an array.

**Decision.** An algorithm lesson is a trace: the code, the data, and one move per beat from a
menu (show, run, look, compare, discard, fill, count, clear). The model says which cell is
compared or which cells a value is worked out from. Code decides the outcome of the compare,
computes the value, counts the checks, and writes the text each beat must show.

**Why not the alternative.** Running the model's code to check the trace would mean executing
untrusted code and still would not say what to draw. Letting the model state results ("the
value is 8", "that took six checks") is exactly where it was wrong before; a number computed
from the picture cannot disagree with the picture.

**Consequence.** A lesson can only combine cells by sum, minimum or maximum plus a constant,
which covers the common table problems and not all of them. Nothing checks that the moves
follow the code shown beside them: a lesson could light one line and do another thing.

### 2026-10-11 — The question is shown, and code asks the check question

**Context.** With the teaching brief in place the narration opened on a problem and a question
and closed on a check question, but a still frame looked the same as before. The owner saw no
difference. The question lived only in the voice.

**Decision.** A question and an answer are things the viewer sees: lines of text under the
picture, placed by two moves, `ask` and `answer`. The opening `ask` is the model's to place, at
the moment the problem has made the learner want to ask. The closing check question and its
answer are appended by code from the brief, with a pause between them for the viewer to think.

**Why not the alternative.** Asking the model to write the check as beats cost it two of its
beats, and it could forget them or word them unlike the brief; they are the brief's own words,
so nothing is lost by adding them in code. Checking for a question mark in the first scene's
narration was matching words, which tests wording and not teaching; an `ask` move is a
structural fact. Centring the question over an empty stage was rejected because the pieces
would then have to move when they arrive, and every piece keeps one place for the whole scene.

**Consequence.** A lesson is two beats longer than what the model writes, and the length given
to the model allows for that. A scene shows at most a question and one more line, so a scene
that ends on an answer drops its takeaway.

### 2026-10-10 — A system lesson is narration plus one move per beat, and code draws it

**Context.** A system lesson cost six model calls (one for the script, one per scene) plus
retries: about $0.07 on `gpt-4o`, and cheap models failed. Most rejections came from the clerical
part of a scene (ids, timing, proof records) and from the script step promising a proof the
visual step could not honestly draw. The owner asked for the cost to come down without going
back to boxes.

**Decision.** For a lesson taught on a map the model writes the map once and, for each sentence,
one move from a menu of seven. Code derives the claim, the proof kind and the anchors from the
move, and compiles every scene. The compiled scenes pass through the unchanged validator, and a
failure goes back to the single lesson call. The recipe, not the model, decides whether a topic
is taught on a map.

**Why not the alternative.** Keeping the model-written visual step and batching all scenes into
one call would have halved the calls but kept the retries and the disagreement between the two
steps. Shrinking prompts alone saves a fraction of a cent, because output tokens and call count
dominate. Letting the model choose the board failed in practice: `gpt-4.1-mini` wrote a
free-form lesson for a system topic.

**Consequence.** One call per system video (about $0.0013 on `deepseek-v4.1-flash`). A map
lesson can only show what the menu offers, so variety now comes from adding moves, each with a
test. The script and the picture share one source, so nothing checks that a sentence matches its
move; that check is open.

### 2026-10-10 — Planning calls turn reasoning off

**Context.** `deepseek-v4.1-flash` returned an empty answer on its first two tries in every run.
One probe showed 4,096 reasoning tokens, no content, finish reason `length`. With
`reasoning: {"enabled": false}` the same call returned a complete lesson in 943 tokens at a
quarter of the cost; `{"effort": "low"}` changed nothing.

**Decision.** Both planning calls send `PLAN_EXTRA` (reasoning off). The client drops that field
for a provider that is not OpenRouter, and no longer retries a blank answer that was cut off by
the token limit.

**Why not the alternative.** Raising the token limit would pay for the thinking on every call.
A plan is structured writing checked by code, and the checks, not the model's deliberation,
are what make it correct.

**Consequence.** A model that cannot turn reasoning off may ignore or reject the field; that is
untested.

### 2026-10-10 — The ball is a step of its own, not a side effect of drawing an arrow

**Context.** The first map board sent the ball along each arrow as the arrow was drawn. The owner
watched it and said the diagram should be built first and the ball should come in afterwards,
when the flow is explained, and that the ball should adapt to the situation.

**Decision.** `connect` only draws the arrow. A new `trace` action names a path of pieces and
sends the ball along the arrows between them; `count` sends several for a busy system and `tone`
colours them. The ball rests where its trace ended until the scene ends. The validator requires an
arrow under every hop and every piece on screen.

**Why not the alternative.** Keeping the ball on `connect` and delaying it would still tie one
ball to one arrow at the moment of drawing, so a flow could never be replayed over a finished
diagram or shown under load. A free-form ball position was rejected: a path over named arrows is
something the checker can verify without rendering.

**Consequence.** Old plans that relied on a connect to move the ball now show only the arrow
drawing itself. A planner that wants the ball must ask for it, which Phase 4 has to teach.

### 2026-10-10 — A scene is one of a few fixed board types, not a free layout

**Context.** The owner asked whether code could be taught with the code fixed on one side, the
highlight moving part by part and the effect animated on the other, and then what to do for flows
and similar scenes. The reference video uses a handful of repeating arrangements.

**Decision.** The renderer offers a small fixed set of boards, each with its own layout rule: map,
code and picture, ideas beside the map, compare. A board is chosen by what the scene contains (a
code object beside other objects in a non-flow scene is pinned left), and each is proved by a
hand-written fixture before the planner is asked for it. The lit code lines are plain state
(`active_lines`), so the validator sees a moved highlight as a change on screen.

**Why not the alternative.** Letting the planner place things freely is what failed in September:
positions it cannot see produce overlaps that only a render reveals. A separate renderer per board
was rejected too; the boards share the stage, the slots, the fit and the checks, so a fix lands
once.

**Consequence.** A lesson that needs an arrangement outside the set cannot be drawn until a board
is added for it. The planner prompt in Phase 4 can name boards instead of describing layouts.

### 2026-10-10 — The target is one named reference style, and the renderer learns it before the planner

**Context.** After the card look was approved, the owner asked whether videos were only boxes and
arrows, then showed seven frames of a "System Design for Beginners" explainer and said it was the
exact style wanted: one map built piece by piece, icon pieces with one or two words, a simple
palette on black, and a small ball that moves to each step as it is spoken.

**Decision.** That reference is the target for system and process lessons. The plan's next phase
teaches the renderer the style and proves it on a hand-written plan of the reference's own diagram,
with no model calls. Only after the owner approves that render does the lesson step learn to plan
one map per lesson.

**Why not the alternative.** Changing the prompts first would spend money asking a model for plans
the renderer cannot yet draw, and a bad result could not be told apart from a bad renderer.
Mathematics visuals in the 3Blue1Brown manner, discussed the same day, are a different and larger
build; they moved to the later list. Putting the reference frames in git was rejected because they
are someone else's video.

**Consequence.** The 2026-09-20 "gold" video is no longer the bar. The card look approved in Phase
2 stays for lessons where the values are the point, but gets the black background and flat
palette. The target's motion is known only from still frames and the owner's description.

---

### 2026-10-10 — Every object of a scene has a fixed place, and the stage is sized to the frame

**Context.** On the semantic stage only the visible objects were laid out, so a box jumped when its
neighbour appeared, and two or three small boxes sat in a mostly empty frame. Flows of more than
three boxes overflowed and needed the compact fallback.

**Decision.** An object the scene will show is laid out from the first frame and drawn with no
opacity until it appears. The stage content is then scaled once to the frame: a flow grows up to
1.3 times or shrinks to fit; a stack only shrinks. Flows wrap after four columns, and the arrow that
wraps runs through the gap between the rows.

**Why not the alternative.** Laying out only what is visible is what caused the jumps. A layout
engine for placement adds a dependency the original plan forbids and is untested in video, so it
stays a side experiment. Shrinking a long flow onto one row makes its text unreadable past five
or six boxes.

**Consequence.** Early in a scene one box can sit off-centre beside the empty place of a box that
has not appeared yet. A box that is removed leaves a gap. Carried objects change size between
scenes, because each scene is fitted on its own.

### 2026-10-10 — Frames are rasterised in software so that they are repeatable

**Context.** With cards scaled to fit, the last frame of a beat differed from the same moment
drawn by a second browser process in 2 of 14 runs: one pixel of a soft shadow, by one level out of
255. It is invisible, but the regression harness and one test rely on identical frames.

**Decision.** `render_animated_beat` launches Chrome with `--disable-gpu`, as the layout check
already did. CSS transitions are switched off on the stage, because they run in real time while
frames are captured at chosen moments.

**Why not the alternative.** Tolerating a few differing pixels in the test would have hidden the
cause and left the output dependent on the process that drew it. Keeping whole-pixel sizes is not
possible once the stage is scaled by an arbitrary factor.

**Consequence.** 0 differences in 38 runs afterwards. Every animated frame changed very slightly
(anti-aliasing), so the baseline for animated cases has to be re-approved once.

---

### 2026-10-09 — A cut or reordered learning video is refused only when the scene chain breaks

**Context.** Scenes of a learning video usually build on each other: an object one scene leaves on
screen opens the next. Dropping the middle scene in the outline crashed the build with a raw
`KeyError`. The hardening plan said to refuse every cut or reorder for these projects.

**Decision.** `Engine.check_build` narrows the saved plan to the approved scenes and runs the
validator on what remains, before a job is queued. The build endpoint answers 400 with the
validator's reason when the chain is broken, and builds normally when the remaining scenes still
validate. The validator checks carryover against the previous scene before it replays anything,
so a broken chain is a reason, not a crash.

**Why not the alternative.** A blanket refusal: an existing API test builds a project after
dropping its first scene, with independent scenes, so that would remove behaviour that works.
Hiding the outline controls: same loss, and the server would still need the check for any other
caller. Letting the job fail later: the user waits for a failure they could have been told at once.

**Consequence.** Whether a cut is allowed depends on the plan, which the user cannot see, so the
outline text now warns that it may not be possible. Adding a scene after planning is always
refused, and that control is hidden for these projects.

### 2026-10-09 — Proof looks at the objects a claim names, not at the actions the plan cites

**Context.** After 2026-09-29 the validator judged proof from screen effects, but only the effects
of the actions the plan cited, on any object. A correct screen failed when the model forgot to
cite one action, and a change to an unrelated card passed as proof.

**Decision.** For `state_change` and `sequence`, every action of the beat is considered, and a step
counts only when it reveals, changes or removes an object the claim's evidence names, or the array
under a named pointer. Earlier-beat actions count only for `sequence` and only when cited. Hides
the planner inserts to tidy the screen never count.

**Why not the alternative.** Dropping the evidence block entirely: the claim still has to say which
objects it is about, and nothing else in the plan does. Ignoring the evidence kind as well: an
existing test treats "a label cannot prove a state change" as intended behaviour, so that stays.

**Consequence.** A hide the model adds itself now counts as a state change without being cited.
The evidence kind is still the model's own label and can still cause a false failure.

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
exactly 1.0 on this machine. The first threshold of 0.995 was too loose: a label that stopped
fading moved the lowest frame only to 0.9989. Anything below 0.9999 is now reported as changed.

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
