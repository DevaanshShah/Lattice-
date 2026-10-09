# Learning video hardening plan

Date: 2026-10-09 · Branch: `codex/learning-video-continuity-20260922` · Status: proposed, not started

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

## 2. Working rules

1. One phase at a time. A phase is one commit, or a few small ones, on this branch.
2. A phase is finished only when its gate passes. If the gate fails, revert that phase and write
   down why.
3. Phases 0 to 2 make no AI calls. They are tested by re-rendering saved plans, which is free.
4. No AI spend without the owner's go-ahead. Every live run states its maximum cost first.
5. Never judge by tests or plan files alone. Every gate includes rendered frames.
6. Do not hand-edit a generated plan as a fix. Fix the planner, the checker or the renderer.
7. `main` and the old Manim pipeline stay untouched until Phase 4.
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
6. The owner judges the look at least as good as the 2026-09-20 gold video.
7. Unit tests and the regression harness are green.

## 4. Phases

| Phase | Goal | AI calls | Size | Gate |
|---|---|---|---|---|
| 0 | Checkpoint and safety net | none | medium | Harness green; owner accepts the starting contact sheets |
| 1 | Correctness fixes | none | medium | Tests green; saved-plan verdicts as expected; frames change only where intended |
| 2 | Look | none | large | No compact-layout fallback on the fixed set; owner approves contact sheets |
| 3 | Lesson step and prompts | yes, capped | large | Plan battery beats the baseline; lesson length within budget |
| 4 | Acceptance and merge | yes, capped | small | Definition of done; owner sign-off |

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

### Phase 3: lesson step and prompts

This phase changes what the AI is asked, so it needs live runs.

0. **Measure first.** Run the plan battery on the unchanged prompts with `gpt-4o-mini` and
   `gpt-4o`, and store it as the baseline.
1. **Duration reaches the lesson.** `composition/browser_video.py` passes the requested duration
   and scene count to the lesson step. The prompt gets a word budget of duration × 2.3 words per
   second, the pace the old pipeline already uses. The lesson is rejected and retried when it is
   more than 25% away from the budget. Cutting scenes off a finished lesson is removed.
2. **The lesson step is told what can be drawn.** Its prompt refers to a list of visual forms
   that is not there today.
3. **A plain-language demonstration per beat.** A new optional field in the lesson says what the
   viewer should see change. It is passed to the visual step. Old saved lessons still load.
4. **No label-only scenes.** Every scene needs at least one claim that requires real proof.
5. **Split planner prompt.** A short core, plus one section per family: algorithm, flow, data,
   media. The lesson step tags each scene with a family and only that section is sent. An
   unknown family sends everything, as today. The four contradictions are removed.
6. **Proof failures name the object.** The retry message says which claimed object did not change.
7. **Default model.** Chosen from the battery numbers.

Gate: against the baseline, plan success and first-try scene passes do not fall, and should rise.
Lessons are within the word budget. Unit tests and the regression harness stay green. Expected
spend for the phase is about one to two US dollars, as an estimate from measured costs
(`gpt-4o-mini` about $0.003 per plan, `gpt-4o` about $0.06 to $0.16). Each run is confirmed first.

### Phase 4: acceptance and merge

1. Three full videos through the web engine with `scripts/selftest.py --renderer browser_v2`:
   binary search, the order-lookup harness, and one more topic the owner picks.
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
- **Math components:** graphs and tables from the old Manim scaffold (`generation/lattice_scene.py`).
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
- The checker cannot prove that a picture teaches the claim. No published system can. Phase 4
  relies on a person for this.
- Drafts planned before 2026-09-29 may need planning again.

## 7. Questions for the owner

1. Which third acceptance topic: the contour lesson from the original plan, or another?
2. If `gpt-4o-mini` fails the battery, is `gpt-4o` acceptable as the default?
3. Should `reports/` go into git and `research_notes/` be ignored?
4. Should the checkpoint commit be pushed, and with or without the co-author line?
5. Can Docker Desktop stay on while gates are run?
