"""Is this box actually configured to run Lattice in production?

    python -m scripts.preflight          # exit code = number of FAILs

Deploying this app is not "start the web server". It needs a model key, a way to run Manim, voice
model files, somewhere durable to put finished videos, and a memory budget that its own concurrency
knobs can't exceed. Every one of those fails LATE and quietly if it is wrong: a missing render image
looks like a broken scene, missing Kokoro files ship a silent video, an unset admin token makes the
console answer only to loopback (so on a server, to nobody), and over-subscribed workers get the
container OOM-killed mid-render.

So: one command that says what is wrong BEFORE a user hits it. Checks are pure functions over
`settings` plus a few probes, so they are unit-testable without a server.

FAIL = the product is broken or unsafe in this configuration.
WARN = it will run, but something is worse than you probably intend.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.config import settings

FAIL, WARN, OK = "FAIL", "WARN", "ok"


@dataclass(frozen=True)
class Check:
    name: str
    level: str          # FAIL | WARN | OK
    detail: str = ""

    @property
    def bad(self) -> bool:
        return self.level == FAIL


# --- helpers (pure where they can be) ---------------------------------------------------------
def parse_size(text: str) -> float | None:
    """Docker-style size ("2g", "1500m", "512k") -> GiB. None if unparseable."""
    t = (text or "").strip().lower()
    if not t:
        return None
    unit, num = t[-1], t[:-1]
    scale = {"g": 1.0, "m": 1 / 1024, "k": 1 / 1024 / 1024, "b": 1 / 1024 ** 3}.get(unit)
    if scale is None:                       # a bare number is bytes
        unit, num, scale = "b", t, 1 / 1024 ** 3
    try:
        return float(num) * scale
    except ValueError:
        return None


def host_memory_gb() -> float | None:
    """RAM this process may actually use: the cgroup limit inside a container, else the host's.
    None when it cannot be determined (Windows dev boxes) — the caller degrades to a WARN."""
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(p).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw and raw != "max":
            try:
                n = int(raw)
            except ValueError:
                continue
            if 0 < n < 2 ** 62:            # cgroup v1 writes a sentinel ~2^63 for "no limit"
                return n / 1024 ** 3
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return None


def worst_case_renders() -> int:
    """Concurrent renders this configuration permits: every build job fans out to scene workers."""
    return max(1, settings.job_workers) * max(1, settings.scene_workers)


def memory_check(available_gb: float | None) -> Check:
    """The sizing mistake that gets a container OOM-killed mid-render, in one line of arithmetic."""
    n = worst_case_renders()
    per = parse_size(settings.render_memory) or 0.0
    need = n * per
    knobs = ("LATTICE_JOB_WORKERS / LATTICE_SCENE_WORKERS / LATTICE_RENDER_MEMORY")
    detail = (f"{settings.job_workers} job workers x {settings.scene_workers} scene workers "
              f"= up to {n} concurrent renders x {settings.render_memory} = {need:.1f} GiB")
    if available_gb is None:
        return Check("memory budget", WARN, f"{detail}; could not read this box's limit — size it yourself")
    if need > available_gb:
        return Check("memory budget", FAIL,
                     f"{detail}, but only {available_gb:.1f} GiB available. Turn down {knobs}")
    if need > available_gb * 0.8:
        return Check("memory budget", WARN,
                     f"{detail}, against {available_gb:.1f} GiB — little headroom for the web process")
    return Check("memory budget", OK, f"{detail}, within {available_gb:.1f} GiB")


def _docker_reachable() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _image_present(image: str) -> bool:
    try:
        r = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# --- the checks --------------------------------------------------------------------------------
def check_model() -> list[Check]:
    if not settings.llm_api_key.strip():
        return [Check("model key", FAIL, "LATTICE_LLM_API_KEY is empty — nothing can be generated")]
    return [Check("model key", OK, f"{settings.llm_model} via {settings.llm_base_url}")]


def check_execution() -> list[Check]:
    """Docker mode is the sandbox. Local mode runs model-written Python in this container."""
    if settings.exec_mode == "docker":
        if not _docker_reachable():
            return [Check("docker daemon", FAIL,
                          "exec_mode=docker but no daemon answers. Renders will all fail; either "
                          "expose the socket or set LATTICE_EXEC_MODE=local (NOT a sandbox)")]
        out = [Check("docker daemon", OK, "reachable; renders run sandboxed")]
        if not _image_present(settings.render_image):
            out.append(Check("render image", FAIL,
                             f"{settings.render_image} not present — build it with "
                             f"`docker build -f deploy/Dockerfile.render -t {settings.render_image} backend`"))
        else:
            out.append(Check("render image", OK, settings.render_image))
        if settings.render_network:
            out.append(Check("render network", WARN,
                             "LATTICE_RENDER_NETWORK is on — model-written code has egress"))
        return out

    missing = [t for t in ("manim", "ffmpeg") if not shutil.which(t)]
    out = [Check("local toolchain", FAIL if missing else OK,
                 f"missing from PATH: {', '.join(missing)}" if missing
                 else "manim + ffmpeg present")]
    out.append(Check("sandbox", WARN,
                     "exec_mode=local: model-written Python runs IN this container, sharing its "
                     "filesystem and network. Prefer docker mode wherever a daemon exists"))
    return out


def check_voice() -> list[Check]:
    if settings.tts_engine != "kokoro":
        return [Check("voice", WARN, f"tts_engine={settings.tts_engine}: gTTS needs network at "
                                     "synthesis time and sounds worse than Kokoro")]
    missing = [p for p in (settings.kokoro_model, settings.kokoro_voices) if not Path(p).is_file()]
    if missing:
        return [Check("voice", FAIL,
                      f"kokoro selected but model files are missing: {', '.join(missing)} — "
                      "builds would ship SILENT. Bake them into the image")]
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return [Check("voice", FAIL, "kokoro model files present but `kokoro-onnx` is not installed")]
    return [Check("voice", OK, f"kokoro ({settings.kokoro_voice})")]


def check_storage() -> list[Check]:
    """Finished videos, and the JSON state that is NOT covered by object storage."""
    out: list[Check] = []
    r2 = {"account": settings.r2_account_id, "bucket": settings.r2_bucket,
          "key": settings.r2_access_key_id, "secret": settings.r2_secret_access_key}
    set_ = {k for k, v in r2.items() if str(v).strip()}
    if not set_:
        # How bad this is depends on the disk underneath, which we cannot detect: on a PaaS or a
        # Space it means every video dies on the next rebuild; on a VPS with a real volume it is
        # "no backup" rather than "no storage". Say which, instead of one alarmist sentence.
        out.append(Check("object storage", WARN,
                         "no R2 configured: finished videos live only on this disk. On an "
                         "ephemeral one (PaaS/Space) they die on the next rebuild; on a VPS volume "
                         "they persist but have no off-box backup"))
    elif len(set_) < len(r2):
        out.append(Check("object storage", FAIL,
                         f"R2 half-configured (missing: {', '.join(sorted(set(r2) - set_))})"))
    else:
        # configured != working: only a round-trip proves the secret and the bucket match.
        out.append(Check("object storage", OK,
                         f"R2 bucket {settings.r2_bucket} configured — verify with "
                         "`python -m scripts.r2 check`"))

    out_dir = Path(settings.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        out.append(Check("state directory", OK,
                         f"{out_dir} writable — mount a VOLUME here: projects, Learn threads, deck "
                         "records and the usage ledger are files, and R2 only holds the videos"))
    except OSError as e:
        out.append(Check("state directory", FAIL, f"{out_dir} is not writable: {e}"))
    return out


def check_admin() -> list[Check]:
    token = (settings.admin_token or "").strip()
    if not token:
        return [Check("admin console", WARN,
                      "LATTICE_ADMIN_TOKEN empty: the console answers only to loopback, so on a "
                      "server it answers to nobody. Set one to use it (and to keep others out)")]
    if len(token) < 16:
        return [Check("admin console", WARN, f"admin token is only {len(token)} chars — use a long random one")]
    return [Check("admin console", OK, "token set")]


def check_bounds() -> list[Check]:
    """Phase A/B knobs: a job that can never end is a production incident, not a slow build."""
    if not settings.job_deadline_s:
        return [Check("job deadline", WARN,
                      "LATTICE_JOB_DEADLINE_S=0: a wedged build can retry until someone notices")]
    worst = settings.llm_attempts * settings.llm_timeout_s
    return [Check("job deadline", OK,
                  f"{settings.job_deadline_s}s per job, {settings.scene_deadline_s}s per scene; "
                  f"one model call is bounded at {worst:.0f}s")]


def check_host_tools() -> list[Check]:
    """What the app itself shells out to on the HOST, whatever the exec mode.

    Docker mode sandboxes the Manim render, but slides, stitching and browser scenes run in this
    process: ffmpeg/ffprobe for video, a system Chrome driven through playwright for frames. None of
    it is in requirements.txt or the render image, and a box without them starts fine and fails on the
    first build, so preflight said "deployable" on a server that could not make a video.
    """
    out: list[Check] = []
    missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    out.append(Check("ffmpeg", FAIL if missing else OK,
                     f"missing from PATH: {', '.join(missing)} — `sudo apt-get install -y ffmpeg`"
                     if missing else "ffmpeg + ffprobe present"))
    try:
        import playwright  # noqa: F401
        out.append(Check("playwright", OK, "installed"))
    except ImportError:
        out.append(Check("playwright", FAIL, "python package missing — `pip install -r requirements.txt`"))
    try:
        from composition.slides import chrome_path
        out.append(Check("chrome", OK, chrome_path()))
    except Exception as e:      # noqa: BLE001 — SlideRenderError, or anything odd while probing
        out.append(Check("chrome", FAIL, f"{e} — install google-chrome-stable or set LATTICE_CHROME"))
    return out


def disk_check(free_bytes: int, total_bytes: int, where: str) -> Check:
    """Finished videos, scene clips and the ledger all accumulate on this disk. A full one fails builds
    in confusing ways (a half-written MP4, a ledger line lost), so warn well before it is full."""
    gb, pct = free_bytes / 1024 ** 3, 100.0 * free_bytes / max(total_bytes, 1)
    detail = f"{gb:.1f} GiB free ({pct:.0f}%) at {where}"
    if gb < 1:
        return Check("disk space", FAIL, f"{detail}: builds will fail. Delete old projects or grow the disk")
    if gb < 5 or pct < 10:
        return Check("disk space", WARN, f"{detail}: running low. Clean up old projects soon")
    return Check("disk space", OK, detail)


def check_disk() -> list[Check]:
    out_dir = Path(settings.out_dir)
    probe = out_dir if out_dir.exists() else out_dir.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as e:
        return [Check("disk space", WARN, f"could not read free space at {probe}: {e}")]
    return [disk_check(usage.free, usage.total, str(probe))]


def check_access() -> list[Check]:
    """Who can use this instance, and what the most they can cost is. Sign-in OFF on a server is a
    public app with no accounts and no limits, so that is a warning; open sign-in with no global
    ceiling is a WARN too, because every Google account is free to make."""
    if not (settings.supabase_url and settings.supabase_anon_key):
        return [Check("sign-in", WARN, "off: anyone with the link can use the app with no accounts or "
                                       "limits. Fine locally; set LATTICE_SUPABASE_URL/_ANON_KEY on a server")]
    out = [Check("sign-in", OK, "on" + ("" if settings.auth_required else " (guests allowed)"))]
    if not settings.public_url.strip():
        out.append(Check("public url", WARN, "LATTICE_PUBLIC_URL is empty: the sign-in return address "
                                             "is guessed from the request. Set it to your https address"))
    if settings.auth_allowed_emails.strip():
        out.append(Check("invite list", OK, "restricted to the listed emails/domains"))
    elif not settings.quota_global_spend_usd_per_day:
        out.append(Check("spend ceiling", WARN,
                         "open to any Google account with NO global spend ceiling: the bill is bounded "
                         "only by how many accounts show up. Set LATTICE_QUOTA_GLOBAL_SPEND_USD_PER_DAY"))
    else:
        out.append(Check("invite list", WARN,
                         f"open to any Google account; worst case a day is "
                         f"${settings.quota_global_spend_usd_per_day:g} in model spend"))
    return out


def run() -> list[Check]:
    checks: list[Check] = []
    for fn in (check_model, check_execution, check_host_tools, check_voice, check_storage, check_disk,
               check_admin, check_access, check_bounds):
        checks.extend(fn())
    checks.append(memory_check(host_memory_gb()))
    return checks


def main() -> int:
    checks = run()
    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = {FAIL: "FAIL", WARN: "warn", OK: "  ok"}[c.level]
        print(f"  [{mark}] {c.name.ljust(width)}  {c.detail}")
    fails = sum(1 for c in checks if c.bad)
    warns = sum(1 for c in checks if c.level == WARN)
    print(f"\n{fails} failing, {warns} warning(s)."
          + ("" if fails else "  Configuration is deployable."))
    return fails


if __name__ == "__main__":
    sys.exit(main())
