#!/usr/bin/env bash
# Update a running Lattice server to the latest code, and go back by itself if the new code is broken.
#
#   bash ~/lattice-new/deploy/oracle/update.sh            # latest main
#   BRANCH=my-branch bash ~/lattice-new/deploy/oracle/update.sh
#
# Steps, and why each one:
#   1. remember the commit that is running now, so there is somewhere to go back to
#   2. undo the server's own edits (the contact email filled into the legal pages), pull, refill them
#   3. install the pinned requirements of the new code
#   4. run preflight against the NEW code: a FAIL stops here, before anything is restarted
#   5. restart and wait for /health; if it never answers, return to the old commit and restart that
#
# The contact email comes from LATTICE_CONTACT_EMAIL in backend/.env (optional).
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"     # the repo root: backend/, frontend/, deploy/
BACKEND_DIR="$APP_DIR/backend"
BRANCH="${BRANCH:-main}"
LOCAL_EDITS=(frontend/static/privacy.html frontend/static/terms.html deploy/oracle/setup.sh)

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
undo_local_edits() { git -C "$APP_DIR" checkout -q -- "${LOCAL_EDITS[@]}" 2>/dev/null || true; }
fill_contact() {
  local contact
  contact="$(grep -E '^LATTICE_CONTACT_EMAIL=' "$BACKEND_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  [ -n "$contact" ] && sed -i "s|{{CONTACT}}|$contact|g" "$APP_DIR/frontend/static/privacy.html" "$APP_DIR/frontend/static/terms.html"
  return 0
}
install() { "$BACKEND_DIR/.venv/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"; }
healthy() {
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:8080/health > /dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}
go_back() {
  echo "Going back to $(git -C "$APP_DIR" log -1 --format='%h %s' "$PREV" | cut -c1-72)"
  undo_local_edits
  git -C "$APP_DIR" checkout -q "$PREV"
  fill_contact
  install
}

cd "$APP_DIR"
PREV="$(git rev-parse HEAD)"
say "1/5  running now: $(git log -1 --format='%h %s' | cut -c1-72)"

say "2/5  fetching $BRANCH"
undo_local_edits
git fetch -q origin "$BRANCH"
git checkout -q "$BRANCH"
git merge -q --ff-only "origin/$BRANCH"
fill_contact
if [ "$(git rev-parse HEAD)" = "$PREV" ]; then
  echo "Already up to date. Restarting anyway, so a changed .env takes effect."
else
  git log --format='   %h %s' "$PREV..HEAD" | cut -c1-90
fi

say "3/5  python packages"
install

say "4/5  preflight on the new code"
if ! (cd "$BACKEND_DIR" && ./.venv/bin/python -m scripts.preflight); then
  echo "Preflight failed. The running server was NOT restarted."
  go_back
  exit 1
fi

say "5/5  restart and health check"
sudo systemctl restart lattice
if healthy; then
  echo "Healthy on $(git log -1 --format='%h %s' | cut -c1-72)"
  exit 0
fi
echo "No answer from /health after 60 s."
go_back
sudo systemctl restart lattice
healthy && echo "Rolled back and healthy." || echo "Rolled back, but still not healthy: journalctl -u lattice -n 50"
exit 1
