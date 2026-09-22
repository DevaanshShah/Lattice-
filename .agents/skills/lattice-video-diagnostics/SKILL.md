---
name: lattice-video-diagnostics
description: Diagnose and repair Lattice learning-video generation failures, narration-to-visual mismatches, layout QA errors, media failures, or interrupted browser_v2 runs using the saved run report and artifacts. Do not use for ordinary feature work unrelated to generated-video reliability.
---

# Lattice Video Diagnostics

Use the runtime evidence before changing code.

1. Read `run_report.json`, `lesson_plan.json`, and `browser_visual_plan.json` from the failed output folder.
2. Inspect only the failed scene/beat HTML and image named in the report. Replay from saved plans; do not spend another LLM call unless the plan itself is defective.
3. Assign one owner:
   - `content_contract`: lesson or visual planner/validator. Repair the planner contract; never hand-edit only the generated artifact as the final fix.
   - `layout`: renderer-owned HTML/CSS or layout fallback. Fix the general pattern/count case, not topic-specific coordinates.
   - `browser_infrastructure`, `timeout`, or `media`: repair the environment or media stage. Do not ask the LLM to rewrite a valid plan.
   - `narration`: preserve completed frames and clips while repairing TTS or pronunciation.
4. If the report shows a compact-layout retry passed, treat the run as recovered. Promote a new deterministic layout rule only when the normal layout should support that recurring shape.
5. Reduce the failure to a unit fixture using the smallest lesson/visual scene that reproduces it. Add the regression test before or with the fix.
6. Run the focused test, the full unit gate, and one saved-plan replay through real Chrome/FFmpeg when renderer or media code changed.
7. Run `graphify update .` after source changes. If it fails, report the exact dependency problem; do not install dependencies without authorization.

Do not create an open-ended learning agent or database. Keep repairs bounded: deterministic fix first, one compact renderer retry, and the planner's existing capped JSON/contract repair. Preserve failed HTML, geometry, exception type, traceback, stage timing, and the repair action in `run_report.json`.

The main ownership seams are:

- `composition/browser_video.py`: run supervision and stage boundaries.
- `planner/lesson_plan.py`: narration and required visual anchors.
- `planner/browser_visual_plan.py`: scene planning and bounded contract repair.
- `verification/visual_plan_validation.py`: narration-to-visual contract.
- `verification/browser_layout.py`: geometry evidence.
- `generation/browser_scene.py`: renderer-owned layouts and fallbacks.
