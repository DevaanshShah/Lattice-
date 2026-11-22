"""Execution-mode abstraction: run the sandbox's tools (manim/ffmpeg/ffprobe) either via
`docker run` (default; the hardened sandbox) or as direct local subprocesses. Selected by
`core.config.settings.exec_mode` ("docker" | "local"). Every render/ffmpeg call site in
render/sandbox.py, render/worker.py, composition/stitch.py, and composition/export.py builds
its argv through `argv()`/`prefix()` here, so both modes stay byte-identical in shape and the
existing pure-builder unit tests (which assert docker argv) keep passing under the default mode.

"local" mode exists for PaaS deploys (Railway/Render) that don't expose a docker daemon — the
render image's own base already ships manim + ffmpeg, so on those platforms the APP image IS
the render image and tools run in-process. THIS IS NOT A SANDBOX: model-written code shares the
app container's filesystem and (unless blocked at the platform level) its network. The only
mitigations applied are (1) environment scrubbing, so API keys never reach a child process, and
(2) best-effort resource limits + process-group kill on timeout (POSIX only), so a runaway
render can't outlive its wall clock or fork-bomb the container. Prefer "docker" mode — the
`--network=none` + memory/cpu/pids caps in `hardening_args` — whenever a real daemon is available.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from core.config import settings

_SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
_POSIX = os.name == "posix"


def hardening_args(*, network: bool | None = None, name: str | None = None) -> list[str]:
    """The sandbox flags every HARDENED container run shares (FR-23). Pure; the single source
    of truth for docker-mode manim/burn renders (worker/stitch's plain ffmpeg probes are not
    hardened — see `prefix()` — they're short-lived and not model-controlled).

    `--rm` (no leftover writable layer) + `--network=none` (no egress) + resource caps
    (`--memory`/`--cpus`/`--pids-limit`) + the image's non-root user (or an explicit `--user`).
    Read-only root FS + an ephemeral `/tmp` tmpfs are opt-in (`render_read_only`) so the verified
    render path isn't disturbed; the mounted `/manim` volume stays writable regardless.
    """
    net = settings.render_network if network is None else network
    args = ["--rm"]
    if name:
        args += ["--name", name]            # so callers can `docker kill` it on wall-clock timeout
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


def prefix(work_dir: str | Path, *, network: bool | None = None, image: str | None = None) -> list[str]:
    """The un-hardened `docker run --rm [--network=none] -v work_dir:/manim -w /manim image`
    prefix — the caller appends its own tool + args. Local mode: empty (the tool runs directly).
    """
    if settings.exec_mode == "local":
        return []
    net = settings.render_network if network is None else network
    img = image or settings.render_image
    cmd = ["docker", "run", "--rm"]
    if not net:
        cmd.append("--network=none")
    cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img]
    return cmd


def argv(
    work_dir: str | Path,
    tool: str,
    tool_args: list[str],
    *,
    network: bool | None = None,
    image: str | None = None,
    hardened: bool = False,
    name: str | None = None,
) -> list[str]:
    """Build the argv that runs `tool *tool_args` against `work_dir`.

    docker mode: `docker run <hardening or plain flags> -v work_dir:/manim -w /manim image tool
    *tool_args` (identical to the pre-exec-layer argv, for hardened=True and False alike).
    local mode: `[tool, *tool_args]` — a direct subprocess; `run()` supplies cwd=work_dir.
    """
    if settings.exec_mode == "local":
        return [tool, *tool_args]
    if hardened:
        img = image or settings.render_image
        cmd = ["docker", "run", *hardening_args(network=network, name=name)]
        cmd += ["-v", f"{Path(work_dir).resolve().as_posix()}:/manim", "-w", "/manim", img]
        return cmd + [tool, *tool_args]
    return prefix(work_dir, network=network, image=image) + [tool, *tool_args]


def _scrubbed_env() -> dict[str, str]:
    """A minimal env for local-mode subprocesses: no LATTICE_* config, no key/token/secret/
    password-shaped vars. Model-written code must never be able to read the LLM API key out of
    its own process environment."""
    return {
        k: v for k, v in os.environ.items()
        if not k.startswith("LATTICE_") and not _SECRET_RE.search(k)
    }


def _parse_bytes(spec: str) -> int | None:
    """'2g' / '512m' -> bytes; None if unparseable (the rlimit is then skipped, not fatal)."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*$", spec or "")
    if not m:
        return None
    mult = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2).lower()]
    return int(float(m.group(1)) * mult)


def _preexec_limits():
    """Best-effort rlimits for a local-mode child, applied post-fork/pre-exec (POSIX only)."""
    try:
        import resource
    except ImportError:  # Windows dev box — local mode isn't used there anyway
        return None

    mem = _parse_bytes(settings.render_memory)
    pids = settings.render_pids_limit

    def _apply() -> None:
        if mem:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            except (ValueError, OSError):
                pass
        if pids:
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (pids, pids))
            except (ValueError, OSError, AttributeError):
                pass

    return _apply


def run(cmd: list[str], *, work_dir: str | Path, timeout: int) -> subprocess.CompletedProcess:
    """Execute `cmd` (as built by `argv()`/manual docker argv). Docker mode: `subprocess.run`
    exactly as before — docker itself is the sandbox. Local mode: run with cwd=work_dir, a
    scrubbed env, and (POSIX) its own process group + best-effort rlimits; on wall-clock timeout
    the WHOLE process group is killed (manim spawns ffmpeg children — killing only the direct
    child would leak them) and `subprocess.TimeoutExpired` is raised, same as docker mode, so
    existing callers' `except subprocess.TimeoutExpired` handling is unchanged.
    """
    if settings.exec_mode != "local":
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)

    popen_kwargs: dict = {"cwd": str(work_dir), "env": _scrubbed_env()}
    if _POSIX:
        popen_kwargs["start_new_session"] = True
        preexec = _preexec_limits()
        if preexec:
            popen_kwargs["preexec_fn"] = preexec

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if _POSIX:
            try:
                os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL the whole tree, not just proc
            except OSError:
                pass
        else:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(
        cmd, proc.returncode,
        out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
    )
