# Learn hybrid video: reuse audit and phased proposal

Status: architecture proposal based on a source audit, not an implemented replacement.

## 1. Audited state and scope

- Main checkout: `C:/Users/Dev/Desktop/Franko`, commit `06df33c` at inspection.
- Earlier experimental worktree: `C:/Users/Dev/Desktop/Franko-learn-story`, branch `codex/learn-story-contract`, base `1dcc164`, with uncommitted lesson-contract changes and a browser attention prototype.
- Main has subsequently received reliability, Learn image-attachment, storage/accounting, and UI changes. The earlier worktree must not be copied wholesale over main. Reconcile individual changes against the current source.
- Existing user files, including `PRODUCT.md` and the concurrently appearing `scripts/preflight.py`, are outside this audit's edits.
- This audit inspects the Learn and Teach entry points, planning contracts, positioning components, browser and Manim rendering, narration/timing, checks, jobs, persistence, and export. It is not a production/security audit of every endpoint.
- Verified baseline: `python -B -m pytest -m unit -q -p no:cacheprovider` using the project `.venv`: **365 passed, 39 deselected in 44.03s**. No paid generation or fresh video render was run for this audit. The deselected tests are not counted as passing.

## 2. Current end-to-end paths

### Learn and Slides

`web/app.py` registers `web/learn.py` and `web/decks.py`. Learn produces a text answer and a short video offer. Accepting the offer sends its `video_prompt` into `planner/slide_plan.py`, which loads `prompts/slide-deck.md`. The resulting `Slide` objects go to `composition/slides.py`.

- HTML kinds use `generation/slide_deck.py`: one fixed CSS composition per kind, captured by Chrome as a PNG for each spoken beat.
- A math kind uses `generation/math_scene.py` and the Manim scaffold: plot one function and move a dot along its curve.
- TTS duration determines each still's hold time. Beat clips are concatenated; scene clips are crossfaded.
- Learn stores video status/path/version, then offloads the video through `core/storage.py`. It does not currently retain a complete lesson plan or deck script.
- Attached images are described through `web/seed.py` for the immediate chat reply. The stored user message retains the question and `has_image`, not the image description as a separate source record. The video planner subsequently sees the short offer prompt, not the full input context.
- Refinement plans a new deck from the old title plus the instruction. It does not edit a persisted scene plan.

### Teach

`web/engine.py` uses an outline and shared style, then calls `composition/decoupled.py`. Each scene is expanded into `SceneSpec`, converted into model-written Manim code, rendered and checked, then narrated and muxed. Project scenes have stable scene IDs, saved scripts, versions, and editing support.

This path has richer layout components and checks than Learn, but narration is generated after the animation and is budgeted against its duration. Reusing that orchestration unchanged would preserve a major limitation for the proposed narration-led lessons.

## 3. Positioning: useful existing code, with specific boundaries

### Named areas and fitting — KEEP for Manim; ADAPT for browser layouts

`generation/lattice_scene.py:29` defines a 40-cell grid, A–E by 1–8. `place()` at line 218 positions an object at a cell; `place_in_area()` at line 224 scales a group to an area.

These are useful geometry helpers. They do not maintain occupied regions or check whether another group is already in the requested area. Two independently placed objects can still collide.

`fit_content()` at line 309 fits the collected content near the end of a scene. It preserves existing relative positions, so it cannot untangle overlaps. It can also cause a late scale/recentre movement that interrupts continuity. Its minimum scale of 0.35 is not an absolute bounds guarantee: a 100-unit-wide group becomes 35 units wide even though the target width is 12.4. This arithmetic was checked locally; it is not a rendered reproduction.

There is also a concrete prompt inconsistency: the comparison example at line 125 recommends area `E2`–`F5`, but row F does not exist. A direct grid probe confirms `F5` is absent. Correct this before using the scaffold prompt as an authoritative geometry contract.

### Box labels, tables, flows, icons — KEEP existing helpers and assets

`labeled_box`, `node`, `table`, and `flow` already size or arrange related objects together. `assets/icons` and the generated icon catalogue are reusable assets.

Use those helpers for existing Manim scenes. For HTML, reuse their sizing/ownership rules and assets, but implement DOM/SVG equivalents; Python Manim objects cannot serve as browser layout objects directly. Fitting must respect a minimum readable text size; overcrowded content should split into steps rather than keep shrinking.

### Arrow attachment — KEEP rule; EXTEND routing

`connect()` at line 275 creates boundary-to-boundary arrows with spacing. This addresses arrows passing through their own endpoint boxes.

It does not avoid unrelated boxes or other arrows. It returns an arrow for the current geometry without maintaining a live connection when endpoints move separately. The browser needs measured object bounds, explicit connection ports, route selection, and updates whenever connected objects move. Dense graphs may require an established layout/routing library or staged visibility. Zero crossings cannot be guaranteed for every graph.

### Graph and geometry helpers — KEEP; make results data-driven

`graph()` at line 376 samples a function to estimate its y-range and returns a grouped plot, dots, and labels. `square_on_segment()` and the pure orientation helper encode valuable tested mathematics. `generation/components.py` also contains fitted formula and geometry helpers.

Preserve these. Improve domain/discontinuity handling when needed: a 60-sample range estimate is not proof that an arbitrary function fits everywhere. Replace the unconditional dot sweep in the Learn math template with explicit, checked state sequences when teaching an algorithm. A gradient-descent animation must use computed updates, not merely traverse the curve.

## 4. Reuse map

| Existing component | Decision | New role or limitation |
|---|---|---|
| `web/learn.py`, `web/static/learn.js`, `web/seed.py` | EXTEND | Preserve chat, attachments, offers, versions, status and storage; supply a complete lesson request to the new planner. |
| `planner/outline.py`, `planner/expand.py` | ADAPT | Reuse contextual planning patterns; replace fixed duration-to-scene assumptions for the new path with concept and speech budgets. |
| Worktree lesson brief and saved narration | ADAPT | Preserve original question, explanation and plan; add image description, source references and final timing. Avoid regex-only scope decisions and silent loss of required concepts. |
| `planner/slide_plan.py`, `prompts/slide-deck.md` | RETAIN for legacy decks | The five-kind schema and mandatory opening/summary sequence are unsuitable as the new Learn contract. Existing Slides still uses them. |
| `core/schemas/scene_spec.py` | REUSE pattern; add versioned successor | Stable IDs, allowed actions and target validation are useful. Free-text layout notes are not executable layout or timeline data. |
| `generation/lattice_scene.py`, `generation/components.py` | KEEP / ADAPT | Retain Manim geometry and fitting; add a bounded-region mode with optional title/watermark so HTML can own those. |
| `generation/slide_deck.py` | KEEP fallback; EXTRACT styling | Reuse palette/typography/icon assets. Add flexible browser composition rather than stretching the old fixed Slide dataclass. |
| `generation/math_scene.py` | EXTEND | Accept formula/plot/geometry tasks, explicit data states and duration; produce a mathematical visual for an assigned region. |
| `verification/layout_lint.py` | REUSE checks; add browser adapter | Use common geometry facts with clear coordinate units. Browser extraction and sampling are new. Distinguish failed inspection from passed inspection. |
| `verification/vision_critic.py` | KEEP optional review | Reuse report handling and bounded budgets. Model inspection complements geometry and subject checks; it does not prove correctness. |
| `narration/tts.py` | KEEP | Speech synthesis, local Kokoro, measured duration and audio caching. |
| `narration/script.py` | ADAPT | Existing story-context input is useful. It currently receives an already specified scene; new lesson narration should precede detailed layout. |
| `narration/captions.py` | EXTEND | Retain SRT formatting; accept explicit cue start/end times so scene holds and transitions cannot cause drift. |
| `composition/slides.py` | REUSE parts; replace capture/timing for new path | Keep encoding concepts and optional music. Add persistent browser rendering and an explicit scene timeline. |
| `render/exec.py`, `render/sandbox.py`, `render/worker.py` | KEEP / EXTEND adapter | Reuse execution modes, process limits, timeouts, container tools and probes. Current deck helpers still assume host FFmpeg; route the new encoder through the existing abstraction. |
| `composition/stitch.py`, `composition/export.py` | KEEP / ADAPT | Reuse MP4/caption/export operations with timeline-aware offsets. Existing portrait output is padded landscape, not a newly laid-out portrait lesson. |
| `web/jobs.py`, `core/cancel.py`, `composition/pool.py` | KEEP | Existing progress, bounded concurrency, cancellation and deadlines. Integrate browser-process cleanup and stage checkpoints. |
| `composition/scene_dag.py`, editing helpers | REUSE identity/versioning | Stable scene IDs and revisions are valuable. The model is currently an ordered scene collection; it does not implement object continuity or dependency invalidation between scenes. |
| `core/cache.py`, `core/usage.py`, `core/storage.py` | KEEP / EXTEND | Retain hashing, accounting and storage. Cache keys must include applicable data, assets, theme, timing, voice and renderer versions. Persist plan packages as well as MP4s. |
| Attention reference script | ARCHIVE as experiment | Handwritten content/coordinates, 10 unique frames/s encoded at 30, no narration, and Chrome restarted per frame. Do not promote it into the general renderer. |

## 5. Checks that need stronger contracts

The current geometry lint is more capable than its introductory docstring suggests: it collects nested text and snapshots after play calls. It checks bounds, overlaps, covered text, tiny text, contrast and centering.

However, it applies animation end states rather than sampling the full continuous movement. It can miss objects crossing midway through a move. A failed probe returns `ok=True` with no score, deferring to vision. The new runtime needs `passed`, `failed`, and `unavailable` distinctions; unavailable checks cannot silently satisfy a release gate.

Claims in existing comments and `PRODUCT.md` that CSS cannot overflow are too strong. Fixed containers, long strings, wrapped rows and SVG connections still need measurement. New browser checks should reuse pure geometric rules where possible, with adapters for pixel coordinates, nesting, visibility and intended containment.

Teach also deliberately preserves silent clips when narration fails. That preserves expensive rendering work but is insufficient for a requested narrated Learn lesson: retain the clip for retry and expose incomplete audio rather than declaring the narrated lesson complete.

## 6. Proposed contracts and ownership

Keep the existing application and worker architecture. Add a new Learn path alongside legacy decks, behind an explicit internal renderer version/feature switch.

1. **Lesson request:** original question, selected context, attachment description/source IDs, learner scope, language and duration preference.
2. **Lesson plan:** learning objective, prerequisites needed for that question, complete narration, example, claims, labelled assumptions and coverage links. Numerical examples refer to computed data; historical claims can refer to evidence. Review meaning before rendering.
3. **Visual plan:** stable object IDs, groups, relationships/ports, reusable layout patterns, actions, data references and narration-beat references. No keyword branches for subject names or compulsory title/card/summary order.
4. **Compiled scene:** measured bounds, routes, renderer ownership, shared theme, explicit state transitions and final timestamps. Reject unsupported requests explicitly or simplify the visual while retaining the explanation.
5. **Rendered lesson package:** MP4, transcript, captions, lesson and visual plans, computed data/assets, timing, inspection results, renderer version and usage measurements.

HTML/CSS owns outer composition, text, boxes, tables and caption areas. SVG owns connections and diagram motion. Manim owns requested formula/graph/geometric visuals within assigned regions. Each element has one owner; there must be no duplicate headings or independent timing guesses.

For the first hybrid implementation, use an opaque rectangular math region with matching background and explicit pixel dimensions. Compose the mathematical clip into that reserved region through the shared export timeline. This avoids making transparent video support a prerequisite. Preview must use the same region and timestamps; deterministic final export must not depend on approximate live video seeking. Alpha layers can be added only if a real design needs them.

Narration duration determines action windows. After a scene's final spoken phrase, hold the final visual for **1.0 second by default**, then transition. This is a scene-level hold, not a pause between video frames or every sentence. Define the hold separately from the transition; both count toward total duration. Speech from consecutive scenes must not overlap. Captions end with their spoken phrase rather than remaining through an unrelated transition.

Cross-scene continuity uses stable lesson object IDs, the preceding end state, and declared changes for the next scene. A scene may recompose objects deliberately, but independent prompts must not invent new identities/colours for the same example. Precompute these boundary states so independent rendering is possible; an upstream change invalidates downstream scenes that actually depend on its state.

## 7. Phased implementation and acceptance gates

### Phase 0 — baseline and reconcile the existing work

Output: a working implementation branch based on the latest main, the unchanged legacy test baseline, and reviewed ports of useful lesson-contract changes.

Preserve attachment handling, usage attribution, storage fallback and the current Learn UI. Preserve the experimental worktree for comparison. Correct the invalid grid example as a small separate change when implementation is authorised. Do not wholesale merge the old web files.

Gate: legacy APIs/artifacts still load; no loss of the newer main functionality; baseline test failures resolved before new features are judged.

### Phase 1 — narration and lesson persistence

Output: inspectable lesson plans, exact scripts and worked-example data before any video render. Reuse chat/context, TTS and persistence seams.

Evaluate broad ANN, focused ANN weight updates, a sorting explanation and a history question. Review scope, prerequisite order, factual claims, arithmetic, consistency and whether the ending answers the question. Avoid binding quality checks to a fixed list of attention terms.

Gate: scripts can be reviewed independently of design; input context survives offers and refinement; examples are computed or supported and labelled; no silent truncation to meet an arbitrary slide count.

### Phase 2 — generic visual specification and browser positioning

Output: deterministic HTML/SVG previews from a versioned visual plan, using measured labels, safe regions, ports and composable layouts (sequence, grouping, hierarchy/network, timeline and comparison).

Build reusable objects/actions rather than classes such as `TransformerScene`. Reuse existing assets and geometric checks. Start with common layouts; select an existing graph-layout/routing library if graph complexity demonstrates the need.

Gate: manually authored fixtures for an algorithm, history and a network all use the same runtime without subject-specific code; long labels, crowded diagrams and moved endpoints have deliberate, readable outcomes. Valid JSON alone does not pass the visual gate.

### Phase 3 — browser animation, narration and continuity

Output: narrated HTML/SVG videos and a seekable preview using a persistent browser worker and deterministic scene time.

Schedule actions from measured speech, implement scene end holds and transitions, keep object IDs through scene boundaries, and emit explicit caption timing. Reuse cancellation, deadlines and FFmpeg execution helpers.

Gate: actual intermediate movement is checked; no speech overlap or truncated narration; 1.0-second holds are measured; preview and exported key states match. Verify genuine motion frame cadence rather than only the container FPS.

### Phase 4 — bounded Manim regions

Output: an HTML-led scene containing a Manim formula/graph animation that shares the same data and timeline.

Adapt the existing graph/formula/geometry helpers. Decouple scaffold title/background/whole-frame fitting from mathematical content. Implement explicit coordinate/region conversion and single ownership of labels. Use computed traces for algorithms such as gradient descent.

Gate: browser text and the mathematical animation agree numerically and temporally; no duplicated headings, cropping or unexpected late fitting; cancellation and cache reuse work for both renderers.

### Phase 5 — connect Learn to the new renderer

Output: new lesson videos through the existing Learn UI, controlled rollout, saved plans/scripts, explicit stage status and replayable versions.

Reuse thread IDs, job IDs, attribution, storage and download contracts. Add renderer-version metadata. Keep old MP4s playable and old deck records interpretable. Reuse scene identity/version patterns via an adapter instead of forcing Learn thread records into all of Teach's code-editing schema.

Gate: follow-ups, attachments, refinement, cancellation, restart recovery, audio retry and artifact serving are exercised end to end. No incomplete narrated lesson is marked complete merely because a silent MP4 exists.

### Phase 6 — cross-subject acceptance and selective retirement

Output: a comparison report with scripts, videos, failures, latency and actual cost for multiple unrelated and held-out prompts.

Include ANN overview, weight updates, attention, a sorting algorithm, a network protocol, history and biology. Test unfamiliar prompts without adding subject-name conditions. Judge learning correctness, readability, continuity, timing, first-pass success and total resource cost independently.

Measure cold/warm rendering and cache hits; establish budget thresholds from measurements, not guessed sub-minute promises. Do not use one handcrafted clip as evidence of generalisation.

Gate: promote the new Learn renderer only after it meets agreed content and runtime criteria. Legacy Slides remains supported. Remove obsolete Learn routing/prompt assumptions only when no supported path or stored record needs them. Preserve the old renderers and their tests until that dependency check passes.

## 8. What is actually new

The largest new pieces are the executable visual contract, browser layout/animation runtime, math-region composition, and shared speech-driven timeline. Existing job infrastructure, mathematical helpers, TTS, accounting, storage, versioning patterns and many verification rules remain useful.

Reusing source requires checking its guarantees, not copying its comments. This audit supports a staged extension; it does not support either a wholesale rewrite or the claim that positioning is already solved.
