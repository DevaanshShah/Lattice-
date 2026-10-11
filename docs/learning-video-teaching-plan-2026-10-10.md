# Learning videos: the teaching plan

Written 2026-10-10. This follows `docs/learning-video-hardening-plan-2026-10-09.md`, whose
Phases 0 to 3 and the first part of Phase 4 are done. It replaces the "what remains" list of
that Phase 4. How the system works today is in `docs/learning-video-system-flow.md`.

## Where we are

- **Drawing works.** Icon pieces on black, panels, a load bar, a ball that follows a request,
  code beside an array. Nine fixed test videos render the same way every run.
- **A system topic is planned in one AI call**, for about $0.0013 on
  `deepseek/deepseek-v4.1-flash`. Food delivery, an agent harness and backpropagation were
  planned and rendered this way.
- **It shows a system. It does not teach.** Every video tells the same story in the same order,
  because the prompt dictates the story and carries one worked example that models copy.
- **Algorithm topics fail.** Binary search and dynamic programming go through the older route,
  where the AI writes every object and action, and no model tried could do that.
- **A teacher has no say.** The web app shows scene titles to tick or untick. Nobody approves
  what is taught, in what order, or with which example.
- The app's `.env` still names `openai/gpt-4o-mini`, which planned nothing in any test.

## What we are building

Today: topic → video.

Target: topic → a teaching brief the teacher approves → a video drawn from that brief.

Three ideas carry the plan:

1. **The story comes from the learner's problem, not from our prompt.** Before any scene is
   written, the lesson states the question a learner would ask, the real-life problem that makes
   the idea necessary, the mistake beginners make, and the question that checks they understood.
2. **The AI is free in the story and held in the staging.** It chooses what to teach and how to
   tell it. It stages that with moves from a menu, and code draws and checks the result. The
   checks test craft (was the piece shown before it was used, is the opening a question), never
   a fixed plot.
3. **Each kind of topic gets its own playbook.** A playbook is a short prompt, a menu of moves
   and the code that draws them: a map for systems, code beside data for algorithms, a table
   for dynamic programming, two sides for a comparison.

## Working rules

Carried over from the hardening plan and `AGENTS.md`:

- No patchwork. A fix is a general rule with a test that fails without it.
- No AI spend without the owner's go-ahead. Each phase states its cap.
- A new picture is proved on a hand-written plan before the AI is asked for it.
- The full test suite and the regression set, Manim case included, pass before every commit.
- Quality is judged by watching the rendered video. A pass rate says a video was made, not
  that it is good.
- Commits carry the owner's name only.

## Definition of done

- A teacher types a topic, gets a syllabus, and for each lesson a brief they can edit and
  approve before anything is drawn.
- Three acceptance topics produce videos the owner accepts as teaching, not touring: one
  system, one algorithm, one dynamic programming.
- Two videos on different topics do not share a plot.
- A video costs at most the ceiling the owner sets (see Questions), on
  `deepseek/deepseek-v4.1-flash`.
- At least 5 of 6 live runs per acceptance topic produce a video with no manual repair.

## Phase A: the teaching brief (the story layer)

No new drawing. This phase changes what the AI is asked, for the map playbook that already
works, so the effect can be seen on topics we already have videos for.

**Status on 2026-10-10: built, and run live three times; the gate is still open.** Items 1 to
5 are in the code. On `deepseek/deepseek-v4.1-flash` the first two runs planned 1 of 6 each,
for reasons that were faults in the prompt and the checks and are fixed (a required field the
prompt did not mention, a rule that refused a closing recap, and a fixed scene count that made
lessons a third too long). The third run planned 2 of 3 before the key ran out of credit, with
three runs unstarted. The lessons that planned no longer share a plot and read as teaching;
two are rendered in `out/phase4_review/`. What the gate still needs: six completed runs with at
least five planned, and the owner's verdict on the videos.

Found on the way and fixed, because an AI-drawn map hit them: three layout rules (a feeder
piece sits beside what it feeds; a long arrow goes round the pieces between; a stepped arrow's
label sits beside its upright stroke) and two checks (an arrow may not cross a piece it does
not join; a label may not touch an icon piece).

1. **A teaching brief per lesson.** It is written in the same AI call as the lesson, as the
   first thing in the answer, so a video still costs one call. A teacher who edits the brief
   pays for one more lesson call; one who accepts it pays nothing extra. It holds:
   - who the learner is and what they already know;
   - the one thing they will be able to do afterwards;
   - the opening question, in the learner's words;
   - a real-life problem with concrete details that makes the idea necessary;
   - the naive attempt and why it fails;
   - the turning point: the idea that resolves it;
   - the exit question and its answer.
2. **The lesson is written to serve the brief.** The prompt has the model decide the brief
   first and tells it that every scene must move the learner from the question to the turning
   point. When a teacher edits a brief (Phase E), the lesson call receives the edited one.
3. **The prompt stops dictating the plot.** The "first introduce, then follow, then break,
   then fix" order comes out of `prompts/lesson-plan-map.md`. So does the single worked example
   that models copy; the shape is described instead. In its place are principles: open on the
   question, bring a piece on when the story first needs it, name an idea only after its need
   has been shown, end by answering the opening question.
4. **Craft checks in code,** each sent back to the lesson call with its reason when it fails:
   - the lesson has a brief, and its two questions are written as questions;
   - the first sentence asks something;
   - no beat brings more than three new pieces on screen, which also stops the whole system
     appearing in the first beat;
   - every piece on the map is used by a move other than its introduction;
   - a meter exists only if some move changes it.
   Since 2026-10-11 the opening check is "the first scene has an ask move", and the closing
   check question and answer are added by code from the brief, so neither needs a check on
   wording.
5. **A sameness measure.** The battery reports, across lessons, the kind of the first move, how
   many pieces the first beat shows, and the order of move kinds. Three lessons with one
   pattern is a failure of this phase even if all three planned.

Tests: a brief missing a part is refused; each craft check has a lesson that trips it; a lesson
that follows a brief passes; old saved lessons without a brief still load.

Gate: food delivery, the agent harness and backpropagation are planned and rendered again. The
owner watches the three and confirms they no longer read as one template. Planning stays at or
above 5 of 6. Cap: $0.30.

## Phase B: playbooks and the choice between them

No new drawing.

**Status on 2026-10-11: item 1 is built.** There is a registry (`planner/playbooks.py`) with
two playbooks, map and trace, and the planners go through it. Item 2 is not built as written:
the brief is written in the same call as the lesson, so the playbook has to be known before
that call, and it still comes from keyword matching on the topic. A small routing step is the
open piece. Item 3 (several playbooks in one lesson) is not built.

1. **A playbook registry.** One place lists each playbook: its name, a one-line description of
   what it is for, its lesson prompt, its move menu, its compiler and its craft checks. The map
   is the first entry. Keyword matching on `board` in the recipes file is removed.
2. **The brief names the playbook.** The brief call is given the registry's names and
   descriptions and picks one. This costs no extra call. A name not in the registry is refused.
3. **One lesson, several playbooks.** A scene names its playbook, so a lesson can open on one
   picture and continue on another. What carries over between two playbooks is defined: nothing
   on screen, the same title and narration thread.

Tests: scripted briefs route to the right playbook; an unknown name is sent back; a two-playbook
lesson compiles and validates; the map lessons of Phase A are unchanged.

Gate: unit tests and the regression set pass. No live spend beyond re-running the Phase A
battery once (cap $0.10).

## Phase C: the algorithm playbook

Code on the left, data on the right. The renderer already draws the code window with a moving
highlight, an array, a pointer, tick and cross marks, discarded cells and a counter.

**Added late on 2026-10-11, not yet run live: the table rule.** What held the gate open was
the model keeping a table straight: which cells start filled, with what, and in which order the
rest are worked out. That bookkeeping is now code's. The table states its rule once
(`"rule": {"start": [1, 1], "back": [1, 2], "op": "sum"}`), code works the whole table out, and
a fill names only a cell and the number the lesson expects there; every cell still empty before
it is filled first. The three forms in which a fill carried its own working are gone, so there
is one way to fill a table. A fourth hand-written lesson, `taught_coins` (fewest coins of 1, 3
and 4 that make 6, where taking the biggest coin first is wrong), uses `min` plus one. Whether
this raises the live pass rate is not known: the key has no credit, so no live run has been
made on it.

**Where it stood earlier on 2026-10-11.** Three hand-written lessons (`taught_search`,
`taught_stairs`, `taught_recursion`) compile, validate and render. With a live model the
lessons are right when they plan, because code checks the numbers the lesson states against
what the picture comes to; before that check one lesson planned and taught a wrong answer. On
the final code, with five tries, `deepseek/deepseek-v4.1-flash` planned binary search and
Fibonacci and failed climbing stairs; a fourth run stopped when the key ran out of credit.
Three runs are not a pass rate. The gate below is open, and what holds it open is the model
keeping a table's starting cells straight, not the drawing.

**Earlier the same day: built, proved on two hand-written lessons, and run live four times.**
On `deepseek/deepseek-v4.1-flash` the first version of the prompt planned 0 of 2; after four
fixes found from those answers it planned 2 of 2 (binary search, climbing stairs). That is too
few runs for a pass rate, so the gate below is open. The AI-written binary-search lesson is
rendered in `out/phase4_review/ai_binary_search/`. Its weak spot is the naive attempt for
climbing stairs: with no recursion tree to draw (Phase D), the model acts it out with moves
that mean something else.

Items 1 to 5 are in the code, with two changes from what is written below. The
working of a filled cell is shown as a line under the table ("Ways[3] = 2 + 1 = 3") with the
cells it reads lit, not as arrows between cells. And the trace checks do not run the lesson's
code: the model names which cells are compared or combined, and code works out every result,
so the numbers on screen cannot be wrong, but nothing checks that the moves follow the code.
Added on the way: a compare over several cells in one beat, a counter that counts a pointer's
checks by itself, and a clear move for starting a second attempt on the same data. Fixtures:
`taught_search` and `taught_stairs`. Item 6 (use of the frame) is done for traces only.

1. **Hand-written fixtures first.** `binary_search` exists. Add `dp_stairs`: climbing five
   stairs, a table of answers filled from left to right, each cell lit together with the two
   cells it is computed from.
2. **What the renderer still needs:** a table whose cells start empty and are filled, with a
   short arrow from the cells a value comes from; a heading on the data side.
3. **The move menu:** show the code and the data; light lines of code; point at a cell;
   compare a cell with the target; discard cells; fill a cell from other cells; count a step.
4. **The lesson prompt for this playbook,** written like the map's: the AI writes the code, the
   data, and for every sentence one move. Code fills in ids, claims, proof and timing.
5. **Checks specific to algorithms,** done by code that actually runs the trace: the lit lines
   exist; a pointer stays inside the array; a cell is filled only from cells already filled;
   the value written into a cell is the value the code would compute.
6. **The frame is used.** A short chain or a small array sits in the middle of the frame at a
   readable size, and a meter is drawn beside the piece it measures. Today a four-piece map
   leaves the lower half of the frame empty.

Tests: each move has a compile test; the trace checks each have a lesson that trips them; both
fixtures join the regression set.

Gate: binary search and climbing stairs plan in at least 5 of 6 live runs and the owner accepts
both videos. Cap: $0.40.

## Phase D: teaching moves

These are available to every playbook.

1. **Ask and reveal.** The question appears on screen, the picture holds for a moment, then the
   answer is shown. This is how a video asks a learner to predict.
   **Built on 2026-10-11, ahead of Phases B and C,** because the owner could see no difference
   in the brief-led videos: the question was spoken but not shown. Moves `ask` and `answer`
   put a line of text under the map; the opening question is the brief's; the check question
   and its answer are added by code after the last beat, with a 1.6-second hold between them.
   Proved on the hand-written fixture `taught_map`, which is compiled by the same code as an
   AI-written lesson. Live, with the ask move in the prompt, two system lessons planned out of
   two (food delivery on the first call, backpropagation on the second). Phase A's gate of five
   in six is still owed.
2. **A recursion tree with a work counter.** Calls grow as a tree, a repeated call is marked,
   and a counter shows the work done. This is the picture of the need for dynamic programming,
   shown before the table that solves it.
   **Built on 2026-10-11** as part of the trace playbook: the lesson gives the recursion as a
   start value, the steps each call takes and where it stops, and code works out every call.
   Moves `grow` and `spot`, a counter that reads the calls shown, and `remove` to clear the
   tree before the table. It covers recursions that step down by fixed amounts (stairs,
   Fibonacci, coin change); halving recursions such as merge sort are not covered. Proved on
   the hand-written fixture `taught_recursion`; not yet run against a live model.
3. **Compare.** Two approaches side by side with one difference marked. Carried over from the
   hardening plan's Phase 3.
4. **Zoom into a piece.** One piece of a map opens into its own small picture and closes again.

Each is built as: a hand-written fixture, the renderer piece, the move, its checks, then one
live topic. Items are independent, and the owner may reorder or drop any.

Gate per item: the fixture renders with no layout fallback, tests pass, and the owner accepts
one live video that uses it. Cap: $0.30 for the phase.

## Phase E: the teacher approves

Built after the brief has settled in Phases A to D, so the screen is built once.

1. **The brief is the approval screen.** After a topic is typed, the Teach tab shows the brief
   as editable fields. Today it shows scene titles. Approving it writes the lesson; editing it
   and approving costs one lesson call, not a new brief.
2. **The storyboard stays as a second, optional look:** the scenes with their sentences, before
   the render starts.
3. **A quick mode** skips approval for a user who wants a video from a topic in one step.
4. **The project stores the brief,** so a video can be traced back to what was approved.

Tests: API tests for brief, edit, approve and build; a project without a brief still opens.

Gate: the owner makes one video through the web app, editing the brief on the way. No AI spend
beyond that video.

## Phase F: the syllabus

1. **Topic to syllabus.** One AI call turns "teach dynamic programming" into an ordered list of
   lessons, each with its prerequisite and the one thing it teaches.
2. **The teacher edits the list:** reorder, drop, rename, add.
3. **Each entry becomes a brief** when the teacher opens it. Nothing is generated for a lesson
   the teacher has not opened, so a ten-lesson syllabus costs one call until videos are wanted.
4. **A later lesson knows the earlier ones:** its brief is given what the learner has already
   been taught, so it does not re-explain it.

Tests: a syllabus with a cycle of prerequisites is refused; a brief written from a syllabus
entry keeps its capability.

Gate: a five-lesson syllabus on dynamic programming, with the first two lessons made into
videos the owner accepts. Cap: $0.30.

## Phase G: acceptance and merge

1. The three acceptance topics each pass 5 of 6 live runs and are accepted by the owner.
2. The regression baseline is accepted for every fixture, including those added here.
3. The default model is set where the app reads it.
4. `docs/learning-video-system-flow.md` and the prompts document are regenerated.
5. The branch is merged into `main`.

## Order and cost

| Phase | What changes for the viewer | AI calls per video after it | Spend cap |
|---|---|---|---|
| A. Teaching brief | system videos stop sharing one plot | 1 | $0.30 |
| B. Playbooks | nothing visible; makes C and D possible | 1 | $0.10 |
| C. Algorithm playbook | binary search and dynamic programming work | 1 | $0.40 |
| D. Teaching moves | questions, the recursion tree, comparisons | 1 | $0.30 |
| E. Teacher approval | the teacher shapes the lesson | 1, or 2 if the brief is edited | one video |
| F. Syllabus | a course, not a single video | 1, plus 1 per course | $0.30 |
| G. Acceptance and merge | | | $0.20 |

The brief is written in the lesson's own call, so the cost per video stays close to the
₹0.12 measured today on `deepseek/deepseek-v4.1-flash`: the brief adds about 200 output tokens.
What may raise it is retries, because a freer prompt and the craft checks give the model more
ways to be sent back. Phase A's live run measures that.

## Risks

- **More freedom, more failures.** Taking the plot out of the prompt will lower the planning
  rate before the craft checks catch up. Phase A's gate holds it at 5 of 6.
- **A cheap model's teaching may be shallow.** The brief may be well-formed and dull. Code
  cannot judge that. The teacher's approval and the owner's review are the only checks, which
  is why approval is a phase and not an option.
- **Nothing checks that a sentence matches its move.** A sentence can say one thing while the
  move shows another. On 2026-10-11 this produced a lesson that planned and was wrong (a table
  ending at five under narration saying eight). For traces it is now partly closed: a computed
  cell and a counter's total carry the number the lesson expects, and code rejects a mismatch.
  It is still open for a number no move states, and for maps, where a second cheap call that
  reads the lesson against the brief is the likely answer.
- **Each playbook is real work.** A new picture needs a fixture, a renderer piece, moves, checks
  and a live test. Phase D lists four; more will be asked for.
- **Approval adds a step.** Some users want one click. Quick mode is there for them.

## Questions for the owner

1. **Order.** This plan puts the algorithm playbook (C) before the teacher's approval screen
   (E), so the screen is built once the brief has stopped changing. Should approval come
   earlier?
2. **Cost ceiling.** Is ₹0.5 a video acceptable as the limit? The design aims at ₹0.15.
3. **Acceptance topics.** Proposed: food delivery under load, binary search, climbing stairs
   by dynamic programming. Different ones?
4. **Syllabus.** Should a syllabus generate nothing until a lesson is opened, as written here,
   or generate every brief at once?
5. **`.env`.** The app still reads `openai/gpt-4o-mini`. Phase A's live runs name the model
   explicitly, but the web app will fail until that line is changed.
