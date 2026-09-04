# Cloudflare R2 — storing finished videos

## Why this exists

A PaaS container (Railway, Render, Fly) gives you an **ephemeral disk**. Every redeploy, crash or
restart wipes `out/` — and with it every video the product has ever made. Locally that is invisible;
in production it means a user's video is gone the next time you ship.

R2 is the cheapest correct fix:

| | R2 | AWS S3 |
|---|---|---|
| Storage | $0.015/GB-month | $0.023/GB-month |
| **Egress** | **$0** | ~$0.09/GB |
| Writes (Class A) | $4.50/million | $5/million |
| Reads (Class B) | $0.36/million | $0.40/million |

Egress is the line that matters: the artifact here is a video that people stream. 1,000 videos at
~10 MB is 10 GB — about **$0.15/month**, versus a bill that scales with views on S3.

For comparison, storage is far cheaper than what it stores: one deck video costs ~$0.0017 in model
calls, so a month of storage for 1,000 of them costs less than making one.

### Why not send users to their own Google Drive?

It is a different thing, not a cheaper version of this one. Drive would need Google OAuth per user —
which means building an account system first (Lattice has none; users are anonymous cookie ids) —
and the file would leave your product: no in-app playback, no gallery, no re-export to Reel/YouTube,
no thumbnails, nothing in the admin console. It also asks for a Google authorization at the worst
possible moment, right when the video is ready.

"Save a copy to Drive" is a fine **export button** to add later. It still needs the file to live
somewhere first, which is this.

---

## Setup (about 5 minutes)

### 0. Activate R2 (a card is required, even on the free tier)

Cloudflare asks for a payment method before it will enable R2 at all. Check that **"Due today"
reads $0.00** on that screen — the free tier is the default, and it covers, per month:

- **10 GB** stored
- **1 million** Class A ops (writes — roughly one per finished video)
- **10 million** Class B ops (reads)
- **unmetered free egress**

Past that it is $0.015/GB-month and $4.50 per million writes. A thousand videos a month sits inside
the free tier on ops and costs cents on storage.

**Don't want to give Cloudflare a card?** `core/storage.py` speaks plain S3, so any S3-compatible
provider works by pointing `LATTICE_R2_ENDPOINT` at it — Backblaze B2, Wasabi, or a self-hosted
MinIO. The only R2-specific thing in the code is the default endpoint derived from the account id.
A platform persistent volume (Railway/Render, ~$0.25/GB-month) also solves the ephemeral-disk
problem, at ~16x the storage price and tied to one service.

### 1. Create the bucket

1. Cloudflare dashboard → **R2** → **Create bucket**
2. Name it `lattice-videos`
3. Location: **Automatic**, unless you know your users are concentrated in one region
4. Create

### 2. Create an API token

1. R2 → **Manage R2 API Tokens** → **Create API token**
2. Permission: **Object Read & Write** (not Admin — this token only needs to move objects)
3. Scope it to the `lattice-videos` bucket specifically, not "all buckets"
4. Create, then copy the two values it shows you:
   - **Access Key ID**
   - **Secret Access Key** — shown **once**; if you lose it, roll a new token

### 3. Find your account id

It is in the R2 overview page sidebar, and in the S3 endpoint Cloudflare shows you:
`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

### 4. Put them in `.env`

```ini
LATTICE_R2_ACCOUNT_ID=<the 32-char account id>
LATTICE_R2_BUCKET=lattice-videos
LATTICE_R2_ACCESS_KEY_ID=<Access Key ID>
LATTICE_R2_SECRET_ACCESS_KEY=<Secret Access Key>
```

### 5. Verify before trusting it

```bash
pip install boto3
python -m scripts.r2 check
```

This writes a tiny object, reads it back and deletes it. A wrong secret or a bucket in another
account fails **here**, with a message — instead of silently swallowing every upload mid-render.

### 6. Move what you already have

```bash
python -m scripts.r2 push          # upload every finished video already in out/
python -m scripts.r2 list          # what is in the bucket + the monthly cost
```

---

## How it behaves once it is on

- **Every finished build is uploaded** — the stitched video, deck videos, and Learn chat videos —
  right after the render, from inside the job. The key is derived from the id
  (`videos/<pid>/final.mp4`, `decks/<did>/deck.mp4`, `learn/<tid>/<mid>.mp4`), so nothing had to be
  added to any saved record.
- **Uploads are best-effort.** If R2 is down, the upload logs a line and the local file stays exactly
  where it was. A storage outage degrades to the old behaviour; it never loses a render.
- **Serving prefers local, falls back to R2.** If the file is on disk it is streamed directly. If the
  disk was wiped, the request is redirected (307) to the object — so the video plays from Cloudflare
  rather than 404ing.
- **Export pulls the file back.** Reframing to a Reel or burning captions needs the real file, so
  `/download` fetches it from R2 first when this container no longer has it.
- **Nothing changes until it is configured.** With the settings empty, `storage.enabled()` is False
  and every call is a no-op.

## Public URLs vs presigned (the one real decision)

Default (nothing set): the bucket stays **private** and each request gets a **presigned URL** valid
for an hour. Links cannot be shared forever, and nothing is enumerable.

If you want permanent, shareable, CDN-cached links — for a public gallery or embedding — attach a
custom domain to the bucket (R2 → your bucket → **Settings** → **Public access** → Connect a domain)
and set:

```ini
LATTICE_R2_PUBLIC_BASE=https://videos.yourdomain.com
```

Every video then becomes a permanent public URL. That is a product decision, not a technical one:
**anyone with the link can watch, forever**, including videos other people made.

## Keeping the bill at zero

- **Lifecycle rule**: R2 → bucket → Settings → Object lifecycle → delete objects older than e.g. 30
  days. Preview-quality builds are throwaway; this stops them accumulating.
- **`LATTICE_R2_DELETE_LOCAL=true`** frees the container's disk right after upload. Only worth it on
  a small-disk deploy: the scene editor, re-export and restitch all read the local file and will
  have to pull it back down first.

## Admin data

The usage ledger and user registry (`out/admin/`) are also on that ephemeral disk, so the admin
console's history dies with a redeploy too. Snapshot them:

```bash
python -m scripts.r2 backup        # -> admin/<timestamp>/usage.jsonl, users.json
```

Run it from cron (or your platform's scheduler) daily. A proper database is the real answer if the
console's history ever becomes something you depend on.

## Commands

```bash
python -m scripts.r2 check              # verify credentials end to end
python -m scripts.r2 push               # upload everything in out/ that isn't there yet
python -m scripts.r2 push --delete      # ...and free the local copies
python -m scripts.r2 list [prefix]      # contents + monthly storage cost
python -m scripts.r2 backup             # snapshot the admin ledger + user registry
python -m scripts.r2 pull <key> <dest>  # fetch one object back
```
