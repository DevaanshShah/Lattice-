# Deploying Lattice

Platform-agnostic. Read §1 and §2 whatever you deploy on; §4 covers cost and the free options, §5 the three concrete paths.

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

`docs/r2-setup.md` covers the bucket itself.

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

## 5. The three paths


### A. VPS + Docker — recommended

Keeps the sandbox, keeps a real disk, cheapest per core (~€4–14/mo on Hetzner; DigitalOcean
Bangalore or Hetzner Singapore if your users are in India).

```bash
# on the server, once
git clone <repo> lattice && cd lattice
docker build -t lattice-render:0.2 .                  # the render sandbox image
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
scp kokoro-v1.0.onnx voices-v1.0.bin <server>:~/lattice/    # from your machine; gitignored
cp .env.example .env && $EDITOR .env
.venv/bin/python -m scripts.preflight                 # must print 0 failing
.venv/bin/python -m scripts.serve --host 127.0.0.1 --port 8080
```

Then a systemd unit for restarts, and Caddy in front for TLS:

```
lattice.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

**Run the app on the host, not in a container, on this path.** In docker mode the app shells out to
`docker run`; containerising it would mean mounting `/var/run/docker.sock`, which hands the app
container root-equivalent control of the host. Running the app directly and letting it drive the
daemon avoids that entirely, and the render sandbox is unchanged.

### B. Fly.io — push-to-deploy, no daemon

```bash
docker build -f Dockerfile.app --build-arg BASE=manimcommunity/manim:v0.18.1 -t lattice-app-local .
fly launch --no-deploy && fly volumes create data --size 10
fly secrets set LATTICE_LLM_API_KEY=... LATTICE_ADMIN_TOKEN=... LATTICE_R2_...
fly deploy
```

with `LATTICE_EXEC_MODE=local`, the volume mounted at `/data`, and `[[mounts]] destination = "/data"`.
The image is ~3 GB (Manim + LaTeX + Kokoro + onnxruntime). **Model-written Python executes in your
app container** — child-process environments are scrubbed of secrets and rlimits are applied, but
the filesystem and network are shared. Accept that consciously or use path A.

### C. Render / Railway

Same trade-offs as Fly, plus a paid persistent disk for `/data` and slower builds on a ~3 GB image.
Point the service at `Dockerfile.app` with the same `--build-arg`, set the same env, mount the disk
at `/data`.

---

## 6. Known limits — read before you promise uptime

- **A restart loses running jobs.** The queue is in-memory; finished scene clips survive on disk and
  the boot recovery path can stitch them, but an in-flight build does not resume.
- **Users are anonymous cookie ids.** There is no account system, so "my videos" is per browser.
- **State is files, not a database.** Fine for one box; it is what makes horizontal scaling a
  rewrite rather than a config change.
- **Cancellation is cooperative** — a stop waits out at most one in-flight render.
- **Back up the volume.** `LATTICE_OUT_DIR` holds everything R2 does not.

---

## 7. After deploying

```bash
python -m scripts.preflight     # 0 failing
curl -fsS https://your-domain/  # 200
python -m scripts.cost          # per-key spend
```

Then build one real video end to end and watch the job log: it names the step, the attempt and the
elapsed time, and the Stop button should end it within one render.
