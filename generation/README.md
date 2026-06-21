# generation/

NL/scene-spec → Manim CE code. The codegen layer. Built in **M1** (Phase 1), extended in **M5**.

**Owns**
- `scene_spec` — NL prompt → structured scene spec (objects, layout intent, narration line, animation beats) **before** any code (**FR-1**).
- `codegen` — scene spec → Manim CE code targeting the pinned version (**FR-2**).
- `guardrails` — Manim API constraints: no CE/GL mixing, no deprecated calls, house positioning conventions (**FR-8**).
- `style` — inject the shared **style spec** into every scene's generation prompt so independent scenes look like one film (**FR-4**).
- `tiered` — cheap/fast model first; escalate to a strong model only after repeated failure on a scene.

**Maps to:** Phase 1 / M1 (single scene), Phase 3 / M5 (style spec). **FRs:** FR-1, FR-2, FR-4, FR-8.
