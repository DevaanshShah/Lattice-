# IDEAS.md — future directions & parking lot

> **Not active scope.** Captured from brainstorming so it's here when you want it. The live
> roadmap is `MILESTONES.md`; this file is "maybe later / things considered." Nothing here is
> committed work.

---

## The core principle (the dividing line that sorts every idea)

- **Manim / code-gen** = precise, **animated**, *technical* content (math, ML/DL, CS, diagrams).
  Cheap + deterministic: the AI only writes **code**, the machine renders pixels for **free**.
- **Stable Diffusion / DALL-E** = **illustrations / photoreal images**. A different tool → a
  **different product**, not a feature of Lattice.

Almost every idea below falls into one of these two buckets.

---

## Use-case fit for the current Manim engine

| Use case | Fit | Note |
|---|---|---|
| Math / ML / CS explainers, algorithm viz, diagrams | ✅ perfect | the core lane — strongest, cheapest, most precise |
| Nursery: ABC / 123 / shapes | 🟡 partial | geometric letters/numbers/counting = yes; *cute illustrated* apples/animals = needs image-gen |
| 2D ads / promos | 🟡 weak | Manim is motion-graphic-ish but ads want branding/photoreal |
| Comic generation | ❌ no | needs illustrated characters → image-gen, not Manim |
| Illustrated storybook (prompt → picture + narration) | ❌ different product | image-gen + TTS + story LLM, not code-gen |
| Static flowcharts / architecture diagrams | 🟡 use Mermaid | cheaper deterministic path (see below) |

---

## Decisions / anti-patterns (things NOT to do, and why)

- **Don't fine-tune Stable Diffusion for Lattice.** Wrong target — SD makes pixels, can't do exact
  equations / labels / animation; fine-tuning is expensive and off-strategy. SD only matters if you
  spin up a *separate* illustration product.
- **Don't go "fully agentic" / CrewAI for the core pipeline.** It's already orchestrated
  *deterministically* (planner → spec → code → verify → stitch), which is more reliable and cheaper.
  Agents add nondeterminism, extra API calls, and failure modes. Use agents only for genuinely
  open-ended reasoning, not a fixed assembly line. Resist agent-washing.
- **Mermaid = complementary, not a replacement.** Great as a cheap, **no-LLM** path for *static*
  technical diagrams (flowcharts, sequence/ER, architecture). But it can't animate, do math, or
  narrate — so it's a lane for diagram-only scenes, not the explainer engine.

---

## Cost note (why code-gen beats image-gen for video)

- **Lattice (code-gen):** ~$0.003–0.15 per *whole video* (text tokens) + **free** local render.
- **Image-gen (SD/DALL-E):** ~$0.01–0.04 per *image*, and a video needs *many* non-animated,
  imprecise images.
- → code-gen is ~10–100× cheaper for technical video **and** gives animation + correctness.

---

## Future product idea (keep SEPARATE from Lattice)

**AI storybook / comic generator** — a different stack:
- prompt → **illustrated image** (Stable Diffusion / DALL-E) + **storyteller narration** (TTS) + a
  **story LLM**; optionally orchestrated with **CrewAI** (here open-ended agents make sense).
- Targets: nursery illustrated content, comics, primary-student picture-stories.
- **Keep it as its own product** — merging illustration into Lattice would dilute the precise-technical
  core that actually works.

---

## Candidate use cases to revisit later
- Nursery ABC/123/shapes (geometric parts already work in Manim; add image-gen only for characters).
- Mermaid-based static-diagram lane (cheap, deterministic, no LLM).
- 2D ads/promos (weak fit — only if a clear customer appears).
- Separate image-gen storybook/comic product (the friend's "prompt→image + storyteller" idea).

*(Source: brainstorm with collaborator + analysis, 2026-06-23.)*
