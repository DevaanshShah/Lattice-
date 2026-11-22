# Lattice as a Hugging Face Space (Docker SDK, free CPU tier).
#
# This is the LOCAL-exec variant: a Space has no Docker daemon, so the app image must carry the
# render toolchain itself and Manim runs in-process. That means model-written Python executes
# inside this container, sharing its filesystem and network — fine for a public demo, not the
# shape you want for real users' work. The Oracle path keeps the sandbox; see docs/DEPLOY.md.
#
# It is a separate file from ../Dockerfile.app for one reason: a Space builds the file named
# `Dockerfile` at its repo root, and it needs HF-specific bits (uid 1000, /data writability,
# port 7860) that do not belong in the general image.
FROM manimcommunity/manim:v0.18.1

USER root
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Host-side Chrome: slides and browser scenes drive it through playwright (composition/slides.py).
# Google publishes the .deb for amd64 only; on arm64 set LATTICE_CHROME to a chromium you provide.
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
        && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
        && rm -rf /tmp/chrome.deb /var/lib/apt/lists/*; \
    fi

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The voice files travel with the Space repo via git-lfs (push-space.sh sets that up). Without
# them narration raises and every scene ships silent — there is no gtts fallback.
COPY backend/kokoro-v1.0.onnx backend/voices-v1.0.bin /app/

COPY backend/ /app/
COPY frontend/ /frontend/

# Spaces run the container as uid 1000 and only $HOME and /data are writable.
RUN mkdir -p /data && chown -R 1000:1000 /app /data
USER 1000

ENV HOME=/home/user \
    LATTICE_EXEC_MODE=local \
    LATTICE_OUT_DIR=/data \
    LATTICE_TTS_ENGINE=kokoro \
    LATTICE_KOKORO_MODEL=/app/kokoro-v1.0.onnx \
    LATTICE_KOKORO_VOICES=/app/voices-v1.0.bin \
    LATTICE_QUALITY_PREVIEW_FLAG=-ql \
    LATTICE_JOB_WORKERS=1 \
    LATTICE_SCENE_WORKERS=2 \
    LATTICE_RENDER_MEMORY=2g \
    LATTICE_JOB_DEADLINE_S=1800

# 7860 is the port a Space exposes.
EXPOSE 7860
CMD ["sh", "-c", "python -m scripts.preflight; exec python -m scripts.serve --host 0.0.0.0 --port 7860"]
