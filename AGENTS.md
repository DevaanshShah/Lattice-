## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Lattice video diagnostics

For a generated-video crash, layout failure, narration/visual mismatch, interrupted run, or request to make the generator learn from a failure, read and follow `.agents/skills/lattice-video-diagnostics/SKILL.md` before changing code. Start from the output folder's `run_report.json` and saved plans; do not hand-edit one generated video as the final system fix.

## No patchwork

Clients run this app on their own. Nobody is there to repair a video after it is made, so every
fix must hold for lessons nobody has seen yet.

- Fix the cause as a general rule in the renderer, the validator or the planner. Never special-case
  one topic, one fixture, one object id or one label to make a render look right.
- Never loosen a check or add a blind retry to get a pass.
- Every fix comes with a test that fails without it, and the whole regression set
  (`python -m scripts.video_regression`) is run before a commit. The Manim case is part of that set
  and must pass on every run.
- Judge a fix by the rendered frames, not by the code.
