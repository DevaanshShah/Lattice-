# The Lattice APP image (the web server + engine). The RENDER image is the other Dockerfile —
# they are deliberately separate, and which one does the rendering depends on LATTICE_EXEC_MODE.
#
#   docker mode (default, RECOMMENDED — keeps the sandbox):
#       docker build -f deploy/Dockerfile.app -t lattice-app .   (from the repo root)
#     This image stays small: it never runs Manim itself, it calls `docker run lattice-render:0.2`
#     with --network=none and memory/cpu caps. It therefore needs the docker CLI and a mounted
#     docker socket, which is why it suits a VPS rather than a PaaS.
#
#   local mode (PaaS with no docker daemon — Fly / Render / Railway):
#       docker build -f deploy/Dockerfile.app --build-arg BASE=manimcommunity/manim:v0.18.1 \
#                    -t lattice-app-local .
#     The Manim base already carries Manim + LaTeX + FFmpeg, so the app image IS the render image
#     and tools run in-process. Set LATTICE_EXEC_MODE=local. Understand the trade: model-written
#     Python then runs inside this container, sharing its filesystem and network. Not a sandbox.
ARG BASE=python:3.11-slim
FROM ${BASE}

# The Manim base runs as a non-root user and needs root to install; harmless on python:slim.
USER root
WORKDIR /app

# docker CLI only (not the daemon): docker-mode renders shell out to `docker run` against the
# socket mounted at runtime. ffmpeg/ffprobe for the host-side duration probes.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so a code change doesn't re-install them.
# Host-side Chrome: slides and browser scenes drive it through playwright (composition/slides.py).
# Google publishes the .deb for amd64 only; on arm64 set LATTICE_CHROME to a chromium you provide.
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
        && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
        && rm -rf /tmp/chrome.deb /var/lib/apt/lists/*; \
    fi

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The voice. ~338 MB, gitignored, and NOT optional: without these files narration raises and every
# scene ships silent (see narration/tts.py). Baked in so the container starts with a voice rather
# than discovering it hasn't got one on the first build.
COPY backend/kokoro-v1.0.onnx backend/voices-v1.0.bin /app/

# The API at /app, the UI at /frontend (web/app.py looks for it next to the backend).
COPY backend/ /app/
COPY frontend/ /frontend/

# Projects, Learn threads, deck records and the usage ledger are FILES under here. Object storage
# (R2) covers the finished videos only, so this path wants a real volume in production or a
# redeploy takes the rest with it.
ENV LATTICE_OUT_DIR=/data
VOLUME ["/data"]
EXPOSE 8080

# Fail loudly at boot on a misconfiguration instead of at the first user's first build. It exits
# non-zero on a FAIL, so this line is also the thing to check in the deploy logs.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s \
    CMD curl -fsS http://127.0.0.1:8080/ > /dev/null || exit 1

CMD ["sh", "-c", "python -m scripts.preflight; exec python -m scripts.serve --host 0.0.0.0 --port 8080"]
