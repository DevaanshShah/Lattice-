"""Autonomous end-to-end self-test — run ONE real video through the ACTUAL user path and GRADE it.

    python -m scripts.selftest ["<topic>"] [--max-scenes N] [--quality preview|final]
                               [--target-seconds S] [--keep-workspace]
                               [--renderer legacy|browser_v2]

This is the "run it like a user, without a human in the loop, and check everything" harness.
It does NOT re-implement the pipeline: it drives the SAME `web.engine.Engine` the browser drives
(plan -> auto-approve the theme/outline gate -> build -> stitch), then runs a battery of automated
checks on the RENDERED OUTPUT (not on how clean the code looks — see the "judge by frames" rule):

  preflight   key present · docker daemon + render image (unless exec_mode=local) · TTS import
  build       plan() -> build() end to end, logs streamed, cost metered
  grade       CRITICAL: project loads · final.mp4 exists & non-trivial · every scene rendered ·
                        final duration > 0
              WARN:     per-scene clip duration sane · stitched ≈ sum(scenes) · narration present ·
                        no chat/meta-commentary leaked into narration · narration within word budget ·
                        theme applied

`--renderer browser_v2` drives the learning-video path the web Teach tab uses. Docker is then
only needed for Manim-drawn array scenes, so its absence is a warning, durations are probed on
the host, the theme check is dropped, and the video length is compared with --target-seconds.

Exit code 0 iff every CRITICAL check passes. A markdown report + the full workspace are left under
out/selftest/<topic>/ so a failure is inspectable without re-running.
"""
from __future__ import annotations

import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from composition import decoupled
from composition.stitch import _docker_prefix
from core.config import settings
from core.console import enable_utf8
from core.llm import reset_usage, usage_snapshot


# --- check bookkeeping -----------------------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    critical: bool
    detail: str = ""


@dataclass
class Report:
    topic: str
    checks: list[Check] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, *, critical: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, ok, critical, detail))
        mark = "OK " if ok else ("FAIL" if critical else "WARN")
        print(f"   [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    @property
    def critical_failed(self) -> list[Check]:
        return [c for c in self.checks if c.critical and not c.ok]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.critical and not c.ok]

    @property
    def passed(self) -> bool:
        return not self.critical_failed


def _slug(s: str, n: int = 48) -> str:
    return (re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower())[:n] or "untitled"


# --- preflight (fail fast, BEFORE spending on an LLM run) -------------------------------------
def _docker_ok(rep: Report, *, critical: bool = True) -> bool:
    """Docker daemon reachable AND the pinned render image present. Skipped when exec_mode=local.
    `critical=False` records a missing daemon as a warning and lets the run continue."""
    if settings.exec_mode == "local":
        rep.add("exec mode = local (no docker preflight)", True, critical=False)
        return True
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, encoding="utf-8",
                              errors="replace", timeout=30)
        if info.returncode != 0:
            return rep.add("docker daemon reachable", False, critical=critical,
                           detail="`docker info` failed — is Docker Desktop running?") or not critical
        rep.add("docker daemon reachable", True, critical=critical)
    except (OSError, subprocess.SubprocessError) as e:
        return rep.add("docker daemon reachable", False, critical=critical,
                       detail=f"{type(e).__name__}: {e}") or not critical
    img = subprocess.run(["docker", "image", "inspect", settings.render_image],
                         capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    return rep.add(f"render image {settings.render_image} present", img.returncode == 0,
                   critical=critical,
                   detail="" if img.returncode == 0 else "run `python -m scripts.setup_env`") or not critical


def preflight(rep: Report, *, renderer: str = "legacy") -> bool:
    print("-> preflight")
    ok = True
    key = bool(settings.llm_api_key.strip())
    ok &= rep.add("LLM API key configured", key, critical=True,
                  detail="" if key else "set LATTICE_LLM_API_KEY in .env")
    # browser_v2 renders in Chrome; only its Manim-drawn array scenes need the render container
    ok &= _docker_ok(rep, critical=renderer == "legacy")
    try:
        from narration import tts  # noqa: F401
        rep.add(f"TTS engine importable ({settings.tts_engine})", True, critical=False)
    except Exception as e:  # noqa: BLE001
        rep.add(f"TTS engine importable ({settings.tts_engine})", False, critical=False,
                detail=f"{type(e).__name__}: {e} (build ships silent if TTS fails)")
    return ok


# --- output grading (judge the RENDERED artifacts, not the code) -----------------------------
def _duration(work_dir: Path, mp4: Path, *, host: bool = False) -> float:
    if host:    # browser_v2 clips are made on the host, so they can be probed without the container
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(mp4)], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=60)
        try:
            return float((probe.stdout or "0").strip())
        except ValueError:
            return 0.0
    try:
        rel = mp4.resolve().relative_to(work_dir.resolve()).as_posix()
    except ValueError:
        rel = mp4.name
    return decoupled._probe_duration(work_dir, rel)


def _has_meta_leak(text: str) -> str | None:
    """Return the offending phrase if narration leaked chat/meta framing (the exact defect the
    decoupled cleaner exists to kill), else None. Reuses the pipeline's own marker list so the
    test and the fix can't drift apart."""
    low = (text or "").lower()
    for marker in decoupled._NARRATION_META:
        if marker in low:
            return marker
    # a line that talks ABOUT the narration/animation rather than being narration
    if re.search(r"\b(here('s| is) the narration|the narration (flows|is|stays))\b", low):
        return "meta sentence about the narration"
    return None


def grade(rep: Report, project, workspace: Path, final: Path | None, *,
          renderer: str = "legacy") -> None:
    print("-> grading output")
    host = renderer == "browser_v2"
    # CRITICAL — did the pipeline actually produce a playable film?
    rep.add("project.json persisted", (workspace / "project.json").exists(), critical=True)
    fsize = final.stat().st_size if (final and final.exists()) else 0
    rep.add("final.mp4 exists & non-trivial (>10 KB)", fsize > 10_240, critical=True,
            detail=f"{fsize/1024:.0f} KB" if final else "no final.mp4")
    n = len(project.scenes)
    rendered = [s for s in project.scenes if s.mp4 and Path(s.mp4).exists()]
    rep.add(f"every scene rendered ({len(rendered)}/{n})", len(rendered) == n and n > 0, critical=True,
            detail="" if len(rendered) == n else "at least one scene failed all retries")

    final_dur = _duration(workspace, final, host=host) if (final and final.exists()) else 0.0
    rep.add("final video has real duration (>0s)", final_dur > 0, critical=True,
            detail=f"{final_dur:.1f}s")

    # WARN — quality signals a human reviewer would eyeball
    scene_durs = []
    for s in rendered:
        d = _duration(Path(s.mp4).parent, Path(s.mp4), host=host)
        scene_durs.append(d)
    bad_dur = [i for i, d in enumerate(scene_durs) if d < 2.0]
    rep.add("each scene clip ≥ 2s", not bad_dur, critical=False,
            detail="" if not bad_dur else f"scenes {bad_dur} suspiciously short")

    if scene_durs and final_dur > 0:
        total = sum(scene_durs)
        drift = abs(final_dur - total) / total
        rep.add("stitched length ≈ sum of scenes (±15%)", drift <= 0.15, critical=False,
                detail=f"final {final_dur:.1f}s vs Σscenes {total:.1f}s ({drift*100:.0f}% off)")

    empty = [s.index for s in rendered if not (s.script and any(t.strip() for t in s.script))]
    rep.add("every scene has narration text", not empty, critical=False,
            detail="" if not empty else f"scenes {empty} silent/blank narration")

    leaks = []
    for s in rendered:
        txt = " ".join(s.script or [])
        hit = _has_meta_leak(txt)
        if hit:
            leaks.append(f"scene {s.index}: {hit!r}")
    rep.add("no chat/meta-commentary leaked into narration", not leaks, critical=False,
            detail="" if not leaks else "; ".join(leaks))

    if project.target_seconds and rendered:
        budget = max(decoupled._MIN_NARRATION_WORDS,
                     round((project.target_seconds / n) * decoupled._WORDS_PER_SECOND))
        ceiling = int(budget * 1.6)
        over = [f"scene {s.index}: {len(' '.join(s.script or '').split())}w"
                for s in rendered if len(" ".join(s.script or "").split()) > ceiling]
        rep.add(f"narration within word budget (≤{ceiling}w/scene)", not over, critical=False,
                detail="" if not over else "; ".join(over))

    if host:    # browser_v2 has no generated theme; what it owes the user is the requested length
        if project.target_seconds and final_dur > 0:
            off = abs(final_dur - project.target_seconds) / project.target_seconds
            rep.add("video length within 20% of the requested duration", off <= 0.20, critical=False,
                    detail=f"{final_dur:.1f}s for a {project.target_seconds}s request ({off*100:.0f}% off)")
        return
    rep.add("theme/style applied", project.style is not None, critical=False,
            detail="" if project.style else "build proceeded without a StyleSpec")


# --- report file -----------------------------------------------------------------------------
def write_report(rep: Report, out_dir: Path, *, final: Path | None, usage: dict, n_scenes: int) -> Path:
    lines = [f"# Self-test report — {rep.topic}", ""]
    lines.append(f"**Result:** {'✅ PASS' if rep.passed else '❌ FAIL'} "
                 f"({len(rep.critical_failed)} critical failure(s), {len(rep.warnings)} warning(s))")
    lines.append(f"**Scenes:** {n_scenes}   **Final:** {final or '(none)'}")
    lines.append(f"**Cost:** ${usage.get('cost_usd', 0):.4f} over {usage.get('calls', 0)} LLM call(s) "
                 f"({usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} tok)")
    lines += ["", "| result | check | detail |", "|---|---|---|"]
    for c in rep.checks:
        mark = "OK" if c.ok else ("**FAIL**" if c.critical else "WARN")
        lines.append(f"| {mark} | {c.name} | {c.detail} |")
    lines += ["", "<details><summary>Build log</summary>", "", "```"]
    lines += rep.logs[-400:]
    lines += ["```", "</details>", ""]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- driver ----------------------------------------------------------------------------------
def run(topic: str, *, max_scenes: int, quality: str, target_seconds: int | None,
        keep_workspace: bool, renderer: str = "legacy") -> int:
    from web.engine import Engine  # imported here so preflight failures don't need the web stack

    rep = Report(topic=topic)
    out_dir = settings.out_dir / "selftest" / _slug(topic)
    workspace_root = out_dir / "web"
    if not keep_workspace and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Lattice self-test ===\n   topic:   {topic!r}\n   model:   {settings.llm_model}\n"
          f"   renderer: {renderer}\n"
          f"   quality: {quality}   max-scenes: {max_scenes}"
          f"   target: {target_seconds or '(planner default)'}s\n")

    if not preflight(rep, renderer=renderer):
        write_report(rep, out_dir, final=None, usage=usage_snapshot(), n_scenes=0)
        _summarize(rep, out_dir, final=None)
        return 2

    def log(msg: str) -> None:
        s = str(msg)
        rep.logs.append(s)
        print(f"      {s}")

    reset_usage()
    project = final = None
    try:
        engine = Engine(root=workspace_root)
        print("\n-> plan (outline + theme) — the user's Step 2 gate, auto-approved")
        plan_kwargs = {"renderer": renderer} if renderer != "legacy" else {}
        pid, _draft = engine.plan(topic, max_scenes=max_scenes, target_seconds=target_seconds,
                                  log=log, **plan_kwargs)
        # auto-approve exactly what a user clicking "looks good" does: keep all planned scenes in order,
        # but honor --max-scenes as the cap the outline gate would apply.
        keep = list(range(min(max_scenes, len(_draft.scenes)))) if max_scenes else None
        print(f"\n-> build (render {len(_draft.scenes)} scene(s) -> stitch) — no human in the loop")
        project = engine.build(pid, keep=keep, quality=quality, log=log,
                               on_scene=lambda i, st: print(f"      · scene {i}: {st}"))
        final = engine.final_mp4(pid)
    except Exception as e:  # noqa: BLE001 — a crash IS a test result, not an excuse to abort silently
        rep.add("build ran without raising", False, critical=True, detail=f"{type(e).__name__}: {e}")
        rep.logs.append(traceback.format_exc())

    if project is not None:
        grade(rep, project, engine.workspace(pid), final, renderer=renderer)

    usage = usage_snapshot()
    write_report(rep, out_dir, final=final, usage=usage,
                 n_scenes=len(project.scenes) if project else 0)
    return _summarize(rep, out_dir, final=final, usage=usage)


def _summarize(rep: Report, out_dir: Path, *, final: Path | None, usage: dict | None = None) -> int:
    print("\n=== summary ===")
    if usage:
        print(f"   cost: ${usage.get('cost_usd', 0):.4f} · {usage.get('calls', 0)} calls")
    if final:
        print(f"   video: {final}")
    for c in rep.critical_failed:
        print(f"   FAIL  {c.name}: {c.detail}")
    for c in rep.warnings:
        print(f"   warn  {c.name}: {c.detail}")
    print(f"   report: {out_dir / 'report.md'}")
    verdict = "PASS ✅" if rep.passed else "FAIL ❌"
    print(f"\n   {verdict} — {len(rep.critical_failed)} critical failure(s), {len(rep.warnings)} warning(s)")
    return 0 if rep.passed else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Autonomous end-to-end self-test of the video pipeline.")
    ap.add_argument("topic", nargs="?", default="How binary search finds a number in a sorted list",
                    help="topic to generate (default: a simple, reliable one)")
    ap.add_argument("--max-scenes", type=int, default=2, help="cap scenes (keeps a smoke run cheap)")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--target-seconds", type=int, default=None, help="duration budget (paces narration)")
    ap.add_argument("--keep-workspace", action="store_true",
                    help="reuse the prior workspace instead of wiping it (cache/inspect)")
    ap.add_argument("--renderer", choices=["legacy", "browser_v2"], default="legacy",
                    help="browser_v2 = the learning-video path the web Teach tab uses")
    args = ap.parse_args(argv)
    return run(args.topic, max_scenes=args.max_scenes, quality=args.quality,
               target_seconds=args.target_seconds, keep_workspace=args.keep_workspace,
               renderer=args.renderer)


if __name__ == "__main__":
    sys.exit(main())
