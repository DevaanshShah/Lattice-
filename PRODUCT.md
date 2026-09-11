# Lattice — product map

**Two engines, five front doors.**

Lattice turns an idea — typed, pasted as code, or photographed — into a narrated explainer video.
Every surface in the product is one of two rendering engines wearing a different door.

This document is what exists **today**: what each page does, what it costs, and what is still
missing. Companion docs: `README.md` (setup), `MILESTONES.md` (roadmap), `MEMORY.md` (phase log),
`docs/r2-setup.md` (storage).

| | |
|---|---|
| Product surfaces | 5 (+ an admin console) |
| Render engines | 2 |
| Tests passing | 404 |
| Measured cost per deck | $0.0013 |
| Measured time per deck | 76s |

---

## 1. The mental model: everything is one of two engines

The tabs blur this, and it is the single most useful distinction in the product. One engine lets the
model write the picture. The other never does — which is precisely why it cannot produce a broken
frame.

### Deck engine — fixed layout, written script

`planner.slide_plan` → `composition.slides`

```
one LLM call → HTML slides → headless Chrome → ffmpeg → mp4
```

- The model writes **the script and the structure only**. Layout is CSS the model never touches.
- Five slide kinds: **title, cards, chips, bullets, math**. Only `math` routes out to Manim, where a
  real function gets plotted.
- Beat-synced highlighting: the active card or bullet lights while the rest dim.
- Narration via gTTS or local Kokoro; optional crossfades and background music.

**Cannot fail layout.** Flexbox cannot push a card off-frame or overlap two labels, so there is
nothing to lint, critique or repair. A slide rasterises in ~0.2s for $0.

### Manim engine — model-authored animation

`composition.decoupled` · LatticeScene grid scaffold

```
outline → theme → codegen → sandbox render → layout lint → vision critic → stitch
```

- The model writes **real Manim code per scene**, on a grid scaffold that fixes the composition it
  is allowed to build inside.
- Guards, in cost order: compile-repair (4 tries) → **free geometric layout lint** → paid vision
  critic (3 iterations) → best-of-2 → whole-scene rebuild (3 attempts).
- Hard stops so nothing runs forever: 900s per scene, 3600s per job, 8 scenes maximum.
- Every render executes inside a locked-down container, never on the host.

**Real animation, real risk.** Minutes and many model calls per scene — this is where the quality
ceiling and the cost both live.

---

## 2. The pages

Two of these doors open onto the same engine. That is noted where true, because it is a product
decision waiting to be made rather than an accident.

### Home — no engine

`GET /`

The landing. Three cards route to Learn, Teach and Slides, over a 3D laptop intro that plays once
and self-destructs after 16s if it ever hangs.

- **Choose a door** — the only job this page has
- **Theme toggle** — dark and light, shared across every surface

### Learn — deck engine

`POST /api/learn/threads` · measured **$0.00013 / 4.1s per turn**

A chat tutor, not a video tool. Every turn is a fast text answer, because a conversation cannot wait
minutes for a render. One model call both answers the question *and* decides whether the idea is
worth animating — the offer is the model's call, not a keyword match in the frontend.

- **Ask anything** — threaded, searchable, persisted per browser
- **Accept the offer**, or type your own video prompt
- **Watch inline** — the deck builds in the background
- **Refine** — a full re-plan, versioned; *not* a per-slide edit

```
POST /api/learn/threads
POST /api/learn/threads/{tid}/messages
POST /api/learn/threads/{tid}/video
POST /api/learn/threads/{tid}/messages/{mid}/refine
GET  /api/learn/threads/{tid}/video/{mid}
```

### Teach — Manim engine

`POST /api/projects` · minutes per build, many calls per scene

The deep surface — the only one with real editing, and the only one that pays for animation. Nothing
renders until you have approved both the outline and the visual theme, so you never pay for scenes
you would have cut.

- **Three inputs** — a topic, an image (vision derives the topic), or a code snippet
  (segment-by-segment walkthrough)
- **Duration budget** — 30s → 2 scenes, 60s → 4, 2.5min → 8, at ~15s each
- **Approval gate** — reorder, cut and keep outline items before spend
- **Quality toggle** — preview 480p15, final 1080p60
- **Live progress** — SSE stream, per-scene state, replayable from a cursor
- **Regenerate** a single scene without touching the rest
- **Tweak in words** — "make the arrow red", applied to one scene
- **Edit narration** line by line, re-synced and re-muxed
- **Insert, reorder, delete** scenes — structural edits need no render
- **Version history** per scene, with rollback to any prior take
- **Inspect the source** — generated code, exact prompt, spec, narration
- **Export** — YouTube 16:9 or Reel 9:16 from one build, no re-render
- **Captions** — burned in, or a sidecar `.srt`; plus the plain transcript

```
POST   /api/projects              POST /api/projects/from-code    POST /api/projects/from-image
POST   /api/projects/{pid}/build
POST   /api/projects/{pid}/scenes/{i}/regenerate|tweak|narration|rollback
POST   /api/projects/{pid}/scenes/insert|reorder      DELETE /api/projects/{pid}/scenes/{i}
GET    /api/projects/{pid}/download?format=youtube|reel&subtitles=none|burn
GET    /api/projects/{pid}/captions | /script | /final | /scenes/{i}/preview | /scenes/{i}/source
GET    /api/jobs/{id} | /api/jobs/{id}/events | /api/jobs/{id}/stream
```

### Slides — deck engine

`POST /api/decks` · measured **$0.0013 / 76s / 4 slides**

The deck engine with a form in front of it. One model call, no re-rolls. The gate here is the script
itself — you read every word the video will say before a single frame is rendered.

- **Plan from a topic** — returns the full slide script to review
- **Keep or cut** any slide before building
- **Narration toggle** — silent deck or voiced
- **Crossfades** — 0.45s, or off
- **Math quality** — draft through final for the Manim slides
- **Background music** — by name, resolved from `assets/music`

```
POST /api/decks
POST /api/decks/{did}/build
GET  /api/decks/{did}/video
```

### Gallery — read only

`GET /api/projects`

Everything made, newest first, with a search box.

- **Search** across every project topic
- **See state at a glance** — scene count, and whether it is ready
- **Reopen** straight into the studio

### Admin — back office

`GET /admin` · token- or loopback-gated

The owner's console. Every model call, created project and finished job is written to an attributed
ledger on disk, so these numbers survive a restart. Gated by `LATTICE_ADMIN_TOKEN`; with none set it
answers only to localhost, so a public deploy fails closed.

- **Users** — total, active today, new, and who is online now
- **Spend** — all time, today, 7 and 30 days, per video, per user
- **Live jobs** — progress bars, whose build it is, how long it has run
- **Per-user drawer** — their projects, models, events, editable label
- **Cost by model and by surface** — where the money actually goes
- **Provider balance** — the real account number beside our own estimate
- **Honesty counter** — flags calls on unpriced models, so the total reads as a floor, not a fact

```
GET  /api/admin/summary | /users | /users/{uid} | /jobs | /costs | /projects | /events
POST /api/admin/users/{uid}/label
```

---

## 3. The systems every surface rides on

None of these are features a user would name, and all of them are the reason the product works twice
in a row.

| System | What it does | Spec |
|---|---|---|
| **Sandboxed rendering** | Model-written code never executes on the host | `--network=none` · 2g RAM · 2.0 CPU · 512 pids · non-root · `--rm` |
| **Layout lint before spend** | Geometry catches off-frame and overlap exactly, for free, before any paid vision call | `verification.layout_lint`, deterministic |
| **Vision critic** | The only layer that actually sees the render — merged glyphs, crowding, text on a shape | 2 keyframes · `detail=low` · max 3 iterations |
| **Crash recovery** | A killed build leaves good clips but an unsaved project; on boot the server reconciles disk and stitches what survived | runs at startup, never blocks boot |
| **Warm-cache routing** | Pinning one provider keeps its prefix cache warm, so the large static system prompt bills at the cached rate | ~90% off repeated input, fallbacks stay on |
| **Narration** | Voice synthesis runs on the host so the render stays offline | gTTS (online) · Kokoro ONNX (local, free) |
| **Two aspect ratios, one build** | Reel is a reframe, not a re-render — one ffmpeg pass, zero extra tokens | 1920×1080 → 1080×1920, background sampled from the frame |
| **Durable storage** | A PaaS disk is wiped on redeploy; finished videos upload to R2 and serving falls back to the object | keys derived from ids · best-effort · $0 egress |
| **Brand on every frame** | The Lattice watermark is composited into both engines' output | both paths, no render cost |

---

## 4. What it actually costs

Measured on a real run through the running server, not estimated. The Manim path is deliberately
left blank rather than guessed at.

| Path | Engine | Model calls | Cost | Wall clock | Output |
|---|---|---:|---:|---:|---|
| Learn — one chat turn | text only | 1 | $0.000133 | 4.1s | answer + offer |
| Slides — plan a deck | Deck | 1 | $0.001287 | 20.5s | 4 slides |
| Slides — render it | Deck | 0 | $0 | 76s | 48.8s · 720p · 1.25 MB |
| Teach — full video | Manim | many / scene | *not measured* | minutes | up to 8 scenes |

---

## 5. What is missing or unfinished

Everything above is built and running. This is the part that is not.

- **No accounts.** Users are anonymous cookie ids, not logins. Enough to attribute usage and count
  people; not enough to let anyone sign in, recover work on a new device, or be billed.
- **Duplication.** Slides and Learn produce the same artifact through the same engine — the only
  difference is a form versus a conversation. One should probably absorb the other.
- **No slide editing.** The deck path has no per-slide edit. Learn's "refine" re-plans the entire
  deck with the instruction folded in; the API says so plainly rather than implying a patch.
- **Composition.** The Manim math slide sits left of centre, leaving the right third of the frame
  empty. Visible in a real render; the CSS slides are correctly centred.
- **History starts late.** The admin ledger begins the day it was created — projects made before it
  show up in the counts with no owner and no cost — and it lives on the same ephemeral disk until it
  is backed up (`python -m scripts.r2 backup`).
- **Dead code.** An earlier Learn screen (ask → auto-build a Manim video → watch) still sits in
  `web/static/app.js` and is unreachable, since the route always delegates to the chat.
- **Standing risk: provider reliability.** Gateway 500-streaks and blank completions are the
  recurring failure mode. It is why retries, backoff and deadlines exist, and why the Manim path is
  the expensive one to trust.
