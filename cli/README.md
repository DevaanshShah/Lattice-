# cli/

The engine, driven from the command line. **The CLI is the engine; the web UI is a skin on top.** Built in **M3**, the user-facing entrypoint for everything before Phase 5.

**Owns**
- `generate-scene "<prompt>"` → one verified, narrated MP4 (full pipeline: spec → code → render → repair → critic → final).
- `generate-video "<topic>"` → outline → approval gate → multi-scene narrated explainer.
- Scene-level editing commands (Phase 4) exposed here before the web UI wraps them.

**Maps to:** Phase 1 / M3 (`generate-scene`), Phase 3 / M5 (`generate-video`). **FRs:** FR-27.
