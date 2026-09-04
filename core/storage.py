"""Durable object storage for finished videos — Cloudflare R2, with local disk as the fallback.

The problem this solves is not "we need a CDN": it is that a PaaS container's filesystem is
EPHEMERAL. Every redeploy, crash or scale event wipes `out/`, taking every video the product ever
made with it. R2 is the cheapest correct place to put them — $0.015/GB-month and, unlike S3, no
egress charge at all, which matters when the artifact IS a video people stream.

Shape of the seam:
- keys are DERIVED from ids (`videos/<pid>/final.mp4`), never stored in a record, so nothing in the
  project/deck/thread schemas had to change to adopt this;
- `put()` is called after a build finishes and is best-effort: a failed upload logs and leaves the
  local file exactly where it was, so an R2 outage degrades to today's behaviour instead of losing
  the render;
- `url_for()` returns a presigned GET (or a public custom-domain URL if you set one), which the web
  layer redirects to when the local copy is gone.

Everything is inert until credentials are set: `enabled()` is False, `put()` no-ops, and the whole
product behaves exactly as it did before. That is what makes this safe to merge before the bucket
even exists.
"""
from __future__ import annotations

import mimetypes
import threading
from pathlib import Path
from typing import Any

from core.config import settings

_client: Any = None
_client_lock = threading.Lock()
_warned = False


def endpoint() -> str:
    """R2's S3 endpoint. Explicit override wins; otherwise it is derived from the account id."""
    if settings.r2_endpoint:
        return settings.r2_endpoint.rstrip("/")
    if settings.r2_account_id:
        return f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return ""


def configured() -> bool:
    return bool(settings.r2_bucket and settings.r2_access_key_id
                and settings.r2_secret_access_key and endpoint())


def client() -> Any:
    """The boto3 S3 client pointed at R2, or None. Built once, lazily — importing this module must
    never require boto3 or the network."""
    global _client, _warned
    if not configured():
        return None
    with _client_lock:
        if _client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                if not _warned:
                    print("[storage] R2 is configured but boto3 is not installed "
                          "(pip install boto3) — falling back to local disk")
                    _warned = True
                return None
            _client = boto3.client(
                "s3", endpoint_url=endpoint(),
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                # R2 ignores regions but the SDK insists on one; "auto" is what Cloudflare documents.
                region_name="auto",
                config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
            )
        return _client


def enabled() -> bool:
    return client() is not None


def reset() -> None:
    """Drop the cached client (tests, or a credential change without a restart)."""
    global _client
    with _client_lock:
        _client = None


# --- keys --------------------------------------------------------------------------------------
def video_key(pid: str, name: str = "final.mp4") -> str:
    return f"videos/{pid}/{name}"


def deck_key(did: str) -> str:
    return f"decks/{did}/deck.mp4"


def learn_key(tid: str, mid: str) -> str:
    return f"learn/{tid}/{mid}.mp4"


# --- operations (every one is best-effort: storage must never break a render) --------------------
def put(local: str | Path, key: str, *, content_type: str | None = None, log=None) -> bool:
    """Upload one finished file. Returns True on success; False (quietly) when storage is off."""
    c = client()
    if c is None:
        return False
    path = Path(local)
    if not path.is_file():
        return False
    ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        c.upload_file(str(path), settings.r2_bucket, key, ExtraArgs={"ContentType": ctype})
    except Exception as e:  # noqa: BLE001 — a storage outage must not lose the local render
        if log:
            log(f"[storage] upload failed for {key}: {type(e).__name__}: {e}")
        return False
    if log:
        log(f"[storage] uploaded {key} ({path.stat().st_size / 1e6:.1f} MB)")
    return True


def exists(key: str) -> bool:
    c = client()
    if c is None:
        return False
    try:
        c.head_object(Bucket=settings.r2_bucket, Key=key)
        return True
    except Exception:       # noqa: BLE001 — 404 and every transport error mean "can't serve it"
        return False


def url_for(key: str, *, expires: int = 3600, filename: str | None = None) -> str | None:
    """A URL a browser can fetch. A public base (custom domain or r2.dev) is used verbatim;
    otherwise a presigned GET, which keeps the bucket private."""
    if settings.r2_public_base:
        return settings.r2_public_base.rstrip("/") + "/" + key.lstrip("/")
    c = client()
    if c is None:
        return None
    params: dict[str, Any] = {"Bucket": settings.r2_bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    try:
        return c.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)
    except Exception:       # noqa: BLE001
        return None


def get(key: str, dest: str | Path) -> Path | None:
    """Pull an object back to disk — how a restarted container re-exports a video it no longer has."""
    c = client()
    if c is None:
        return None
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        c.download_file(settings.r2_bucket, key, str(out))
        return out
    except Exception:       # noqa: BLE001
        return None


def delete(key: str) -> bool:
    c = client()
    if c is None:
        return False
    try:
        c.delete_object(Bucket=settings.r2_bucket, Key=key)
        return True
    except Exception:       # noqa: BLE001
        return False


def listing(prefix: str = "", *, limit: int = 1000) -> list[dict]:
    """Objects under a prefix: [{key, size, modified}]. Used by `python -m scripts.r2 list`."""
    c = client()
    if c is None:
        return []
    out: list[dict] = []
    try:
        token = None
        while len(out) < limit:
            kw: dict[str, Any] = {"Bucket": settings.r2_bucket, "Prefix": prefix,
                                  "MaxKeys": min(1000, limit - len(out))}
            if token:
                kw["ContinuationToken"] = token
            page = c.list_objects_v2(**kw)
            for o in page.get("Contents", []):
                out.append({"key": o["Key"], "size": o.get("Size", 0),
                            "modified": o.get("LastModified")})
            token = page.get("NextContinuationToken")
            if not token:
                break
    except Exception:       # noqa: BLE001
        return out
    return out


def offload(local: str | Path, key: str, *, log=None) -> bool:
    """Upload and then, if `r2_delete_local` is on, remove the local copy to reclaim disk.

    Off by default and deliberately so: the local file is what re-export, restitch and the scene
    editor read. Turn it on only for a small-disk deploy, where `get()` pulls files back on demand.
    """
    ok = put(local, key, log=log)
    if ok and settings.r2_delete_local:
        try:
            Path(local).unlink()
        except OSError:
            pass
    return ok
