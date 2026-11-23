# Deploying Lattice

Everything needed to run it on a server. Start with [DEPLOY.md](DEPLOY.md), which covers what the app
needs, sizing, cost and the two step-by-step paths (a VM, or a Hugging Face Space).

| Path | What it is |
|---|---|
| `DEPLOY.md` | The runbook: requirements, configuration, sizing, hosting options, known limits |
| `Dockerfile.render` | The Manim sandbox image. Build with `docker build -f deploy/Dockerfile.render -t lattice-render:0.2 backend` |
| `Dockerfile.app` | The app image (backend + frontend). Build from the repo root: `docker build -f deploy/Dockerfile.app -t lattice-app .` |
| `oracle/` | A VM with a Docker daemon (Oracle, GCP, Hetzner): `setup.sh`, the systemd units, the Caddy config for automatic HTTPS |
| `oracle/update.sh` | Update a running server in one command: pull, install, preflight, restart, and roll back by itself if the new code does not come up |
| `oracle/backup-to-pc.ps1` | Run on your own PC: copies the server's data (accounts, ledger, projects, videos) into a dated folder, keeps the last 8 |
| `huggingface/` | A free public demo as a Hugging Face Space (no sandbox; see DEPLOY.md) |
| `vercel-site/` | A one-page homepage with the privacy policy and terms, for a static host such as Vercel |
| `r2-setup.md` | Object storage for finished videos (Cloudflare R2) |
| `google-sign-in.md` | Setting up Google sign-in through Supabase |

On a VM the layout is the repo itself: `backend/` runs under systemd, `frontend/` is served by the
backend, and Caddy sits in front. The UI can instead be hosted separately: see "Split deploy" in
DEPLOY.md, which needs a domain you own.
