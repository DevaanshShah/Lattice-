#!/usr/bin/env bash
# Bootstrap Lattice on a fresh Oracle Cloud Always Free ARM box (Ubuntu 22.04/24.04).
#
#   curl -fsSL <raw-url>/deploy/oracle/setup.sh | bash -s -- lattice.example.com
#   ...or: git clone <repo> ~/lattice && bash ~/lattice/deploy/oracle/setup.sh lattice.example.com
#
# What it does NOT do, on purpose: write your .env, or copy the Kokoro voice files. Both carry
# things that should not travel through a script in a public repo — see the printed next steps.
#
# The app runs ON THE HOST under systemd, not in a container: in docker mode it drives the daemon
# to run renders, and containerising it would mean mounting /var/run/docker.sock, which is
# root-equivalent on the host. The render sandbox is unaffected either way.
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="${APP_DIR:-$HOME/lattice}"
REPO="${REPO:-}"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

say "1/7  system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io python3-venv python3-pip git curl ca-certificates
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"          # takes effect on next login; sudo is used below meanwhile

say "2/7  source"
if [ ! -d "$APP_DIR" ]; then
  [ -n "$REPO" ] || { echo "set REPO=<git url> or clone to $APP_DIR first"; exit 1; }
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

say "3/7  render sandbox image (arm64 — the pinned base publishes one)"
sudo docker build -t lattice-render:0.2 .

say "4/7  python environment"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

say "5/7  open the firewall"
# Oracle's Ubuntu images ship iptables rules that drop everything except SSH. This is the step
# people miss: the VCN security list alone is not enough, the instance blocks it too.
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 7 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || sudo apt-get install -y -qq iptables-persistent

say "6/7  systemd service"
sudo cp deploy/oracle/lattice.service /etc/systemd/system/lattice.service
sudo sed -i "s|__APP_DIR__|$APP_DIR|g; s|__USER__|$USER|g" /etc/systemd/system/lattice.service
# ...and a daily snapshot of the admin ledger + user registry into R2. The videos upload
# themselves after every build; this data does not, and it is on the same mortal disk.
sudo cp deploy/oracle/lattice-backup.service deploy/oracle/lattice-backup.timer /etc/systemd/system/
sudo sed -i "s|__APP_DIR__|$APP_DIR|g; s|__USER__|$USER|g" /etc/systemd/system/lattice-backup.service
sudo systemctl daemon-reload
sudo systemctl enable lattice
sudo systemctl enable --now lattice-backup.timer

say "7/7  caddy (automatic TLS)"
if [ -n "$DOMAIN" ]; then
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] \
https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
  sudo sed "s|__DOMAIN__|$DOMAIN|" deploy/oracle/Caddyfile | sudo tee /etc/caddy/Caddyfile > /dev/null
  sudo systemctl restart caddy
else
  echo "no domain given — skipping Caddy. Re-run with the domain once DNS points here."
fi

cat <<EOF

Done. Three things left, and they are the two this script deliberately did not do:

  1. cp .env.example .env && nano .env
       LATTICE_LLM_API_KEY, LATTICE_ADMIN_TOKEN (32+ random chars), the four LATTICE_R2_* vars,
       LATTICE_OUT_DIR=$APP_DIR/out
       Sizing for 4 OCPU / 24 GB:
       LATTICE_JOB_WORKERS=1  LATTICE_SCENE_WORKERS=3  LATTICE_RENDER_MEMORY=3g  LATTICE_RENDER_CPUS=1.0

  2. From your own machine (the voice files are gitignored, ~338 MB):
       scp kokoro-v1.0.onnx voices-v1.0.bin $USER@<this-ip>:$APP_DIR/

  3. ./.venv/bin/python -m scripts.preflight     # must print 0 failing
     sudo systemctl start lattice
     journalctl -u lattice -f

EOF
