# Learning video implementation plan

Keep the existing browser and sandboxed Manim renderers. Consistent visual identity is
not a fixed scene template. Do not add a learning database, unrestricted generated
scene code, new agent framework, or new dependencies for these phases.

## Phase 1: reliable entry points and relationships

Status: implemented locally. Unit and real Chrome/FFmpeg regressions passed.
Graphify update attempted but blocked by missing tree-sitter; graph is absent.

- New web browser projects explicitly request semantic schema v2.
- Existing saved v1 projects remain readable and build with their saved schema.
- Semantic browser scenes render declared relationships between visible endpoints.
- Reuse the existing boundary-anchored SVG relationship renderer.
- Gate: route regression, visible/hidden endpoint regression, full unit suite,
  and real Chrome/FFmpeg replay without generation-model calls.

## Phase 2: executable storyboard and cue timing

Status: audience/prerequisite metadata, whole-lesson scene context, validated
normalized cues and measured-audio timelines implemented locally. Browser still
segments honor cue start times; Manim executes cue windows. Browser continuous
motion remains Phase 3. Fractions are planning estimates, not word alignment.
Old plans retain untimed fallback. Timed plans require explicit visibility actions
rather than silently inserting unscheduled actions. Existing evidence/capability
validators remain in use; semantic proof of arbitrary narrated claims is not solved.

- Extend existing lesson/visual contracts with learner context, visual evidence,
  retained context and optional validated start/duration cues; preserve old plans.
- Plan narration and visual evidence together in the existing planner passes.
- Reject unsupported demonstrations before locking narration.
- Derive timings from measured cached speech duration; never silently truncate audio.
- Gate: invalid timing, unsupported evidence and continuity regressions.

## Phase 3: continuous browser animation

- Use one browser page with native Web Animations/SVG, paused and deterministically
  sampled at frame times. Wait for fonts and images before measuring geometry.
- Preserve existing render supervision, saved artifacts and bounded layout retry.
- Agent-harness vertical slice: concrete request, validated tool arguments, execution,
  returned result and visible failure/retry. No topic-specific renderer coordinates.
- Gate: inspect start/middle/end frames, actual motion, speech timing and export cost.

## Phase 4: mathematical and algorithm demonstrations

- Extend the bounded Manim compiler using installed 0.18.1 capabilities: MathTex,
  matching transforms, trackers/updaters and computed curves where appropriate.
- Binary search must show computed midpoint, comparison and excluded interval;
  use executable trace checks, not self-declared claim coverage alone.
- Contours must represent computed level sets of the declared function, not
  decorative rings. Check numerical values and trajectories independently.
- Choose one renderer per scene initially; do not create a parallel scene engine.

## Phase 5: acceptance and quality gates

- Complete binary-search, agent-harness and contour lessons through the same routes.
- Separate factual/semantic correctness, visual coverage, geometry/readability,
  continuity, motion and narration timing. Check intermediate frames too.
- Record elapsed time and actual model calls; reuse saved plans/audio for retries.
- Keep optional semantic classifiers advisory until evaluated against failures.
- Do not claim measured learning effectiveness without learner testing.

## Removal policy

Retain legacy rendering for existing projects. Remove fixed-slide restrictions only
from upgraded planning paths after their replacement passes acceptance. Replace
equal-duration still-frame export only once deterministic animation export passes.
Remove decorative math fallbacks from upgraded mathematical lessons, not unrelated
historical projects. No broad cleanup or deletion during the first phase.
