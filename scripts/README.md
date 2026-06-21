# scripts/

Operational / one-shot scripts that wrap the engine — the operator layer, never product logic.

**Expected scripts**
- `setup_env` — the single documented command that produces a working Manim CE + LaTeX + FFmpeg environment from clean (Phase 0 acceptance).
- `render_sample` — render the checked-in hand-written sample scene (shapes + `MathTex`) to MP4 at preview and final quality + export one keyframe PNG (Phase 0 DoD).
- `run_eval` — execute the eval battery and print the regression score table (M3).
- `smoke` — end-to-end smoke: topic → outline approval → multi-scene video (M5+).

**Maps to:** all phases (operator tooling).
