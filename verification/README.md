# verification/

The reliability layer — **the moat**. Built in **M2** (Phase 1). Existing text→Manim tools skip this; that's why they look like demos.

**Owns**
- `compile_repair` — render the code; on crash feed the **trimmed** traceback back and retry up to N times (**FR-5**). The free, deterministic correctness signal.
- `vision_critic` — render **multiple** keyframes → vision model checks overlap / off-screen / intent → structured issues (type + location + fix) fed back and re-rendered (**FR-6**). The paid, probabilistic visual-correctness signal.
- `best_of_n` — on critic non-convergence, generate N candidates, render, keep the highest-scoring (**FR-6** fallback).
- `caps` — hard caps on repair and critic iterations; on failure return the best attempt with a useful error — never hang or loop forever (**FR-7**).

**Invariants this package enforces**
- Cheapest checks first — the free compile check gates every paid vision call.
- The two signals are **never conflated**: "it compiles" ≠ "it looks right." Compile is deterministic; vision is probabilistic.
- Verified-before-seen — no scene reaches the user without passing both layers (or a documented best-of-N fallback).

**Maps to:** Phase 1 / M2. **FRs:** FR-5, FR-6, FR-7.
