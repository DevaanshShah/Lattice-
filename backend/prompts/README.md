# prompts/

Versioned system/instruction prompts, loaded — never inlined in code. Grows from **M1** onward.

**Expected prompts**
- `manim-conventions` — Manim CE house rules tied to the pinned version (no CE/GL mixing, no deprecated calls, positioning conventions). Backs **FR-8**.
- `scene-spec` — NL prompt → structured scene spec (**FR-1**).
- `codegen` — scene spec → Manim code (**FR-2**).
- `vision-critic` — frame(s) → structured overlap/off-screen/intent issues (**FR-6**).
- `planner` — topic → outline (**FR-3**).
- `narration` — narration-first script generation (**FR-9**).
- `style-spec` — generate the per-video JSON design system (**FR-4**).

Keep critic output **structured** (typed issues + location + fix), not free prose — free-text critiques don't feed back reliably.
