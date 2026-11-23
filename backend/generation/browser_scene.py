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
from core.call_tree import positions, repeats
from core.visual_assets import asset_data_uri, icon_svg
from core import cancel
from core.visual_state import TONES, VisualState, apply_action, displayed_fields
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
.semantic-tree .semantic-caption{margin-bottom:6px}.tree-calls{display:block;margin:0 auto;overflow:visible}
.tree-edge{stroke:#5b6474;stroke-width:2}.tree-node circle{fill:#1a2633;stroke:#61758c;stroke-width:2}
.tree-node text{fill:#f4f4f5;font:650 20px/1 Segoe UI,system-ui,sans-serif;text-anchor:middle;dominant-baseline:central}
.tree-edge.is-waiting,.tree-node.is-waiting{opacity:0}
.semantic-graph .semantic-caption{margin-bottom:6px}.graph-map{display:block;margin:0 auto;overflow:visible}
.graph-edge{stroke:#4b5563;stroke-width:2.5}.graph-edge.is-path{stroke:#4ade80;stroke-width:5}
.graph-node circle{fill:#141922;stroke:#61758c;stroke-width:2.5}.graph-node text{fill:#f4f4f5;font:700 22px/1 Segoe UI,system-ui,sans-serif;text-anchor:middle;dominant-baseline:central}
.graph-node.is-waiting circle{stroke:#fbbf24;stroke-dasharray:6 5;stroke-width:3}
.graph-node.is-visited circle{fill:#0f3b3a;stroke:#2dd4bf}
.graph-node.is-current circle{fill:#4a3507;stroke:#fbbf24;stroke-width:4;filter:drop-shadow(0 0 10px #fbbf24)}
.graph-node.is-path circle{fill:#123d22;stroke:#4ade80;stroke-width:4}
.graph-node.is-goal circle{stroke-width:4}.graph-node.is-goal:not(.is-path):not(.is-current) circle{stroke:#f472b6}
.graph-scout{fill:#fbbf24;filter:drop-shadow(0 0 6px #fbbf24)}.graph-walker{fill:#f4f4f5;stroke:#4ade80;stroke-width:4;filter:drop-shadow(0 0 10px #4ade80)}
.graph-frontier{margin-top:12px;text-align:center;color:#fbbf24;font:650 22px/1.3 Cascadia Code,Consolas,monospace}
.tree-node.is-marked circle{fill:#3a1518;stroke:#f87171;stroke-width:3}.tree-node.is-marked text{fill:#fecaca}
.tree-note{margin-top:8px;min-height:30px;color:#f87171;font:650 22px/1.3 Segoe UI,system-ui,sans-serif}
.semantic-cell.is-empty{border-style:dashed;border-color:#3a4656;background:transparent}
.semantic-cell.is-lit{border-color:#fbbf24;box-shadow:0 0 0 3px #fbbf2444}
.semantic-cell.is-new{border-color:#2dd4bf;background:#11302d;box-shadow:0 0 26px #2dd4bf66}
.semantic-cell.is-pointed{border-color:var(--amber);background:#3c2d18;box-shadow:0 0 28px #edb34a55}
.semantic-cell.is-veiled{border-style:dashed;color:var(--muted);font-size:30px}.peel{opacity:.55;text-decoration-thickness:3px;margin-left:1px}.semantic-cell.in-group{border-width:3px}.semantic-cell.group-0{border-color:#2dd4bf;background:#0f2f2c}
.semantic-cell.group-1{border-color:#f472b6;background:#33172a}.semantic-cell.group-2{border-color:#a78bfa;background:#221a3a}
.group-legend{display:flex;gap:28px;justify-content:center;margin-top:12px;font:650 22px/1.2 Segoe UI,system-ui,sans-serif}
.group-name.group-0{color:#2dd4bf}.group-name.group-1{color:#f472b6}.group-name.group-2{color:#a78bfa}
.semantic-cell.is-long{font-size:22px}.semantic-cell.is-longer{font-size:16px}.compact .semantic-cell.is-long{font-size:18px}
.semantic-index{font:500 15px/1 Segoe UI,system-ui,sans-serif;color:var(--muted);margin-top:11px}
.semantic-pointer-label{height:26px;margin-bottom:10px;font:700 18px/1 Segoe UI,system-ui,sans-serif;color:var(--amber)}
.semantic-check{position:absolute;top:5px;right:9px;font:800 21px/1 Segoe UI,system-ui,sans-serif}.semantic-check.is-match{color:var(--green)}.semantic-check.is-miss{color:var(--red)}
.semantic-cell-wrap{display:flex;flex-direction:column;align-items:center;width:min(11vw,110px);min-width:60px}
.semantic-counter{font:650 28px/1.2 Segoe UI,system-ui,sans-serif;color:var(--amber)}
.semantic-formula{font:550 38px/1.25 Cambria,Georgia,serif}.semantic-code{max-width:90%;font:24px/1.45 Consolas,monospace;text-align:left;white-space:pre-wrap}
.semantic-note{font:600 25px/1.3 Segoe UI,system-ui,sans-serif}.semantic-field{margin-top:8px;font:500 22px/1.25 Cascadia Code,Consolas,monospace;color:var(--amber)}.semantic-chart{display:flex;align-items:end;justify-content:center;gap:52px;height:300px;padding-bottom:64px;box-sizing:border-box}
.semantic-bar{width:min(19vw,185px);min-height:8px;background:var(--cyan);border-radius:8px 8px 0 0;position:relative}.semantic-bar span{position:absolute;left:-8px;right:-8px;bottom:-54px;font:650 22px/1.15 Segoe UI,system-ui,sans-serif}
.compact .semantic-cell-wrap,.compact .semantic-cell{width:min(9vw,88px);min-width:48px}.compact .semantic-cell{height:86px;font-size:27px}.compact .semantic-cells{gap:7px}.compact .semantic-stage{gap:20px}
.semantic-stack{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;width:100%}
.semantic-linked .semantic-stack{gap:64px}.compact .semantic-stack{gap:20px}
.semantic-flow{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--row-gap,96px);width:max-content}
.semantic-row{display:flex;align-items:center;justify-content:center;gap:var(--flow-gap,110px)}
.semantic-column{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px}
.frame:has(.semantic-flow) .edge-label{font-size:calc(18px * var(--fit,1))}
/* Stage elements are replaced on every step and moved by paused Web Animations. A CSS transition
   here would run in wall-clock time (fitting the stage changes shadow sizes) and make a frame
   depend on when it was captured. */
.semantic-stage,.semantic-stage *{transition:none!important}.semantic-object.is-past{opacity:.62}.semantic-caption-line.is-past{opacity:1}
.semantic-object.is-hidden{opacity:0;transform:none;pointer-events:none}
.semantic-card{flex:none;flex-direction:column;min-width:200px;max-width:380px;min-height:92px;padding:16px 24px;font-size:22px;line-height:1.25}
.semantic-card .semantic-field{margin-top:7px;font-size:18px;overflow-wrap:anywhere}
.semantic-card.is-active{transform:none;border-color:var(--cyan);box-shadow:0 0 44px #32b9c566}
.semantic-card.kind-tool{padding-left:34px;padding-right:34px}
.semantic-card.kind-gate.has-fields{min-height:92px;clip-path:none;border:1px solid #b88d43;border-radius:16px;padding:16px 24px}
.semantic-card.kind-gate.is-active{background:linear-gradient(145deg,#7a5d26,#3a2d16)}
.semantic-flow .semantic-code{max-width:560px;overflow-wrap:anywhere;font-size:21px;margin:0;padding:14px 18px;border:1px solid var(--line);border-radius:10px;background:#0d0f15}
.compact .semantic-row{gap:calc(var(--flow-gap,110px) * .75)}.compact .semantic-column{gap:24px}
.compact .semantic-card{width:auto;min-width:0;min-height:70px;padding:10px 16px;font-size:19px}.compact .semantic-card .semantic-field{font-size:16px}
/* Map pieces: thin outlines on black, one colour (tone) per idea, red for a problem. */
body:has(.semantic-stage){background:#0a0a0a}
.tone-pink{--tone:#f472b6}.tone-purple{--tone:#a78bfa}.tone-teal{--tone:#2dd4bf}.tone-yellow{--tone:#fbbf24}.tone-blue{--tone:#60a5fa}.tone-green{--tone:#4ade80}.tone-white{--tone:#e5e7eb}.tone-red{--tone:#f87171}
.frame:has(.semantic-stage) .edge{stroke:#8d919e}
.semantic-card.node{background:#0f1013;border-color:var(--tone);box-shadow:none}
.semantic-card .semantic-title{color:var(--tone)}
.semantic-card.is-active{border-color:var(--tone);box-shadow:0 0 30px color-mix(in srgb,var(--tone) 55%,transparent)}
.semantic-card.kind-gate{background:#16130b}
.semantic-card.is-placeholder{border-style:dashed}.semantic-card.is-placeholder>*{visibility:hidden}
.card-icon svg{display:block;width:34px;height:34px;margin:0 auto 6px;color:var(--tone)}
.semantic-piece{display:flex;flex-direction:column;align-items:center;gap:10px;min-width:120px;color:var(--tone)}
.piece-icons{display:grid;grid-template-columns:repeat(var(--cols,1),auto);gap:10px;padding:10px;border:2px dashed transparent;border-radius:14px}
.piece-icons svg{display:block;width:96px;height:96px;stroke-width:1.3}
.piece-icons.is-many svg{width:46px;height:46px}
.piece-label{font:700 19px/1.15 Segoe UI,system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase}
.semantic-piece.is-active .piece-icons{filter:drop-shadow(0 0 12px var(--tone))}
.semantic-piece.is-placeholder .piece-icons{border-color:var(--tone)}
.semantic-piece.is-placeholder svg,.semantic-piece.is-placeholder .piece-label{visibility:hidden}.semantic-piece.is-placeholder .piece-icons{position:relative}.semantic-piece.is-placeholder .piece-icons::after{content:'?';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--tone);font:700 54px/1 Segoe UI,system-ui,sans-serif;opacity:.85}
.semantic-panel{display:flex;flex-direction:column;gap:16px;padding:16px 22px 22px;border:1.5px solid color-mix(in srgb,var(--tone) 45%,transparent);border-radius:20px;background:#0d1114}
.panel-header{padding:8px 12px;border-radius:8px;background:color-mix(in srgb,var(--tone) 14%,transparent);color:var(--tone);font:700 16px/1 Segoe UI,system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase}
.panel-body{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:64px 56px;max-width:420px}
.semantic-captions{display:flex;flex-direction:column;align-items:center;gap:10px;width:100%;position:absolute;left:0;right:0;bottom:0}.semantic-stage:has(> .semantic-captions){position:relative}.semantic-caption-line{align-self:center;width:100%;text-align:center;color:var(--tone);font:650 24px/1.2 Segoe UI,system-ui,sans-serif;letter-spacing:.02em}
.semantic-caption-line.is-question{color:#f4f4f5;font-size:29px;line-height:1.3}
.semantic-caption-line.is-idea{color:#fde68a;font-size:27px;line-height:1.3}
.idea-mark{background:transparent;border:2px solid #fbbf24;color:#fbbf24;line-height:32px}
.ask-mark{display:inline-block;width:36px;height:36px;line-height:36px;margin-right:14px;border-radius:50%;background:#fbbf24;color:#0a0a0a;font-weight:800;font-size:24px;vertical-align:2px}
.semantic-meter{min-width:180px;color:var(--tone)}
.meter-label{margin-bottom:8px;font:700 16px/1 Segoe UI,system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase}
.meter-bar{height:14px;border:1.5px solid var(--tone);border-radius:4px}.meter-bar i{display:block;height:100%;background:var(--tone)}
.semantic-codewin{overflow:hidden;border:1px solid #2a2f3a;border-radius:10px;background:#0d0f15;text-align:left}
.codewin-bar{display:flex;align-items:center;gap:7px;padding:9px 12px;background:#141821;color:#8d919e;font:500 14px/1 Consolas,monospace}
.codewin-bar i{width:10px;height:10px;border-radius:50%;background:#f87171}.codewin-bar i:nth-child(2){background:#fbbf24}.codewin-bar i:nth-child(3){background:#4ade80}.codewin-bar span{margin-left:8px}
.semantic-codewin .semantic-code{max-width:560px;margin:0;padding:14px 18px;border:0;background:none;overflow-wrap:anywhere;font-size:21px}
.code-line{display:block}.code-line.is-off{opacity:.34}.code-line.is-on{margin:0 -18px;padding:0 15px;border-left:3px solid #fbbf24;background:#fbbf2418}
.semantic-split{flex-direction:row;align-items:center;gap:60px;width:max-content}
.split-code{flex:none}.split-rest{display:flex;flex-direction:column;align-items:center;gap:34px}
.semantic-split{gap:48px}.semantic-split .semantic-array{width:auto}.semantic-split .semantic-code{max-width:none;white-space:pre;font-size:30px;line-height:1.5;padding:18px 24px}.semantic-split .codewin-bar{font-size:18px;padding:12px 16px}.semantic-split .code-line.is-on{margin:0 -24px;padding:0 21px}
.semantic-media img{max-width:700px;max-height:350px;object-fit:contain}.semantic-icon img{width:120px;height:120px;filter:brightness(0) invert(1)}.semantic-media figcaption{font:600 23px/1.2 Segoe UI,system-ui,sans-serif;margin-top:16px}
"""


_ROLE_TONES = {"input": "pink", "source": "pink", "context": "pink", "before": "pink",
               "operation": "teal", "tool": "teal", "decision": "yellow", "metric": "yellow",
               "audit": "yellow", "output": "purple", "result": "purple",
               "destination": "purple", "after": "purple"}


def _tree_html(obj, payload: dict, flags: str, ident: str, label: str) -> str:
    """A recursion's calls as a tree. Every call has its place from the first frame; `shown` says
    how many are revealed, and the calls for a `marked` value are picked out in red, with a line
    underneath saying how many times that value is worked out."""
    nodes = payload["nodes"]
    where, width, height = positions(nodes)
    revealed, marked = payload.get("shown", 1), set(payload.get("marked") or [])
    parts = []
    for node in nodes:
        if node["parent"] is None:
            continue
        (x1, y1), (x2, y2) = where[node["parent"]], where[node["id"]]
        state = "" if node["id"] < revealed else " is-waiting"
        parts.append(f'<line class="tree-edge{state}" data-visual-key="{escape(obj.id)}:edge:{node["id"]}" '
                     f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    for node in nodes:
        x, y = where[node["id"]]
        state = (" is-waiting" if node["id"] >= revealed
                 else " is-marked" if node["value"] in marked else "")
        parts.append(f'<g class="tree-node{state}" data-visual-key="{escape(obj.id)}:node:{node["id"]}">'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="23"/>'
                     f'<text x="{x:.1f}" y="{y:.1f}">{escape(str(node["value"]))}</text></g>')
    note = " · ".join(repeats(payload))
    return (f'<section class="semantic-object{flags} semantic-tree" {ident}>'
            f'<div class="semantic-caption">{label}</div>'
            f'<svg class="tree-calls" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}">{"".join(parts)}</svg>'
            f'<div class="tree-note">{escape(note) or "&nbsp;"}</div></section>')


def _graph_html(obj, payload: dict, flags: str, ident: str, label: str) -> str:
    """A graph being searched. Every node has its place from the first frame (its column is its
    distance from the start); taken nodes are filled, the node just taken is lit, nodes waiting in
    the queue or on the stack are outlined, and the path found is drawn last."""
    from core.graph_search import frontier_line, layout
    nodes, edges = payload["nodes"], payload.get("edges") or []
    places = layout(nodes, edges, payload.get("start", nodes[0]))
    columns = max(column for column, _ in places.values()) + 1
    rows = max(row for _, row in places.values()) + 1
    width, height = 150 * columns, 112 * rows
    where = {node: (75 + 150 * column, 56 + 112 * row) for node, (column, row) in places.items()}
    visited, waiting = set(payload.get("visited") or []), set(payload.get("frontier") or [])
    current, path = payload.get("current"), list(payload.get("path") or [])
    on_path = {frozenset(pair) for pair in zip(path, path[1:])}
    parts = []
    for a, b in edges:
        (x1, y1), (x2, y2) = where[a], where[b]
        state = " is-path" if frozenset((a, b)) in on_path else ""
        parts.append(f'<line class="graph-edge{state}" data-visual-key="{escape(obj.id)}:edge:{escape(a)}-{escape(b)}" '
                     f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    for node in nodes:
        x, y = where[node]
        state = (" is-current" if node == current else " is-path" if node in path
                 else " is-visited" if node in visited else " is-waiting" if node in waiting else "")
        goal = " is-goal" if node == payload.get("goal") else ""
        parts.append(f'<g class="graph-node{state}{goal}" data-visual-key="{escape(obj.id)}:node:{escape(node)}">'
                     f'<circle cx="{x}" cy="{y}" r="28"/><text x="{x}" y="{y}">{escape(node)}</text></g>')
    return (f'<section class="semantic-object{flags} semantic-graph" {ident}>'
            f'<div class="semantic-caption">{label}</div>'
            f'<svg class="graph-map" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'{"".join(parts)}</svg>'
            f'<div class="graph-frontier">{escape(frontier_line(payload))}</div></section>')


def _tone(obj, payload: dict) -> str:
    """The piece's colour: the one the plan gave it, else one that follows its role."""
    tone = payload.get("tone")
    return tone if tone in TONES else _ROLE_TONES.get(obj.role, "white")


def _containers(scene: BrowserScene) -> dict[str, str]:
    """Member id -> the panel (a group with `members`) that holds it."""
    ids = {obj.id for obj in scene.objects}
    return {member: obj.id for obj in scene.objects
            if obj.kind == "group" and isinstance(obj.payload.get("members"), list)
            for member in obj.payload["members"] if member in ids and member != obj.id}


def _flow_layers(scene: BrowserScene) -> dict[str, int]:
    """Column per top-level object from the relationship arrows, so a flow reads left to right.
    A piece inside a panel counts as its panel, and a caption line is not part of the flow."""
    if not scene.relationships:
        return {}
    containers = _containers(scene)
    top = lambda obj_id: containers.get(obj_id, obj_id)
    order = [obj.id for obj in scene.objects if obj.id not in containers and obj.kind != "caption"]
    edges: dict[str, list[str]] = {obj_id: [] for obj_id in order}
    for relation in scene.relationships:
        source, target = top(relation.source_id), top(relation.target_id)
        if source != target and source in edges and target in edges:
            edges[source].append(target)
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
    # A piece nothing points to, which only feeds later pieces, sits in the column just before the
    # first of them. Left in the first column, its arrow would have to cross the whole diagram.
    fed = {target for _, target in dag}
    for node in order:
        feeds = [layer[target] for source, target in dag if source == node]
        if node not in fed and feeds:
            layer[node] = max(layer[node], min(feeds) - 1)
    linked = {node for pair in dag for node in pair}
    last = max((layer[node] for node in linked), default=-1)
    roles = {obj.id: obj.role for obj in scene.objects}
    # Unlinked inputs start the flow with the other inputs; anything else follows it.
    return {node: layer[node] if node in linked
            else 0 if roles[node] in {"input", "source", "context", "before"} else last + 1
            for node in order}


MAX_FLOW_COLUMNS = 4     # a longer flow of cards wraps to a second row instead of shrinking to fit
# A row holds as much as four cards. An icon piece is narrower than a card and a panel with pieces
# inside is wider, so a row takes six icon pieces, or three panels, before it wraps.
ROW_WIDTH = MAX_FLOW_COLUMNS * 1.5


def _column_width(obj) -> float:
    if obj.kind == "icon":
        return 1
    return 2 if obj.kind == "group" and obj.payload.get("members") else 1.5


_REVEALS = {"appear", "connect", "expand", "branch", "activate", "transform"}   # actions that bring an object on


def _shown_in_scene(scene: BrowserScene) -> set[str]:
    """Every object this scene puts on screen at some point. Each one keeps a fixed place for the
    whole scene, so nothing jumps when another object appears."""
    shown = set(scene.opening_visible_ids)
    for beat in scene.beats:
        for action in beat.actions:
            if action.kind in _REVEALS:
                shown.update(action.target_ids)
    return shown


def _label_lines(label: str) -> list[str]:
    """An arrow label on at most two lines, split at the space nearest its middle, so the gap it
    has to fit between two boxes stays short."""
    label = " ".join(label.split())
    spaces = [index for index, char in enumerate(label) if char == " "]
    if len(label) <= 14 or not spaces:
        return [label]
    cut = min(spaces, key=lambda index: abs(index - len(label) / 2))
    return [label[:cut], label[cut + 1:]]


def _peeled(item, ends: str | None) -> str:
    """A case drawn with its last choice struck through: what is left is a smaller case."""
    text = str(item)
    if not ends or not text.endswith(ends) or len(ends) >= len(text):
        return escape(text)
    return f'{escape(text[:-len(ends)])}<s class="peel">{escape(ends)}</s>'


def _semantic_html(scene: BrowserScene, state: VisualState, active: set[str] | None = None,
                   current: set[str] | None = None, room: set[str] | None = None) -> str:
    """The stage for one moment of a scene. `active` is what the beat has touched so far and
    `current` what the latest action touches; in a flow the first dims the rest and the second glows.
    `room` is what is still to be seen from this beat on: outside a flow, an item that has left
    for good gives up its place, so what follows it is not drawn small beside a hole."""
    objects = {obj.id: obj for obj in scene.objects}
    containers = _containers(scene)
    layers = _flow_layers(scene)
    held = _shown_in_scene(scene) if room is None or layers else room
    slots = held | state.visible | set(scene.layout_ids)
    placed = [obj.id for obj in scene.objects if obj.kind != "pointer" and obj.id in slots]
    # A flow is pieces joined by arrows. An array or chart is the subject of every step even when
    # the action names its pointer or counter, so such a scene is never dimmed or lit as "steps".
    flow = bool(layers) and not any(objects[obj_id].kind in {"array", "chart"} for obj_id in placed)
    pointers = [obj for obj in scene.objects if obj.kind == "pointer" and obj.id in state.visible]
    inside = {obj_id: containers[obj_id] for obj_id in placed if containers.get(obj_id) in placed}
    drawn: dict[str, str] = {}
    # What this scene puts on screen at some point: the camera frames these, not the whole
    # lesson's map, whose other pieces keep their places off to the side.
    in_scene = _shown_in_scene(scene) | state.visible
    for obj_id in sorted(placed, key=lambda item: item not in inside):   # members before their panel
        obj = objects[obj_id]
        payload = state.payloads[obj.id]
        label = escape(obj.label)
        tone = f" tone-{_tone(obj, payload)}"
        if obj.id not in state.visible:
            flags = " is-hidden"     # holds its place, drawn with no opacity until it appears
        elif flow and active and obj.id in (current or ()):
            flags = " is-active"
        elif flow and active and obj.id not in active:
            flags = " is-past"       # earlier steps stay readable but step back
        else:
            flags = ""
        if payload.get("placeholder"):
            flags += " is-placeholder"   # a dashed outline where a piece is about to go
        if obj.id in in_scene:
            flags += " in-scene"
        ident = f'data-object-id="{escape(obj.id)}"'
        if obj.kind == "array":
            discarded = set(payload.get("discarded_indices", []))
            # a table being filled: empty cells, the cells a value is read from, the cell just written
            read, written = set(payload.get("lit_indices") or []), payload.get("new_index")
            first = payload.get("first") or 0       # the number the first cell goes by
            # cells marked as belonging together: one colour a group, named under the array
            groups = payload.get("groups") or []
            veiled = set(payload.get("veiled") or [])        # held back: drawn as "?" until revealed
            member = {cell: number for number, group in enumerate(groups) for cell in group["cells"]}
            peel = {cell: group["ends"] for group in groups if group.get("ends") for cell in group["cells"]}
            tints = {int(cell): number for cell, number in (payload.get("tints") or {}).items()}
            cells = []
            for index, item in enumerate(payload["items"]):
                here = [pointer for pointer in pointers
                        if state.payloads[pointer.id]["target_id"] == obj.id
                        and state.payloads[pointer.id]["index"] == index]
                pointed = " is-pointed" if here else ""
                dimmed = " is-discarded" if index in discarded else ""
                dimmed += " is-empty" if item is None else ""
                dimmed += " is-new" if index == written else " is-lit" if index in read else ""
                dimmed += ((" is-longer" if len(str(item)) > 7 else " is-long")
                           if len(str(item)) > 3 and item is not None else "")    # a short string
                dimmed += f" in-group group-{member[index] % 3}" if index in member else ""
                dimmed += f" in-group group-{tints[index] % 3}" if index in tints else ""
                dimmed += " is-veiled" if index in veiled else ""
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
                             f'{"?" if index in veiled else "" if item is None else _peeled(item, peel.get(index))}{marker}'
                             + ("" if payload.get("unnumbered") else
                                f'<span class="semantic-index">{index + first}</span>')
                             + '</div></div>')
            legend = "".join(
                f'<span class="group-name group-{number % 3}" data-visual-key="{escape(obj.id)}:group:{number}">'
                f'{escape(group["label"])}: {len(group["cells"])}</span>' for number, group in enumerate(groups))
            html = (f'<section class="semantic-object{flags} semantic-array" {ident}>'
                    f'<div class="semantic-caption">{label}</div><div class="semantic-cells">'
                    f'{"".join(cells)}</div>'
                    + (f'<div class="group-legend">{legend}</div>' if legend else "") + '</section>')
        elif obj.kind in {"counter", "metric", "value"}:
            raw = payload.get("value")
            value = escape(str(raw if raw is not None else "?"))
            ceiling = payload.get("max")
            if (obj.kind == "metric" and isinstance(ceiling, (int, float)) and ceiling > 0
                    and isinstance(raw, (int, float))):
                # a load bar: the value is shown as a filled part of its maximum
                filled = max(0.0, min(100.0, 100.0 * raw / ceiling))
                html = (f'<div class="semantic-object{flags} semantic-meter{tone}" {ident}>'
                        f'<div class="meter-label">{label}: {value}</div>'
                        f'<div class="meter-bar"><i style="width:{filled:.0f}%"></i></div></div>')
            else:
                html = (f'<div class="semantic-object{flags} semantic-counter" {ident}>'
                        f'{label}: {value}</div>')
        elif obj.kind == "formula":
            html = (f'<div class="semantic-object{flags} semantic-formula" {ident}>'
                    f'{escape(str(payload["expression"]))}</div>')
        elif obj.kind == "graph":
            html = _graph_html(obj, payload, flags, ident, label)
        elif obj.kind == "tree":
            html = _tree_html(obj, payload, flags, ident, label)
        elif obj.kind == "code":
            # an editor window: the label is the file name in its title bar
            # `active_lines` (1-based) are the lines being explained: they stay bright, the rest dim
            lit = {line for line in payload.get("active_lines") or [] if isinstance(line, int)}
            rows = str(payload["source"]).split("\n")
            body = escape(rows[0]) if len(rows) == 1 and not lit else "".join(
                f'<span class="code-line{" is-on" if number in lit else " is-off" if lit else ""}" '
                f'data-visual-key="{escape(obj.id)}:line:{number}">{escape(row) or " "}</span>'
                for number, row in enumerate(rows, 1))
            html = (f'<div class="semantic-object{flags} semantic-codewin" {ident}>'
                    f'<div class="codewin-bar"><i></i><i></i><i></i><span>{label}</span></div>'
                    f'<pre class="semantic-code">{body}</pre></div>')
        elif obj.kind == "chart":
            series = payload["series"]
            numbers = [float(item["value"]) for item in series]
            scale = max(numbers + [1.0])
            bars = "".join(f'<div class="semantic-bar" style="height:{max(8, 210 * value / scale):.1f}px">'
                           f'<span>{escape(str(item["label"]))}: {escape(str(item["value"]))}</span></div>'
                           for item, value in zip(series, numbers))
            html = (f'<div class="semantic-object{flags}" {ident}>'
                    f'<div class="semantic-caption">{label}</div><div class="semantic-chart">'
                    f'{bars}</div></div>')
        elif obj.kind == "image":
            uri = asset_data_uri(obj.kind, str(payload["asset_id"]))
            html = (f'<figure class="semantic-object{flags} semantic-media" {ident}>'
                    f'<img src="{uri}" alt="{label}"><figcaption>{label}</figcaption></figure>')
        elif obj.kind == "icon":
            # a map piece: an outlined icon in its colour with a short label under it; `count`
            # repeats the icon to show a quantity
            count = payload.get("count")
            count = count if isinstance(count, int) and 1 <= count <= 12 else 1
            many = f' is-many" style="--cols:{min(count, 3)}' if count > 1 else ""
            html = (f'<div class="semantic-object{flags} semantic-piece{tone}" {ident}>'
                    f'<div class="piece-icons{many}">{icon_svg(str(payload["asset_id"])) * count}</div>'
                    f'<div class="piece-label">{label}</div></div>')
        elif obj.kind == "caption":
            tick = "✓ " if payload.get("tick") else ""
            # a question is the line the viewer is asked to think about, the turning point the line
            # the lesson hinges on: each larger than a caption, shown while it is said. No "?" or
            # "!" badge: on every such line they read as a fixed template (owner review, 2026-11-22).
            asks = " is-question" if payload.get("ask") else " is-idea" if payload.get("idea") else ""
            html = (f'<div class="semantic-object{flags} semantic-caption-line{asks}{tone}" {ident}>'
                    f'{tick}{label}</div>')
        elif obj.kind == "group" and any(holder == obj.id for holder in inside.values()):
            # a panel: its members are drawn inside it
            members = "".join(drawn[member] for member in placed if inside.get(member) == obj.id)
            html = (f'<div class="semantic-object{flags} semantic-panel{tone}" {ident}>'
                    f'<div class="panel-header">{label}</div><div class="panel-body">{members}</div></div>')
        else:
            # Message, tool, document, card, node, gate, group: the original card shapes, with
            # the object's values inside the card.
            pairs = displayed_fields(obj.kind, payload)
            fields = "".join(
                f'<div class="semantic-field" data-visual-key="{escape(obj.id)}:field:'
                f'{escape(key)}:{escape(value)}">{escape(key)}: {escape(value)}</div>'
                for key, value in pairs)
            shape = " has-fields" if pairs else ""
            figure = (f'<div class="card-icon">{icon_svg(str(payload["icon"]))}</div>'
                      if payload.get("icon") else "")
            html = (f'<div class="semantic-object{flags} semantic-note semantic-card node '
                    f'kind-{obj.kind} role-{obj.role}{shape}{tone}" {ident}>'
                    f'{figure}<div class="semantic-title">{label}</div>{fields}</div>')
        drawn[obj_id] = html
    top = [obj_id for obj_id in placed if obj_id not in inside and objects[obj_id].kind != "caption"]
    captions = "".join(drawn[obj_id] for obj_id in placed if objects[obj_id].kind == "caption")
    # The lines of text under the picture sit together in one band, close to each other: as
    # separate children of the stage each took the stage's wide gap, and a recap's three lines
    # held the bottom half of the frame empty for the whole scene.
    captions = f'<div class="semantic-captions">{captions}</div>' if captions else ""
    if not flow:
        code = [obj_id for obj_id in top if objects[obj_id].kind == "code"]
        rest = [obj_id for obj_id in top if objects[obj_id].kind != "code"]
        if code and rest:
            # code and picture: the code is pinned on the left, what it does plays out on the right
            return ('<div class="semantic-stack semantic-split"><div class="split-code">'
                    + "".join(drawn[obj_id] for obj_id in code) + '</div><div class="split-rest">'
                    + "".join(drawn[obj_id] for obj_id in rest) + f'</div></div>{captions}')
        return f'<div class="semantic-stack">{"".join(drawn[obj_id] for obj_id in top)}</div>{captions}'
    columns: dict[int, list[str]] = {}
    widths: dict[int, float] = {}
    for obj_id in top:
        columns.setdefault(layers[obj_id], []).append(drawn[obj_id])
        widths[layers[obj_id]] = max(widths.get(layers[obj_id], 0), _column_width(objects[obj_id]))
    rows, used = [[]], 0.0
    for index in sorted(columns):
        if rows[-1] and used + widths[index] > ROW_WIDTH:
            rows.append([])
            used = 0.0
        rows[-1].append(columns[index])
        used += widths[index]
    # The gap between columns is as wide as the longest arrow label that has to sit in it.
    lines = [_label_lines(relation.label) for relation in scene.relationships if relation.label
             and relation.source_id in slots and relation.target_id in slots]
    longest = max((len(line) for label in lines for line in label), default=0)
    gap = max(84, 40 + 11 * longest)
    row_gap = 132 if any(len(label) > 1 for label in lines) else 96   # room for a wrapped arrow's label
    return f'<div class="semantic-flow" style="--flow-gap:{gap}px;--row-gap:{row_gap}px">' + "".join(
        '<div class="semantic-row">' + "".join(
            f'<div class="semantic-column">{"".join(column)}</div>' for column in row) + "</div>"
        for row in rows) + "</div>" + captions


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


def _semantic_relations_json(scene: BrowserScene) -> str:
    """Relationships for the semantic stage, with each label already split into its lines."""
    data = [{**relation.model_dump(), "lines": _label_lines(relation.label) if relation.label else []}
            for relation in scene.relationships]
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


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


# An arrow label on the semantic stage: its lines sit just above the arrow, inside the gap between
# the two boxes (the gap is sized for it), instead of high above a row of equally tall boxes.
_SEMANTIC_LABEL_JS = (
    "if(r.label){const label=document.createElementNS('http://www.w3.org/2000/svg','text'),"
    "horizontal=!route.side&&Math.abs(x2-x1)>Math.abs(y2-y1),fit=window.flowFit||1,"
    "lines=r.lines&&r.lines.length?r.lines:[r.label],"
    "x=route.labelX+(horizontal?0:18*fit),bottom=route.labelY-(horizontal?17*fit:-5*fit);"
    "label.setAttribute('text-anchor',horizontal?'middle':'start');"
    "label.setAttribute('class','edge-label');"
    "lines.forEach((text,i)=>{const span=document.createElementNS('http://www.w3.org/2000/svg','tspan');"
    "span.setAttribute('x',x);span.setAttribute('y',bottom-(lines.length-1-i)*21*fit);"
    "span.textContent=text+(i<lines.length-1?' ':'');label.append(span)});svg.append(label);"
    # A label that lands on another label or on a piece moves along its own arrow to the first
    # free spot: the same things the layout check counts, so a placed label is one it accepts.
    "const overlap=(p,q)=>Math.max(0,Math.min(p.right,q.right)-Math.max(p.left,q.left))"
    "*Math.max(0,Math.min(p.bottom,q.bottom)-Math.max(p.top,q.top));"
    "const others=[...svg.querySelectorAll('text.edge-label')].filter(e=>e!==label)"
    ".map(e=>e.getBoundingClientRect());"
    "const solids=[...document.querySelectorAll('.semantic-object:not(.is-hidden)')]"
    ".filter(e=>!e.classList.contains('semantic-panel')).map(e=>e.getBoundingClientRect());"
    "const hits=()=>{const own=label.getBoundingClientRect();"
    "return others.some(o=>overlap(o,own)>1)||solids.some(o=>overlap(o,own)>1)};"
    "if(hits()){const own=label.getBoundingClientRect(),h=own.height+6*fit,w=own.width/2+12*fit;"
    "const steps=horizontal?[[0,h+30*fit],[-w,0],[w,0],[-w,h+30*fit],[w,h+30*fit]]"
    ":[[0,h],[0,-h],[0,2*h],[0,-2*h],[0,3*h]];"
    "const spans=[...label.querySelectorAll('tspan')].map(t=>[t,+t.getAttribute('x'),+t.getAttribute('y')]);"
    "for(const [dx,dy] of steps){spans.forEach(([t,x0,y0])=>{t.setAttribute('x',x0+dx);"
    "t.setAttribute('y',y0+dy)});if(!hits())break}"
    "if(hits())spans.forEach(([t,x0,y0])=>{t.setAttribute('x',x0);t.setAttribute('y',y0)})}}")


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
window.fitFlow=()=>{
  // Size the stage content to the frame: a flow grows up to 1.3x or shrinks until it fits, a
  // stack only ever shrinks.
  const stage=document.querySelector('.semantic-stage');
  const block=stage&&stage.querySelector('.semantic-flow,.semantic-stack');
  if(!block)return;
  block.style.zoom=1;block.style.left='';block.style.top='';
  const flow=block.classList.contains('semantic-flow');
  const sized=flow||block.classList.contains('semantic-split');   // these have a width of their own
  // a graph being searched is the whole picture: it grows to fill the frame like a map
  const drawing=!flow&&!!block.querySelector(':scope > .semantic-graph');
  const room=stage.getBoundingClientRect();
  // The lines of text under the picture, measured with their real gap: estimated, they came out
  // short, and a recap scene's map was pushed up into the title.
  const band=stage.querySelector(':scope > .semantic-captions');
  const lines=band?band.getBoundingClientRect().height+parseFloat(getComputedStyle(stage).rowGap||0):0;
  // A lesson keeps one map, every piece in one place for the whole lesson. Each scene is framed
  // on the pieces it shows: framed on the whole map, a first scene's two pieces were drawn small
  // in the middle of an empty frame (reviewed 2026-11-22). The scene's pieces never move within it.
  const pieces=(drawing?[block.querySelector(':scope > .semantic-graph')]
      :flow?[...block.querySelectorAll('.in-scene')].filter(e=>!e.parentElement.closest('.in-scene')):[])
    .map(e=>e.getBoundingClientRect()).filter(r=>r.width>0);
  const whole=block.getBoundingClientRect();
  const frame=pieces.length?{left:Math.min(...pieces.map(r=>r.left)),top:Math.min(...pieces.map(r=>r.top)),
    right:Math.max(...pieces.map(r=>r.right)),bottom:Math.max(...pieces.map(r=>r.bottom))}:whole;
  // room around the framed pieces for their arrows' labels and the lanes outside a row
  const pad=pieces.length&&pieces.length<block.querySelectorAll('.semantic-object').length?60:0;
  const w=frame.right-frame.left+pad*2,h=frame.bottom-frame.top+pad*2;
  const fit=Math.min(flow?1.3:drawing?1.7:1,sized||drawing?room.width*.96/w:1,(room.height*.96-lines)/h);
  block.style.zoom=fit;window.flowFit=fit;
  document.documentElement.style.setProperty('--fit',fit);
  // Centre the picture (the framed pieces, or the whole block) in the room above the lines of
  // text, which are pinned to the bottom so a large map cannot push them out of the frame.
  const now=pieces.length&&pad?[...block.querySelectorAll('.in-scene')]
      .filter(e=>!e.parentElement.closest('.in-scene')).map(e=>e.getBoundingClientRect()).filter(r=>r.width>0)
    :[block.getBoundingClientRect()];
  const cx=(Math.min(...now.map(r=>r.left))+Math.max(...now.map(r=>r.right)))/2;
  const cy=(Math.min(...now.map(r=>r.top))+Math.max(...now.map(r=>r.bottom)))/2;
  const bottom=band?band.getBoundingClientRect().top-parseFloat(getComputedStyle(stage).rowGap||0):room.bottom;
  block.style.position='relative';
  block.style.left=(pieces.length&&pad?((room.left+room.right)/2-cx)/fit:0)+'px';
  block.style.top=((room.top+bottom)/2-cy)/fit+'px';
};
window.routeConnection=(stage,svg,line,a,b,x1,y1,x2,y2)=>{
  const box=stage.getBoundingClientRect();
  if(Math.abs(y2-y1)<=14&&Math.abs(x2-x1)>40){
    // two pieces almost level: a slightly sloping arrow reads as a mistake, so draw it level
    y1=y2=(y1+y2)/2;line.setAttribute('y1',y1);line.setAttribute('y2',y2);
  }
  let points=[[x1,y1],[x2,y2]],labelX=(x1+x2)/2,labelY=(y1+y2)/2,bent=false,lane='',side=false;
  const rowA=a.closest('.semantic-row'),rowB=b.closest('.semantic-row');
  if(rowA&&rowB&&rowA!==rowB){
    // The flow wrapped to another row: leave the box, run along the empty gap between the two
    // rows, and enter the next box from that side. It never crosses a box, and each row still
    // reads left to right.
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect(),down=rb.top>=ra.top;
    const from=rowA.getBoundingClientRect(),to=rowB.getBoundingClientRect();
    const lane=((down?from.bottom:from.top)+(down?to.top:to.bottom))/2-box.top;
    const ax=ra.left+ra.width/2-box.left,bx=rb.left+rb.width/2-box.left;
    points=[[ax,(down?ra.bottom:ra.top)-box.top],[ax,lane],[bx,lane],
            [bx,(down?rb.top:rb.bottom)-box.top]];
    labelX=(ax+bx)/2;labelY=lane;bent=true;
  }else if(rowA&&rowA===rowB&&a.closest('.semantic-column')&&b.closest('.semantic-column')
      &&Math.abs([...rowA.children].indexOf(a.closest('.semantic-column'))
                 -[...rowA.children].indexOf(b.closest('.semantic-column')))>1){
    // The two pieces have other columns between them. Leave upward (or downward), run along a
    // lane outside the whole row, and come back in at the target: the arrow goes round the
    // pieces between, never through them. A second long arrow takes the next lane out.
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect(),row=rowA.getBoundingClientRect();
    const fit=window.flowFit||1;
    let above=(ra.top+rb.top)/2-row.top<=row.bottom-(ra.bottom+rb.bottom)/2;
    const taken=side=>svg.querySelectorAll(`path.edge[data-lane="${side}"]`).length;
    if(above&&row.top-box.top-(26+22*taken('above'))*fit<8)above=false;
    lane=above?'above':'below';
    const y=above?row.top-box.top-(26+22*taken('above'))*fit:row.bottom-box.top+(44+30*taken('below'))*fit;
    const ax=ra.left+ra.width/2-box.left,bx=rb.left+rb.width/2-box.left;
    points=[[ax,(above?ra.top:ra.bottom)-box.top],[ax,y],[bx,y],[bx,(above?rb.top:rb.bottom)-box.top]];
    labelX=(ax+bx)/2;labelY=y;bent=true;
  }else if(a.closest('.semantic-column')&&b.closest('.semantic-column')
      &&a.closest('.semantic-column')!==b.closest('.semantic-column')
      &&!a.contains(b)&&!b.contains(a)&&Math.abs(y2-y1)>14){
    // Two pieces in different columns at different heights: leave sideways, turn in the empty
    // gap between the columns, and arrive sideways. The turn never crosses a piece.
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect(),right=rb.left>=ra.left;
    const ca=a.closest('.semantic-column').getBoundingClientRect();
    const cb=b.closest('.semantic-column').getBoundingClientRect();
    const sx=(right?ra.right:ra.left)-box.left,ex=(right?rb.left:rb.right)-box.left;
    // Turn just outside the source's column, then run level into the target. The upright
    // stroke stays clear of a level arrow's label, which is centred in the same gap, and this
    // arrow's own label sits beside that stroke: the one part of it no other arrow shares, even
    // when a second arrow runs level into the same target.
    // Arrows leaving the same column each take their own lane, further out: sharing one, two
    // arrows ran as a single line and their labels landed on one spot (a health check beside a
    // load balancer, both pointing at servers).
    const column=(right?'r':'l')+Math.round(ca.left);
    const before=svg.querySelectorAll(`path.edge[data-turn="${column}"]`).length;
    const turn=(right?ca.right:ca.left)-box.left+(right?1:-1)*(12+16*before)*(window.flowFit||1);
    line.dataset.turn=column;
    const sy=ra.top+ra.height/2-box.top,ey=rb.top+rb.height/2-box.top;
    points=[[sx,sy],[turn,sy],[turn,ey],[ex,ey]];
    labelX=turn;labelY=(sy+ey)/2;bent=true;side=true;
    // A piece with several arrows out would stack them in the one gap, a turn through another
    // arrow's label. Leave from its top or bottom instead when nothing in its column is in the way.
    const several=JSON.parse(document.getElementById('relations').textContent)
      .filter(r=>r.source_id===a.dataset.objectId).length>1;
    const edge=(ey<sy?ra.top:ra.bottom)-box.top,low=Math.min(edge,ey)-8,high=Math.max(edge,ey)+8;
    const clear=![...a.closest('.semantic-column').querySelectorAll('[data-object-id]')]
      .filter(e=>e!==a&&!e.contains(a)&&!a.contains(e)).map(e=>e.getBoundingClientRect())
      .some(r=>r.bottom-box.top>low&&r.top-box.top<high);
    if(several&&clear){
      const cx=ra.left+ra.width/2-box.left;
      // the label sits on the part of the run that is clear of the source and its name
      const clear=right?Math.max(cx,ra.right-box.left):Math.min(cx,ra.left-box.left);
      points=[[cx,edge],[cx,ey],[ex,ey]];labelX=(clear+ex)/2;labelY=ey;side=false;
      delete line.dataset.turn;     // it leaves from the top or bottom, not through the lane
    }
  }else{
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
    const together=a.closest('.panel-body')&&a.closest('.panel-body')===b.closest('.panel-body');
    const blocked=together?[]:[...stage.querySelectorAll('[data-object-id]')].filter(e=>e!==a&&e!==b
        &&!e.contains(a)&&!e.contains(b)&&!a.contains(e)&&!b.contains(e)
        &&!e.classList.contains('semantic-caption-line'))
      .map(e=>e.getBoundingClientRect()).filter(intersects);
    if(blocked.length){
      bent=true;
      if(Math.abs(y2-y1)>=Math.abs(x2-x1)){
        let lane=Math.max(x1,x2,...blocked.map(r=>r.right-box.left))+28;
        if(lane>box.width-24)lane=Math.min(x1,x2,...blocked.map(r=>r.left-box.left))-28;
        points=[[x1,y1],[lane,y1],[lane,y2],[x2,y2]];labelX=lane;
      }else{
        let lane=Math.max(y1,y2,...blocked.map(r=>r.bottom-box.top))+28;
        if(lane>box.height-24)lane=Math.min(y1,y2,...blocked.map(r=>r.top-box.top))-28;
        points=[[x1,y1],[x1,lane],[x2,lane],[x2,y2]];labelY=lane;
      }
    }
  }
  if(bent){
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    for(const attr of ['class','marker-end'])path.setAttribute(attr,line.getAttribute(attr));
    path.setAttribute('d',points.map((p,i)=>(i?'L':'M')+' '+p.join(' ')).join(' '));
    path.dataset.sourceId=line.dataset.sourceId;path.dataset.targetId=line.dataset.targetId;
    if(lane)path.dataset.lane=lane;
    if(line.dataset.turn)path.dataset.turn=line.dataset.turn;
    line.replaceWith(path);line=path;
  }
  line.dataset.route=JSON.stringify(points);
  return {labelX,labelY,side};
};
"""
        script = script.replace("line.setAttribute('x1',x1);",
                                "line.dataset.sourceId=r.source_id;line.dataset.targetId=r.target_id;line.setAttribute('x1',x1);")
        script = script.replace("svg.querySelectorAll('line,text,marker')",
                                "svg.querySelectorAll('line,text,marker,path.edge')")
        script = script.replace("svg.append(line);if(r.label)",
                                "svg.append(line);const route=window.routeConnection(stage,svg,line,a,b,x1,y1,x2,y2);if(r.label)")
        label_from = script.index("if(r.label){")
        label_to = script.index("svg.append(label)}", label_from) + len("svg.append(label)}")
        script = script[:label_from] + _SEMANTIC_LABEL_JS + script[label_to:]
        script = script.replace("};window.drawConnections();",
                                "};window.fitFlow();window.drawConnections();")
        script = routing + script
        relations = _semantic_relations_json(scene)
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


def _ball_step(scene: BrowserScene, action, ball: list[str] | None) -> list[str] | None:
    """The arrow the ball is on after an action, as [source, target, colour]. Only a `trace` moves
    it: the diagram is built first, and the ball comes in when the flow is being explained."""
    if action.kind == "trace":
        ball = [*action.target_ids[-2:], _BALL.get(action.params.get("tone"), _BALL[None])]
    return ball


_BALL = {None: "#f4f4f5", "pink": "#f472b6", "purple": "#a78bfa", "teal": "#2dd4bf",
         "yellow": "#fbbf24", "blue": "#60a5fa", "green": "#4ade80", "white": "#f4f4f5",
         "red": "#f87171"}


def ball_after(scene: BrowserScene, beat: VisualBeat, ball: list[str] | None) -> list[str] | None:
    """Where the ball rests when a beat ends, as the [source, target] of the arrow it travelled."""
    for action in beat.actions:
        ball = _ball_step(scene, action, ball)
    return ball


def animation_html(scene: BrowserScene, beat: VisualBeat, *, title: str,
                   opening: VisualState, duration: float, layout_mode: str = "auto",
                   ball: list[str] | None = None) -> str:
    windows = beat.timeline(duration)
    state = deepcopy(opening)
    # what holds a place during this beat: what is on screen as it opens, and what this beat or a
    # later one of the scene brings on. The same for every moment of the beat, so nothing jumps.
    ahead = scene.beats[next((index for index, each in enumerate(scene.beats) if each is beat), 0):]
    room = set(opening.visible) | {target for each in ahead for action in each.actions
                                   if action.kind in _REVEALS for target in action.target_ids}
    snapshots = [_semantic_html(scene, state, room=room)]
    active: set[str] = set()
    rest = [ball]   # where the ball sits at each snapshot: it stays on the piece it last reached
    for action in beat.actions:
        apply_action(state, action)
        # an object being cleared away is not the step in progress
        current = set() if action.kind in {"hide", "deactivate"} else set(action.target_ids)
        active.update(current)
        snapshots.append(_semantic_html(scene, state, active, current, room))
        ball = _ball_step(scene, action, ball)
        rest.append(ball)
    data = json.dumps({"snapshots": snapshots, "windows": windows, "rest": rest,
                       "actions": [action.model_dump() for action in beat.actions],
                       "relations": [relation.model_dump() for relation in scene.relationships]},
                      ensure_ascii=False).replace("</", "<\\/")
    document = page_html(scene, title=title, state=opening, layout_mode=layout_mode)
    script = r"""
const plan=JSON.parse(document.getElementById('animation-plan').textContent);
const stage=document.querySelector('.semantic-stage');
let current=-2, animations=[], fresh=new Set();
const BRISK=.6, DRAW=.7, HOP=1.1, EASE='cubic-bezier(.45,0,.2,1)';
const ease=t=>t<.5?2*t*t:1-(2-2*t)*(2-2*t)/2;
const edges=()=>[...document.querySelectorAll('.connections line,.connections path.edge')];
const edgeKey=e=>e.dataset.sourceId+'>'+e.dataset.targetId;
function restBall(pair){
  // the ball waits at the end of the arrow it last travelled, on the piece being talked about
  const edge=pair&&edges().find(e=>edgeKey(e)===pair[0]+'>'+pair[1]);
  const back=!edge&&pair&&edges().find(e=>edgeKey(e)===pair[1]+'>'+pair[0]);
  if(!edge&&!back)return;
  // a reply rests where it arrived: at the start of the arrow it travelled backwards
  const points=JSON.parse((edge||back).dataset.route),end=edge?points[points.length-1]:points[0];
  const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
  dot.setAttribute('r','7');dot.setAttribute('fill',pair[2]||'#f4f4f5');dot.setAttribute('class','flow-ball');
  dot.setAttribute('transform',`translate(${end[0]} ${end[1]})`);
  document.querySelector('.connections').append(dot);
}
const nodes=()=>[...stage.querySelectorAll('[data-object-id],[data-visual-key]')];
const key=e=>e.dataset.visualKey||e.dataset.objectId;
function display(index){
  for(const animation of animations)animation.cancel();
  animations=[];
  document.querySelectorAll('.animation-ghost,.flow-packet,.flow-ball').forEach(e=>e.remove());
  fresh=new Set();
  stage.innerHTML=plan.snapshots[Math.max(0,index)];window.fitFlow();
  const before=new Map(nodes().map(e=>[key(e),{rect:e.getBoundingClientRect(),
    opacity:getComputedStyle(e).opacity,element:e.cloneNode(true),
    parent:e.parentElement.closest('[data-object-id],[data-visual-key]')?.dataset.objectId}]));
  window.drawConnections();
  if(index<0){restBall(plan.rest[0]);return;}
  const had=new Set(edges().map(edgeKey));
  stage.innerHTML=plan.snapshots[index+1];window.fitFlow();
  window.drawConnections();
  fresh=new Set(edges().map(edgeKey).filter(k=>!had.has(k)));   // these arrows draw themselves
  if(plan.actions[index].kind!=='trace')restBall(plan.rest[index+1]);
  const seconds=plan.windows[index][1]-plan.windows[index][0];
  // A change takes a brisk, eased moment at the start of its step and then holds, rather than
  // crawling at one speed for as long as the sentence lasts.
  const animate=(e,frames,most=BRISK,easing=EASE)=>{const a=e.animate(frames,{
    duration:Math.min(seconds,most)*1000,fill:'both',easing});a.pause();animations.push(a);};
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
  if(action.kind==='trace'){
    // The ball follows the named pieces along their arrows, one hop after another. `count` sends
    // several in a stream (a busy system); `tone` colours them (a failing request in red).
    const svg=document.querySelector('.connections'),points=[];
    let hops=0;
    for(let i=1;i<action.target_ids.length;i++){
      const edge=edges().find(e=>edgeKey(e)===action.target_ids[i-1]+'>'+action.target_ids[i]);
      const back=!edge&&edges().find(e=>edgeKey(e)===action.target_ids[i]+'>'+action.target_ids[i-1]);
      if(!edge&&!back)continue;
      const route=JSON.parse((edge||back).dataset.route);
      points.push(...(edge?route:route.reverse()));hops++;
    }
    const distances=[0];
    for(let i=1;i<points.length;i++)distances.push(distances[i-1]+
      Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));
    const total=distances[distances.length-1],count=action.params.count||1,gap=.14;
    const run=1-gap*(count-1),fill=plan.rest[index+1]?plan.rest[index+1][2]:'#f4f4f5';
    for(let k=0;points.length&&k<count;k++){
      const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
      dot.setAttribute('r','7');dot.setAttribute('fill',fill);dot.setAttribute('class','flow-packet');
      const start=gap*k,frames=points.map((p,i)=>({transform:`translate(${p[0]}px,${p[1]}px)`,
        opacity:1,offset:start+run*(total?distances[i]/total:i/(points.length-1))}));
      // a later ball waits unseen at the start; all but the last fade out on arrival
      if(start)frames.unshift({...frames[0],opacity:0,offset:0},{...frames[0],opacity:0,offset:start-.001});
      if(k<count-1)frames.push({...frames[frames.length-1],opacity:0,offset:1});
      svg.append(dot);animate(dot,frames,HOP*hops*(1+gap*(count-1)),count>1?'linear':EASE);
    }
  }
  if(action.kind==='set_state')searchMotion(action,before,animate);
}
// A graph search moves, not only changes colour (owner review, 2026-11-22: "the components are
// dynamic"). When a node is taken, a dot runs down each doorway to the nodes it has just found;
// when the path is found, a walker goes from the start to the goal and the path draws behind it.
function searchMotion(action,before,animate){
  const holder=stage.querySelector(`[data-object-id="${CSS.escape(action.target_ids[0])}"]`);
  const map=holder&&holder.querySelector('svg.graph-map');
  if(!map)return;
  const nodeOf=n=>map.querySelector(`[data-visual-key="${CSS.escape(action.target_ids[0]+':node:'+n)}"] circle`);
  const at=n=>{const c=nodeOf(n);return c&&[+c.getAttribute('cx'),+c.getAttribute('cy')];};
  const dot=(r,cls)=>{const d=document.createElementNS('http://www.w3.org/2000/svg','circle');
    d.setAttribute('r',r);d.setAttribute('class','flow-packet '+cls);map.append(d);return d;};
  const p=action.params||{};
  if(Array.isArray(p.path)&&p.path.length>1){
    // the walk takes .85 of the time; then the walker fades at the goal, so its name shows again
    const stops=p.path.map(at).filter(Boolean),hop=.7,total=hop*(stops.length-1)/.85,last=stops[stops.length-1];
    const walker=dot(13,'graph-walker');
    animate(walker,[...stops.map((s,i)=>({transform:`translate(${s[0]}px,${s[1]}px)`,opacity:1,
      offset:.85*i/(stops.length-1)})),{transform:`translate(${last[0]}px,${last[1]}px)`,opacity:0,offset:1}],
      total,'linear');
    for(let i=1;i<p.path.length;i++){
      const a=p.path[i-1],b=p.path[i],id=action.target_ids[0]+':edge:';
      const forward=map.querySelector(`[data-visual-key="${CSS.escape(id+a+'-'+b)}"]`);
      const edge=forward||map.querySelector(`[data-visual-key="${CSS.escape(id+b+'-'+a)}"]`);
      if(!edge)continue;
      // a line's own endpoints: getTotalLength throws on a line not yet rendered
      const length=Math.hypot(edge.x2.baseVal.value-edge.x1.baseVal.value,edge.y2.baseVal.value-edge.y1.baseVal.value),
        from=forward?length:-length;
      edge.style.strokeDasharray=length;
      const start=.85*(i-1)/(stops.length-1),end=.85*i/(stops.length-1);
      animate(edge,[{strokeDashoffset:from,offset:0},{strokeDashoffset:from,offset:start},
        {strokeDashoffset:0,offset:end},{strokeDashoffset:0,offset:1}],total,'linear');
    }
    return;
  }
  if(!p.current||!Array.isArray(p.frontier))return;
  const was=new Set([...before].filter(([,old])=>old.element.classList&&
    old.element.classList.contains('is-waiting')).map(([id])=>id.split(':node:')[1]));
  const from=at(p.current);
  if(!from)return;
  for(const n of p.frontier){
    const to=at(n);
    if(!to||was.has(n)||n===p.current)continue;
    animate(dot(10,'graph-scout'),[
      {transform:`translate(${from[0]}px,${from[1]}px)`,opacity:0,offset:0},
      {transform:`translate(${from[0]}px,${from[1]}px)`,opacity:1,offset:.2},
      {transform:`translate(${to[0]}px,${to[1]}px)`,opacity:1,offset:.85},
      {transform:`translate(${to[0]}px,${to[1]}px)`,opacity:0,offset:1}],HOP*1.3);
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
  }
  window.drawConnections();
  if(index>=0&&fresh.size){
    const span=Math.min(DRAW,plan.windows[index][1]-plan.windows[index][0]);
    const done=span?ease(Math.min(1,Math.max(0,(seconds-plan.windows[index][0])/span))):1;
    if(done<1)for(const edge of edges()){
      if(!fresh.has(edgeKey(edge)))continue;
      const length=edge.getTotalLength();
      edge.style.strokeDasharray=length;edge.style.strokeDashoffset=length*(1-done);
      edge.removeAttribute('marker-end');     // the arrowhead arrives with the end of the line
      const label=edge.nextElementSibling;    // its label fades in as the line is drawn
      if(label&&label.classList.contains('edge-label'))label.style.opacity=done;
    }
  }
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


# Frames are rasterised in software. The GPU path draws a soft shadow at a fractional position
# with a pixel that can differ by one level between two browser processes (measured: 2 of 14 runs,
# against 0 of 38 here), and a frame must not depend on which process drew it.
CAPTURE_ARGS = ["--disable-gpu"]


def render_animated_beat(scene: BrowserScene, beat: VisualBeat, out_mp4: str | Path, *,
                         title: str, opening: VisualState, duration: float,
                         audio: str | Path, fps: int = 30,
                         layout_mode: str = "auto", ball: list[str] | None = None) -> list[Path]:
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
                              duration=duration, layout_mode=layout_mode, ball=ball)
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
        browser = playwright.chromium.launch(executable_path=chrome_path(), headless=True,
                                             args=CAPTURE_ARGS)
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
        str(directory / "frame_%06d.png"), "-i", str(audio), "-af", "apad", "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out_mp4)], capture_output=True, timeout=300)
    if result.returncode or not out_mp4.exists():
        raise SlideRenderError(f"FFmpeg animated beat encode failed: {result.stderr.decode('utf-8','replace')[-500:]}")
    return frames
