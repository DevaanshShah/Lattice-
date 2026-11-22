"""M5 driver — topic -> approved outline -> multi-scene narrated video (the demo).

    python -m scripts.generate_video "<topic>" [--yes] [--quality preview|final]
                                      [--max-scenes N] [--cap N]

The outline-approval gate prints the scenes; without --yes you can reorder/cut BEFORE any
scene renders. LIVE (needs the LLM key + Docker; TTS uses the host network). Writes out/video/.
"""
from __future__ import annotations

import sys

from composition import browser_video, video
from core.config import settings
from core.console import enable_utf8
from planner import approval, product_recipe


def _make_approver(auto: bool, max_scenes: int = 0):
    def approve(outline):
        if max_scenes and len(outline.items) > max_scenes:
            outline = approval.apply_edits(outline, keep=list(range(max_scenes)))
        print(approval.render_for_review(outline))
        if auto:
            print("(auto-approved with --yes)")
            return outline
        resp = input("\nApprove? [Enter=yes | 'keep 0 2 3'=reorder/cut | 'drop 1' | 'q'=abort]: ").strip()
        if resp.lower() in ("q", "quit", "abort"):
            raise SystemExit("aborted at the outline gate.")
        if not resp:
            return outline
        parts = resp.split()
        cmd, idxs = parts[0].lower(), [int(x) for x in parts[1:] if x.lstrip("-").isdigit()]
        if cmd == "keep":
            return approval.apply_edits(outline, keep=idxs)
        if cmd == "drop":
            return approval.apply_edits(outline, drop=idxs)
        print("(unrecognized — approving as-is)")
        return outline

    return approve


def _make_lesson_approver(auto: bool):
    def approve(lesson):
        print(f"Lesson: {lesson.learning_objective}")
        for index, scene in enumerate(lesson.scenes, 1):
            print(f"  {index}. {scene.title} — {scene.learning_goal}")
        if auto:
            print("(auto-approved with --yes)")
            return lesson
        if input("\nApprove lesson plan? [Enter=yes | q=abort]: ").strip().lower() in ("q", "quit", "abort"):
            raise SystemExit("aborted at the lesson-plan gate.")
        return lesson

    return approve


def main(argv: list[str] | None = None) -> int:
    import argparse

    enable_utf8()
    ap = argparse.ArgumentParser(description="Generate a multi-scene narrated video (M5).")
    ap.add_argument("topic")
    ap.add_argument("--yes", action="store_true", help="auto-approve the outline (non-interactive)")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--max-scenes", type=int, default=0, help="cap scenes (0 = planner default)")
    ap.add_argument("--cap", type=int, default=0, help="parallel render cap (0 = config default)")
    ap.add_argument("--renderer", choices=["legacy", "browser_v2"], default="legacy",
                    help="legacy keeps the current pipeline; browser_v2 uses lesson and visual plans")
    ap.add_argument("--semantic-visuals", action="store_true",
                    help="opt into claim-linked actions and semantic/Manim visuals with browser_v2")
    ap.add_argument("--recipe", default=None,
                    choices=["auto", *product_recipe.load_recipes()],
                    help="select teaching guidance. Omit entirely for "
                         "the generic legacy behavior; 'auto' runs the deterministic keyword picker "
                         "(falls back to workflow_explainer); or name a recipe directly.")
    args = ap.parse_args(argv)
    if args.semantic_visuals and args.renderer != "browser_v2":
        ap.error("--semantic-visuals requires --renderer browser_v2")

    out = settings.out_dir / "video"
    if args.renderer == "browser_v2":
        if args.max_scenes or args.cap:
            ap.error("--max-scenes and --cap are not supported by browser_v2 yet")
        result = browser_video.generate(
            args.topic, recipe=args.recipe or "auto", approve_fn=_make_lesson_approver(args.yes),
            out_dir=out, transition=0.45, log=print,
            **({"schema_version": 2} if args.semantic_visuals else {}),
        )
        print("---")
        print(f"[OK] final video: {result.render.mp4}")
        print(f"     lesson:      {out / 'lesson_plan.json'}")
        print(f"     visual plan: {out / 'browser_visual_plan.json'}")
        print(f"     run report:  {out / 'run_report.json'}")
        return 0

    proj = video.generate_video(
        args.topic, approve_fn=_make_approver(args.yes, args.max_scenes),
        quality=args.quality, out_dir=out, cap=(args.cap or None), log=print,
        recipe=args.recipe,
    )

    print("---")
    rendered = sum(1 for s in proj.scenes if s.mp4)
    print(f"scenes: {rendered}/{len(proj.scenes)} rendered")
    if proj.final_mp4:
        print(f"[OK] final video: {proj.final_mp4}")
        print(f"     project:     {out / 'project.json'}")
        return 0
    print("[X] no final video produced.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
