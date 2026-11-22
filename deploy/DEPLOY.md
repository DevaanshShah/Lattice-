# Deploying Lattice

Platform-agnostic. Read §1 and §2 whatever you deploy on; §4 covers cost and the free options; §5 and §6 are the two step-by-step deploys.

Run `python -m scripts.preflight` first, and again on the server. It exits non-zero on a FAIL and
names the env var to change for every finding.

---

## 1. What this app needs, and why

| Need | Why it is not negotiable |
|---|---|
| **A long-lived container** | Builds take minutes, the job queue is in-memory, progress streams over SSE. Anything that scales to zero or caps request duration kills in-flight builds. Rules out Vercel/Netlify/Lambda, and Cloud Run as currently written. |
| **2+ vCPU, and RAM sized to the knobs** | Manim + FFmpeg are CPU-bound. See §3 — the default knobs permit **6 concurrent renders**. |
| **A Docker daemon, or you lose the sandbox** | `exec_mode=docker` runs model-written Python with `--network=none` and memory/cpu/pids caps. `exec_mode=local` runs it *in the app container*. Both are supported; only one is a sandbox. |
| **A writable volume** | Projects, Learn threads, deck records and the usage ledger are **files** under `LATTICE_OUT_DIR`. R2 covers finished videos only. No volume = every redeploy wipes the rest. |
| **The Kokoro model files** | 338 MB, gitignored. Without them narration raises and every scene ships **silent** — the product still "works", which is why preflight fails on it. `Dockerfile.app` bakes them in. |

---

## 2. Configuration

Copy `.env.example` and fill in. The ones that decide whether a deploy is sound:

```bash
LATTICE_LLM_API_KEY=...            # required; nothing generates without it
LATTICE_EXEC_MODE=docker           # docker (sandboxed) | local (NOT a sandbox)
LATTICE_OUT_DIR=/data              # point at the mounted volume
LATTICE_TTS_ENGINE=kokoro          # needs the two model files present
LATTICE_ADMIN_TOKEN=<32+ random>   # without it /admin answers only to loopback = to nobody
LATTICE_R2_ACCOUNT_ID=...          # all four R2 vars, or none — half-configured is a FAIL
LATTICE_R2_BUCKET=...
LATTICE_R2_ACCESS_KEY_ID=...
LATTICE_R2_SECRET_ACCESS_KEY=...
LATTICE_JOB_WORKERS=1              # see §3 before changing
LATTICE_SCENE_WORKERS=2
LATTICE_RENDER_MEMORY=1500m
```

`r2-setup.md` (next to this file) covers the bucket itself.

---

## 3. Sizing — the arithmetic that gets containers OOM-killed

Concurrent renders = `JOB_WORKERS × SCENE_WORKERS`, each allowed `RENDER_MEMORY`.
**Defaults are 2 × 3 = 6 renders × 2g = 12 GiB.** That is a development default, not a server one.

| Box | JOB_WORKERS | SCENE_WORKERS | RENDER_MEMORY | RENDER_CPUS | Peak |
|---|---|---|---|---|---|
| 2 vCPU / 4 GB | 1 | 2 | `1500m` | `1.0` | ~3 GiB |
| 4 vCPU / 8 GB | 1 | 3 | `2g` | `1.5` | ~6 GiB |
| 8 vCPU / 16 GB | 2 | 3 | `2g` | `2.0` | ~12 GiB |

`preflight` does this arithmetic against the cgroup limit and fails if it does not fit.
Final quality (`-qh`, 1080p60) costs several times preview (`-ql`, 480p15) in both CPU and time.

---

## 4. What it costs, and what is genuinely free

Prices approximate and drift — verify before committing. Two things are worth separating: **hosting**
(below) and **model calls** (~$0.007–0.02 per video at current settings). Free hosting does not make
the product free; at any real volume the models are the bill.

### Free, and actually capable of rendering

| | What you get | The catch |
|---|---|---|
| **Oracle Cloud Always Free** | **4 ARM cores + 24 GB RAM**, 200 GB disk, 10 TB/mo egress. Free forever, a real VM with a real Docker daemon — so `exec_mode=docker` and the sandbox survive. | "Out of capacity" errors are common in popular regions (Mumbai, Hyderabad) — retry, or pick a quieter one. Needs a card to verify. Idle Always Free compute can be reclaimed; upgrading to pay-as-you-go keeps the free resources and costs nothing while you stay inside them. **ARM64** — verified fine: `manimcommunity/manim:v0.18.1` publishes an arm64 image, as does `python:3.11-slim`. |
| **Cloudflare R2 free tier** | 10 GB storage, 1M writes, 10M reads per month, **zero egress**. | ~1,000 videos fits inside it. This is already wired (`core/storage.py`), so video storage is free at your scale. |
| **Hugging Face Space** (Docker, CPU basic) | 2 vCPU, 16 GB RAM, free, and the easiest public demo link you can get. | Ephemeral disk (state dies), sleeps when idle, public by default, no Docker daemon → `exec_mode=local`, so no sandbox. Good for showing people; not for saved work. |
| **Google Cloud trial** | $300 for 90 days — an e2-standard-2 (2 vCPU / 8 GB) runs free for that window. | It ends. Fine for a launch, not a home. |

### Every good free host asks for a card — here is what that means

Oracle, Google Cloud, Fly and Cloudflare R2 all require a payment method **for identity
verification**, not billing. Oracle places a temporary hold (~$1, often ₹75–100) that reverses in a
few days, and Always Free resources never charge; you are billed only if you upgrade to Paid *and*
exceed the free limits.

The practical risk is rejection, not cost. Oracle refuses prepaid cards and rejects many Indian
**debit** cards at this step. Use a Visa/Mastercard **credit** card with international transactions
enabled; RuPay generally fails.

### If you cannot (or will not) give a card

| Option | Card? | What you get | The trade |
|---|---|---|---|
| **Hugging Face Space** | **No** — an HF account is enough | Public URL, 2 vCPU / 16 GB, free forever | Ephemeral disk, sleeps when idle, no sandbox (`exec_mode=local`), public by default. §6 |
| **Your own machine + Cloudflare Quick Tunnel** | **No** — no account, no domain | A public `https://<random>.trycloudflare.com` URL pointing at the app running on your PC, with the **full docker sandbox** and your real disk | Your machine has to stay on, and the URL changes every restart |
| Oracle / GCP / Fly | Yes | See above | — |

**The tunnel route, in full** (Windows, from the repo):

```powershell
# 1. run the app as usual
.\.venv\Scripts\python.exe -m scripts.serve --host 127.0.0.1 --port 8080

# 2. in a second terminal: download cloudflared once, then
.\cloudflared.exe tunnel --url http://127.0.0.1:8080
```

It prints a public HTTPS URL. Nothing is installed on Cloudflare's side, no account is created, and
the tunnel is outbound-only — you are not opening a port on your router. Stop the process and the
URL dies. For a stable address you need a domain on a (free) Cloudflare account and a *named*
tunnel; that is when a card enters the picture again, for the domain rather than for Cloudflare.

This is a genuinely good way to show the product to someone today. It is not where a product with
users lives: your machine is the server, so it is up only while your machine is.

### Free tiers that cannot run this

**Render free** (512 MB, 0.1 CPU, sleeps after 15 min) and equivalents: a single Manim render needs
~1.5 GB and real CPU for minutes. It will OOM or time out. **Fly.io and Railway no longer have a free
allowance** — Fly is pay-as-you-go, Railway's hobby plan starts around $5/mo.

### Cheapest paid, when free stops fitting

| | Spec | ~Monthly |
|---|---|---|
| Hetzner CX22 | 2 vCPU / 4 GB / 40 GB | ~€4 |
| Hetzner CPX31 | 4 vCPU / 8 GB / 160 GB | ~€14 |
| DigitalOcean (Bangalore) | 2 vCPU / 4 GB | ~$24 |
| Fly.io shared-2x + volume | 2 vCPU / 4 GB | ~$15–25 |
| Render Standard + disk | 2 GB | ~$25 + $0.25/GB |

**Recommendation: Oracle Always Free ARM + R2 free tier.** It is the only free option that keeps the
sandbox and a durable disk, and 4 cores / 24 GB is more than the paid boxes above. If capacity blocks
you, a €4 Hetzner CX22 with the §3 sizing is the pragmatic fallback.

---

## 5. Path A — Oracle Cloud Always Free (recommended)

Free forever, 4 ARM cores / 24 GB, a real Docker daemon — so the render sandbox survives.

**1. Create the VM.** Oracle Cloud console → Compute → Instances → Create.
   - Image **Ubuntu 22.04 or 24.04**, shape **VM.Standard.A1.Flex**, **4 OCPUs / 24 GB** (all of
     the Always Free ARM allowance).
   - Add your SSH public key. Assign a public IPv4.
   - If you get *"Out of host capacity"* — common in Mumbai/Hyderabad — try another availability
     domain, or another region, and retry. It is capacity, not your account.

**2. Open the ports.** Two separate firewalls, and people miss the second one:
   - VCN → Security List → Add **Ingress** rules for TCP 80 and 443 from `0.0.0.0/0`.
   - The instance's own iptables — handled by `setup.sh` below.

**3. Run the bootstrap.**

```bash
ssh ubuntu@<your-ip>
git clone <your-repo> ~/lattice
bash ~/lattice/deploy/oracle/setup.sh lattice.example.com     # omit the domain to skip Caddy
```

It installs Docker + Python + Caddy, builds `lattice-render:0.2` (the pinned base publishes an
arm64 image, so this Just Works on Ampere), creates the venv, opens the firewall, and installs the
systemd unit.

**4. Configuration and the voice files** — deliberately not scripted, because both carry secrets or
338 MB:

```bash
cp ~/lattice/backend/.env.example ~/lattice/backend/.env && nano ~/lattice/backend/.env
# LATTICE_LLM_API_KEY, LATTICE_ADMIN_TOKEN (32+ random), the four LATTICE_R2_*,
# LATTICE_OUT_DIR=/home/ubuntu/lattice/backend/out
# 4 OCPU / 24 GB sizing:
# LATTICE_JOB_WORKERS=1  LATTICE_SCENE_WORKERS=3  LATTICE_RENDER_MEMORY=3g  LATTICE_RENDER_CPUS=1.0

# from your own machine (gitignored, ~338 MB):
scp kokoro-v1.0.onnx voices-v1.0.bin ubuntu@<your-ip>:~/lattice/
```

**5. Point DNS** — an `A` record for your domain at the instance IP. Caddy gets a certificate
automatically on the first request.

**6. Start it.**

```bash
cd ~/lattice/backend && ./.venv/bin/python -m scripts.preflight   # must print 0 failing
sudo systemctl start lattice && journalctl -u lattice -f
```

**Keep it alive.** Oracle reclaims *idle* Always Free compute. Upgrading the account to
pay-as-you-go keeps the Always Free resources and still bills nothing while you stay inside them —
the usual advice for anything you actually depend on.

---

## 6. Path B — Hugging Face Space (public demo, zero setup)

Free CPU tier: 2 vCPU / 16 GB, a public URL, and no server to run. It is a **demo**, not a home:
the disk is ephemeral, it sleeps when idle, and with no Docker daemon it runs `exec_mode=local`,
so model-written Python executes in the container.

**1. Create the Space** at huggingface.co/new-space → SDK **Docker** → blank template.

**2. Push this app into it:**

```bash
bash deploy/huggingface/push-space.sh <hf-username>/<space-name>
```

That assembles a clean copy of the tracked files, swaps in `deploy/huggingface/Dockerfile` as the
Space's root `Dockerfile` (its own root Dockerfile is the render image, a different thing), adds
the README frontmatter HF needs, and pushes the two Kokoro files through **git-lfs**. Use an HF
access token with write scope as the password.

**3. Set secrets** in Settings → Variables and secrets — never in the repo:
`LATTICE_LLM_API_KEY`, and the four `LATTICE_R2_*` if you want finished videos to outlive the
container.

**4. Watch the build log**, then the container log: the first lines are the preflight report.
The build is slow the first time (Manim base + onnxruntime is a few GB).

### Other PaaS (Fly.io, Render, Railway)

Same shape as the Space — `exec_mode=local`, no sandbox — but paid, with a disk you attach for
`/data`. Build `deploy/Dockerfile.app` (from the repo root) with `--build-arg BASE=manimcommunity/manim:v0.18.1`, mount a
volume at `/data`, set the same env. Worth it over a Space only when you need persistence *and*
push-to-deploy.

---

## 7. Running both at once

Yes — they are independent deployments of the same code, and nothing in the app coordinates
between them. The sensible split is **Space = public demo, Oracle = the real thing**.

**What they share, if you let them:**

| | Shared? | What to do |
|---|---|---|
| Model API key | Only if you use the same one — and both then spend from it | Give the demo **its own key**, so a demo that goes viral cannot spend your production budget, and `scripts/cost` shows them apart |
| R2 bucket | Safe to share: keys are derived from random ids (`videos/<pid>/final.mp4`), so they cannot collide | Separate buckets only if you care *which* instance wrote an object |

**What they do not share, at all:** projects, Learn threads, deck records, the usage ledger and
users. All of it is files on each box, and users are anonymous per-browser cookie ids scoped to a
domain. A video made on the Space is invisible on Oracle, and vice versa.

Hosting both costs nothing. Only the model calls cost, and only when someone actually builds.

---

## 7b. Split deploy: UI on Vercel, API on your own server

The default is one server serving both. You can instead host `frontend/` (static files) on Vercel and
keep the backend where it is. It is off unless you configure it, so nothing above changes.

**The one hard requirement: a domain you own.** Sign-in uses secure cookies, and a browser only sends
them to an API that is on the same *site* as the page (the same registrable domain). So
`app.example.com` + `api.example.com` works; `lattice.vercel.app` + `x.duckdns.org` does not (they are
different sites, and the session would silently never arrive). Proxying the API through Vercel to avoid
that is a bad idea here: builds stream progress for minutes over one connection.

The backend still has to run on a host with a Docker daemon (your GCP/Oracle/Hetzner VM). Render, and
other platforms without one, cannot keep the render sandbox.

1. Point `api.example.com` at the server (A record), and `app.example.com` at Vercel (CNAME, as Vercel
   shows you). Re-run `deploy/oracle/setup.sh api.example.com` so Caddy gets a certificate for the API name.
2. On the server `.env`: `LATTICE_FRONTEND_ORIGINS=https://app.example.com` and
   `LATTICE_PUBLIC_URL=https://api.example.com`. Restart. (CORS is enabled only for the origins listed.)
3. Supabase: Site URL `https://app.example.com`; Redirect URLs add `https://api.example.com/auth/callback`.
4. Build and upload the frontend: `powershell -File frontend\build.ps1 -Api https://api.example.com -Contact you@example.com`,
   then upload `frontend-out\` to Vercel and attach the `app.example.com` domain.
5. Google consent screen: homepage `https://app.example.com`, privacy `https://app.example.com/static/privacy.html`.

Sign-in then starts on the API, and returns the browser to the frontend. Only addresses listed in
`LATTICE_FRONTEND_ORIGINS` are ever returned to.

---

## 8. Known limits — read before you promise uptime

- **A restart loses running jobs.** The queue is in-memory; finished scene clips survive on disk and
  the boot recovery path can stitch them, but an in-flight build does not resume.
- **Users are anonymous cookie ids.** There is no account system, so "my videos" is per browser.
- **State is files, not a database.** Fine for one box; it is what makes horizontal scaling a
  rewrite rather than a config change.
- **Cancellation is cooperative** — a stop waits out at most one in-flight render.
- **Back up the volume.** `LATTICE_OUT_DIR` holds everything R2 does not.

---

## 9. After deploying

```bash
python -m scripts.preflight     # 0 failing
curl -fsS https://your-domain/  # 200
python -m scripts.cost          # per-key spend
```

Then build one real video end to end and watch the job log: it names the step, the attempt and the
elapsed time, and the Stop button should end it within one render.
