"""M2 driver — full single-scene verify pipeline: prompt → spec → code → (compile-repair →
vision critic), with an optional best-of-N fallback.

    python -m verification.run "<prompt>" [--best-of N] [--quality preview|final]

This is the M2 end of the pipeline that M3's `generate-scene` CLI will wrap. It needs Docker
(render) and an LLM key (spec/codegen/critic), so it is a LIVE check, not a unit test.
Writes candidate work dirs under out/m2/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.config import settings
from generation import codegen
from generation import scene_spec as ss
from verification import best_of_n, vision_critic
from verification.caps import Caps
from verification.vision_critic import CritiqueResult


@dataclass
class PipelineResult:
    result: CritiqueResult | None
    out_dir: Path
    best_of: int


def run_pipeline(prompt: str, *, best_of: int = 1, quality: str = "preview",
                 out_dir: str | Path | None = None,
                 log=print) -> PipelineResult:
    out = Path(out_dir) if out_dir else settings.out_dir / "m2"
    out.mkdir(parents=True, exist_ok=True)

    log(f"-> scene spec for: {prompt!r}")
    spec = ss.generate(prompt)
    (out / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    log(f"   {len(spec.objects)} objects, {len(spec.beats)} beats — {spec.title}")

    caps = Caps(best_of_n=max(1, best_of))
    if caps.best_of_n > 1:
        log(f"-> best-of-{caps.best_of_n}: generating + verifying candidates")
        # diversity comes from the generator's own sampling across independent calls
        def generate_fn(i: int) -> str:
            return codegen.generate(spec)

        def evaluate_fn(code: str, i: int) -> CritiqueResult:
            return vision_critic.run(code, out / f"cand{i}", spec,
                                     quality=quality, caps=caps, log=log)

        best = best_of_n.run(generate_fn, evaluate_fn, n=caps.best_of_n, caps=caps, log=log)
        result = best.best.result if best.best else None
    else:
        log("-> generating code + verifying (compile-repair → vision critic)")
        code = codegen.generate(spec)
        result = vision_critic.run(code, out, spec, quality=quality, caps=caps, log=log)

    return PipelineResult(result, out, caps.best_of_n)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from core.console import enable_utf8
    enable_utf8()  # progress logs use → / — / ✓ ; keep Windows cp1252 from crashing on them

    ap = argparse.ArgumentParser(description="Verify a single scene end-to-end (M2).")
    ap.add_argument("prompt")
    ap.add_argument("--best-of", type=int, default=1)
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    args = ap.parse_args(argv)

    pr = run_pipeline(args.prompt, best_of=args.best_of, quality=args.quality)
    r = pr.result
    print("---")
    if r is None:
        print("[X] no candidate produced a result.")
        return 1
    # the two signals, reported separately and never conflated
    print(f"compiled:    {r.compiled}")
    if r.critique is not None:
        print(f"vision:      ok={r.critique.ok} score={r.critique.effective_score()} "
              f"issues={r.critique.n_issues}")
        for i in r.critique.issues:
            print(f"  - [{i.type}] {i.location}: {i.description} -> {i.suggested_fix}")
    if r.passed:
        print(f"[OK] scene passed both layers -> {r.mp4}")
        return 0
    print(f"[!] best attempt returned (did not fully pass within caps) -> {r.mp4 or r.code[:0]!r}")
    print(f"     code at: {pr.out_dir / 'scene.py'}")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
