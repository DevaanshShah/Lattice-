"""Sandboxed render primitive — the one place Manim code is executed.

Model-written code (from M1 on) and our own sample scene both run through here, inside
the pinned `lattice-render` container with `--network=none` and the image's non-root
`manimuser`. Network is OFF unless a caller explicitly opts in.

M7 / FR-23 — now that strangers can submit prompts (web UI), this is hardened: every run
is bounded by `--memory`/`--cpus` (no host resource monopoly), `--pids-limit` (contains a
fork bomb), optionally a read-only root FS with an ephemeral `/tmp` tmpfs, and a wall-clock
kill (`render` names the container and `docker kill`s it on timeout, so nothing lingers).
`--rm` + per-job mounted dirs already make the filesystem ephemeral between jobs. These layer
ON TOP of the day-one no-network + non-root guarantees — `hardening_args` is the single source.

`build_command` / `build_python_command` / `hardening_args` are pure (unit-testable without
Docker); `render` / `run_python_file` execute them.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings

# Manim writes videos under media/videos/<stem>/<RES>/. Map a quality flag -> its RES dir
# so a render reports only the file it just produced, not stale artifacts from earlier runs.
_RES_BY_FLAG = {
    "-ql": "480p15",
    "-qm": "720p30",
    "-qh": "1080p60",
    "-qp": "1440p60",
    "-qk": "2160p60",
}


@dataclass
class RenderResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    outputs: list[Path] = field(default_factory=list)
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def hardening_args(*, network: bool | None = None, name: str | None = None) -> list[str]:
    """The sandbox flags every container run shares (FR-23). Pure; the single source of truth.

    `--rm` (no leftover writable layer) + `--network=none` (no egress) + resource caps
    (`--memory`/`--cpus`/`--pids-limit`) + the image's non-root user (or an explicit `--user`).
    Read-only root FS + an ephemeral `/tmp` tmpfs are opt-in (`render_read_only`) so the verified
    render path isn't disturbed; the mounted `/manim` volume stays writable regardless.
    """
    net = settings.render_network if network is None else network
    args = ["--rm"]
    if name:
        args += ["--name", name]            # so `render` can `docker kill` it on wall-clock timeout
    if not net:
        args.append("--network=none")       # no egress (contains network-egress snippets)
    if settings.render_user:
        args += ["--user", settings.render_user]  # else the image's non-root default user
    args += [
        "--memory", settings.render_memory,
        "--memory-swap", settings.render_memory,   # no swap escape hatch past the RAM cap
        "--cpus", settings.render_cpus,
        "--pids-limit", str(settings.render_pids_limit),  # contains fork bombs
    ]
    if settings.render_read_only:
        args += ["--read-only", "--tmpfs", f"/tmp:rw,size={settings.render_tmpfs_size}"]
    return args


def build_command(
    work_dir: str | Path,
    scene_file: str,
    scene_name: str,
    *,
    quality: str = "preview",
    still: bool = False,
    network: bool | None = None,
    image: str | None = None,
    name: str | None = None,
) -> list[str]:
    """Build the `docker run` argv that renders `scene_file::scene_name` in a hardened sandbox.

    `--network=none` + resource caps unless overridden (the sandbox invariant). `work_dir` is
    mounted at /manim; Manim writes its `media/` tree there, so outputs land on the host.
    """
    work_dir = Path(work_dir).resolve()
    img = image or settings.render_image

    cmd = ["docker", "run", *hardening_args(network=network, name=name)]
    cmd += ["-v", f"{work_dir.as_posix()}:/manim", "-w", "/manim", img, "manim",
            settings.quality_flag(quality)]
    if still:
        cmd.append("-s")  # save the last frame as a PNG (the vision-critic hook)
    cmd += [scene_file, scene_name]
    return cmd


def build_python_command(
    work_dir: str | Path,
    py_file: str,
    *,
    network: bool | None = None,
    image: str | None = None,
    name: str | None = None,
) -> list[str]:
    """Build the `docker run` argv that runs an arbitrary python file in the hardened sandbox.

    The FR-23 containment harness: `lattice render-sandbox <hostile.py>` runs untrusted code
    here so the caps (no-net, pids-limit, memory) are what stop it — not the host.
    """
    work_dir = Path(work_dir).resolve()
    img = image or settings.render_image
    return ["docker", "run", *hardening_args(network=network, name=name),
            "-v", f"{work_dir.as_posix()}:/manim", "-w", "/manim", img, "python", py_file]


def _kill_container(name: str) -> None:
    """Best-effort `docker kill` so a wall-clock-timed-out container never lingers (FR-23)."""
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        pass  # already gone, or docker unreachable — nothing more we can do


def _run_sandboxed(cmd: list[str], name: str, timeout: int) -> tuple[subprocess.CompletedProcess | None, bool]:
    """Run a named sandbox container; on wall-clock timeout, kill it and report timed_out=True."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True,
            encoding="utf-8", errors="replace",  # Manim emits UTF-8; don't let Windows cp1252 crash the reader
            timeout=timeout,
        )
        return proc, False
    except subprocess.TimeoutExpired:
        _kill_container(name)  # subprocess.run killed the client; this stops the container itself
        return None, True


def render(
    work_dir: str | Path,
    scene_file: str,
    scene_name: str,
    *,
    quality: str = "preview",
    still: bool = False,
    network: bool | None = None,
    image: str | None = None,
    timeout: int | None = None,
) -> RenderResult:
    name = f"lattice-render-{uuid.uuid4().hex[:12]}"
    cmd = build_command(
        work_dir, scene_file, scene_name,
        quality=quality, still=still, network=network, image=image, name=name,
    )
    proc, timed_out = _run_sandboxed(cmd, name, timeout or settings.render_timeout_s)
    if timed_out:
        return RenderResult(124, "", f"wall-clock timeout (> {timeout or settings.render_timeout_s}s); container killed",
                            cmd, [], timed_out=True)

    outputs: list[Path] = []
    if proc.returncode == 0:
        media = Path(work_dir).resolve() / "media"
        if media.exists():
            if still:
                # `-s` produces a keyframe PNG, no video
                outputs = sorted(media.rglob("*.png"))
            else:
                # scope to this quality's resolution dir; skip per-animation scratch clips
                res = _RES_BY_FLAG.get(settings.quality_flag(quality), "")
                outputs = sorted(
                    p for p in media.rglob("*.mp4")
                    if "partial_movie_files" not in p.parts and (not res or res in p.parts)
                )
    return RenderResult(proc.returncode, proc.stdout, proc.stderr, cmd, outputs)


def run_python_file(
    py_file: str | Path,
    *,
    network: bool | None = None,
    image: str | None = None,
    timeout: int | None = None,
) -> RenderResult:
    """Run an arbitrary python file inside the hardened sandbox (the FR-23 containment harness).

    Copies `py_file` into a private work dir, mounts it, and runs `python` on it under all the
    sandbox caps. A hostile snippet (network egress / fork bomb) is contained by the caps, not
    the host: it exits non-zero (or is killed on timeout), and the host is untouched.
    """
    src = Path(py_file).resolve()
    work_dir = src.parent
    name = f"lattice-sandbox-{uuid.uuid4().hex[:12]}"
    cmd = build_python_command(work_dir, src.name, network=network, image=image, name=name)
    proc, timed_out = _run_sandboxed(cmd, name, timeout or settings.render_timeout_s)
    if timed_out:
        return RenderResult(124, "", f"wall-clock timeout (> {timeout or settings.render_timeout_s}s); container killed",
                            cmd, [], timed_out=True)
    return RenderResult(proc.returncode, proc.stdout, proc.stderr, cmd, [])

# NB: multi-frame extraction lives in render/worker.py (worker.extract_frames), which wraps
# this module and adds duration-aware even sampling. sandbox stays manim-render-only.
