"""FR-5 / FR-7 — the free, deterministic correctness signal: compile-check + auto-repair.

Render the code. If it crashes, feed the **trimmed** traceback (not the whole noisy Manim
banner — that's the cost control) back to the generator and retry, up to a hard cap. This is
the cheap layer that gates the paid vision critic: a scene that can't even render never costs
a vision call. On non-recovery within the cap it returns the best (last) attempt plus a useful
error — it never spins.

`render_fn` and `regen_fn` are injectable so the loop is unit-testable with no Docker/model.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SceneSpec
from core.textutil import strip_code_fences
from prompts.loader import load
from render import worker
from render.worker import WorkerResult
from verification.caps import Caps

# (code, work_dir) -> WorkerResult ; (code, trimmed_error) -> new_code
RenderFn = Callable[[str, Path], WorkerResult]
RegenFn = Callable[[str, str], str]


def trim_traceback(output: str, *, max_chars: int = 2000, max_lines: int = 40) -> str:
    """Reduce render stderr to the part worth sending back: the Python traceback's tail.

    Manim wraps failures in a large rich-formatted banner; resending all of it every retry
    burns tokens for no signal. We keep from the last `Traceback (most recent call last)`
    (or the last few lines if there's no traceback), then cap to the tail by chars.
    """
    text = (output or "").strip()
    if not text:
        return "(no error output captured)"
    idx = text.rfind("Traceback (most recent call last)")
    if idx != -1:
        text = text[idx:]
    else:
        text = "\n".join(text.splitlines()[-max_lines:])
    if len(text) > max_chars:
        text = text[-max_chars:]  # the exception line lives at the end — keep the tail
    return text.strip()


@dataclass
class Attempt:
    n: int
    ok: bool
    error: str | None = None  # trimmed traceback when this attempt failed


@dataclass
class RepairResult:
    ok: bool
    code: str                       # working code if ok, else the best (last) attempt
    mp4: Path | None = None
    frames: list[Path] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    error: str | None = None        # set when we never recovered within the cap

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)


def _default_fixer(spec: SceneSpec | None, client: LLMClient | None) -> RegenFn:
    """Build the LLM-backed repair function (the generator model, not the critic)."""
    client = client or get_client()
    system = load("manim-conventions") + "\n\n---\n\n" + load("compile-repair")
    intent = ""
    if spec is not None:
        intent = f"\n\nScene intent (for context, do not change it):\n{spec.model_dump_json(indent=2)}"

    def fix(code: str, error: str) -> str:
        user = (f"TRIMMED TRACEBACK:\n{error}\n\nCURRENT CODE:\n{code}{intent}\n\n"
                "Resend the full corrected file (code only).")
        raw = client.chat([{"role": "system", "content": system},
                           {"role": "user", "content": user}])
        return strip_code_fences(raw)

    return fix


# A render can fail because the SANDBOX is unavailable (Docker daemon down) rather than because the
# code is wrong. Repairing the code can't fix that, so the loop must abort instead of burning LLM
# fix calls + renders against a dead daemon (the eval once spent ~$0.16 doing exactly that).
_INFRA_MARKERS = (
    "error during connect",                # docker client can't reach the daemon (Desktop stopped)
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "dockerdesktoplinuxengine",
)


def _is_infra_failure(res: WorkerResult) -> bool:
    s = ((res.stderr or "") + " " + (res.stdout or "")).lower()
    return any(m in s for m in _INFRA_MARKERS)


def repair(code: str, work_dir: str | Path, *, render_fn: RenderFn | None = None,
           regen_fn: RegenFn | None = None, caps: Caps | None = None,
           quality: str = "preview", frames: int = 3,
           spec: SceneSpec | None = None, client: LLMClient | None = None,
           log: Callable[[str], None] | None = None) -> RepairResult:
    caps = caps or Caps()
    work_dir = Path(work_dir)
    if render_fn is None:
        def render_fn(c: str, wd: Path) -> WorkerResult:  # noqa: E306
            return worker.render_code(c, wd, quality=quality, frames=frames)
    if regen_fn is None:
        regen_fn = _default_fixer(spec, client)
    say = log or (lambda _m: None)

    current = code
    attempts: list[Attempt] = []
    last_error: str | None = None

    for i in range(1, caps.max_repair_attempts + 1):
        res = render_fn(current, work_dir)
        if res.ok:
            attempts.append(Attempt(i, True))
            say(f"[compile] attempt {i}/{caps.max_repair_attempts}: OK")
            return RepairResult(True, current, res.mp4, list(res.frames), attempts)

        if _is_infra_failure(res):
            # sandbox is unavailable — NOT a code defect; retrying/fixing wastes tokens. Abort now.
            say("[compile] sandbox unavailable (Docker daemon unreachable) — aborting; not a code "
                "defect. Start Docker Desktop and retry.")
            attempts.append(Attempt(i, False, "infrastructure: Docker daemon unreachable"))
            return RepairResult(False, current, None, [], attempts,
                                "sandbox unavailable: Docker daemon unreachable (start Docker and retry)")

        last_error = trim_traceback(res.stderr or res.stdout)
        attempts.append(Attempt(i, False, last_error))
        say(f"[compile] attempt {i}/{caps.max_repair_attempts}: FAILED (exit {res.returncode})")
        if i < caps.max_repair_attempts:
            current = regen_fn(current, last_error)

    # cap exhausted: graceful failure — best attempt + a useful error, never a hang
    say(f"[compile] gave up after {caps.max_repair_attempts} attempts")
    return RepairResult(False, current, None, [], attempts,
                        f"did not compile within {caps.max_repair_attempts} attempts; "
                        f"last error:\n{last_error}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Compile-repair a (possibly broken) Manim file.")
    ap.add_argument("scene_file")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    code = Path(args.scene_file).read_text(encoding="utf-8")
    res = repair(code, Path(args.scene_file).resolve().parent,
                 quality=args.quality, log=print)
    print("---")
    for a in res.attempts:
        print(f"  attempt {a.n}: {'OK' if a.ok else 'failed'}")
    if res.ok:
        print(f"[OK] recovered in {res.n_attempts} attempt(s) -> {res.mp4}")
        return 0
    print(f"[X] {res.error}")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
