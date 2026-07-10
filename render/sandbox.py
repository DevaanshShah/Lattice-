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

Execution itself goes through `render.exec` (docker run vs. local subprocess — see that module's
docstring); this module only builds argv and owns the docker-specific timeout-kill fallback.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings
from render import exec as exec_mod
from render.exec import hardening_args  # re-exported: callers/tests use sandbox.hardening_args

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
    """Build the argv that renders `scene_file::scene_name` in a hardened sandbox (docker mode)
    or as a direct `manim` subprocess (local mode — see `render.exec`).

    `--network=none` + resource caps unless overridden (the sandbox invariant, docker mode only).
    `work_dir` is mounted/used at /manim (docker) or as `cwd` (local); Manim writes its `media/`
    tree there either way, so outputs land on the host.
    """
    tool_args = [settings.quality_flag(quality)]
    if still:
        tool_args.append("-s")  # save the last frame as a PNG (the vision-critic hook)
    tool_args += [scene_file, scene_name]
    return exec_mod.argv(work_dir, "manim", tool_args, network=network, image=image,
                         hardened=True, name=name)


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
    here so the caps (no-net, pids-limit, memory) are what stop it — not the host. Docker-only
    (see `run_python_file`): local mode has no sandbox to speak of, so containment would be a lie.
    """
    return exec_mod.argv(work_dir, "python", [py_file], network=network, image=image,
                         hardened=True, name=name)


def _kill_container(name: str) -> None:
    """Best-effort `docker kill` so a wall-clock-timed-out container never lingers (FR-23)."""
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        pass  # already gone, or docker unreachable — nothing more we can do


def _run_sandboxed(cmd: list[str], name: str, timeout: int,
                   work_dir: str | Path) -> tuple[subprocess.CompletedProcess | None, bool]:
    """Run the render (docker container or local subprocess, per `exec_mod.run`); on wall-clock
    timeout, make sure nothing lingers and report timed_out=True. In docker mode the client-side
    wait is what `exec_mod.run` kills — the container itself needs its own `docker kill`; in
    local mode `exec_mod.run` already killed the whole process group, so this is a no-op there.
    """
    try:
        proc = exec_mod.run(cmd, work_dir=work_dir, timeout=timeout)
        return proc, False
    except subprocess.TimeoutExpired:
        if settings.exec_mode != "local":
            _kill_container(name)
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
    proc, timed_out = _run_sandboxed(cmd, name, timeout or settings.render_timeout_s, work_dir)
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

    Docker-only: local mode has no container boundary, so "containment" would be a lie.
    """
    if settings.exec_mode == "local":
        raise RuntimeError(
            "run_python_file (FR-23 containment harness) requires exec_mode='docker' — "
            "local mode has no sandbox boundary to contain untrusted code"
        )
    src = Path(py_file).resolve()
    work_dir = src.parent
    name = f"lattice-sandbox-{uuid.uuid4().hex[:12]}"
    cmd = build_python_command(work_dir, src.name, network=network, image=image, name=name)
    proc, timed_out = _run_sandboxed(cmd, name, timeout or settings.render_timeout_s, work_dir)
    if timed_out:
        return RenderResult(124, "", f"wall-clock timeout (> {timeout or settings.render_timeout_s}s); container killed",
                            cmd, [], timed_out=True)
    return RenderResult(proc.returncode, proc.stdout, proc.stderr, cmd, [])

# NB: multi-frame extraction lives in render/worker.py (worker.extract_frames), which wraps
# this module and adds duration-aware even sampling. sandbox stays manim-render-only.
