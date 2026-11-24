"""Plan, compile and render one map lesson in the whiteboard style (a proof of the look).

    python -m scripts.whiteboard_demo "How to fix 'I cannot stream my show'" out/whiteboard_demo
"""
from __future__ import annotations

import sys
from pathlib import Path

from composition import browser_video
from planner import browser_visual_plan, lesson_plan
from planner.product_recipe import load_recipes


def main(topic: str, out: str, seconds: int = 150, recipe: str = "workflow_explainer") -> None:
    skill = load_recipes()[recipe]
    lesson = lesson_plan.generate(topic, skill, schema_version=2, target_seconds=seconds, style="whiteboard",
                                  on_reject=lambda why: print("  repaired:", why[:140]))
    plan = browser_visual_plan.generate(lesson, skill, schema_version=2)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "lesson_plan.json").write_text(lesson.model_dump_json(indent=1), encoding="utf-8")
    (folder / "browser_visual_plan.json").write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    result = browser_video.build(lesson, plan, skill, out_dir=folder, log=lambda *_: None)
    print("video:", result.mp4)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:4]))
