"""T-7 — run the eval battery through the verify pipeline, print a score table, flag regressions.

    python -m scripts.run_eval [--quality preview|final] [--limit N] [--set-baseline]

LIVE (needs the LLM key + Docker). Saves out/eval/last.json and compares against
out/eval/baseline.json; `--set-baseline` saves the current run as the baseline.
"""
from __future__ import annotations

import sys

from core import llm
from core.config import settings
from core.console import enable_utf8
from eval.battery import BATTERY
from eval.score import BatteryReport, PromptResult, compare


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Run the eval battery and check for regressions.")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N prompts")
    ap.add_argument("--set-baseline", action="store_true", help="save this run as the baseline")
    ap.add_argument("--structural", action="store_true",
                    help="generate against the LatticeScene grid scaffold (A/B vs the free-hand baseline)")
    ap.add_argument("--vision", action="store_true",
                    help="include the paid vision-critic loop (slow). Default OFF: measure compile/"
                         "first-try/off-frame via compile-repair + free lint only (~3-5x faster).")
    args = ap.parse_args(argv)

    if not args.vision:
        settings.vision_confirm = False     # skip the critic re-render loop — the eval measures, not polishes
        print("(vision critic OFF — fast measurement; pass --vision for the full pipeline)")
    if args.structural:
        settings.structural_layout = True   # read by generation.codegen at call time
        print("(structural layout ON — LatticeScene grid scaffold)")

    prompts = BATTERY[: args.limit] if args.limit else BATTERY
    out = settings.out_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)

    from verification.run import run_pipeline

    def _issue_count(crit, *types) -> int:
        return sum(1 for iss in (crit.issues if crit else []) if iss.type in types)

    step = lambda m: print("      " + str(m))   # live sub-step progress (so it never looks hung)

    results: list[PromptResult] = []
    for i, p in enumerate(prompts, 1):
        print(f"[{i}/{len(prompts)}] {p}")
        llm.reset_usage()   # measure tokens/cost for THIS prompt (all calls: spec+codegen+repair+critic)
        try:
            pr = run_pipeline(p, quality=args.quality, out_dir=out / f"case{i}", log=step)
            r = pr.result
            u = llm.usage_snapshot()
            if r is None:
                results.append(PromptResult(p, False, False, -1, 0,
                    prompt_tokens=u["prompt_tokens"], completion_tokens=u["completion_tokens"],
                    cost_usd=u["cost_usd"]))
            else:
                crit, rep = r.critique, r.repair
                results.append(PromptResult(
                    p, r.compiled, r.passed,
                    crit.effective_score() if crit else -1,
                    crit.n_issues if crit else 0,
                    first_try_compiled=bool(rep and rep.attempts and rep.attempts[0].ok),
                    compile_attempts=(rep.n_attempts if rep else 0),
                    off_frame_issues=_issue_count(crit, "off_frame"),
                    overlap_issues=_issue_count(crit, "overlap", "text_overlap"),
                    prompt_tokens=u["prompt_tokens"], completion_tokens=u["completion_tokens"],
                    cost_usd=u["cost_usd"],
                ))
            last = results[-1]
            print(f"      compiled={last.compiled} first-try={last.first_try_compiled} "
                  f"ok={last.ok} score={last.score} off-frame={last.off_frame_issues} "
                  f"${last.cost_usd:.4f}")
        except Exception as e:  # one bad prompt must not abort the battery
            print(f"      error: {e}")
            u = llm.usage_snapshot()
            results.append(PromptResult(p, False, False, -1, 0,
                prompt_tokens=u["prompt_tokens"], completion_tokens=u["completion_tokens"],
                cost_usd=u["cost_usd"]))

    report = BatteryReport(results)
    print("\n" + report.table())
    report.save(out / "last.json")

    baseline = out / "baseline.json"
    if args.set_baseline:
        report.save(baseline)
        print(f"\n[OK] baseline saved ({report.n} prompts).")
        return 0
    if baseline.exists():
        reg = compare(report, BatteryReport.load(baseline))
        print("\n=== vs baseline ===")
        if reg.is_regression:
            print("[REGRESSION]")
            for x in reg.reasons:
                print("  - " + x)
            return 1
        print("[OK] no regression vs baseline.")
    else:
        print("\n(no baseline yet — run with --set-baseline to save one)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
