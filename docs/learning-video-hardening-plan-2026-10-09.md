# Learning video hardening plan

Date: 2026-10-09 · Branch: `codex/learning-video-continuity-20260922` · Status: Phases 0 and 1
done on 2026-10-09; Phase 2 (look) done on 2026-10-10. On 2026-10-10 the owner set a target
style, and the plan from Phase 3 onward was rewritten around it; Phase 3 (map pieces) is next

This plan covers the new learning-video path: the web Teach tab, renderer `browser_v2`, plan
format version 2. It replaces one-off fixing with phases, and every phase ends with a test gate.
It builds on `docs/learning-video-implementation-plan.md` (the original five-phase plan) and does
not replace it.

## 1. Where we are

How the path works: one AI call writes the lesson (narration, on-screen facts, proof needed). One
AI call per scene writes the visual plan (objects and timed actions). Code then checks the plan,
makes the narration audio, renders in Chrome (or Manim in Docker for array scenes) and stitches
the clips. Rendering makes no AI calls.

What works today:

- Values inside message, tool and document boxes are drawn (`order_id: 42`, `validated: ✓`).
- The checker replays every action and judges what visibly appeared, changed or was removed.
- A full three-scene video renders end to end from saved plans.
- 527 unit tests pass. Two more need Docker Desktop, which is switched off on this machine.

What is wrong (each item was reproduced offline on 2026-10-09 unless marked):

1. Cutting or reordering a scene in the outline crashes the build.
2. The duration the user picks never reaches the lesson step, so lessons come out short.
3. A change to an unrelated object still counts as proof.
4. A lesson that marks every claim as `label` switches the proof check off (read from the code).
5. A correct screen is rejected when the AI forgets to cite one action.
6. Videos look worse than the 2026-09-20 ones: plain text instead of cards.
7. Flows with more than three linked boxes overflow the normal layout; seven or more fail.
8. Step dimming also dims the array in browser-drawn array scenes.
9. One network error ends planning, because automatic retries are switched off for these calls.
10. The planner prompt is 70% of every scene request and more than half of it is about arrays
    and binary search. It also contradicts the code in four places.
11. Nothing tests how a new-path video looks. The existing harness (`eval/`, `scripts/selftest.py`)
    only covers the old Manim pipeline.
12. Not known: whether the web default model (`gpt-4o-mini`) can pass the checker. Every scene
    that passed so far came from `gpt-4o`.

Evidence: the `MEMORY.md` entries for 2026-09-29 and 2026-10-09, and the research report
`reports/Explainer video generation architectures.md`. The research supports keeping this
architecture and strengthening the checks.

## Target style (set by the owner on 2026-10-10)

The owner named one reference: a "System Design for Beginners" explainer video. Seven frames of
it are kept locally in `out/reference/system-design-style-2026-10-10/`. They are not in git,
because it is someone else's video. A learning video about a system or a process should look and
move like this:

1. **One map for the whole lesson.** The diagram is not restarted for each scene. It is built
   piece by piece along the path of a request, and every piece keeps its place to the end.
2. **Pieces are icons.** A phone, server racks, a database cylinder, a lightning bolt. A card with
   values is used only when the values are the point.
3. **One or two words per piece.** The voice explains; the screen names.
4. **A simple palette on a black background.** Thin outlines, one colour per idea (pink, purple,
   teal, yellow), the label in the colour of its piece, light grey arrows.
5. **A small ball moves along the arrows** to the piece the narrator is talking about.
6. **Related pieces sit in one panel,** such as a database with its replica, shards and indexes.
7. **Lines draw themselves,** and a new piece goes from dim to bright.
8. **The title starts as a card** and then stays as a small header.

Three more frames from the owner (8 to 10 in the same folder) add these points:

9. **The video is a series of boards.** Each has a hand-lettered heading, and the same pieces
   come back from board to board. The big map is one board the video returns to.
10. **Code is an editor window:** a title bar, a file name and coloured code, joined to the
    diagram by an arrow.
11. **A state is shown, not said.** A load bar at 100% above a server that has turned red, many
    balls on one arrow for many requests, a cracked database.
12. **A quantity is shown by repeating a piece:** nine phones stand for ten thousand users.
13. **Ideas that are not parts of the system** are a short stack of cards beside the map, each
    with a small figure, a title and one line.
14. **A board can end with a one-line takeaway** with a tick in front of it.

The motion in points 5 and 7 is read from differences between still frames and from the owner's
description, not from the video itself.

Owner's choices on 2026-10-10: use the icons the project already has (the Lucide set in
`assets/icons`), and keep this colour combination as the only palette: black background, thin
outlines, pink, purple, teal and yellow, with red for a problem. The first five minutes of the
reference also showed a story shape the lesson step should follow: a simple system, a problem
shown in red, a dashed empty box where the fix will go, the fix filling it, and a one-line
takeaway, repeated on the same diagram, then a recap. Phase 3 therefore also needs a dashed
placeholder box, a red problem state, a bottom caption line and a heading that can change colour.

Not part of this target, and moved to section 5: graphs, equations that transform, and other
mathematics visuals.

## 2. Working rules

1. One phase at a time. A phase is one commit, or a few small ones, on this branch.
2. A phase is finished only when its gate passes. If the gate fails, revert that phase and write
   down why.
3. Phases 0 to 3 make no AI calls. They are tested by re-rendering saved plans, which is free.
4. No AI spend without the owner's go-ahead. Every live run states its maximum cost first.
5. Never judge by tests or plan files alone. Every gate includes rendered frames.
6. Do not hand-edit a generated plan as a fix. Fix the planner, the checker or the renderer.
7. `main` and the old Manim pipeline stay untouched until Phase 5.
8. A second agent session also writes to this repo. Check file modification times before editing.
9. After code changes run `graphify update .`. After each phase add a `MEMORY.md` entry, and a
   `DECISIONS.md` entry for any choice a reader could question.

## 3. Definition of done

The new path can replace the old one on `main` when all of these are true:

1. Three fixed topics each produce a full video in one run through the web engine, on the model
   chosen as default.
2. Each video's length is within 20% of the requested duration.
3. Everything the topic text asks for is spoken. A person checks this against a short list.
4. No sampled frame has overlapping boxes, cut-off text or a hidden arrow label.
5. Each process step visibly changes something, the current step is highlighted, and flows read
   left to right.
6. A lesson about a system is one map built piece by piece in the target style: icon pieces, one
   or two words each, one colour per idea on black, and a ball that moves to each step as it is
   spoken.
7. The owner judges the result against the reference frames.
8. Unit tests and the regression harness are green.

## 4. Phases

| Phase | Goal | AI calls | Size | Gate |
|---|---|---|---|---|
| 0 | Checkpoint and safety net | none | medium | Harness green; owner accepts the starting contact sheets |
| 1 | Correctness fixes | none | medium | Tests green; saved-plan verdicts as expected; frames change only where intended |
| 2 | Look | none | large | No compact-layout fallback on the fixed set; owner approves contact sheets |
| 3 | Map pieces: the target style in the renderer | none | large | The hand-written system map renders; owner approves its style against the reference frames |
| 4 | One map per lesson: lesson step and prompts | yes, capped | large | Plan battery beats the baseline; lesson length within budget |
| 5 | Acceptance and merge | yes, capped | small | Definition of done; owner sign-off |

### Phase 0: checkpoint and safety net

No behaviour changes in this phase.

1. **Checkpoint commit.** Commit the current working tree on this branch: ten changed files plus
   `tests/test_browser_animation.py`, which is still untracked. Do not push until the owner says so.
2. **Fixed set of plans in the repo.** `out/` is not in git, so copy the plans into
   `tests/fixtures/video_golden/<case>/` as `lesson_plan.json` and `browser_visual_plan.json`:
   - `tool_flow`: the three-scene order-lookup video (`out/live-acceptance-harness-20260926/attempt-09-offline`).
   - `binary_search`: arrays, pointer, compare and discard, from the fixture in `tests/test_visual_state.py`.
   - `chart_compare`: the chart fixture from the same test file.
   - `structured_args`: the three-scene code-object fixture in `tests/test_browser_animation.py`.
   - `legacy_cards`: an old-format plan (`out/browser-v2-agent-harness-auto-carryover-20260921`).
     It protects old saved projects and is the visual reference for Phase 2.
3. **`scripts/video_regression.py`** (new, offline). For each case it validates the plan, builds
   the video with silent audio of a fixed length per beat (so frames are repeatable), and reports:
   plan valid, build finished, number of compact-layout fallbacks, nothing cut off, audio and
   video the same length. It writes one contact-sheet image per case and compares sampled frames
   with the last approved run using FFmpeg, so no new dependency is needed. `--set-baseline`
   stores the approved run. Manim cases are reported as skipped when Docker is not running.
4. **Self-test on the new path.** Add `--renderer browser_v2` to `scripts/selftest.py`. The checks
   that only apply to the old pipeline (style, old word budget) become conditional. This is a
   live test, so it is used in Phases 3 and 4, not here.
5. **`scripts/plan_battery.py`** (new, live, planning only). It plans three fixed topics, with no
   rendering, and records per scene: passed first try, tries used, tokens, cost and the failure
   reason. It keeps a baseline and compares against it, in the same way as `eval/score.py`. It
   takes a hard cap on calls. In this phase it is only tested with a fake client.

Gate: the regression script is green on every case (or skipped for a stated reason), the baseline
is stored, and the owner has looked at the contact sheets.

**Result, 2026-10-09.** Built as planned, with three additions.

- The fixed set has seven cases, not five. `binary_search_stills` covers the still-frame route
  that older untimed plans use, and `binary_search_manim` covers the Manim route.
- `--accept-last` approves the previous run as the baseline without rendering it again.
- A Manim case is skipped, with the reason, when Docker or the render image is missing.

Run it with `python -m scripts.video_regression`. It takes about five minutes. All seven cases
pass with no compact-layout fallback, and a second run matched the first on every frame (SSIM
1.0000), so a reported change means the code changed the picture. The approved videos and contact
sheets are in `out/video_regression/baseline/`; they are local files and are not in git. Unit
tests: 552 pass.

The starting contact sheets already show two known problems: "Target: 8" fades out in the last
beat of `binary_search` (problem 8), and code text overlaps a box for a moment when it appears in
`structured_args` (the reason for Phase 2 item 3).

While this ran, the Docker render image `lattice-render:0.2` was found deleted and was rebuilt
with `python -m scripts.setup_env`.

The owner gave the go-ahead for Phase 1 on 2026-10-09.

### Phase 1: correctness fixes

1. **Scene cutting** (`web/engine.py`, `web/static/app.js`). For new-path projects the server
   refuses a build that drops or reorders scenes, with a clear message. The outline screen hides
   the switch and the drag handle for these projects. Proper scene editing is listed under
   section 5.
2. **Proof looks at the claimed objects, not at citations** (`verification/visual_plan_validation.py`,
   function `_proves`). A step counts when it reveals, changes or removes an object the claim
   names, or the array a named pointer sits on. All actions in the beat are considered, cited or
   not. This closes problems 3 and 5 together.
3. **Readable error for old drafts.** When a saved plan fails the stricter checker at build time,
   the message says the draft must be planned again.
4. **Dimming** (`generation/browser_scene.py`). Step dimming applies only to flow scenes, never to
   scenes that contain an array or a chart.
5. **Network retries** (`planner/lesson_plan.py`, `planner/browser_visual_plan.py`). Allow three
   transport attempts per call instead of one.
6. **Small cleanups.** A shadowed variable and a wrong comment in the checker.

Tests to add: cut-scene build returns a clean error; unrelated-object change is rejected;
forgotten citation is accepted; a transient error is retried; an array is never dimmed.

Gate: unit tests green. Replaying the saved attempts gives the same verdicts as today (honest
plans pass, fakes fail). The regression frames change only in array scenes.

**Result, 2026-10-09.** Gate passed: 561 unit tests pass, all 15 saved attempts keep their verdict
(5 honest plans pass, 10 fakes fail), and the only frames that changed are in `binary_search`,
where "Target: 8" no longer fades out. Three things differ from the plan above.

- **Scene cutting is refused only when it breaks the chain.** An existing test showed that
  dropping a scene is a supported feature when scenes do not depend on each other, so a blanket
  refusal would have removed working behaviour. The build endpoint now checks the selection
  first and answers with a clear message when the remaining scenes depend on a removed one. The
  outline screen keeps its switch and drag handle, hides "Add a scene" for these projects, and
  says that dropping or reordering may not be possible. The validator reports a broken chain as
  a reason instead of crashing.
- **The evidence kind still has to match the requirement.** An existing test treats "a label
  cannot prove a state change" as intended, so only citations stopped mattering. Hides that the
  planner adds to tidy the screen are excluded from proof.
- **The regression threshold was too loose.** The dimming fix moved the lowest frame score only
  to 0.9989, which the first threshold of 0.995 called "same". Unchanged code scores exactly 1.0,
  so anything below 0.9999 is now reported as changed.

Left for later phases: the kind label is still the model's own paperwork, and a hide the model
adds itself counts as a state change even when it was not cited.

### Phase 2: look

1. **Cards.** Message, tool, document, card, node, gate and group objects are drawn with the
   original card styles that already exist in `generation/browser_scene.py`, with their values
   inside the card. The current step gets the original glow. Earlier steps dim slightly. Arrays,
   counters, charts, formulas, code and images keep the current drawing.
2. **Placement.** Boxes are placed left to right in arrow order. More than four columns wrap to
   a second row, so normal layout passes without the compact fallback.
3. **Stable positions.** The scene is laid out once with all its objects. A box that is not
   visible yet keeps its place, so nothing jumps when it appears.
4. **Arrow labels.** A label may not overlap any box. The gap adapts to the longest label.
5. **Optional.** Decision scenes use the original diamond with yes and no branches. Adopt only if
   the contact sheets are clearly better.

Tests to add: flows of five, six and eight boxes pass normal layout; a box's rectangle is the same
before and after another box appears; a label never overlaps a box.

Gate: unit tests green. No compact-layout fallback on the fixed set. The owner compares three
contact sheets per case (Phase 0 baseline, new, and the 2026-09-20 gold video) and approves.
Then the baseline is updated.

**Result, 2026-10-10.** Gate passed: the owner approved the look and the baseline was updated. 572
unit tests pass. All seven regression cases pass with no compact-layout fallback. The original card
renderer (`legacy_cards`), the Manim case, the still-frame case and the chart are frame-identical
to the baseline. `tool_flow` and `structured_args` changed as intended. `binary_search` changed
only in how its first fade-in is drawn. Two runs of the new code match on every frame.

What was built, beyond the five items above:

- **Fit to the frame.** The stage content is sized to the frame once per scene: a flow grows up to
  1.3 times or shrinks until it fits. This is why two- and three-box scenes are no longer small.
- **Arrow labels** sit just above the arrow inside the gap, on at most two lines. The gap is as
  wide as the longest label line.
- **A flow that wraps** runs its connector through the empty gap between the rows, so each row
  still reads left to right and no arrow crosses a box.
- **The current step** is the latest action's targets, which glow. Objects the beat has not
  touched dim to 62%. An object being cleared away is never lit.
- **Decision diamonds** come with the card styles; yes and no are the arrow labels (item 5).
- **Code snippets in a flow** get a thin dark panel. Code in algorithm scenes is unchanged.
- **Frames are rasterised in software.** With cards scaled to fit, the GPU path drew one shadow
  pixel one level differently in 2 of 14 runs; software rasterising gave 0 in 38. CSS transitions
  are also switched off on the stage, because they run in real time.

Things for the owner to judge on the contact sheets:

- A box's place is reserved before it appears, so early in a scene one box can sit off-centre
  with empty space beside it.
- When a value changes, the old and new text overlap for a moment while they cross-fade. This
  was already so before this phase.
- Scene 3 of `tool_flow` still shows `missing` beside `validated: ✓`. That is the old saved plan,
  and it is a Phase 3 matter.

Review material: `out/video_regression/phase2_review/` holds a before-over-after sheet and both
videos for each changed case, and the gold video with its sheet. Approve with
`python -m scripts.video_regression`, then `--accept-last`.

### Phase 3: map pieces (the target style in the renderer)

No AI calls. The renderer learns the target style, and a hand-written plan on a topic of our own
proves it, before the planner is asked to write such plans. The reference gives the way a lesson
is organised and the palette. Its drawings, wording and example are not copied.

1. **Icon pieces.** An icon object becomes a piece of a flow: an outlined icon in its colour with
   a one- or two-word label under it. It takes part in the layout, the glow and the dimming like
   a card. The colour is a `tone` from a fixed palette.
2. **Palette and background.** The stage is black. Cards, arrows and labels use the same palette
   with thin outlines and flat fills. Old-format plans are not touched.
3. **Panels.** A group object draws a rounded panel around its member pieces, with a header
   strip, and an arrow can end at the panel's edge.
4. **The ball.** It moves along an arrow during a connect action, as today, and then stays on the
   piece it reached until its next move.
5. **Lines draw themselves** when a connection first appears.
6. **One layout for the whole lesson.** When scenes share a map, every scene uses the layout of
   the full map, so a piece keeps its place and size across scenes.
7. **Icons that are missing.** A lightning bolt for the cache and a load-balancer icon, from the
   Lucide set the other 43 come from.
8. **A hand-written fixture, `system_map`.** A system of our own choosing with the same kinds of
   piece: a client, a router, several workers, a fast store, and a panel holding a main store
   with its copies. It is revealed in eight to ten steps and joins the fixed regression set.
9. **Supporting pieces,** after items 1 to 8 work: code as an editor window; a load bar with a
   value; a piece repeated to show a quantity; a piece that changes colour when its state
   changes; a card with a small figure, a title and one line; a takeaway line with a tick. A
   second hand-written fixture, an overload board (many users, one red server, load at 100%),
   shows them together.

10. **Board types.** A scene is one of a small fixed set of boards, each with its own layout,
    so the planner later picks a board instead of inventing a layout. Built in this order:
    - **Map** (done, fixture `system_map`): pieces and arrows, shared by several scenes.
    - **Code and picture** (done, fixture `code_and_picture`): the code stays fixed on the left,
      `active_lines` lights the lines being explained and dims the rest, and what those lines do
      plays out on the right.
    - **Ideas beside the map**, with a ring around the piece being discussed (next).
    - **Compare**, two things side by side (after that).
    - **Formula and graph**, drawn by Manim (after compare): an equation that changes step by
      step and a plotted curve, on the same black palette. Manim already draws array scenes; this
      extends that route, and its case stays in the regression set.
    One hand-written test board each for problem-and-fix, code-into-system and recap follows.
11. **The ball is its own step.** A `connect` only draws the arrow. A `trace` action sends the
    ball along a named path of pieces, so the diagram is built first and the ball comes in when
    the flow is explained. `count` sends a stream of balls for a busy system; `tone` colours them.
    The validator rejects a trace with no arrow under it.
12. **Motion.** Every change is eased and takes a brisk moment at the start of its step (0.6 s
    for a fade or move, 0.7 s for a line, 1.1 s per hop for the ball) instead of running at one
    speed for the length of the sentence. No animation library is added: frames are captured by
    seeking to an exact time, so smoothness comes from easing and frame rate, not from a runtime.

Status on 2026-10-10: items 1 to 8 and the first two boards are built and tested. A piece with
several arrows out sends a stepped arrow from its top or bottom, so it does not cross another
arrow's label. Still open in item 9: a heading that changes colour, and the card with a small
figure. The owner has not yet reviewed the videos in `out/video_regression/phase3_review/`, and
the regression baseline for this phase is not accepted until then.

Tests to add: an icon piece carries its tone and label; panel members sit inside the panel; a
piece has the same rectangle in every scene of a shared map; the ball is on the reached piece
after its move; old-format frames stay identical.

Gate: unit tests green. The regression set passes with no compact-layout fallback, and the
old-format case is frame-identical. The owner compares the `system_map` video and contact
sheet with the reference frames and approves.

### Phase 4: one map per lesson (lesson step and prompts)

This phase changes what the AI is asked, so it needs live runs.

0. **Measure first.** Run the plan battery on the unchanged prompts with `gpt-4o-mini` and
   `gpt-4o`, and store it as the baseline.
1. **The lesson step plans one map.** For a system or process topic it first lists the pieces
   (icon, one- or two-word label, colour, panel) and the arrows, then the order in which they
   are revealed, with the narration for each step. The visual step reveals pieces of that map
   and moves the ball. It cannot add a piece the map does not have.
2. **Duration reaches the lesson.** `composition/browser_video.py` passes the requested duration
   and scene count to the lesson step. The prompt gets a word budget of duration × 2.3 words per
   second, the pace the old pipeline already uses. The lesson is rejected and retried when it is
   more than 25% away from the budget. Cutting scenes off a finished lesson is removed.
3. **The lesson step is told what can be drawn.** Its prompt refers to a list of visual forms
   that is not there today.
4. **A plain-language demonstration per beat.** A new optional field in the lesson says what the
   viewer should see change. It is passed to the visual step. Old saved lessons still load.
5. **No label-only scenes.** Every scene needs at least one claim that requires real proof.
6. **Split planner prompt.** A short core, plus one section per family: algorithm, flow, data,
   media. The lesson step tags each scene with a family and only that section is sent. An
   unknown family sends everything, as today. The four contradictions are removed.
7. **Proof failures name the object.** The retry message says which claimed object did not change.
8. **Default model.** Chosen from the battery numbers.

Gate: against the baseline, plan success and first-try scene passes do not fall, and should rise.
Lessons are within the word budget. Unit tests and the regression harness stay green. Expected
spend for the phase is about one to two US dollars, as an estimate from measured costs
(`gpt-4o-mini` about $0.003 per plan, `gpt-4o` about $0.06 to $0.16). Each run is confirmed first.

### Phase 5: acceptance and merge

1. Three full videos through the web engine with `scripts/selftest.py --renderer browser_v2`:
   a system topic of our own in the target style, the
   order-lookup harness, and binary search.
2. The owner reviews them against section 3. Results are written into this file.
3. Update the status lines in `docs/learning-video-implementation-plan.md`, `MEMORY.md` and
   `DECISIONS.md`. Add the rule "judge by screen change, never by the evidence block" to the
   diagnostics skill.
4. Open a pull request to `main`. The old pipeline stays for existing projects.

Gate: the definition of done, and the owner's sign-off.

## 5. Later, each needs a separate go-ahead

- **Layout engine** for placing boxes and arrows. It adds a dependency, which the original plan
  forbids, and nobody has tested it in video. Try it on a side branch and compare contact sheets.
- **Editing on the new path:** regenerate one scene, then re-check the scenes that depend on it.
- **Mathematics visuals:** graphs with a moving point, equations that change step by step, simple
  geometry. The old Manim scaffold (`generation/lattice_scene.py`) has graph and table pieces to
  start from.
- **A title card that shrinks into the header,** and a hand-lettered font. The font needs a
  bundled font file with an open licence.
- **Illustrated pieces:** a phone screen with a feed, a figure on a concept card, a ring or a zoom
  on one part of the map.
- **Computed states for algorithm topics:** code runs the algorithm and fills the plan.
- **Meaning checks:** read text from frames, ask a vision model narrow yes or no questions, and
  hand-label a sample of passing videos to measure how often the checker is wrong.
- Music bed, and a check that export and captions work for new-path videos.

## 6. Risks

- `gpt-4o-mini` may not pass the checker. Planning on `gpt-4o` costs about twenty times more per
  video, which is still cents.
- Tying proof to claimed objects may reject a valid algorithm plan. The array rule and the fixed
  set are there to catch this.
- Stable positions can leave a gap when a box is removed in the middle of a scene.
- Array scenes need Docker.
- The checker cannot prove that a picture teaches the claim. No published system can. Phase 5
  relies on a person for this.
- The target style is known from seven still frames. Its motion is inferred, so the first
  rendered map may need a round of changes after the owner sees it move.
- One map for a long lesson can get crowded. Scrolling or zooming the map is not planned yet.
- Drafts planned before 2026-09-29 may need planning again.

## 7. Questions for the owner

1. Answered 2026-10-10: the target is the reference video's style, so the third acceptance topic
   is a system topic in that style.
2. If `gpt-4o-mini` fails the battery, is `gpt-4o` acceptable as the default?
3. Should `reports/` go into git and `research_notes/` be ignored?
4. Answered 2026-10-09: commits are pushed, with only the owner's name on them.
5. Can Docker Desktop stay on while gates are run?
6. May two more Lucide icons be added in Phase 3 (same source and licence as the existing 43)?
