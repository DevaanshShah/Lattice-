# Lattice — Plan & Strategy

> Synthesized from the competitor teardowns (manimator, generative-manim, animg.app, Code2Video,
> TheoremExplainAgent, the LLM2Manim paper) and our own build. This is the durable plan; act from it.

---

## 0. TL;DR — the honest situation

Lattice is technically solid and **ahead of the weak tools** (manimator / generative-manim) and **behind
Code2Video on exactly one axis: structural layout.** Like *everyone* in this space, **we have published no
accuracy number.** So the two real gaps are:

1. **Measurement** — we can't prove any of our reliability machinery works, or whether a change helped.
2. **Layout is done by prose + a partial check, not by structure** — the root of the overlap you keep hitting.

Everything else (reliability layer, sandbox, narration-first, multi-scene, editing, web UI) is genuinely good.
**The headline opportunity:** publish the first credible compile-rate number in this space (nobody has), and
fix layout *structurally* (components + a placement scaffold) so it stops breaking. Both are achievable.

---

## 1. Where we stand vs the field (evidence-based)

The whole field forms one ladder on the axis that matters — **layout/overlap defense**:

| System | Layout defense | Repair | Eval | Verdict |
|---|---|---|---|---|
| **manimator** | prose nagging ("don't overlap" ×4) | **none** (crash → 500) | none | floor — prompt-and-pray |
| **generative-manim** | prose + vision self-check; compile-repair **disabled** in prod | vision-only | harness exists, **never run**; fine-tune pipeline **unrun** (no weights, 409 rows) | aspirational |
| **animg.app** | closed, silent product | unknown | unknown | black box |
| **LLM2Manim (paper)** | prose + symbol ledger + **mandatory human hand-fixes overlap** | regen broken part | N=100 *learning* study, **no generation-accuracy metric** | human-gated |
| **Lattice (us)** | prose rules + **off-frame geometry lint** (off-frame only, not overlap) + optional vision critic | **whole-file** repair, ≤4× | **none yet** | middle |
| **Code2Video** | **structural named grid; `.move_to()` banned** + Gemini grid-critic with surgical fixes + real icon assets | **error-class-aware, region-scoped** patch | **MMMC benchmark, reports numbers** (+40% TeachQuiz / +50% aesthetics vs *naive* baselines) | top (on layout) |

**Two honest caveats so we don't fool ourselves:**
- Code2Video's "+50%" is vs *naive single-prompt* baselines and pixel-T2V — **not vs Lattice.** We already
  capture the *reliability* part of that gain (we repair + lint). The **layout part transfers** (we have no grid).
- Even Code2Video / TheoremExplainBench (93.8% "success") **admit residual layout issues.** Nobody has *solved*
  this. We are not behind a solved bar — but on layout specifically, structure beats our prose, and that's real.

---

## 2. The plan (sequenced — each step makes the next provable)

### ① Eval harness — **do this first** (~a weekend)
Freeze ~15–20 prompts (math/ML/CS; optionally mirror MMMC / TheoremExplainBench topics so we can claim
comparability). Score per pipeline layer:
- **first-try compile rate**, **post-repair compile rate**
- **off-frame incidence** (our lint computes this **for free**)
- **overlap incidence** (needs the overlap lint from §3 / step ②)
- **tokens + $ per video**, **wall-clock**

*Why first:* you cannot tell if the grid (or any fix) helps without it; it's the résumé headline
("scored X, comparable to Code2Video"); it's the prerequisite for everything incl. ever fine-tuning.
**Nobody publishes this number — it's unclaimed.**

### ② Components & layout architecture — **the real accuracy lever** (see §3 for the full design)
Stop letting the model free-hand coordinates. Give it (a) a **placement scaffold** (named full-frame grid/zones
+ helpers, discourage raw `.move_to()`), and (b) a small **component library** (parametric, self-laying-out
builders) — plus **ManimML** for neural-net scenes. Then re-run ① and watch overlap/off-frame drop. *That
before/after delta is the portfolio story and the r/manim post.*

### ③ Cheaper / better repair (cost)
- **Error-memory** (Mem0) — store every (error → working fix); retrieve similar past fixes on a new error. *(chosen)*
- **Scope-guided auto-fix** — classify the error, patch only the broken line/block, don't resend the whole file.
- **Make the off-frame lint overlap-aware** (VGroup/glyph-aware predicate) so it catches overlap, not just off-frame.

### ④ Cheap differentiator: symbol ledger
A maintained notation/units/assumptions table injected into every scene (extends the style spec). High value for
math/physics; ~a day. (From LLM2Manim.)

### ⑤ Ship it (portfolio)
Surface the **M6 scene editing** behind the M7 UI; seed a **gallery** with good examples (cold-start + social
proof); post to **r/manim**. (BYOK is dead — students won't bring keys.)

### Deliberately NOT now
Fine-tuning (no data/eval yet — gen-manim proved this fails without data); the human A/B study (only if a
professor opens a class); long-form (>8-scene) planner; GitHub-Actions rendering (conflicts with the sandbox);
PDF/arXiv ingestion (manimator's one trick — a nice-to-have use-case unlock, not accuracy).

---

## 3. Components architecture (the deep dive)

**Goal:** make overlap/off-frame *structurally hard*, the way Code2Video's grid does — but adapted to Lattice.
This is the existing **M8 / FR-32 (component library)** promoted to the front, plus a placement scaffold.

**Key Lattice advantage to exploit:** Code2Video burns the left third of the frame on on-screen lecture bullets.
**We narrate via audio** (narration-first + captions) — so we have the **full frame** for visuals. Our scaffold
can use the entire canvas, not a cramped right-side grid.

Three layers:

### A. Placement scaffold — a `LatticeScene` base class
A base `Scene` (mirrors Code2Video's `TeachingScene`) that exposes **named placement** instead of raw coordinates:
- **Semantic zones:** `TITLE` (top), `MAIN` (center, full-frame), `CAPTION` (bottom), optional `LEFT`/`RIGHT`.
- **A full-frame named grid** for precise placement (e.g. cols `1–8` × rows `A–E`), with helpers:
  - `self.place(obj, "C4", scale=0.8)` — drop a mobject in a named cell
  - `self.place_in_area(obj, "B2", "D6")` — fit into a rectangular region (auto-scales to fit)
  - `self.row([a, b, c], at="C")` / `self.stack([...], in_="MAIN")` — even-spaced arrangement in a zone
- **Codegen rule:** prefer these; **avoid raw `.move_to(LEFT*n)`** (mirror Code2Video's "NEVER use .move_to()").
- The grid cells have fixed, non-overlapping coordinates → **overlap/off-frame prevented by construction** for
  anything placed via the scaffold.

### B. Component library — parametric, self-laying-out builders
Each is a function/class returning a `VGroup` that computes its **own internal layout** (no internal overlap) and
exposes a bounding box so the scaffold can place it. The LLM **selects + parameterizes** a component instead of
hand-drawing primitives — which is exactly where the w₂/w₃-merge and single-arrow-network bugs came from.

Starter set (cover the 80%; build ~3 first, expand by what the eval shows breaks most):
- `neural_network(layers=[3,4,2])` → **use ManimML** (`NeuralNetwork`, MIT-licensed; handles feedforward + CNN,
  edges node-to-node *by construction*). Pin/verify against our Manim CE version, or vendor the needed parts.
- `labeled_box(text)`, `node(label)`, `arrow_between(a, b)` (buffed, never zero-length)
- `flow([s1, s2, s3])` — pipeline/flowchart of boxes + arrows, auto-spaced
- `array(values)` / `stack(values)` / `tree(...)` — data structures (consider `manim-dsa` plugin)
- `axes_plot(fn, x_range)` — a safe finite plot
- `matrix(data)` — already a native mobject; just wrap with safe defaults
Each component owns its labels (placed within the component, never colliding), so labels can't merge across siblings.

### C. Composition contract — how it wires into the existing pipeline
We already have a **scene-spec IR** that lists `objects` with `kind`s. The change is in **codegen**, not a rewrite:
1. scene-spec `objects[].kind` → **map to a library component** when one exists.
2. codegen emits **component calls + scaffold placement** (`self.place(neural_network([3,4,2]), "MAIN")`),
   falling back to **free-hand Manim + prose rules** only for kinds with no component (hybrid — graceful).
3. render → **off-frame + overlap lint** (now mostly passes) → vision critic rarely needed.

### Honest tradeoffs
- **More templated output** (like Code2Video). Less arbitrary flexibility — accept it; you've fought overlap enough
  that a cleaner, more constrained look is a win.
- **Build cost is real** — that's why it's phased: scaffold + 3 components first, measured against ①, then expand.
- **Coverage** — the hybrid fallback means novel scenes still work (free-hand), just without the structural guarantee.

### Phasing for §2-②
1. `LatticeScene` scaffold + `place`/`place_in_area` + codegen prompt update (no new components yet) — measure.
2. Add ManimML for NN scenes + `labeled_box`/`flow` — measure the overlap drop on ML/CS prompts.
3. Expand components by whatever the eval flags as the top remaining overlap source.

---

## 4. Harvest table — what to take, from whom (finalized)

| From | Take | Priority |
|---|---|---|
| **Code2Video** | named-grid **placement scaffold** + **scope-guided region-scoped repair** + grid-aware critic fixes | ★★★ |
| **ManimML** | drop-in **neural-network components** (deterministic layout) | ★★★ |
| **ManimGen** | **error-memory (Mem0)**: store error→fix, retrieve similar | ★★★ (chosen) |
| **LLM2Manim** | **symbol ledger** + cheap pre-render semantic checks (goal-coverage) | ★★ |
| **Code2Video / TEA** | their **benchmarks (MMMC / TheoremExplainBench)** as our eval harness | ★★★ |
| **manimator** | PDF/arXiv ingestion (use-case unlock, not accuracy) | ★ (later) |

---

## 5. Suggested execution order (next ~3–4 weeks)

1. **Week 1:** eval harness (①) — prompt set + scorer (compile-rate, off-frame-rate, cost). Record the *baseline number*.
2. **Week 2:** `LatticeScene` scaffold + ManimML for NN scenes (②, phase 1–2). Re-run eval → before/after delta.
3. **Week 3:** error-memory + scope-guided repair (③); make the lint overlap-aware. Re-run eval.
4. **Week 4:** symbol ledger (④) + seed the gallery and ship the editing UI (⑤). Write up the numbers.

**North star:** by week 4 you have a *measured* "first-try compile X% → Y%, overlap Z% → W%, $N/video" story —
the one thing no competitor has — backed by a working, narrated, editable demo. That's the portfolio.
