# Lattice render image (M0).
#   Q2 — Manim CE is PINNED here (v0.18.1) and nowhere else drifts.
#   Q5 — containerized render IS the sandbox.
# The base image bundles Manim CE + a LaTeX distribution (Tex/MathTex) + FFmpeg,
# and runs as the non-root user `manimuser`. render/sandbox.py invokes it with
# `--network=none`, so model-written code has no network and no root from day one.
FROM manimcommunity/manim:v0.18.1
WORKDIR /manim
# Curated Lucide (ISC) line-icons for the self.icon("name") scaffold helper. Baked in so the no-network
# render loads them offline, independent of the work-dir mount. COPY lands them root:root 0644 =
# world-readable to the non-root manimuser. This is why the image tag is bumped 0.1 -> 0.2.
COPY assets/icons /opt/icons
