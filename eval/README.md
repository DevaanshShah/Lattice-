# eval/

The regression harness that keeps you from tuning blind. Built in **M3** (Phase 1), run on every prompt/model change thereafter.

**Owns**
- A small **fixed battery** of ≥10 varied prompts with expected outcomes.
- A scoring pass (compile success + vision-critic flag count) per prompt.
- A regression gate: re-run on every prompt/model change to catch quality drops before they ship; prove a change *helped*, not just *ran*.

**Why it exists:** prompt tweaks can secretly regress quality. Without a fixed eval set you're flying blind.

**Maps to:** Phase 1 / M3, ongoing. **FRs:** supports FR-1/FR-2/FR-6 reliability claims.
