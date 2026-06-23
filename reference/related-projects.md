# Related projects — prior art & references

External projects in **Lattice's exact space** (natural-language → Manim animation). Reference /
inspiration only — **not part of the build path**. Worth studying their codegen prompting, how (or
whether) they handle broken/ugly output, and their UX. Lattice's bet is the reliability layer most
of these skip (compile-repair + vision/geometry checks + shared style spec).

## Repos

- **HyperCluster-Tech/manimator** — https://github.com/HyperCluster-Tech/manimator
  Prompt / research-paper → Manim animation. A full clone lives locally at `../manimator/`
  (gitignored — reference only, not committed).
  Look at: prompt→code structure, paper ingestion, any sandboxing, how it recovers from bad renders.

- **marcelo-earth/generative-manim** — https://github.com/marcelo-earth/generative-manim
  GPT-powered Manim code generation (open source; web app + API).
  Look at: its codegen prompting, render pipeline, and what it does when the generated code is wrong.

## Products / sites

- **animg.app** — https://animg.app/en
  AI animation-generator web product.
  Look at: the UX flow (prompt → preview → edit), output quality on math/ML topics, positioning/pricing.

## How these inform Lattice

- Compare their **failure modes** to Lattice's moat: most prompt→Manim tools generate-and-hope, so they
  ship scenes that compile but look broken (overlap, off-frame) — exactly what our verification layer
  (compile-repair → off-frame lint → optional vision critic) and the shared style spec target.
- Mine them for: codegen prompt ideas, reusable scene patterns, narration/UX choices, and product framing.
- Open question they all face (and we do too): you can't fully eliminate layout errors with prompting
  alone — see whether any of them constrain layout with templates/components vs free-hand LLM positioning.
