"""Compile a validated BrowserScene into one safe HTML/SVG frame."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
from copy import deepcopy
from math import ceil
import subprocess
import time

from playwright.sync_api import sync_playwright

from composition.slides import render_html, chrome_path, _ffmpeg, SlideRenderError
from core.schemas.browser_visual_plan import BrowserScene, VisualBeat
from core.visual_assets import asset_data_uri
from core import cancel
from core.visual_state import VisualState, apply_action, displayed_fields
from verification.browser_layout import audit_html, BrowserLayoutError


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
.frame:has(.semantic-stage) .edge-label{font-size:18px}
.semantic-linked{gap:64px}
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
.semantic-note{font:600 25px/1.3 Segoe UI,system-ui,sans-serif}.semantic-field{margin-top:8px;font:500 22px/1.25 Cascadia Code,Consolas,monospace;color:var(--amber)}.semantic-chart{display:flex;align-items:end;justify-content:center;gap:52px;height:300px;padding-bottom:64px;box-sizing:border-box}
.semantic-bar{width:min(19vw,185px);min-height:8px;background:var(--cyan);border-radius:8px 8px 0 0;position:relative}.semantic-bar span{position:absolute;left:-8px;right:-8px;bottom:-54px;font:650 22px/1.15 Segoe UI,system-ui,sans-serif}
.compact .semantic-cell-wrap,.compact .semantic-cell{width:min(9vw,88px);min-width:48px}.compact .semantic-cell{height:86px;font-size:27px}.compact .semantic-cells{gap:7px}.compact .semantic-stage{gap:20px}
.semantic-flow{display:flex;align-items:center;justify-content:center;gap:170px;width:100%}
.semantic-column{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:44px}
.semantic-flow .semantic-note{min-width:230px;border:1px solid var(--line);border-radius:16px;background:#151720;padding:16px 24px;box-shadow:0 12px 38px #0006}
.semantic-object{transition:opacity .35s}.semantic-object.is-past{opacity:.38}
.semantic-flow .semantic-code{max-width:440px;overflow-wrap:anywhere;font-size:21px}
.compact .semantic-flow{gap:120px}.compact .semantic-column{gap:24px}.compact .semantic-flow .semantic-note{min-width:0;padding:10px 16px;font-size:21px}.compact .semantic-field{font-size:18px}
.semantic-media img{max-width:700px;max-height:350px;object-fit:contain}.semantic-icon img{width:120px;height:120px;filter:brightness(0) invert(1)}.semantic-media figcaption{font:600 23px/1.2 Segoe UI,system-ui,sans-serif;margin-top:16px}
"""


def _flow_layers(scene: BrowserScene) -> dict[str, int]:
    """Column per object from the relationship arrows, so a flow reads left to right."""
    if not scene.relationships:
        return {}
    order = [obj.id for obj in scene.objects]
    edges: dict[str, list[str]] = {obj_id: [] for obj_id in order}
    for relation in scene.relationships:
        edges[relation.source_id].append(relation.target_id)
    dag: list[tuple[str, str]] = []
    state: dict[str, str] = {}

    def visit(node: str) -> None:
        state[node] = "open"
        for target in edges[node]:
            if state.get(target) == "open":
                continue  # a back edge (loop); ignore it for placement
            dag.append((node, target))
            if target not in state:
                visit(target)
        state[node] = "done"

    for node in order:
        if node not in state:
            visit(node)
    layer = {node: 0 for node in order}
    for _ in order:
        for source, target in dag:
            layer[target] = max(layer[target], layer[source] + 1)
    linked = {node for pair in dag for node in pair}
    last = max((layer[node] for node in linked), default=-1)
    roles = {obj.id: obj.role for obj in scene.objects}
    # Unlinked inputs start the flow with the other inputs; anything else follows it.
    return {node: layer[node] if node in linked
            else 0 if roles[node] in {"input", "source", "context", "before"} else last + 1
            for node in order}


def _semantic_html(scene: BrowserScene, state: VisualState,
                   active: set[str] | None = None) -> str:
    objects = {obj.id: obj for obj in scene.objects}
    pointers = [obj for obj in scene.objects if obj.kind == "pointer" and obj.id in state.visible]
    output: list[str] = []
    placed: list[str] = []
    for obj in scene.objects:
        if obj.id not in state.visible or obj.kind == "pointer":
            continue
        placed.append(obj.id)
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
                pointer_label = " / ".join(
                    f'<span data-visual-key="{escape(pointer.id)}">{escape(pointer.label)}</span>'
                    for pointer in here)
                result = payload.get("checked_results", {}).get(str(index))
                marker = (f'<span class="semantic-check is-{result}" '
                          f'data-visual-key="{escape(obj.id)}:check:{index}:{result}">'
                          f'{"✓" if result == "match" else "✗"}</span>' if result else "")
                cells.append(f'<div class="semantic-cell-wrap"><div class="semantic-pointer-label">'
                             f'{pointer_label}</div><div class="semantic-cell{pointed}{dimmed}" '
                             f'data-visual-key="{escape(obj.id)}:cell:{index}">'
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
            fields = "".join(
                f'<div class="semantic-field" data-visual-key="{escape(obj.id)}:field:'
                f'{escape(key)}:{escape(value)}">{escape(key)}: {escape(value)}</div>'
                for key, value in displayed_fields(obj.kind, payload))
            output.append(f'<div class="semantic-object semantic-note" data-object-id="{escape(obj.id)}">'
                          f'{label}{fields}</div>')
    if active:
        # Earlier steps stay readable but step back, so the eye follows the current one.
        output = [html if obj_id in active else html.replace(
                      'class="semantic-object', 'class="semantic-object is-past', 1)
                  for obj_id, html in zip(placed, output)]
    layers = _flow_layers(scene)
    if not layers or any(objects[obj_id].kind in {"array", "chart"} for obj_id in placed):
        return "".join(output)
    columns: dict[int, list[str]] = {}
    for obj_id, html in zip(placed, output):
        columns.setdefault(layers[obj_id], []).append(html)
    return '<div class="semantic-flow">' + "".join(
        f'<div class="semantic-column">{"".join(columns[index])}</div>'
        for index in sorted(columns)) + "</div>"


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
    relations = _relations_json(scene)
    dense = len(scene.objects) > 6 or (scene.pattern == "comparison" and len(scene.objects) > 4)
    frame_class = f"frame {scene.pattern}" + (" dense" if dense else "")
    if layout_mode == "compact":
        frame_class += " compact"
    script = """
const stage=document.querySelector('.diagram'),svg=document.querySelector('.connections');
const marker=document.createElementNS('http://www.w3.org/2000/svg','marker');marker.id='arrow';marker.setAttribute('viewBox','0 0 10 10');marker.setAttribute('refX','8');marker.setAttribute('refY','5');marker.setAttribute('markerWidth','6');marker.setAttribute('markerHeight','6');marker.setAttribute('orient','auto-start-reverse');const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d','M 0 0 L 10 5 L 0 10 z');shape.setAttribute('fill','#6f7384');marker.append(shape);svg.append(marker);const box=stage.getBoundingClientRect();const point=(a,b)=>{const x=a.left+a.width/2,y=a.top+a.height/2,dx=b.left+b.width/2-x,dy=b.top+b.height/2-y,t=1/Math.max(Math.abs(dx)/(a.width/2),Math.abs(dy)/(a.height/2),1);return [x-box.left+dx*t,y-box.top+dy*t]};for(const r of JSON.parse(document.getElementById('relations').textContent)){const a=document.querySelector(`[data-object-id="${CSS.escape(r.source_id)}"]`),b=document.querySelector(`[data-object-id="${CSS.escape(r.target_id)}"]`);if(!a||!b||a.classList.contains('is-hidden')||b.classList.contains('is-hidden'))continue;const [x1,y1]=point(a.getBoundingClientRect(),b.getBoundingClientRect()),[x2,y2]=point(b.getBoundingClientRect(),a.getBoundingClientRect());const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('marker-end','url(#arrow)');line.setAttribute('class',`edge ${r.kind}`);svg.append(line);if(r.label){const label=document.createElementNS('http://www.w3.org/2000/svg','text'),horizontal=Math.abs(y2-y1)<36;label.setAttribute('x',(x1+x2)/2);label.setAttribute('y',(y1+y2)/2-(horizontal?62:10));label.setAttribute('text-anchor','middle');label.setAttribute('class','edge-label');label.textContent=r.label;svg.append(label)}}
"""
    script = "window.drawConnections = () => {" + script.replace(
        "const marker=", "svg.querySelectorAll('line,text,marker').forEach(e=>e.remove());const marker=", 1) + "};window.drawConnections();"
    if state is not None:
        routing = r"""
window.routeConnection=(stage,svg,line,a,b,x1,y1,x2,y2)=>{
  const box=stage.getBoundingClientRect();
  const intersects=r=>{
    let low=0,high=1;
    for(const [start,delta,min,max] of [[x1,x2-x1,r.left-box.left-8,r.right-box.left+8],
                                       [y1,y2-y1,r.top-box.top-8,r.bottom-box.top+8]]){
      if(Math.abs(delta)<.001){if(start<min||start>max)return false;}
      else {const t1=(min-start)/delta,t2=(max-start)/delta;
        low=Math.max(low,Math.min(t1,t2));high=Math.min(high,Math.max(t1,t2));}
    }
    return low<=high;
  };
  const blocked=[...stage.querySelectorAll('[data-object-id]')].filter(e=>
    e!==a&&e!==b&&Number(getComputedStyle(e).opacity)>0)
    .map(e=>e.getBoundingClientRect()).filter(intersects);
  let points=[[x1,y1],[x2,y2]],labelX=(x1+x2)/2,labelY=(y1+y2)/2;
  if(blocked.length){
    if(Math.abs(y2-y1)>=Math.abs(x2-x1)){
      let lane=Math.max(x1,x2,...blocked.map(r=>r.right-box.left))+28;
      if(lane>box.width-24)lane=Math.min(x1,x2,...blocked.map(r=>r.left-box.left))-28;
      points=[[x1,y1],[lane,y1],[lane,y2],[x2,y2]];labelX=lane;
    }else{
      let lane=Math.max(y1,y2,...blocked.map(r=>r.bottom-box.top))+28;
      if(lane>box.height-24)lane=Math.min(y1,y2,...blocked.map(r=>r.top-box.top))-28;
      points=[[x1,y1],[x1,lane],[x2,lane],[x2,y2]];labelY=lane;
    }
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    for(const attr of ['class','marker-end'])path.setAttribute(attr,line.getAttribute(attr));
    path.setAttribute('d',points.map((p,i)=>(i?'L':'M')+' '+p.join(' ')).join(' '));
    path.dataset.sourceId=line.dataset.sourceId;path.dataset.targetId=line.dataset.targetId;
    line.replaceWith(path);line=path;
  }
  line.dataset.route=JSON.stringify(points);
  return {labelX,labelY};
};
"""
        script = script.replace("horizontal=Math.abs(y2-y1)<36",
                                "horizontal=Math.abs(x2-x1)>Math.abs(y2-y1)")
        script = script.replace("(horizontal?62:10)", "(horizontal?62:-5)")
        script = script.replace("label.setAttribute('x',(x1+x2)/2);",
                                "label.setAttribute('x',(x1+x2)/2+(horizontal?0:18));")
        script = script.replace("label.setAttribute('text-anchor','middle');",
                                "label.setAttribute('text-anchor',horizontal?'middle':'start');")
        script = script.replace("line.setAttribute('x1',x1);",
                                "line.dataset.sourceId=r.source_id;line.dataset.targetId=r.target_id;line.setAttribute('x1',x1);")
        script = script.replace("svg.querySelectorAll('line,text,marker')",
                                "svg.querySelectorAll('line,text,marker,path.edge')")
        script = script.replace("svg.append(line);if(r.label)",
                                "svg.append(line);const route=window.routeConnection(stage,svg,line,a,b,x1,y1,x2,y2);if(r.label)")
        script = script.replace("(x1+x2)/2+(horizontal?0:18)", "route.labelX+(horizontal?0:18)")
        script = script.replace("(y1+y2)/2-(horizontal?62:-5)", "route.labelY-(horizontal?62:-5)")
        script = routing + script
        return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}'
                f'{_SEMANTIC_CSS}</style></head><body><main class="frame{(" compact" if layout_mode == "compact" else "")}">'
                f'<h1 class="title">{escape(title)}</h1><section class="diagram">'
                f'<svg class="connections" aria-hidden="true"></svg>'
                f'<div class="semantic-stage{(" semantic-linked" if scene.relationships else "")}">'
                f'{_semantic_html(scene, state)}</div></section>'
                f'<div class="foot">{escape(footer)}</div></main>'
                f'<script id="relations" type="application/json">{relations}</script>'
                f'<script>{script}</script></body></html>')
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


def animation_html(scene: BrowserScene, beat: VisualBeat, *, title: str,
                   opening: VisualState, duration: float, layout_mode: str = "auto") -> str:
    windows = beat.timeline(duration)
    state = deepcopy(opening)
    snapshots = [_semantic_html(scene, state)]
    active: set[str] = set()
    for action in beat.actions:
        apply_action(state, action)
        if action.kind not in {"hide", "deactivate"}:
            active.update(action.target_ids)
        snapshots.append(_semantic_html(scene, state, active))
    data = json.dumps({"snapshots": snapshots, "windows": windows,
                       "actions": [action.model_dump() for action in beat.actions],
                       "relations": [relation.model_dump() for relation in scene.relationships]},
                      ensure_ascii=False).replace("</", "<\\/")
    document = page_html(scene, title=title, state=opening, layout_mode=layout_mode)
    script = r"""
const plan=JSON.parse(document.getElementById('animation-plan').textContent);
const stage=document.querySelector('.semantic-stage');
let current=-2, animations=[];
const nodes=()=>[...stage.querySelectorAll('[data-object-id],[data-visual-key]')];
const key=e=>e.dataset.visualKey||e.dataset.objectId;
function display(index){
  for(const animation of animations)animation.cancel();
  animations=[];
  document.querySelectorAll('.animation-ghost,.flow-packet').forEach(e=>e.remove());
  stage.innerHTML=plan.snapshots[Math.max(0,index)];
  const before=new Map(nodes().map(e=>[key(e),{rect:e.getBoundingClientRect(),
    opacity:getComputedStyle(e).opacity,element:e.cloneNode(true),
    parent:e.parentElement.closest('[data-object-id],[data-visual-key]')?.dataset.objectId}]));
  if(index<0){window.drawConnections();return;}
  stage.innerHTML=plan.snapshots[index+1];
  window.drawConnections();
  const seconds=plan.windows[index][1]-plan.windows[index][0];
  const animate=(e,frames)=>{const a=e.animate(frames,{duration:seconds*1000,
    fill:'both',easing:'linear'});a.pause();animations.push(a);};
  const after=new Set();
  for(const element of nodes()){
    const id=key(element);after.add(id);
    const old=before.get(id),rect=element.getBoundingClientRect();
    const opacity=getComputedStyle(element).opacity;
    if(!old){animate(element,[{opacity:0},{opacity}]);continue;}
    const dx=old.rect.x-rect.x,dy=old.rect.y-rect.y;
    if(dx||dy||old.opacity!==opacity){animate(element,[
      {transform:`translate(${dx}px,${dy}px)`,opacity:old.opacity},
      {transform:'translate(0px,0px)',opacity}]);}
  }
  for(const [id,old] of before){
    if(after.has(id)||(old.parent&&before.has(old.parent)&&!after.has(old.parent)))continue;
    const ghost=old.element;ghost.classList.add('animation-ghost');
    Object.assign(ghost.style,{position:'fixed',left:old.rect.x+'px',top:old.rect.y+'px',
      width:old.rect.width+'px',height:old.rect.height+'px',margin:'0',zIndex:'3'});
    document.body.append(ghost);animate(ghost,[{opacity:old.opacity},{opacity:0}]);
  }
  const action=plan.actions[index];
  if(['highlight','focus','activate'].includes(action.kind)){
    for(const element of stage.querySelectorAll('[data-object-id]')){
      if(action.target_ids.includes(element.dataset.objectId))animate(element,[
        {filter:'brightness(1)'},{filter:'brightness(1.8)',offset:.5},{filter:'brightness(1)'}]);
    }
  }
  if(['connect','branch'].includes(action.kind)){
    const svg=document.querySelector('.connections');
    for(const relation of plan.relations){
      if(!action.target_ids.includes(relation.source_id)||!action.target_ids.includes(relation.target_id))continue;
      const source=stage.querySelector(`[data-object-id="${CSS.escape(relation.source_id)}"]`);
      const target=stage.querySelector(`[data-object-id="${CSS.escape(relation.target_id)}"]`);
      if(!source||!target)continue;
      const edge=[...svg.querySelectorAll('line,path.edge')].find(e=>
        e.dataset.sourceId===relation.source_id&&e.dataset.targetId===relation.target_id);
      if(!edge)continue;
      const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
      dot.setAttribute('r','7');dot.setAttribute('fill','#edb34a');dot.setAttribute('class','flow-packet');
      const points=JSON.parse(edge.dataset.route),distances=[0];
      for(let i=1;i<points.length;i++)distances.push(distances[i-1]+
        Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));
      const total=distances[distances.length-1];
      svg.append(dot);animate(dot,points.map((p,i)=>({
        transform:`translate(${p[0]}px,${p[1]}px)`,offset:total?distances[i]/total:i/(points.length-1)})));
    }
  }
}
window.seekAnimation=seconds=>{
  if(!Number.isFinite(seconds)||seconds<0)throw Error('invalid animation time');
  let index=-1;
  for(let i=0;i<plan.windows.length;i++)if(seconds>=plan.windows[i][0])index=i;
  if(index!==current){display(index);current=index;}
  if(index>=0){const elapsed=Math.max(0,Math.min(seconds-plan.windows[index][0],
    plan.windows[index][1]-plan.windows[index][0]));
    for(const animation of animations)animation.currentTime=elapsed*1000;
    document.querySelectorAll('.flow-packet').forEach(e=>e.style.opacity=
      seconds>=plan.windows[index][1]?'0':'1');
  }
  window.drawConnections();
};
window.animationReady=async()=>{
  await document.fonts.ready;
  const sources=new Set(plan.snapshots.flatMap(html=>[...new DOMParser()
    .parseFromString(html,'text/html').images].map(i=>i.src)));
  await Promise.all([...sources].map(async src=>{const image=new Image();image.src=src;await image.decode();}));
  current=-2;window.seekAnimation(0);
};
"""
    return document.replace("</body>",
        f'<script id="animation-plan" type="application/json">{data}</script>'
        f'<script>{script}</script></body>')


def render_animated_beat(scene: BrowserScene, beat: VisualBeat, out_mp4: str | Path, *,
                         title: str, opening: VisualState, duration: float,
                         audio: str | Path, fps: int = 30,
                         layout_mode: str = "auto") -> list[Path]:
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError("animation fps must be an integer from 1 to 60")
    for action, (start, end) in zip(beat.actions, beat.timeline(duration)):
        if end - start < 2 / fps - 1e-9:
            raise ValueError(
                f"action {action.id!r} is too short to capture at {fps} fps; "
                "allow at least two frame intervals or increase fps")
    deadline = time.monotonic() + 300
    cancel.check()
    document = animation_html(scene, beat, title=title, opening=opening,
                              duration=duration, layout_mode=layout_mode)
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_mp4.with_suffix(f".{layout_mode}.html").write_text(document, encoding="utf-8")
    state = deepcopy(opening)
    audit_html(page_html(scene, title=title, state=state, layout_mode=layout_mode))
    for action in beat.actions:
        cancel.check()
        apply_action(state, action)
        audit_html(page_html(scene, title=title, state=state, layout_mode=layout_mode))
    directory = out_mp4.parent / f"{out_mp4.stem}_frames"
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(document, wait_until="load")
            page.evaluate("() => window.animationReady()")
            frame_count = ceil(duration * fps)
            for index in range(frame_count):
                cancel.check()
                if time.monotonic() > deadline:
                    raise TimeoutError("animated browser capture exceeded 300 seconds")
                seconds = duration if index == frame_count - 1 else index / fps
                page.evaluate("seconds => window.seekAnimation(seconds)", seconds)
                clipped = page.evaluate("""() => [...document.querySelectorAll(
                    '[data-object-id],[data-visual-key],.edge-label')].filter(e=>
                    !e.closest('.animation-ghost') && Number(getComputedStyle(e).opacity)>0)
                    .filter(e=>{const r=e.getBoundingClientRect();return r.left < -1 || r.top < -1 ||
                        r.right > innerWidth+1 || r.bottom > innerHeight+1;}).map(e=>
                        e.dataset.objectId||e.dataset.visualKey||e.textContent)""")
                if clipped:
                    raise BrowserLayoutError("animated frame", [f"object {item!r} is clipped" for item in clipped],
                                             {"time": seconds, "objects": clipped})
                frame = directory / f"frame_{index:06d}.png"
                page.screenshot(path=str(frame), animations="allow")
                frames.append(frame)
        finally:
            browser.close()
    result = subprocess.run([_ffmpeg(), "-y", "-framerate", str(fps), "-i",
        str(directory / "frame_%06d.png"), "-i", str(audio), "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out_mp4)], capture_output=True, timeout=300)
    if result.returncode or not out_mp4.exists():
        raise SlideRenderError(f"FFmpeg animated beat encode failed: {result.stderr.decode('utf-8','replace')[-500:]}")
    return frames
