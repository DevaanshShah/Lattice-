---
title: Lattice
emoji: 🎬
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Lattice

Turns a prompt, a snippet of code, or a photo of a problem into a narrated explainer video.

This Space is a **demo**. Two things differ from a real deployment:

- **Storage is ephemeral.** The Space's disk is wiped on every rebuild and when it sleeps, so
  projects and threads do not persist. Finished videos survive only if `LATTICE_R2_*` secrets are
  set (Cloudflare R2).
- **There is no render sandbox.** A Space has no Docker daemon, so `LATTICE_EXEC_MODE=local`:
  model-written Python runs inside this container instead of a `--network=none` one.

Set `LATTICE_LLM_API_KEY` (and optionally the four `LATTICE_R2_*` values) as **Space secrets**,
never in the repo.
