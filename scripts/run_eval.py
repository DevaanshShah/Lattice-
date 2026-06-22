"""T-7 — run the eval battery through the verify pipeline, print a score table, flag regressions.

    python -m scripts.run_eval [--quality preview|final] [--limit N] [--set-baseline]

LIVE (needs the LLM key + Docker). Saves out/eval/last.json and compares against
out/eval/baseline.json; `--set-baseline` saves the current run as the baseline.
"""
from __future__ import annotations

import sys

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
    args = ap.parse_args(argv)

    prompts = BATTERY[: args.limit] if args.limit else BATTERY
    out = settings.out_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)

    from verification.run import run_pipeline

    results: list[PromptResult] = []
    for i, p in enumerate(prompts, 1):
        print(f"[{i}/{len(prompts)}] {p}")
        try:
            pr = run_pipeline(p, quality=args.quality, out_dir=out / f"case{i}", log=lambda _m: None)
            r = pr.result
            if r is None:
                results.append(PromptResult(p, False, False, -1, 0))
            else:
                crit = r.critique
                results.append(PromptResult(
                    p, r.compiled, r.passed,
                    crit.effective_score() if crit else -1,
                    crit.n_issues if crit else 0,
                ))
            print(f"      compiled={results[-1].compiled} ok={results[-1].ok} score={results[-1].score}")
        except Exception as e:  # one bad prompt must not abort the battery
            print(f"      error: {e}")
            results.append(PromptResult(p, False, False, -1, 0))

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
