# Lattice render image (M0).
#   Q2 — Manim CE is PINNED here (v0.18.1) and nowhere else drifts.
#   Q5 — containerized render IS the sandbox.
# The base image bundles Manim CE + a LaTeX distribution (Tex/MathTex) + FFmpeg,
# and runs as the non-root user `manimuser`. render/sandbox.py invokes it with
# `--network=none`, so model-written code has no network and no root from day one.
FROM manimcommunity/manim:v0.18.1
WORKDIR /manim
# Nothing else needed for M0 — the base does items 1–4 of the Phase 0 spec.
