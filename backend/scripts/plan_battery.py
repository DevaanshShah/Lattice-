"""Planning battery for the learning-video path: plan fixed topics, score them, flag regressions.

    python -m scripts.plan_battery [--model M] [--limit N] [--repeat N] [--max-calls N] [--set-baseline]

LIVE (needs the LLM key; no Docker, nothing is rendered). For each topic it runs the same two steps
the web app runs before a build — `lesson_plan.generate`, then `browser_visual_plan.generate` — and
records whether the topic planned, how many scenes passed the validator on the first try, the
validator's rejection reasons, and the tokens and cost. Results go to out/plan_battery/<model>/last.json
and are compared with baseline.json there; `--set-baseline` stores the current run as the baseline.

`--max-calls` is a hard cap on model calls for the whole run (default 40): when it is reached the
run stops and reports what it has. Exit code: 0 no regression (or no baseline) · 1 regression.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from core.config import settings
from core.console import enable_utf8
from eval.plan_score import PlanBatteryReport, SceneResult, TopicResult, compare

# One topic per visual family the planner has to handle. The third is a stand-in until the owner
# picks the third acceptance topic (docs/learning-video-hardening-plan-2026-10-09.md, question 1).
TOPICS = [
    "How binary search finds 23 in the sorted list [2, 5, 8, 12, 16, 23, 38], compared with "
    "checking every item in order.",
    "Explain an agent harness to a beginner using one order-status example: structured tool "
    "arguments for order 42 are validated and sent to lookup_order, the tool returns status "
    "shipped and tracking AB42 and the answer uses that data, then a missing order_id is rejected "
    "before execution and one corrected call succeeds.",
    "How a sales funnel narrows from 1,000 website visitors to 50 paying customers, stage by stage.",
    # a system topic: the target style is one map built piece by piece, then a problem and its fix
    "How a food delivery order travels from the customer's phone through a gateway, an order "
    "service, a cache and a database, and what happens when the single database gets overloaded.",
]
REPAIR_PREFIX = "This visual scene is invalid: "
LESSON_REPAIR_PREFIX = "That was invalid ("
TARGET_SECONDS = 60     # the web app's middle duration pick


class BudgetExceeded(RuntimeError):
    pass


class CappedClient:
    """Counts model calls, refuses to go past the cap, and keeps the validator's rejection reasons
    (the planner sends each one back to the model as the next user message)."""

    def __init__(self, inner, max_calls: int) -> None:
        self.inner, self.max_calls = inner, max_calls
        self.calls = 0
        self.rejections: list[str] = []
        self.model = getattr(inner, "model", "")

    def chat(self, messages: list[dict], **kwargs) -> str:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"call cap reached ({self.max_calls})")
        last = messages[-1]["content"] if messages else ""
        if len(messages) > 2 and last.startswith(REPAIR_PREFIX):
            self.rejections.append(last[len(REPAIR_PREFIX):].split(". Repair only this scene")[0][:300])
        elif len(messages) > 2 and last.startswith(LESSON_REPAIR_PREFIX):
            self.rejections.append("lesson: " + last[len(LESSON_REPAIR_PREFIX):][:300])
        self.calls += 1
        return self.inner.chat(messages, **kwargs)


def _slug(text: str, n: int = 40) -> str:
    return (re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower())[:n] or "topic"


def plan_topic(topic: str, client: CappedClient, out_dir: Path) -> TopicResult:
    from core.llm import reset_usage, usage_snapshot
    from planner import browser_visual_plan, lesson_plan
    from planner.lesson_shared import story_shape
    from planner.product_recipe import pick_recipe

    result = TopicResult(topic)
    out_dir.mkdir(parents=True, exist_ok=True)
    skill = pick_recipe(topic, "auto")
    reset_usage()
    start_calls, start_rejections = client.calls, len(client.rejections)
    lesson = None
    try:
        lesson = lesson_plan.generate(topic, skill, client=client, schema_version=2,
                                      target_seconds=TARGET_SECONDS,
                                      diagnostic_dir=out_dir / "lesson_attempts")
        result.lesson_ok = True
        result.lesson_tries = client.calls - start_calls
        result.lesson_words = sum(len(beat.spoken_text.split())
                                  for scene in lesson.scenes for beat in scene.beats)
        (out_dir / "lesson_plan.json").write_text(lesson.model_dump_json(indent=2), encoding="utf-8")
        result.shape = story_shape(lesson)
        attempts = out_dir / "visual_attempts"
        try:
            plan = browser_visual_plan.generate(lesson, skill, client=client, schema_version=2,
                                                diagnostic_dir=attempts)
            result.planned = True
            (out_dir / "browser_visual_plan.json").write_text(
                plan.model_dump_json(indent=2), encoding="utf-8")
        finally:    # scenes that were tried are scored even when a later one stops the plan
            for index, scene in enumerate(lesson.scenes):
                tries = len(list(attempts.glob(f"scene_{index:02d}_attempt_*.txt")))
                if tries:
                    result.scenes.append(SceneResult(
                        scene.id, (attempts / f"scene_{index:02d}_accepted.json").exists(), tries))
    except BudgetExceeded:
        result.error = "stopped: call cap reached"
        raise
    except Exception as exc:  # noqa: BLE001 — a failed plan is a score, not a crash
        result.error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        usage = usage_snapshot()
        result.calls = client.calls - start_calls
        result.rejections = client.rejections[start_rejections:]
        result.prompt_tokens = usage.get("prompt_tokens", 0)
        result.completion_tokens = usage.get("completion_tokens", 0)
        result.cost_usd = usage.get("cost_usd", 0.0)
        (out_dir / "result.json").write_text(
            json.dumps({"topic": topic, "error": result.error, "rejections": result.rejections},
                       indent=2), encoding="utf-8")
    return result


def run_battery(topics: list[str], client, *, model: str, out_dir: Path, max_calls: int,
                log=print) -> PlanBatteryReport:
    capped = CappedClient(client, max_calls)
    report = PlanBatteryReport(model=model)
    for index, topic in enumerate(topics):
        log(f"-> [{index + 1}/{len(topics)}] {topic[:70]}")
        folder = out_dir / f"{index:02d}_{_slug(topic)}"
        try:
            result = plan_topic(topic, capped, folder)
        except BudgetExceeded:
            log(f"   stopped: call cap of {max_calls} reached; {len(topics) - index - 1} topic(s) not run")
            break
        report.results.append(result)
        scenes_ok = sum(scene.accepted for scene in result.scenes)
        log(f"   {'planned' if result.planned else 'NOT planned'} · scenes {scenes_ok}/{len(result.scenes)}"
            f" · {result.calls} calls · ${result.cost_usd:.4f} {result.error}".rstrip())
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Plan the fixed learning-video topics and check for regressions.")
    ap.add_argument("--model", default=settings.llm_model)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N topics")
    ap.add_argument("--repeat", type=int, default=1, help="plan every topic this many times")
    ap.add_argument("--max-calls", type=int, default=40, help="hard cap on model calls for the run")
    ap.add_argument("--set-baseline", action="store_true")
    args = ap.parse_args(argv)
    if not settings.llm_api_key.strip():
        ap.error("no LLM key configured: set LATTICE_LLM_API_KEY in .env")

    from core.llm import LLMClient

    topics = (TOPICS[:args.limit] if args.limit else TOPICS) * max(1, args.repeat)
    root = settings.out_dir / "plan_battery" / _slug(args.model)
    print(f"=== planning battery ===\n   model: {args.model}\n   topics: {len(topics)}"
          f"   call cap: {args.max_calls}\n")
    report = run_battery(topics, LLMClient(model=args.model), model=args.model,
                         out_dir=root / "last", max_calls=args.max_calls)
    root.mkdir(parents=True, exist_ok=True)
    (root / "last.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print("\n" + report.table())

    baseline_path = root / "baseline.json"
    if args.set_baseline:
        baseline_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nbaseline stored: {baseline_path}")
        return 0
    if not baseline_path.exists():
        print("\nno baseline yet for this model (run with --set-baseline to store one)")
        return 0
    reasons = compare(report, PlanBatteryReport.from_dict(
        json.loads(baseline_path.read_text(encoding="utf-8"))))
    if reasons:
        print("\nREGRESSION vs baseline:\n  - " + "\n  - ".join(reasons))
        return 1
    print("\nno regression vs baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
