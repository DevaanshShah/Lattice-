"""Render a saved lesson + visual plan into a narrated video. Usage: build_planned.py <plan dir> <out dir>"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from composition import browser_video
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from planner.product_recipe import load_recipes

source, out = Path(sys.argv[1]), Path(sys.argv[2])
lesson = LessonPlan.model_validate_json((source / "lesson_plan.json").read_text(encoding="utf-8"))
plan = BrowserVisualPlan.model_validate_json(
    (source / "browser_visual_plan.json").read_text(encoding="utf-8"))
result = browser_video.build(lesson, plan, load_recipes()[lesson.skill_id], out_dir=out, log=print)
print("VIDEO", result.mp4)
