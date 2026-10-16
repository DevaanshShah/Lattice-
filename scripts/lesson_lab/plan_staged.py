"""Usage: staged.py <tag> <model> <topic>"""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from core.llm import LLMClient, reset_usage, usage_snapshot
from core.schemas.browser_visual_plan import BrowserVisualPlan
from planner import lesson_recurrence, lesson_trace
from planner.lesson_shared import story_shape
from planner.product_recipe import load_recipes
tag, model, topic = sys.argv[1:4]
skill = load_recipes()["algorithm_explainer"]
out = Path("out/domains") / tag; out.mkdir(parents=True, exist_ok=True)
class Counting(LLMClient):
    calls = 0
    def chat(self, messages, **kw):
        Counting.calls += 1
        raw = super().chat(messages, **kw)
        (out / f"call_{Counting.calls:02d}.txt").write_text(raw, encoding="utf-8")
        return raw
reset_usage()
try:
    lesson = lesson_recurrence.generate(topic, skill, client=Counting(model=model))
    plan = BrowserVisualPlan(schema_version=2, topic=topic, skill_id=skill.id, scenes=lesson_trace.plan_trace_scenes(lesson, skill))
    (out / "lesson_plan.json").write_text(lesson.model_dump_json(indent=2), encoding="utf-8")
    (out / "browser_visual_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print("PLANNED | calls", Counting.calls, "|", story_shape(lesson))
    for s in lesson.scenes:
        print(" SCENE:", s.title, "| takeaway:", s.takeaway)
        for b in s.beats: print("    ", b.move.do.ljust(6), "|", b.spoken_text[:200])
except Exception as exc:
    print("FAILED | calls", Counting.calls, "|", str(exc)[:500])
print("cost", usage_snapshot().get("cost_usd"))
