"""FR-6 / FR-7 — the vision-critic loop. The load-bearing feature: it gives the blind
generator eyes.

The generator writes positioning code without ever seeing the result, so it can't know that
two labels stacked or an object slid off-frame. Here we render the scene, sample MULTIPLE
frames across the clip (mid-animation overlaps are invisible in the last frame alone), send
them to a cheap, swappable VISION model, and get back STRUCTURED issues (type + location +
fix) — never free prose. Concrete fixes feed back into generation and we re-render, up to a
hard cap; on non-convergence we return the best-scoring attempt.

Two invariants this module upholds:
- The free compile check (`compile_repair`) runs BEFORE any vision call — a scene that won't
  render never costs a vision call.
- "compiles" and "looks right" are tracked as two distinct signals (`compiled` bool vs the
  critique `score`) and never conflated into one number.

`render_fn` / `critic_fn` / `regen_fn` are injectable so the loop is unit-testable with no
Docker/model.
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.scene_spec import SceneSpec
from core.textutil import extract_json, strip_code_fences
from prompts.loader import load
from verification import compile_repair
from verification.caps import Caps
from verification.compile_repair import RepairResult


# --- structured critic output (the "never free prose" guarantee) ---------------------------

class CritiqueIssue(BaseModel):
    # tolerant of model drift: accept the documented names or short aliases, ignore extras
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    type: str = "other"
    location: str = Field(default="", validation_alias=AliasChoices("location", "where"))
    description: str = ""
    suggested_fix: str = Field(default="", validation_alias=AliasChoices("suggested_fix", "fix"))


class CritiqueReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ok: bool = False
    score: int | None = None           # model-provided; derived if absent
    issues: list[CritiqueIssue] = Field(default_factory=list)

    @property
    def n_issues(self) -> int:
        return len(self.issues)

    def effective_score(self) -> int:
        """A numeric quality score for ranking, whether or not the model returned one.

        Falls back to: flawless if ok & no issues, else penalise per issue. Compile success
        is tracked separately (see CritiqueResult.compiled) and never folded in here.
        """
        if self.score is not None:
            return max(0, min(100, self.score))
        if self.ok and not self.issues:
            return 100
        return max(0, 100 - 20 * len(self.issues))


class CritiqueError(RuntimeError):
    pass


# --- single critic call --------------------------------------------------------------------

def _data_url(png: Path) -> str:
    b64 = base64.b64encode(Path(png).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def critique(frames: list[Path], *, intent: str = "", client: LLMClient | None = None,
             model: str | None = None) -> CritiqueReport:
    """One structured, multi-frame critique. Uses the cheap, swappable critic model.

    Robust by design: if the critic returns unparseable output we degrade to a low-score
    failing report rather than crashing the loop (graceful, never hangs).
    """
    if not frames:
        raise CritiqueError("no frames to critique (compile must succeed first)")
    client = client or get_client(model=model or settings.critic_model)

    text = ("Intended scene content:\n" + (intent or "(none given)")
            + f"\n\nCritique these {len(frames)} frames (sampled start→end) and return JSON.")
    content: list[dict] = [{"type": "text", "text": text}]
    for f in frames:
        # "detail": low -> the vision model downsamples the frame to a fixed small token budget
        # (~85 tok vs ~765 for high). Plenty for spotting overlap/off-screen; a big cut on the
        # single priciest call type in the pipeline.
        content.append({"type": "image_url",
                        "image_url": {"url": _data_url(f), "detail": settings.critic_image_detail}})

    messages = [{"role": "system", "content": load("vision-critic")},
                {"role": "user", "content": content}]
    raw = client.chat(messages, model=model or settings.critic_model)
    try:
        # extract_json raises ValueError; pydantic ValidationError is also a ValueError subclass
        return CritiqueReport.model_validate(extract_json(raw))
    except ValueError:
        # degrade, don't crash: a bad reply yields a low-score failing report so the loop
        # can try another fix and still return a best attempt — never hangs.
        return CritiqueReport(ok=False, score=0, issues=[
            CritiqueIssue(type="other", description="critic returned unparseable output")])


# --- the iterative critic→fix loop ---------------------------------------------------------

@dataclass
class CritiqueResult:
    compiled: bool                       # free, deterministic signal (NEVER conflated...
    critique: CritiqueReport | None      # ...with this paid, probabilistic one)
    code: str
    mp4: Path | None = None
    frames: list[Path] = field(default_factory=list)
    iterations: int = 0
    repair: RepairResult | None = None

    @property
    def passed(self) -> bool:
        """Surfaced to the user only if BOTH layers pass (or best-of-N fallback elsewhere)."""
        return self.compiled and self.critique is not None and self.critique.ok

    def score(self) -> int:
        return self.critique.effective_score() if self.critique else -1


def _default_issue_fixer(spec: SceneSpec | None, client: LLMClient | None) -> Callable[[str, CritiqueReport], str]:
    client = client or get_client()  # the GENERATOR model rewrites code, not the critic
    system = load("manim-conventions") + "\n\n---\n\n" + load("codegen")
    intent = f"\n\nScene spec (keep the intent):\n{spec.model_dump_json(indent=2)}" if spec else ""

    def fix(code: str, report: CritiqueReport) -> str:
        issues = "\n".join(
            f"- [{i.type}] {i.location}: {i.description} -> FIX: {i.suggested_fix}"
            for i in report.issues) or "- (no specific issues listed)"
        user = (f"The rendered scene has these visual defects found by a vision critic:\n{issues}\n\n"
                f"CURRENT CODE:\n{code}{intent}\n\n"
                "Apply the fixes (adjust positions/sizes so nothing overlaps or runs off-frame) "
                "and resend the full corrected file (code only).")
        raw = client.chat([{"role": "system", "content": system},
                           {"role": "user", "content": user}])
        return strip_code_fences(raw)

    return fix


def run(code: str, work_dir: str | Path, spec: SceneSpec | None = None, *,
        render_fn: compile_repair.RenderFn | None = None,
        critic_fn: Callable[[list[Path]], CritiqueReport] | None = None,
        compile_regen_fn: compile_repair.RegenFn | None = None,
        issue_regen_fn: Callable[[str, CritiqueReport], str] | None = None,
        caps: Caps | None = None, quality: str = "preview", frames: int | None = None,
        client: LLMClient | None = None,
        log: Callable[[str], None] | None = None) -> CritiqueResult:
    """Compile-repair → critique → fix → re-render, up to the critic cap; return best."""
    caps = caps or Caps()
    frames = settings.critic_frames if frames is None else frames  # config-driven (cost lever)
    work_dir = Path(work_dir)
    intent = ""
    if spec is not None:
        intent = f"Prompt: {spec.prompt}\nTitle: {spec.title}\nNarration: {spec.narration}"
    if critic_fn is None:
        critic_fn = lambda fr: critique(fr, intent=intent, client=client)  # noqa: E731
    if issue_regen_fn is None:
        issue_regen_fn = _default_issue_fixer(spec, client)
    say = log or (lambda _m: None)

    current = code
    best: CritiqueResult | None = None

    for it in range(1, caps.max_critic_iters + 1):
        # LAYER 1 (free): must render before we ever pay the critic.
        rep = compile_repair.repair(current, work_dir, render_fn=render_fn,
                                    regen_fn=compile_regen_fn, caps=caps,
                                    quality=quality, frames=frames, spec=spec,
                                    client=client, log=log)
        if not rep.ok:
            # never compiled -> vision is NOT called (compile gates vision)
            say(f"[critic] iter {it}: scene never compiled; skipping vision")
            return CritiqueResult(False, None, rep.code, iterations=it, repair=rep)

        # LAYER 2 (paid): structured visual critique of multiple frames.
        report = critic_fn(rep.frames)
        result = CritiqueResult(True, report, rep.code, rep.mp4, list(rep.frames), it, rep)
        say(f"[critic] iter {it}/{caps.max_critic_iters}: "
            f"score={report.effective_score()} issues={report.n_issues} ok={report.ok}")
        if best is None or result.score() > best.score():
            best = result
        if report.ok and not report.issues:
            return result  # both layers pass — done
        if it < caps.max_critic_iters:
            current = issue_regen_fn(rep.code, report)

    if best is not None:
        # report how many critic iterations actually ran (the cap), not the best attempt's index
        best.iterations = caps.max_critic_iters
    say(f"[critic] no convergence in {caps.max_critic_iters} iters; returning best "
        f"(score={best.score() if best else -1})")
    return best  # type: ignore[return-value]  # best is set after iter 1's compile success


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Render a scene file and run one structured critique.")
    ap.add_argument("scene_file")
    ap.add_argument("--json", action="store_true", help="print the critique as JSON")
    ap.add_argument("--prompt", default="", help="intended content, for intent-mismatch checks")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    path = Path(args.scene_file)
    rep = compile_repair.repair(path.read_text(encoding="utf-8"), path.resolve().parent,
                                quality=args.quality, log=print)
    if not rep.ok:
        print(f"[X] scene did not compile; no vision call made.\n{rep.error}")
        return 1
    report = critique(rep.frames, intent=args.prompt)
    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        print(f"[OK] compiled; frames={len(rep.frames)} | critic ok={report.ok} "
              f"score={report.effective_score()} issues={report.n_issues}")
        for i in report.issues:
            print(f"  - [{i.type}] {i.location}: {i.description} -> {i.suggested_fix}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
