"""Compile a validated BrowserScene into one safe HTML/SVG frame."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path

from composition.slides import render_html
from core.schemas.browser_visual_plan import BrowserScene
from core.visual_assets import asset_data_uri
from core.visual_state import VisualState
from verification.browser_layout import audit_html


_CSS = """
:root{--bg:#0d0d12;--ink:#f1efe9;--muted:#aaa9b2;--line:#343541;--panel:#171720;
--blue:#63a8e8;--purple:#c88add;--green:#5fca90;--amber:#edb34a;--cyan:#59c5d2;--red:#eb7063}
*{box-sizing:border-box}body{margin:0;width:1280px;height:720px;overflow:hidden;background:radial-gradient(circle at 50% 45%,#151722 0,#0d0d12 48%,#090a0f 100%);color:var(--ink);font-family:Segoe UI,system-ui,sans-serif}
.frame{height:100%;padding:40px 58px 34px;display:flex;flex-direction:column}.title{font:600 40px/1.1 Georgia,serif;text-align:center;margin:0 0 22px}.diagram{position:relative;flex:1;min-height:0;display:flex;align-items:center;justify-content:center}.nodes{position:relative;z-index:1;width:100%;min-height:360px;display:flex;align-items:center;justify-content:center;gap:64px}.connections{position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}.edge{stroke:#74798c;stroke-width:2.3;fill:none;opacity:.9}.edge.checks{stroke:var(--amber)}.edge.branches_to{stroke:var(--green)}.edge.transforms_to{stroke:var(--purple)}.edge-label{fill:var(--ink);font:650 13px/1 Segoe UI,sans-serif;paint-order:stroke;stroke:var(--bg);stroke-width:7px;stroke-linejoin:round}.node{flex:0 1 220px;min-width:150px;min-height:106px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,#1b1c27,#111218);padding:18px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:19px;font-weight:650;box-shadow:0 12px 38px #0006;transition:opacity .35s,transform .35s,border-color .35s,box-shadow .35s}.node.role-input,.node.role-source{border-color:#4c83b3}.node.role-operation{border-color:#986ca7}.node.role-decision{border-color:#b88d43}.node.role-output,.node.role-result,.node.role-destination{border-color:#4c966d}.node.role-metric{font-size:40px;color:var(--amber);width:min(300px,28vw)}.node.role-before{border-color:var(--red)}.node.role-after{border-color:var(--green)}
.kind-message{border-radius:24px 24px 24px 6px;background:linear-gradient(145deg,#182331,#10151d)}.kind-document{border-radius:8px;background:linear-gradient(135deg,#1b1b25 0 84%,#343646 84%)}.kind-card{border-left:5px solid var(--green);background:#151720}.kind-tool{border-radius:999px;border-color:var(--purple);background:linear-gradient(145deg,#25192b,#15101a)}.kind-gate{min-height:144px;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);border:0;border-radius:0;background:linear-gradient(145deg,#4b3a1c,#211b12);padding:34px}.kind-group{border-style:dashed;background:#12131a}.kind-metric{font-size:38px;color:var(--amber)}
.node.is-hidden{opacity:0;transform:scale(.92);pointer-events:none}.node.is-active{border-color:var(--cyan);box-shadow:0 0 44px #32b9c566;transform:translateY(-5px) scale(1.035)}
.workflow.dense .nodes{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:28px;align-content:center}.workflow.dense .node{min-width:0;width:100%;min-height:86px;padding:12px;font-size:17px}.workflow.dense .nodes:has(.role-before){grid-template-columns:repeat(7,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr))}.workflow.dense .nodes:has(.role-before) .node:nth-child(1){grid-column:2/5;grid-row:1}.workflow.dense .nodes:has(.role-before) .node:nth-child(2){grid-column:5/7;grid-row:1}.workflow.dense .nodes:has(.role-before) .node:nth-child(n+3){grid-row:2}
.architecture .nodes{display:grid;grid-template-columns:repeat(3,minmax(170px,1fr));grid-template-rows:repeat(2,150px);gap:46px}.architecture .node{justify-self:center}.architecture .kind-group{grid-column:span 2;width:86%}
.transformation .nodes{display:flex;gap:46px}.transformation .nodes:before{content:"CHECK + TRANSFORM";position:absolute;left:25%;right:25%;top:28px;bottom:28px;border:1px dashed #986ca766;border-radius:28px;color:#b58abe;font-size:12px;letter-spacing:.18em;padding:16px;text-align:center;z-index:-1}
.decision .nodes{display:grid;grid-template-columns:1fr 1fr 1fr;grid-auto-rows:minmax(106px,1fr);column-gap:72px;row-gap:30px}
.comparison .nodes{display:grid;grid-template-columns:1fr 1fr;gap:100px}.comparison .role-before{grid-column:1}.comparison .role-after{grid-column:2}.comparison .node{min-height:190px}.comparison.dense .nodes{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr));gap:36px 56px}.comparison.dense .node{min-width:0;width:100%;min-height:100px}.comparison.dense .kind-metric{font-size:30px}.comparison.dense .role-before,.comparison.dense .role-after{grid-column:auto}
.contour .nodes{display:block;min-height:440px;border-left:2px solid #74798c;border-bottom:2px solid #74798c;background:repeating-radial-gradient(ellipse at 58% 53%,transparent 0 42px,#59c5d255 44px 47px,transparent 49px 82px);border-radius:0 0 0 4px}.contour .nodes:before{content:"parameter θ₂";position:absolute;left:-44px;top:8px;color:var(--muted);font-size:14px;transform:rotate(-90deg)}.contour .nodes:after{content:"parameter θ₁";position:absolute;right:8px;bottom:-28px;color:var(--muted);font-size:14px}.contour-path{position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}.contour-path polyline{fill:none;stroke:var(--amber);stroke-width:4;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:9 8}.contour-path circle{fill:var(--amber);stroke:var(--bg);stroke-width:3}.contour .node{position:absolute;min-width:120px;max-width:190px;min-height:62px;padding:12px;border-radius:999px}.contour .role-input,.contour .role-source,.contour .role-context{left:5%;top:12%}.contour .role-operation,.contour .role-tool{right:4%;top:14%}.contour .role-metric,.contour .role-destination,.contour .role-result{left:50%;top:43%;transform:translate(-50%,-50%)}.contour .role-output,.contour .role-audit{right:7%;bottom:8%}.contour .node.is-hidden{transform:translate(-50%,-50%) scale(.92)}.contour .node.is-active{box-shadow:0 0 44px #32b9c566}.contour .role-metric.is-active,.contour .role-destination.is-active,.contour .role-result.is-active{transform:translate(-50%,-50%) scale(1.035)}.contour .role-input.is-hidden,.contour .role-source.is-hidden,.contour .role-context.is-hidden,.contour .role-operation.is-hidden,.contour .role-tool.is-hidden,.contour .role-output.is-hidden,.contour .role-audit.is-hidden{transform:scale(.92)}
.timeline .nodes{align-items:flex-start;padding-top:170px}.timeline .nodes:before{content:"";position:absolute;left:8%;right:8%;top:164px;height:3px;background:linear-gradient(90deg,var(--blue),var(--purple),var(--green));border-radius:3px}.timeline .node{min-height:90px;border-radius:12px}.timeline .node:before{content:"";position:absolute;width:16px;height:16px;border-radius:50%;background:var(--cyan);box-shadow:0 0 20px #59c5d288;transform:translateY(-64px)}
.metric .nodes{flex-wrap:wrap}.metric .role-metric{flex-basis:100%}.feedback_loop .nodes{display:grid;grid-template-columns:repeat(3,1fr);gap:54px}.feedback_loop .node:nth-child(2){transform:translateY(-10px)}.foot{position:absolute;right:28px;bottom:18px;color:var(--amber);font-size:12px;opacity:.7}
.frame.compact{padding:28px 42px 28px}.compact .title{font-size:34px;margin-bottom:12px}.workflow.compact .nodes,.architecture.compact .nodes,.decision.compact .nodes,.comparison.compact .nodes,.transformation.compact .nodes,.timeline.compact .nodes,.feedback_loop.compact .nodes,.metric.compact .nodes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:none;grid-auto-rows:minmax(82px,auto);gap:24px 38px;align-content:center;padding-top:0}.compact .node{min-width:0;width:100%;min-height:82px;padding:10px;font-size:16px;transform:none}.compact .kind-metric{font-size:27px}.compact .kind-gate{min-height:112px;padding:28px}.compact .edge-label{font-size:11px;stroke-width:6px}
"""

_SEMANTIC_CSS = """
.semantic-stage{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px}
.semantic-object{max-width:100%;text-align:center}.semantic-array{width:100%}
.semantic-caption{font:600 26px/1.2 Segoe UI,system-ui,sans-serif;margin-bottom:16px;color:var(--ink)}
.semantic-cells{display:flex;justify-content:center;gap:10px;max-width:100%}
.semantic-cell{position:relative;width:min(11vw,110px);min-width:60px;height:112px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:2px solid #61758c;border-radius:14px;background:#1a2633;font:650 34px/1 Segoe UI,system-ui,sans-serif}
.semantic-cell.is-discarded{opacity:.22;border-color:#4c4d55;background:#17171b}
.semantic-cell.is-pointed{border-color:var(--amber);background:#3c2d18;box-shadow:0 0 28px #edb34a55}
.semantic-index{font:500 15px/1 Segoe UI,system-ui,sans-serif;color:var(--muted);margin-top:11px}
.semantic-pointer-label{height:26px;margin-bottom:10px;font:700 18px/1 Segoe UI,system-ui,sans-serif;color:var(--amber)}
.semantic-check{position:absolute;top:5px;right:9px;font:800 21px/1 Segoe UI,system-ui,sans-serif}.semantic-check.is-match{color:var(--green)}.semantic-check.is-miss{color:var(--red)}
.semantic-cell-wrap{display:flex;flex-direction:column;align-items:center;width:min(11vw,110px);min-width:60px}
.semantic-counter{font:650 28px/1.2 Segoe UI,system-ui,sans-serif;color:var(--amber)}
.semantic-formula{font:550 38px/1.25 Cambria,Georgia,serif}.semantic-code{max-width:90%;font:24px/1.45 Consolas,monospace;text-align:left;white-space:pre-wrap}
.semantic-note{font:600 25px/1.3 Segoe UI,system-ui,sans-serif}.semantic-chart{display:flex;align-items:end;justify-content:center;gap:52px;height:300px;padding-bottom:64px;box-sizing:border-box}
.semantic-bar{width:min(19vw,185px);min-height:8px;background:var(--cyan);border-radius:8px 8px 0 0;position:relative}.semantic-bar span{position:absolute;left:-8px;right:-8px;bottom:-54px;font:650 22px/1.15 Segoe UI,system-ui,sans-serif}
.compact .semantic-cell-wrap,.compact .semantic-cell{width:min(9vw,88px);min-width:48px}.compact .semantic-cell{height:86px;font-size:27px}.compact .semantic-cells{gap:7px}.compact .semantic-stage{gap:20px}
.semantic-media img{max-width:700px;max-height:350px;object-fit:contain}.semantic-icon img{width:120px;height:120px;filter:brightness(0) invert(1)}.semantic-media figcaption{font:600 23px/1.2 Segoe UI,system-ui,sans-serif;margin-top:16px}
"""


def _semantic_html(scene: BrowserScene, state: VisualState) -> str:
    objects = {obj.id: obj for obj in scene.objects}
    pointers = [obj for obj in scene.objects if obj.kind == "pointer" and obj.id in state.visible]
    output: list[str] = []
    for obj in scene.objects:
        if obj.id not in state.visible or obj.kind == "pointer":
            continue
        payload = state.payloads[obj.id]
        label = escape(obj.label)
        if obj.kind == "array":
            discarded = set(payload.get("discarded_indices", []))
            cells = []
            for index, item in enumerate(payload["items"]):
                here = [pointer for pointer in pointers
                        if state.payloads[pointer.id]["target_id"] == obj.id
                        and state.payloads[pointer.id]["index"] == index]
                pointed = " is-pointed" if here else ""
                dimmed = " is-discarded" if index in discarded else ""
                pointer_label = " / ".join(escape(pointer.label) for pointer in here)
                result = payload.get("checked_results", {}).get(str(index))
                marker = (f'<span class="semantic-check is-{result}">'
                          f'{"✓" if result == "match" else "✗"}</span>' if result else "")
                cells.append(f'<div class="semantic-cell-wrap"><div class="semantic-pointer-label">'
                             f'{pointer_label}</div><div class="semantic-cell{pointed}{dimmed}">'
                             f'{escape(str(item))}{marker}<span class="semantic-index">{index}</span></div></div>')
            output.append(f'<section class="semantic-object semantic-array" data-object-id="{escape(obj.id)}">'
                          f'<div class="semantic-caption">{label}</div><div class="semantic-cells">'
                          f'{"".join(cells)}</div></section>')
        elif obj.kind in {"counter", "metric", "value"}:
            value = escape(str(payload.get("value") if payload.get("value") is not None else "?"))
            output.append(f'<div class="semantic-object semantic-counter" data-object-id="{escape(obj.id)}">'
                          f'{label}: {value}</div>')
        elif obj.kind == "formula":
            output.append(f'<div class="semantic-object semantic-formula" data-object-id="{escape(obj.id)}">'
                          f'{escape(str(payload["expression"]))}</div>')
        elif obj.kind == "code":
            output.append(f'<pre class="semantic-object semantic-code" data-object-id="{escape(obj.id)}">'
                          f'{escape(str(payload["source"]))}</pre>')
        elif obj.kind == "chart":
            series = payload["series"]
            numbers = [float(item["value"]) for item in series]
            scale = max(numbers + [1.0])
            bars = "".join(f'<div class="semantic-bar" style="height:{max(8, 210 * value / scale):.1f}px">'
                           f'<span>{escape(str(item["label"]))}: {escape(str(item["value"]))}</span></div>'
                           for item, value in zip(series, numbers))
            output.append(f'<div class="semantic-object" data-object-id="{escape(obj.id)}">'
                          f'<div class="semantic-caption">{label}</div><div class="semantic-chart">'
                          f'{bars}</div></div>')
        elif obj.kind in {"image", "icon"}:
            uri = asset_data_uri(obj.kind, str(payload["asset_id"]))
            extra = " semantic-icon" if obj.kind == "icon" else ""
            output.append(f'<figure class="semantic-object semantic-media{extra}" '
                          f'data-object-id="{escape(obj.id)}"><img src="{uri}" alt="{label}">'
                          f'<figcaption>{label}</figcaption></figure>')
        else:
            output.append(f'<div class="semantic-object semantic-note" data-object-id="{escape(obj.id)}">'
                          f'{label}</div>')
    return "".join(output)


def _state(scene: BrowserScene, active_beat_id: str | None) -> tuple[set[str], set[str]]:
    visible = set(scene.opening_visible_ids)
    active: set[str] = set()
    if active_beat_id is None:
        return set(scene.closing_visible_ids), active
    for beat in scene.beats:
        for action in beat.actions:
            if action.kind == "deactivate":
                visible.difference_update(action.target_ids)
            elif action.kind != "hold":
                visible.update(action.target_ids)
        if beat.narration_beat_id == active_beat_id:
            active.update(target for action in beat.actions for target in action.target_ids)
            active.update(target for evidence in beat.evidence for target in evidence.object_ids)
            break
    return visible, active


def _decision_slots(scene: BrowserScene) -> dict[str, tuple[int, int]]:
    columns = {
        "input": 1, "source": 1, "context": 1, "before": 1,
        "operation": 2, "tool": 2, "decision": 2,
    }
    rows = {1: 0, 2: 0, 3: 0}
    slots: dict[str, tuple[int, int]] = {}
    for obj in scene.objects:
        column = columns.get(obj.role, 3)
        rows[column] += 1
        slots[obj.id] = (column, rows[column])
    return slots


def _node_html(scene: BrowserScene, active_beat_id: str | None) -> str:
    visible, active = _state(scene, active_beat_id)
    slots = _decision_slots(scene) if scene.pattern == "decision" else {}
    out = []
    for obj in scene.objects:
        state = "" if obj.id in visible else " is-hidden"
        if obj.id in active:
            state = " is-active"
        style = (f' style="grid-column:{slots[obj.id][0]};grid-row:{slots[obj.id][1]}"'
                 if obj.id in slots else "")
        out.append(f'<div class="node kind-{obj.kind} role-{obj.role}{state}" data-object-id="{escape(obj.id)}"{style}>'
                   f'{escape(obj.label)}</div>')
    return "".join(out)


def _relations_json(scene: BrowserScene) -> str:
    data = [relation.model_dump() for relation in scene.relationships]
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def _pattern_overlay(scene: BrowserScene, active_beat_id: str | None) -> str:
    if scene.pattern != "contour":
        return ""
    visible, _ = _state(scene, active_beat_id)
    moving = any(obj.id in visible and obj.role in {"operation", "tool"} for obj in scene.objects)
    if not moving:
        return ""
    points = [(1040, 76), (920, 118), (825, 164), (750, 202), (688, 226)]
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="8"/>' for x, y in points)
    route = " ".join(f"{x},{y}" for x, y in points)
    return (f'<svg class="contour-path" viewBox="0 0 1164 440" aria-hidden="true">'
            f'<polyline points="{route}"/>{circles}</svg>')


def page_html(scene: BrowserScene, *, title: str, active_beat_id: str | None = None,
              footer: str = "Lattice", layout_mode: str = "auto",
              state: VisualState | None = None) -> str:
    if state is not None:
        return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}'
                f'{_SEMANTIC_CSS}</style></head><body><main class="frame{(" compact" if layout_mode == "compact" else "")}">'
                f'<h1 class="title">{escape(title)}</h1><section class="diagram">'
                f'<div class="semantic-stage">{_semantic_html(scene, state)}</div></section>'
                f'<div class="foot">{escape(footer)}</div></main></body></html>')
    relations = _relations_json(scene)
    dense = len(scene.objects) > 6 or (scene.pattern == "comparison" and len(scene.objects) > 4)
    frame_class = f"frame {scene.pattern}" + (" dense" if dense else "")
    if layout_mode == "compact":
        frame_class += " compact"
    script = """
const stage=document.querySelector('.diagram'),svg=document.querySelector('.connections');
const marker=document.createElementNS('http://www.w3.org/2000/svg','marker');marker.id='arrow';marker.setAttribute('viewBox','0 0 10 10');marker.setAttribute('refX','8');marker.setAttribute('refY','5');marker.setAttribute('markerWidth','6');marker.setAttribute('markerHeight','6');marker.setAttribute('orient','auto-start-reverse');const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d','M 0 0 L 10 5 L 0 10 z');shape.setAttribute('fill','#6f7384');marker.append(shape);svg.append(marker);const box=stage.getBoundingClientRect();const point=(a,b)=>{const x=a.left+a.width/2,y=a.top+a.height/2,dx=b.left+b.width/2-x,dy=b.top+b.height/2-y,t=1/Math.max(Math.abs(dx)/(a.width/2),Math.abs(dy)/(a.height/2),1);return [x-box.left+dx*t,y-box.top+dy*t]};for(const r of JSON.parse(document.getElementById('relations').textContent)){const a=document.querySelector(`[data-object-id="${CSS.escape(r.source_id)}"]`),b=document.querySelector(`[data-object-id="${CSS.escape(r.target_id)}"]`);if(!a||!b||a.classList.contains('is-hidden')||b.classList.contains('is-hidden'))continue;const [x1,y1]=point(a.getBoundingClientRect(),b.getBoundingClientRect()),[x2,y2]=point(b.getBoundingClientRect(),a.getBoundingClientRect());const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('marker-end','url(#arrow)');line.setAttribute('class',`edge ${r.kind}`);svg.append(line);if(r.label){const label=document.createElementNS('http://www.w3.org/2000/svg','text'),horizontal=Math.abs(y2-y1)<36;label.setAttribute('x',(x1+x2)/2);label.setAttribute('y',(y1+y2)/2-(horizontal?62:10));label.setAttribute('text-anchor','middle');label.setAttribute('class','edge-label');label.textContent=r.label;svg.append(label)}}
"""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head><body>'
            f'<main class="{escape(frame_class)}"><h1 class="title">{escape(title)}</h1>'
            f'<section class="diagram"><svg class="connections" aria-hidden="true"></svg>'
            f'<div class="nodes">{_pattern_overlay(scene, active_beat_id)}'
            f'{_node_html(scene, active_beat_id)}</div></section>'
            f'<div class="foot">{escape(footer)}</div></main><script id="relations" type="application/json">'
            f'{relations}</script><script>{script}</script></body></html>')


def render_scene(scene: BrowserScene, out_png: str | Path, *, title: str,
                 active_beat_id: str | None = None, footer: str = "Lattice",
                 layout_mode: str = "auto", state: VisualState | None = None) -> Path:
    document = page_html(scene, title=title, active_beat_id=active_beat_id, footer=footer,
                         layout_mode=layout_mode, state=state)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.with_name(f"{out_png.stem}.{layout_mode}.html").write_text(document, encoding="utf-8")
    audit_html(document, label=f"browser scene {scene.lesson_scene_id!r}")
    return render_html(document, out_png,
                       label=f"browser scene {scene.lesson_scene_id!r}")
