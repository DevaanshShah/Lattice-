# composition/

Assembles many verified scenes into one coherent film. Built in **M5** (Phase 3).

**Owns**
- `scene_dag` — a video = an ordered collection of scene specs + their renders + room for version history. Individual scenes are addressable (**FR-13**).
- `pool` — **bounded** parallel scene rendering through a worker pool with a concurrency cap; one scene failing (after its caps) doesn't abort the others (**FR-14**).
- `stitch` — FFmpeg concatenation of the per-scene MP4s (each already carrying synced narration) into one continuous video, no seam glitches (**FR-15**).
- `regen` — regenerate a single scene in isolation, reuse everything else from cache, re-stitch (**FR-16**). This is the seam Phase 4 editing builds on.

**Invariant this package enforces**
- Bound the fan-out — parallel, but through a capped pool, to avoid rate-limit and cost spikes.

**Maps to:** Phase 3 / M5. **FRs:** FR-13, FR-14, FR-15, FR-16.
