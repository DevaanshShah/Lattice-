# Learning-video path: system flow

Written 2026-10-10 for an outside audit, and corrected the same day after that audit found it
described a half-finished working tree. It covers the web app's Teach path (renderer
`browser_v2`, plan schema version 2) on branch `codex/learning-video-continuity-20260922`.
The older Manim code-generation pipeline (`composition/decoupled.py`, `generation/codegen.py`)
is a separate path and is not covered.

## State of the code when this was written

- Committed and pushed up to `df92029`: the renderer, the validator, the regression harness,
  the hand-written test boards, and the `trace` action.
- The map-lesson work in sections 3 to 5 was committed on 2026-10-10, after this document
  was corrected.
- Test status at that commit: 616 tests pass, Manim tests included. All nine regression cases
  render with no layout fallback; the Manim case and the old-format case are frame-identical
  to the approved baseline.
- The map-lesson design below was run live once per model on one topic (section 10).

## 1. The flow in one page

| # | Stage | Who does it | Where | Costs money |
|---|---|---|---|---|
| 1 | Topic and length come in | user | `web/app.py` `POST /api/projects` → `web/engine.py` `Engine._plan_browser` | no |
| 2 | Pick a recipe (skill) by keywords | code | `planner/product_recipe.py` `pick_recipe`, data in `prompts/product_video_recipes.json` | no |
| 3 | Write the lesson | model, 1 call (up to 3 tries) | `planner/lesson_plan.py` `generate`, prompt `prompts/lesson-plan-v2.md` | yes |
| 4 | Check the lesson | code | `LessonPlan` schema, `planner/lesson_map.py` | no |
| 5 | Write each scene's visuals | lesson with a playbook (map, trace): code. Otherwise: model, 1 call per scene (up to 3 tries) | `planner/playbooks.py` → `lesson_map.py` or `lesson_trace.py`; or `planner/browser_visual_plan.py` `generate` | only without a playbook |
| 6 | Check each scene | code | `verification/visual_plan_validation.py` `validate_scene` | no |
| 7 | User approves the outline, then build starts | user | `POST /api/projects/{pid}/build` → `Engine._build_browser` | no |
| 8 | Speak each beat and measure its length | local voice | `narration/tts.py` `synthesize` (Kokoro when `LATTICE_TTS_ENGINE=kokoro`) | no |
| 9 | Draw the frames | Chrome via Playwright, or Manim in Docker | `generation/browser_scene.py`, `generation/manim_visual_scene.py` | no |
| 10 | Check the layout of every drawn state | code | `verification/browser_layout.py` `audit_html` | no |
| 11 | Join frames and voice | FFmpeg | `composition/browser_video.py` `build`, helpers in `composition/slides.py` | no |

Planning (`composition/browser_video.py` `plan`) covers stages 2 to 6 and writes
`lesson_plan.json` and `browser_visual_plan.json` into the project workspace. Building
(`build`) covers stages 8 to 11 and makes no model calls.

## 2. The two documents that carry everything

**Lesson plan** (`core/schemas/lesson_plan.py`): topic, audience, and scenes. Each scene has
beats. Each beat has:

- `spoken_text`: the sentence that is spoken.
- `claim_ids`: ids for what the sentence asserts.
- `claim_requirements`: for each claim, the kind of proof the picture owes: `label`, `value`,
  `relationship`, `state_change`, `sequence`, `comparison`, `asset`.
- `visual_anchors`: short texts that must be readable on screen during the beat.
- `move` (map lessons only): what happens on the map during the beat.

A lesson may carry one `map`: pieces (icon, label, colour, optional panel, optional meter,
optional "planned" flag) and arrows. A scene may carry a `takeaway` line.

**Visual plan** (`core/schemas/browser_visual_plan.py`): one `BrowserScene` per lesson scene,
with `objects`, `relationships`, and one `VisualBeat` per lesson beat. A beat has timed
`actions` (`appear`, `hide`, `set_state`, `move`, `compare`, `increment`, `highlight`, `trace`,
and others) and `evidence` records that tie claims to objects and actions.

State is not stored. It is replayed: `core/visual_state.py` `opening_state`, `apply_action`,
`closing_state` compute what is visible and each object's payload at any point. The validator
and the renderer both use this replay, so they agree on what is on screen.

## 3. Lesson step (stages 3 and 4)

`planner/lesson_plan.py` `generate(topic, skill, schema_version=2, target_seconds, max_scenes)`.

- The recipe decides the board (`board` in `prompts/product_video_recipes.json`: `map` for
  `architecture_explainer`, `workflow_explainer` and `before_after`; `free` for the rest).
  The model does not choose, and a lesson of the wrong shape is sent back.
- System message: `prompts/lesson-plan-map.md` for a map lesson, otherwise
  `prompts/lesson-plan-v2.md`. User message: topic, recipe guidance, the icon list for a map
  lesson (`core/visual_assets.py` `asset_inventory`), and a word budget of
  `target_seconds × 2.8` (the measured pace of the voice) with ±30% tolerance, also stated as
  a number of beats and scenes.
- The call asks for JSON mode (`response_format={"type": "json_object"}`) and for reasoning to
  be off (`PLAN_EXTRA`), because a reasoning model otherwise spends its whole output budget
  thinking and returns nothing.
- A **map lesson** is a teaching brief (`LessonBrief`: the learner, what they will be able to
  do, their question, a concrete problem, the naive attempt, the turning point, a check question
  and its answer), the map and, for every beat, only `spoken_text` and a `move`. Any other
  lesson is the full shape with claims, requirements and anchors.
- `fill_map_lesson` then completes a map lesson in code: scene and beat ids, one claim per
  beat, the proof kind that move owes (`PROOF`), and the anchors (labels of the pieces the move
  involves, plus the meter reading).
- The answer is checked. On any failure the reason is appended as a user message and the model
  is asked again, up to 3 attempts. Checks, in order:
  1. the `LessonPlan` schema: unique ids, every claim has a requirement, map rules, and
     `_moves_fit_the_map` (every beat of a map lesson has a move and exactly one claim; a move
     names only pieces on the map; a path goes through icon pieces joined by an arrow, in
     either direction; a meter is a meter);
  2. every beat has anchors;
  3. the word count is inside the budget and the scene count within `max_scenes`;
  4. `lesson_map_problems`: icons exist, and no scene consists only of `introduce` and `point`;
  5. for a map lesson, `plan_map_scenes`: the scenes are compiled and run through the same
     validator as a model-written scene (section 5). A lesson that cannot be drawn is rejected
     here, and so is one that has a fix but ends with something still red.
  6. for a map lesson, `craft_problems`: there is a brief; the first scene has an `ask` move;
     no beat brings more than three new pieces on screen; every piece is used by a move other
     than its introduction; every meter is moved by some move. These test craft, not a plot.
- Every rejection reason is passed to `on_reject`; a build records it in its run report and the
  battery prints it.

### The moves

| Move | Fields | Compiled into | Proof owed |
|---|---|---|---|
| `introduce` | pieces | `appear` | label |
| `point` | pieces | `appear` if needed, `highlight` | label |
| `send` | path | `appear` missing pieces, `trace` along the path | relationship |
| `trouble` | pieces, optional meter and value, optional path and count | optional `trace`, meter to value in red, pieces to red | state_change |
| `fix` | pieces, optional meter and value | planned pieces built, every red piece (named or not) back to its own colour, meter to value in its own colour | state_change |
| `measure` | meter, value | meter to value | value |
| `remove` | pieces | `hide` | state_change |
| `ask` | optional text; without it, the brief's question | a question line appears under the map | label |
| `answer` | text | an answer line appears under the question | label |

The check question and its answer are not written by the model. `fill_map_lesson` appends them
after the last beat, as an `ask` and an `answer` in the brief's own words, and the compiler
holds the picture for 3 seconds between them (`pause_after`). A scene has at most one question
and one answer. Piece ids written loosely are tidied by code wherever they are used, and what an
`ask` beat speaks is the question it shows.

Pacing is code's job in both playbooks. Every beat is followed by 0.4 seconds of silence, and a
scene's last beat by 0.9. A beat also carries the least time its steps need (`min_seconds`): 1.8
seconds for each cell worked out or number taken, 0.9 for each cell checked, 0.3 for each call
of a tree revealed. If the sentence is shorter than that, the picture goes on in silence.

### Playbooks

`planner/playbooks.py` lists the playbooks. Each has a lesson prompt, a menu of moves, a fill
step, a compiler and craft checks; `planner/lesson_shared.py` holds what they share. The
recipe's `board` names the playbook.

| Playbook | For | Picture | Moves |
|---|---|---|---|
| `map` | systems and processes | icon pieces joined by arrows | introduce, send, trouble, fix, measure, point, remove |
| `trace` | algorithms | code on the left, data on the right; the data can be arrays, a table to fill, or the tree of calls a recursion makes | show, run, look, compare, take, discard, fill, count, clear, grow, spot, remove |

Both also take `ask` and `answer`. On a trace any move may light lines of the code, and code
works out every result: a compare is decided by the values on screen, a table is worked out in
full from the rule it states once (its first cells, how far back each later cell reads, and
`sum`, `min` or `max` plus a constant), with the working of each cell shown as it is filled, a counter
tied to a pointer counts that pointer's checks, the calls of a recursion tree are worked out
from its start, steps and stop (`core/call_tree.py`), and each beat's anchors are read off the
state its move produced. Where code works a number out, the move also carries the number the
lesson expects (`expect`), and a lesson whose number differs from the real one is sent back. A
fill names only its cell and that number: every cell still empty before it is filled first, in
order, so a lesson cannot fill a table out of order or read a cell that is still empty. A fill
shows where its number comes from (the cells read, the working line) before the number lands.

Three more things are code's on a trace. A `take` move takes the number under a pointer out of
a value and shows the subtraction, for an attempt that grabs one thing at a time. A counter
belongs to one attempt: after a `clear` it keeps its total and counts no further, and a lesson
that goes on counting with it is sent back. And the stage is kept clean: when an attempt ends
(a `clear`, or the first fill of a table) its marks, its pointers and the values its takes used
up leave, unless a later beat uses them; a `count` puts every counted total on screen; an item
that has left for good gives up its room, so what follows is not drawn small beside a hole. An
array's cells are numbered from 0, or from 1 everywhere when it says `"first": 1`.

## 4. Visual step (stage 5)

`planner/browser_visual_plan.py` `generate`.

**Map lesson: no model call.** `plan_map_scenes(lesson, skill)` returns the scenes.
`compile_map_scene` writes each one:

- objects and relationships from the map (`map_objects`), identical in every scene;
- `layout_ids`, so every piece keeps one place across scenes;
- opening and carryover from the previous scene's replayed state;
- actions from each beat's move (`_actions`), given what is on screen and each piece's current
  colour; a piece inside a panel brings its panel; a change that would change nothing is not
  written, and a beat left with no action lights up what the sentence is about;
- action ids and even timing windows across the beat;
- the takeaway caption as the last action of the scene, or, in a scene that ends on the check
  question and its answer, on the beat before the question, which takes its place;
- one evidence record per beat, naming the pieces the move involves.

**Lesson without a map: one model call per scene**, up to 3 attempts, prompt
`prompts/browser-visual-plan-v2.md`. The model returns the whole scene: objects,
relationships, actions, evidence. `_normalise_v2_carryover` repairs carried objects,
`_spread_untimed_beats` fills in timing when the model omits it, `derive_closing` settles what
remains on screen, and `validate_scene` accepts or rejects.

## 5. Validator (stage 6)

`verification/visual_plan_validation.py`. It replays the scene and rejects it when:

- beats do not match the lesson's beats, in order;
- a carried object was not left on screen by the previous scene, or its definition changed;
- an anchor is not readable during its beat (`_visible_labels_by_beat`, `_anchor_visible`);
- evidence cites an object that is hidden in that beat;
- a claim lacks the required proof (`_proves`). Proof is judged from what the actions visibly
  did (`ActionEffect`: revealed, changed, removed), not from what the plan says:
  - `state_change`: an object already on screen changed or was removed;
  - `sequence`: two or more visible steps, at least one a change;
  - `relationship`: the evidence names both ends of an arrow **and the beat shows that arrow**
    (a `connect` or `trace` over it, or an end of it revealed in the beat);
  - `value`: a value-bearing object is on screen;
- an action is malformed: a `move` without a pointer, a `compare` without pointer and value, an
  empty `set_state`, a `trace` over pieces not joined by an arrow or through a hidden piece, a
  recolour to anything other than red or the piece's own colour;
- an icon, tone or panel member does not exist;
- `closing_visible_ids` disagrees with the replay.

Hides that the planner itself adds to tidy the screen (`clear_finished_steps`, `hide_final_*`)
never count as proof.

## 6. Renderer (stages 9 and 10)

`generation/browser_scene.py`. No model calls.

- `_semantic_html(scene, state)` turns a state into HTML. Layout is by rule: arrows define
  columns (`_flow_layers`); a row holds six icon pieces or four cards before wrapping
  (`ROW_WIDTH`, `_column_width`); every object the scene will ever show has a fixed slot from
  the first frame and is invisible until it appears (`_shown_in_scene`); `window.fitFlow`
  scales the stage to the frame.
- Columns come from the arrows (`_flow_layers`); a piece that nothing points to and that only
  feeds later pieces is placed in the column before the first of them.
- Arrows are routed in the page (`window.routeConnection`): straight when level; stepped
  between neighbouring columns at different heights, turning just outside the source's column
  with the label beside the upright stroke; along a lane outside the row when other columns
  lie between the two pieces; through the row gap when a flow wraps; straight inside a panel.
- `animation_html` builds one page per beat holding a snapshot per action. The capture loop in
  `render_animated_beat` seeks the page to each frame time (`window.seekAnimation`) and takes a
  screenshot, 30 frames per second, with software rasterising (`CAPTURE_ARGS`) so frames are
  repeatable.
- Motion: a change eases over at most 0.6 s at the start of its window and then holds; a new
  arrow draws itself over 0.7 s; a `trace` moves the ball 1.1 s per hop, in either direction
  along an arrow.
- Before capture, `verification/browser_layout.py` `audit_html` measures the page: nothing
  clipped, no object overlapping another by more than a quarter, no label on a card or an icon
  piece, no two arrow labels on one spot, no arrow through a piece it does not join, no title
  overlap. On failure the beat is retried once in a compact layout; a second failure stops the
  build with the measured geometry.
- Array scenes marked `render_mode: "manim"` go to `generation/manim_visual_scene.py` and are
  rendered in the Docker image `lattice-render:0.2`.

## 7. What the model decides and what code decides

| Decision | Map lesson | Lesson without a map |
|---|---|---|
| Story and sentences | model | model |
| Which pieces exist, their icons and arrows | model, once | model, per scene |
| What happens in each beat | model, as one move from a menu | model, as free actions |
| Claims, proof kinds, anchors | code, from the move | model |
| Objects per scene, carryover | code | model, repaired by code |
| Actions and their timing | code | model, code fills timing gaps |
| Evidence records | code | model |
| Positions, sizes, arrow routes | code | code |
| Whether a claim is proven | code | code |
| Model calls per video | 1 | 1 + one per scene |

## 8. Settings

Read by `core/config.py` from `.env` with prefix `LATTICE_`:

| Setting | Meaning |
|---|---|
| `LATTICE_LLM_API_KEY` | key for the model provider |
| `LATTICE_LLM_BASE_URL` | default `https://openrouter.ai/api/v1` |
| `LATTICE_LLM_MODEL` | default `openai/gpt-4o-mini` |
| `LATTICE_LLM_PROVIDER_PIN` | preferred OpenRouter upstream, with fallbacks allowed |
| `LATTICE_TTS_ENGINE` | `gtts` or `kokoro` |

`core/llm.py` `LLMClient._create` retries transient errors and blank answers
(`llm_attempts`, default 6; the planners pass 3) and records token use and cost
(`usage_snapshot`).

## 9. How it is tested

| Command | What it proves | Model calls |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | unit and integration tests | none |
| `python -m scripts.video_regression` | renders nine fixed plans and compares frames with an approved baseline by SSIM | none |
| `python -m scripts.plan_battery --model M` | plans four fixed topics live and reports pass rate, tries and cost | yes |
| `python -m scripts.selftest --renderer browser_v2` | one full video through the web engine | yes |
| `python -m scripts.prompt_doc` | regenerates `docs/learning-video-prompts.md` from the prompt files | none |

Fixed plans live in `tests/fixtures/video_golden/`. `system_map` and `code_and_picture` are
hand-written boards for the target style. `tests/test_lesson_map.py` covers the map lesson:
filling, compiling, the single call, the repair loop, and the layout of a compiled map.

## 10. Measured on 2026-10-10

One run each. Results varied between runs, so these do not rank the models. **All map-route
figures are from the earlier design, in which the model also wrote each scene's actions.** The
compiled design in sections 3 and 4 has not been run live.

| What | Result |
|---|---|
| Unchanged prompts, `gpt-4o-mini`, four topics | 0 of 4 planned (the lesson prompt's placeholder key was copied literally) |
| New prompts, `gpt-4o-mini`, four topics | 0 of 4 planned |
| New prompts, `gpt-4o`, four topics | 1 of 4 planned: the system topic, 5 of 5 scenes first try; the three topics without a map failed |
| System topic, six models | planned: `gpt-4.1` ($0.055, 9 calls), DeepSeek V3 ($0.007, 7 calls); failed: `gpt-4.1-mini`, `gpt-4o`, Claude Haiku 4.5, Gemini 2.5 Flash |
| One AI-planned video rendered | a `gpt-4.1-mini` plan from an earlier run, 57 s, no layout fallback |
| Compiled design (one call), system topic, before the recipe chose the board | planned: DeepSeek V4.1 Flash ($0.0029), GLM 4.7 Flash ($0.0016), Gemini 3.1 Flash Lite ($0.0036), each in 2 calls; failed: DeepSeek V3 (path with no arrow), DeepSeek V4 Flash (no JSON returned); `gpt-4.1-mini` wrote no map; Qwen 3.8 Flash was rate-limited |
| Compiled design, video rendered | the DeepSeek V4.1 Flash plan, 57 s, no layout fallback |
| Final code, two topics × three runs | `deepseek-v4.1-flash`: 6 of 6, average 1.7 calls, $0.0013 a lesson. `glm-4.7-flash`: 2 of 6, mostly narration about 10% over the length limit |
| Rejection reasons still seen in that run | a move naming a piece not on the map; a `fix` given a path; a jump with no route; a takeaway over the length limit (limit since raised to 80 characters) |

## 11. Known gaps

1. Reliability is measured on two topics only, three runs each: `deepseek-v4.1-flash` planned
   6 of 6 (2 on the first call), `glm-4.7-flash` 2 of 6. Other topics and other models are
   unmeasured.
2. Nothing checks that a sentence matches its move. A sentence saying the cache is fast with a
   `trouble` move on the cache passes every check, because claim, proof and picture all come
   from the move.
3. A map lesson can only show what the seven moves offer.
4. Lessons without a map (algorithms, data in messages, charts) still use the model-written
   visual step, which failed on every model tried.
5. `.env` still names `gpt-4o-mini`, which planned nothing.
6. A map lesson uses the map for every scene. Mixing boards within one lesson is not built.
7. Boards not built yet: ideas beside the map, compare, formula and graph through Manim.
8. Steps are spaced evenly through a beat, not matched to the words.
9. Length is checked by word count before the voice is made, with ±30% tolerance. The spoken
   duration is not checked against the request.
10. Early frames of a map can be mostly empty, because every later piece already holds its
    place. The layout check looks for clipping and overlap, not for balance.
11. Video quality has been judged from still frames by the developer only. Motion has not been
    reviewed, and the Phase 3 regression baseline is not accepted.

## 12. Audit of 2026-10-10 and what was done

| Finding | Status |
|---|---|
| Map path did not import (`BeatMove`, `compose_map_scene`, `map_scene_brief` missing) | fixed: the move design is finished and wired in |
| Document described checks and functions that did not exist | fixed in this revision |
| Shared evidence weakens attribution when a beat has several claims | a map beat now makes exactly one claim, enforced in the schema |
| `relationship` proof accepted an arrow that merely exists | fixed: the beat must show the arrow |
| ±30% is broad for a duration contract | open (gap 9) |
| Compact-layout retry is not a guarantee | open |
| Sparse early frames | open (gap 10) |
| Battery has five topics | not so: four |
| Prompt character counts stale, no generator in the repo | generator added: `scripts/prompt_doc.py` |
