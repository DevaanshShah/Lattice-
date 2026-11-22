# editing/

Scene-level human control — **a list with a stitch button, not Premiere** (non-goal N1). Built in **M6** (Phase 4).

**Owns**
- `arrange` — reorder / add / delete scenes; inserted scenes inherit the video's style spec; re-stitch without re-rendering unchanged scenes (**FR-17**).
- `narration_edit` — edit a scene's narration → re-run TTS + sync for that scene only; captions update (**FR-18**).
- `tweak` — natural-language per-scene nudges ("move the cache box left", "slow this down") that re-generate just that scene and re-pass verification (**FR-19**).
- `persistence` — save/load a project = scene DAG + specs + style spec + cached renders, resumable across runs (**FR-20**). First phase where state survives between runs.
- `history` — per-scene version history + rollback to a previous good render (**FR-21**).

**Invariant this package enforces**
- Isolation is the whole game — every operation touches only the affected scene(s) and reuses everything else.

**Maps to:** Phase 4 / M6. **FRs:** FR-17, FR-18, FR-19, FR-20, FR-21.
