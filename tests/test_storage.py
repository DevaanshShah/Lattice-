"""Object storage (Cloudflare R2): the seam is off by default, best-effort when on, and the web
layer falls back to it only when the local file is gone. No network — boto3 is replaced by a fake
client that records the calls."""
import pytest
from fastapi.testclient import TestClient

from core import storage


class FakeS3:
    """Just enough of the boto3 S3 client to prove the calls we make are the right ones."""

    def __init__(self, *, fail=False):
        self.objects: dict[str, bytes] = {}
        self.uploads: list[tuple[str, str, dict]] = []
        self.fail = fail

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        if self.fail:
            raise RuntimeError("network down")
        self.uploads.append((path, key, ExtraArgs or {}))
        self.objects[key] = open(path, "rb").read()

    def head_object(self, Bucket=None, Key=None):
        if Key not in self.objects:
            raise RuntimeError("404")
        return {"ContentLength": len(self.objects[Key])}

    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        return f"https://r2.example/{Params['Key']}?sig=abc&exp={ExpiresIn}"

    def download_file(self, bucket, key, dest):
        if key not in self.objects:
            raise RuntimeError("404")
        with open(dest, "wb") as fh:
            fh.write(self.objects[key])

    def delete_object(self, Bucket=None, Key=None):
        self.objects.pop(Key, None)

    def list_objects_v2(self, **kw):
        pre = kw.get("Prefix", "")
        return {"Contents": [{"Key": k, "Size": len(v)} for k, v in self.objects.items()
                             if k.startswith(pre)]}


@pytest.fixture
def fake_r2(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr("core.config.settings.r2_bucket", "lattice")
    monkeypatch.setattr("core.config.settings.r2_account_id", "acct")
    monkeypatch.setattr("core.config.settings.r2_access_key_id", "k")
    monkeypatch.setattr("core.config.settings.r2_secret_access_key", "s")
    monkeypatch.setattr("core.config.settings.r2_public_base", "")
    monkeypatch.setattr("core.config.settings.r2_delete_local", False)
    monkeypatch.setattr(storage, "client", lambda: fake)
    return fake


# --- off by default ----------------------------------------------------------------------------
def test_storage_is_inert_until_configured(tmp_path, monkeypatch):
    """The whole point of the fallback: with no credentials the product behaves exactly as before."""
    monkeypatch.setattr("core.config.settings.r2_bucket", "")
    monkeypatch.setattr("core.config.settings.r2_access_key_id", "")
    monkeypatch.setattr("core.config.settings.r2_secret_access_key", "")
    storage.reset()
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    assert storage.configured() is False and storage.enabled() is False
    assert storage.put(f, "videos/p/final.mp4") is False
    assert storage.url_for("videos/p/final.mp4") is None
    assert storage.exists("videos/p/final.mp4") is False
    assert f.exists()                       # and nothing was moved or deleted


def test_endpoint_is_derived_from_the_account_id(monkeypatch):
    monkeypatch.setattr("core.config.settings.r2_endpoint", "")
    monkeypatch.setattr("core.config.settings.r2_account_id", "abc123")
    assert storage.endpoint() == "https://abc123.r2.cloudflarestorage.com"
    monkeypatch.setattr("core.config.settings.r2_endpoint", "https://custom/")
    assert storage.endpoint() == "https://custom"


def test_keys_are_derived_from_ids():
    assert storage.video_key("p1") == "videos/p1/final.mp4"
    assert storage.video_key("p1", "reel.mp4") == "videos/p1/reel.mp4"
    assert storage.deck_key("d1") == "decks/d1/deck.mp4"
    assert storage.learn_key("t1", "m1") == "learn/t1/m1.mp4"


# --- uploading ----------------------------------------------------------------------------------
def test_put_uploads_with_a_video_content_type(tmp_path, fake_r2):
    f = tmp_path / "final.mp4"
    f.write_bytes(b"video")
    assert storage.put(f, "videos/p1/final.mp4") is True
    _path, key, extra = fake_r2.uploads[0]
    assert key == "videos/p1/final.mp4" and extra["ContentType"] == "video/mp4"


def test_put_failure_never_raises_and_keeps_the_local_file(tmp_path, monkeypatch, fake_r2):
    fake_r2.fail = True
    f = tmp_path / "final.mp4"
    f.write_bytes(b"video")
    logs = []
    assert storage.put(f, "k", log=logs.append) is False
    assert f.exists() and "upload failed" in logs[0]


def test_put_ignores_a_missing_file(tmp_path, fake_r2):
    assert storage.put(tmp_path / "nope.mp4", "k") is False


def test_offload_keeps_the_local_copy_by_default(tmp_path, fake_r2):
    f = tmp_path / "final.mp4"
    f.write_bytes(b"v")
    assert storage.offload(f, "videos/p1/final.mp4") is True
    assert f.exists(), "the editor, re-export and restitch all still read this file"


def test_offload_frees_the_disk_when_asked(tmp_path, fake_r2, monkeypatch):
    monkeypatch.setattr("core.config.settings.r2_delete_local", True)
    f = tmp_path / "final.mp4"
    f.write_bytes(b"v")
    storage.offload(f, "videos/p1/final.mp4")
    assert not f.exists() and "videos/p1/final.mp4" in fake_r2.objects


def test_offload_never_deletes_when_the_upload_failed(tmp_path, fake_r2, monkeypatch):
    monkeypatch.setattr("core.config.settings.r2_delete_local", True)
    fake_r2.fail = True
    f = tmp_path / "final.mp4"
    f.write_bytes(b"v")
    assert storage.offload(f, "k") is False
    assert f.exists(), "losing the only copy because the network blipped is the one unacceptable bug"


# --- reading back --------------------------------------------------------------------------------
def test_url_for_presigns_when_no_public_base(fake_r2):
    assert storage.url_for("videos/p1/final.mp4").startswith("https://r2.example/videos/p1/final.mp4")


def test_url_for_uses_a_public_base_when_set(fake_r2, monkeypatch):
    monkeypatch.setattr("core.config.settings.r2_public_base", "https://cdn.lattice.app/")
    assert storage.url_for("videos/p1/final.mp4") == "https://cdn.lattice.app/videos/p1/final.mp4"


def test_get_pulls_an_object_back_to_disk(tmp_path, fake_r2):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"hello")
    storage.put(src, "videos/p1/final.mp4")
    out = storage.get("videos/p1/final.mp4", tmp_path / "restored" / "final.mp4")
    assert out.read_bytes() == b"hello"
    assert storage.get("videos/missing/final.mp4", tmp_path / "x.mp4") is None


def test_listing_filters_by_prefix(tmp_path, fake_r2):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"12345")
    storage.put(f, "videos/p1/final.mp4")
    storage.put(f, "decks/d1/deck.mp4")
    assert [r["key"] for r in storage.listing("videos/")] == ["videos/p1/final.mp4"]


# --- the web layer falls back to R2 only when the local file is gone -------------------------------
@pytest.fixture
def deck_client(tmp_path, monkeypatch, fake_r2):
    from web import jobs as jobs_mod
    from web.app import create_app

    class Eng:
        root = tmp_path

        def recover_all(self):
            return []

    app = create_app(engine=Eng(), queue=jobs_mod.JobQueue(synchronous=True))
    return TestClient(app), tmp_path


def _write_deck(root, did, mp4_path):
    import json
    ws = root / "decks" / did
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "deck.json").write_text(json.dumps(
        {"id": did, "topic": "t", "title": "T", "slides": [], "mp4": str(mp4_path),
         "created_at": 0.0}), encoding="utf-8")


def test_deck_video_is_served_locally_when_the_file_is_there(deck_client):
    client, root = deck_client
    mp4 = root / "decks" / "d1" / "deck.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"local")
    _write_deck(root, "d1", mp4)
    r = client.get("/api/decks/d1/video")
    assert r.status_code == 200 and r.content == b"local"


def test_deck_video_redirects_to_r2_when_the_disk_was_wiped(deck_client, fake_r2, tmp_path):
    """The redeploy case: project.json survives (it is tiny and re-synced), the mp4 does not."""
    client, root = deck_client
    src = tmp_path / "src.mp4"
    src.write_bytes(b"remote")
    storage.put(src, storage.deck_key("d1"))
    _write_deck(root, "d1", root / "decks" / "d1" / "deck.mp4")     # path recorded, file absent
    r = client.get("/api/decks/d1/video", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://r2.example/decks/d1/deck.mp4")


def test_deck_video_409s_when_it_is_in_neither_place(deck_client):
    client, root = deck_client
    _write_deck(root, "d2", root / "decks" / "d2" / "deck.mp4")
    assert client.get("/api/decks/d2/video").status_code == 409
