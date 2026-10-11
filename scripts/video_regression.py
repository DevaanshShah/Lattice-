"""Offline regression check for the learning-video path: re-render fixed plans, compare with the approved run.

    python -m scripts.video_regression [--case NAME ...] [--set-baseline | --accept-last]
                                       [--voice] [--fps N]

No LLM calls. Every folder in tests/fixtures/video_golden/ holds a saved lesson_plan.json and
browser_visual_plan.json. Each one is validated, built through the same `browser_video.build` the
web app uses, and graded on the RENDERED output:

  valid       the plan still passes the validator
  built       the build finished (layout QA and the per-frame clipping check are part of the build)
  fallbacks   how many times the compact layout had to rescue a frame — may not rise above the baseline
  duration    version-2 videos are exactly as long as their narration
  frames      every frame is compared (SSIM) with the last approved video for that case

Narration is silent audio of a fixed length per beat, so two runs of the same code give the same
frames; `--voice` uses the real TTS engine instead (frames then shift with the voice timing).
A contact sheet per case is written next to the report so a person can judge the look at a glance.
A case with a Manim scene is reported as SKIPPED, not failed, when Docker or the render image is
missing on this machine.

Exit code: 0 everything passed and matches the baseline · 1 a case failed · 2 nothing failed but
frames changed or no baseline exists (look at the contact sheets, then approve with --accept-last).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from core.config import settings
from core.console import enable_utf8

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "video_golden"
WORDS_PER_SECOND = 2.3      # the narration pace composition.decoupled budgets for
MIN_BEAT_SECONDS = 2.0
# Two runs of unchanged code give identical frames (SSIM exactly 1.0), and a small label changing
# opacity only moves a whole-frame score to about 0.999. So anything short of identical is a change.
SSIM_SAME = 0.9999


@dataclass
class CaseResult:
    name: str
    status: str = "pass"            # pass | fail | skipped
    detail: str = ""
    fallbacks: int = 0
    duration: float = 0.0
    expected_duration: float | None = None
    frames_compared: int = 0
    min_ssim: float | None = None   # None = no baseline to compare with
    worst_time: float | None = None
    changed: bool | None = None     # None = no baseline


def cases(root: Path = GOLDEN) -> dict[str, Path]:
    return {folder.name: folder for folder in sorted(root.iterdir())
            if (folder / "lesson_plan.json").exists() and (folder / "browser_visual_plan.json").exists()}


def silent_seconds(text: str) -> float:
    """Length of the stand-in narration for one beat: its word count at the budgeted pace."""
    return max(MIN_BEAT_SECONDS, round(len(text.split()) / WORDS_PER_SECOND, 1))


def parse_ssim_stats(text: str) -> list[float]:
    """Per-frame overall SSIM from FFmpeg's `ssim=stats_file=...` output."""
    return [float(match) for match in re.findall(r"\bAll:([0-9.]+)", text)]


def exit_code(results: list[CaseResult]) -> int:
    if any(result.status == "fail" for result in results):
        return 1
    ran = [result for result in results if result.status == "pass"]
    if any(result.changed is None or result.changed for result in ran):
        return 2
    return 0


def _ffmpeg(*args: str, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-y", "-hide_banner", *args], cwd=cwd, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _duration(mp4: Path) -> float:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    return float(probe.stdout.strip() or 0)


def manim_unavailable() -> str:
    """Why a Manim scene cannot render on this machine right now ('' when it can)."""
    if settings.exec_mode == "local":
        return ""
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode:
            return "Docker is not running"
        if subprocess.run(["docker", "image", "inspect", settings.render_image],
                          capture_output=True, timeout=30).returncode:
            return f"render image {settings.render_image} is missing (python -m scripts.setup_env)"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Docker is not usable ({type(exc).__name__})"
    return ""


def contact_sheet(mp4: Path, out_png: Path, duration: float) -> None:
    count = min(20, max(4, int(duration * 2)))
    columns = 5 if count > 4 else 4
    rows = math.ceil(count / columns)
    _ffmpeg("-i", str(mp4), "-vf",
            f"fps={count}/{max(duration, 0.1):.3f},scale=448:-1,tile={columns}x{rows}",
            "-frames:v", "1", str(out_png))


def compare_frames(mp4: Path, baseline: Path, work: Path) -> tuple[int, float, float]:
    """(frames compared, lowest SSIM, time in seconds of the worst frame) against the approved video."""
    shutil.copyfile(mp4, work / "_new.mp4")
    shutil.copyfile(baseline, work / "_base.mp4")
    try:
        # relative names + cwd: a Windows drive colon inside a filter argument would need escaping
        result = _ffmpeg("-i", "_new.mp4", "-i", "_base.mp4", "-lavfi",
                         "[0:v][1:v]ssim=stats_file=_ssim.txt", "-f", "null", "-", cwd=work)
        stats = work / "_ssim.txt"
        if result.returncode or not stats.exists():
            raise RuntimeError(f"frame comparison failed: {result.stderr[-300:]}")
        values = parse_ssim_stats(stats.read_text(encoding="utf-8"))
    finally:
        for name in ("_new.mp4", "_base.mp4", "_ssim.txt"):
            (work / name).unlink(missing_ok=True)
    if not values:
        raise RuntimeError("frame comparison produced no frames")
    worst = min(range(len(values)), key=values.__getitem__)
    return len(values), values[worst], worst * _duration(mp4) / len(values)


def run_case(name: str, folder: Path, out_dir: Path, *, fps: int = 30, voice: bool = False,
             baseline_dir: Path | None = None, baseline_meta: dict | None = None) -> CaseResult:
    from composition import browser_video
    from core.run_report import RunReport
    from core.schemas.browser_visual_plan import BrowserVisualPlan
    from core.schemas.lesson_plan import LessonPlan
    from narration.tts import Clip
    from planner.product_recipe import load_recipes
    from verification.visual_plan_validation import validate

    result = CaseResult(name)
    work = out_dir / name
    work.mkdir(parents=True, exist_ok=True)
    lesson = LessonPlan.model_validate_json((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    plan = BrowserVisualPlan.model_validate_json(
        (folder / "browser_visual_plan.json").read_text(encoding="utf-8"))
    skill = load_recipes()[lesson.skill_id]
    blocked = manim_unavailable() if any(scene.render_mode == "manim" for scene in plan.scenes) else ""
    if blocked:     # an environment gap, not a regression in the code under test
        result.status, result.detail = "skipped", f"Manim scene not rendered: {blocked}"
        return result
    try:
        validate(lesson, plan, skill)
    except Exception as exc:  # noqa: BLE001 — an invalid saved plan is a result, not a crash
        result.status, result.detail = "fail", f"plan no longer validates: {exc}"
        return result

    spoken: list[float] = []

    def silent(text: str, *, out_dir, engine=None, **_ignored) -> Clip:
        seconds = silent_seconds(text)
        path = Path(out_dir) / f"silence_{round(seconds * 1000)}.wav"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            _ffmpeg("-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", f"{seconds:.3f}", str(path))
        spoken.append(seconds)
        return Clip(text, path, seconds)

    real = browser_video.synthesize

    def measured(text: str, **kwargs) -> Clip:
        clip = real(text, **kwargs)
        spoken.append(clip.duration)
        return clip

    report = RunReport(work, topic=lesson.topic, recipe=skill.id)
    browser_video.synthesize = measured if voice else silent
    try:
        built = browser_video.build(lesson, plan, skill, out_dir=work, fps=fps, report=report)
        report.complete(artifact=built.mp4)
    except Exception as exc:  # noqa: BLE001 — a build failure is exactly what this harness reports
        result.status, result.detail = "fail", f"{type(exc).__name__}: {exc}"[:400]
        (work / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return result
    finally:
        browser_video.synthesize = real

    result.fallbacks = sum(event["status"] == "retry" for event in report.data["events"])
    result.duration = _duration(built.mp4)
    if plan.schema_version == 2:    # version 1 crossfades between clips, so its length is not a plain sum
        pauses = sum(beat.pause_after for scene in plan.scenes for beat in scene.beats)
        result.expected_duration = round(sum(spoken) + pauses, 3)
        if abs(result.duration - result.expected_duration) > 0.2 + 0.1 * len(spoken):
            result.status = "fail"
            result.detail = (f"video is {result.duration:.2f}s but its narration is "
                             f"{result.expected_duration:.2f}s")
    contact_sheet(built.mp4, out_dir / f"{name}.png", result.duration)

    allowed = (baseline_meta or {}).get(name, {}).get("fallbacks")
    if allowed is not None and result.fallbacks > allowed and result.status == "pass":
        result.status = "fail"
        result.detail = f"compact-layout fallback used {result.fallbacks}x (approved run: {allowed}x)"
    approved = baseline_dir / f"{name}.mp4" if baseline_dir else None
    if approved and approved.exists():
        result.frames_compared, result.min_ssim, result.worst_time = compare_frames(
            built.mp4, approved, work)
        result.changed = (result.min_ssim < SSIM_SAME
                          or abs(result.duration - _duration(approved)) > 1.5 / fps)
    return result


def table(results: list[CaseResult]) -> str:
    rows = ["| case | result | fallbacks | length | frames vs approved | note |", "|---|---|---|---|---|---|"]
    for r in results:
        if r.status != "pass":
            look = "-"
        elif r.changed is None:
            look = "no baseline"
        elif r.changed:
            look = f"CHANGED (lowest SSIM {r.min_ssim:.4f} at {r.worst_time:.1f}s)"
        else:
            look = f"same ({r.frames_compared} frames, lowest SSIM {r.min_ssim:.4f})"
        length = f"{r.duration:.1f}s" if r.duration else "-"
        note = " ".join(r.detail.split()).replace("|", "/")    # one table cell, whatever the error text
        rows.append(f"| {r.name} | {r.status.upper()} | {r.fallbacks} | {length} | {look} | {note} |")
    return "\n".join(rows)


def store_baseline(results: list[CaseResult], run_dir: Path, baseline_dir: Path) -> int:
    """Make the passing videos of a run the approved look. Returns how many cases were stored."""
    baseline_dir.mkdir(parents=True, exist_ok=True)
    meta_path = baseline_dir / "baseline.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    stored = 0
    for result in results:
        video = run_dir / result.name / "browser-video.mp4"
        if result.status != "pass" or not video.exists():
            continue
        shutil.copyfile(video, baseline_dir / f"{result.name}.mp4")
        shutil.copyfile(run_dir / f"{result.name}.png", baseline_dir / f"{result.name}.png")
        meta[result.name] = {"fallbacks": result.fallbacks, "duration": result.duration}
        stored += 1
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return stored


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Re-render the fixed learning-video plans and check for regressions.")
    ap.add_argument("--case", action="append", help="run only this case (repeatable)")
    ap.add_argument("--set-baseline", action="store_true",
                    help="store this run's passing videos as the approved look")
    ap.add_argument("--accept-last", action="store_true",
                    help="approve the previous run as the baseline without rendering again")
    ap.add_argument("--voice", action="store_true", help="use the real TTS engine instead of silence")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args(argv)

    if args.accept_last:
        run_dir = settings.out_dir / "video_regression" / "last"
        last = run_dir / "last.json"
        if not last.exists():
            ap.error("no previous run to accept: run the regression first")
        previous = [CaseResult(**row) for row in json.loads(last.read_text(encoding="utf-8"))]
        stored = store_baseline(previous, run_dir, run_dir.parent / "baseline")
        print(f"baseline stored for {stored} case(s) from the previous run: {run_dir.parent / 'baseline'}")
        return 0

    available = cases()
    unknown = sorted(set(args.case or []) - set(available))
    if unknown:
        ap.error(f"unknown case(s): {unknown} (known: {sorted(available)})")
    selected = {name: folder for name, folder in available.items()
                if not args.case or name in args.case}
    root = settings.out_dir / "video_regression"
    run_dir, baseline_dir = root / "last", root / "baseline"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = baseline_dir / "baseline.json"
    baseline_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    results = []
    for name, folder in selected.items():
        print(f"-> {name}", flush=True)
        result = run_case(name, folder, run_dir, fps=args.fps, voice=args.voice,
                          baseline_dir=None if args.voice else baseline_dir,
                          baseline_meta=baseline_meta)
        print(f"   {result.status.upper()} {result.detail}".rstrip(), flush=True)
        results.append(result)

    report = table(results)
    (run_dir / "report.md").write_text(
        "# Learning-video regression\n\n" + report + "\n\nContact sheets: one `<case>.png` in this folder.\n",
        encoding="utf-8")
    (run_dir / "last.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2), encoding="utf-8")
    print("\n" + report + f"\n\nreport and contact sheets: {run_dir}")

    if args.set_baseline:
        if args.voice:
            ap.error("--set-baseline needs the repeatable silent narration; run it without --voice")
        stored = store_baseline(results, run_dir, baseline_dir)
        print(f"baseline stored for {stored} case(s): {baseline_dir}")
        return 1 if any(result.status == "fail" for result in results) else 0
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
