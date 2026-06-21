# web/

The browser skin over the engine, so a non-coder never sees Python. Built in **M7** (Phase 5). **Stays a thin layer** over the Phase 4 engine API — no scene logic re-implemented in the frontend.

**Owns**
- `ui` — prompt box → editable outline → linear scene list → per-scene preview + regenerate + narration editor (**FR-28**). Thin v1 first; the real timeline editor is deferred.
- `queue` — render jobs are async with trackable status: queued → rendering → done/failed per scene; users don't block each other (**FR-24**).
- `streaming` — live per-scene progress so the user reviews scene 1 while scene 8 renders (**FR-29**).
- `export` — download the final MP4, optional burned-in subtitles (**FR-30**).

Pairs with `render/sandbox` hardening (**FR-23**) — the moment strangers submit prompts, the hardened sandbox is non-negotiable.

**Maps to:** Phase 5 / M7. **FRs:** FR-28, FR-24, FR-29, FR-30 (+ FR-23 hardening).
