# planner/

Turns a topic into an ordered, human-approved set of scene specs. Built in **M5** (Phase 3).

**Owns**
- `outline` — topic → ordered scene titles/intents (**FR-3**), bounded by the scene cap (**Q4**). Inspectable as an intermediate artifact.
- `approval` — the **outline-approval gate**: show the scene list, let the user edit / reorder / cut **before** anything renders. This is the guard against paying to render 20 wrong scenes.
- `expand` — each approved outline item → a full scene spec the generation pipeline can build.

**Invariant this package enforces**
- Approve structure before spending — generation never starts until the outline is approved.

**Maps to:** Phase 3 / M5. **FRs:** FR-3.
