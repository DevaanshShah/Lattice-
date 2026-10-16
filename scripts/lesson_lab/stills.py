"""Screenshot the closing state of every scene of a saved plan. Usage: still.py <plan dir> <out prefix>"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
from composition.slides import render_html
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.visual_state import closing_state
from generation.browser_scene import page_html
from verification.browser_layout import audit_html, BrowserLayoutError

plan = BrowserVisualPlan.model_validate_json((Path(sys.argv[1]) / "browser_visual_plan.json").read_text(encoding="utf-8"))
state = None
for index, scene in enumerate(plan.scenes):
    state = closing_state(scene, state)
    document = page_html(scene, title=f"Scene {index + 1}", state=state)
    try:
        audit_html(document)
        verdict = "layout ok"
    except BrowserLayoutError as exc:
        verdict = f"LAYOUT: {exc.issues}"
    render_html(document, f"{sys.argv[2]}_{index}.png")
    print(index, verdict)
