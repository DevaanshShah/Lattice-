# core/

Foundation primitives every other package imports. Built in **M0–M1**, used everywhere after.

**Owns**
- `llm` — OpenAI-compatible client, model swappable via `base_url` / `api_key` / `model`. Generator and critic are **different, swappable models** (strong coder writes; cheap vision model checks).
- `config` — pinned Manim CE version (**Q2**), render quality presets, retry/iteration caps, concurrency cap, TTS engine selection (**Q3**), budget ceiling (**Q1**).
- `schemas` — the locked Pydantic/JSON models: **scene spec**, **style spec**, **outline**, vision-critic issue, scene-DAG. Invalid model output is rejected and regenerated, never passed downstream.
- `cache` — content-hash cache helper. Key = hash(scene spec + style spec + model). Same inputs ⇒ reuse the existing render. TTS audio cached separately.

**Invariants this package enforces**
- Cheapest checks first — config exposes the caps that keep every loop from hanging.
- Cache everything by content hash — idempotent reuse is a `core` utility, not re-implemented per package.

**Maps to:** all phases (foundation). **FRs:** substrate for FR-1, FR-2, FR-25.
