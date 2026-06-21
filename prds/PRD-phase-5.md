# PRD — Phase 5: Web UI

**Goal:** Put the engine behind a browser so a non-coder can produce a narrated explainer end-to-end without ever seeing Python. This is the "website" from the original sketch. It also forces the first hard infrastructure requirement: the moment this is multi-user, you are executing model-written Python for strangers — **sandboxing stops being optional.**

> Context: see `PRD-00-overview.md`. Wraps the Phase 4 engine (scene-level primitives, persistence) in a UI and the production infrastructure it needs.

**Headline demo:** a non-coder makes a narrated, multi-scene explainer end-to-end in the browser.

---

## In scope (FRs)

### FR-28 — Web UI
Front-end with: a prompt box, a scene timeline, per-scene preview, regenerate buttons, and a narration editor — i.e. the Phase 4 primitives made visual.
- *Acceptance:* a user can, from the browser alone, enter a topic, see scenes appear on a timeline, preview each, regenerate or tweak a scene, edit its narration, reorder/add/delete, and download the final video — no CLI.

### FR-23 — Sandboxed render workers *(now mandatory)*
Run model-written Manim code in isolation: no network, resource caps, non-root, ephemeral filesystem.
- *Acceptance:* a render job cannot reach the network, exceeds neither CPU/memory nor wall-clock caps (killed if it does), runs as a non-privileged user, and leaves no persistent filesystem state between jobs. A deliberately hostile snippet (e.g. attempting network egress or a fork bomb) is contained.

### FR-24 — Job queue + async status
Renders are asynchronous jobs with trackable status.
- *Acceptance:* submitting a video/scene queues a job; the UI reflects queued → rendering → done/failed per scene; multiple users' jobs don't block each other.

### FR-25 — Render caching
Skip re-rendering scenes that haven't changed.
- *Acceptance:* editing one scene re-renders only that scene; unchanged scenes are served from cache. Cache keys off the scene spec + style spec so any meaningful change busts the cache and any no-op reuses it.

### FR-26 — Quality/resolution settings
Low-res fast preview vs high-res final render.
- *Acceptance:* the UI offers a fast preview render for iteration and a high-res final render for export; the preview is materially faster and clearly labeled as draft quality.

### FR-29 — Streaming progress
Stream render/generation progress to the UI.
- *Acceptance:* the user sees live progress (per-scene state, queue position, or render percentage) rather than a frozen spinner; long jobs feel responsive.

### FR-30 — Export/download
Export the finished video.
- *Acceptance:* the user can download the final MP4, with an option for burned-in subtitles vs a separate track.

---

## Out of scope

- Auth/billing/orgs beyond what's minimally needed to run multi-user safely — full account management isn't required to hit the demo. (Re-evaluate **N4** as real users arrive.)
- Domain templates, asset library, voice cloning, multi-language, RAG, sharing/gallery (Phase 6).
- Mobile-native apps; this is a web UI.

## Dependencies

- Phase 4 engine: scene-level operations (FR-16–FR-21) and persistence (FR-20) the UI drives.
- Decision: **Q5** — if you deferred containerization in Phase 0, FR-23 forces it now.

## Definition of Done

A first-time, non-coding user opens the web app, types a topic, watches scenes render asynchronously with live progress, previews them quickly in draft quality, edits/regenerates/reorders scenes through the UI, renders a high-res final, and downloads the MP4 — and throughout, every render runs in a sandbox that contains a hostile snippet. No part of this requires the CLI.

## Risks & notes

- **FR-23 is the one that bites you if you skip it.** Executing model-written Python unsandboxed in a multi-user product is the classic, severe mistake. It moved to this phase (not earlier) only because solo/local use doesn't need it — but the instant strangers can submit prompts, it is non-negotiable. Don't let it slip.
- The UI should stay a **thin layer** over the Phase 4 engine API. If you find yourself reimplementing scene logic in the front-end, the engine API needs fixing instead.
- Caching (FR-25) and preview quality (FR-26) are what make iteration in the browser tolerable — without them, every tweak costs a full high-res render and users bounce.
- Streaming (FR-29) is mostly a perceived-performance feature, but for multi-minute renders it's the difference between "working" and "broken" in users' eyes.
