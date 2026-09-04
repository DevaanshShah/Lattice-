#!/usr/bin/env bash
# Publish this app to a Hugging Face Space.
#
#   bash deploy/huggingface/push-space.sh <hf-username>/<space-name>
#
# A Space is its own git repo whose ROOT Dockerfile is what gets built — and this repo's root
# Dockerfile is the render sandbox image, a different thing. So rather than renaming anything
# here, this assembles a clean copy: tracked files, the Space Dockerfile and README in place of
# the originals, and the two Kokoro voice files via git-lfs (338 MB, gitignored in this repo but
# fine on HF, which is built for exactly that).
#
# Secrets are NOT pushed. Set LATTICE_LLM_API_KEY and any LATTICE_R2_* in the Space's
# Settings -> Variables and secrets.
set -euo pipefail

SPACE="${1:-}"
[ -n "$SPACE" ] || { echo "usage: $0 <hf-username>/<space-name>"; exit 1; }
command -v git-lfs > /dev/null || { echo "git-lfs is required: https://git-lfs.com"; exit 1; }

ROOT="$(git rev-parse --show-toplevel)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "==> assembling from tracked files"
git -C "$ROOT" archive HEAD | tar -x -C "$STAGE"
cp "$ROOT/deploy/huggingface/Dockerfile" "$STAGE/Dockerfile"     # replaces the render Dockerfile
cp "$ROOT/deploy/huggingface/README.md" "$STAGE/README.md"        # HF reads its frontmatter

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f "$ROOT/$f" ] || { echo "missing $f — the Space would ship silent video"; exit 1; }
  cp "$ROOT/$f" "$STAGE/$f"
done

echo "==> git + lfs"
cd "$STAGE"
git init -q && git lfs install --local > /dev/null
git lfs track "kokoro-v1.0.onnx" "voices-v1.0.bin" > /dev/null
git add -A && git -c user.email=deploy@local -c user.name=deploy commit -qm "deploy $(date -u +%FT%TZ)"
git remote add space "https://huggingface.co/spaces/$SPACE"

echo "==> pushing to $SPACE (use an HF access token with write scope as the password)"
git push --force space HEAD:main

cat <<MSG

Pushed. Now, in the Space's Settings -> Variables and secrets:
    LATTICE_LLM_API_KEY = ...            (required)
    LATTICE_R2_ACCOUNT_ID / _BUCKET / _ACCESS_KEY_ID / _SECRET_ACCESS_KEY   (optional but
        recommended — without them finished videos die with the container)
    LATTICE_ADMIN_TOKEN = ...            (only if you want /admin reachable)

The build takes a while: the Manim base plus onnxruntime is a few GB. Watch the Space's build log,
then its container log — the first lines are the preflight report.
MSG
