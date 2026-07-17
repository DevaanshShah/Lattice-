// Lattice web client — editorial design, wired to the real FastAPI engine.
// State drives screen/phase; inputs are uncontrolled (read at action time) so typing never re-renders.
"use strict";

const state = {
  screen: "landing",              // landing | studio | gallery | learn
  phase: "prompt",                // prompt | outline | generating | result
  learnPhase: "input",            // input | generating | watch  (student Learn mode)
  learnInputMode: "describe",     // describe | image | code  (what the student gives)
  learnTopic: "",
  inputMode: "describe",          // describe | image | code  (Step-1 seed source)
  theme: "dark",
  projects: [],                   // GET /api/projects
  project: null,                  // current project_dto
  outline: [],                    // [{origIndex,title,intent,enabled}] before build
  selected: 0,                    // selected scene index in result
  length: "standard", quality: "high",
  gen: { pct: 0, label: "Warming up", sub: "", scenes: {}, log: [], detailsOpen: false },
  planning: false, busy: false, downloadOpen: false, subtitles: false,
  format: "youtube",              // youtube (16:9) | reel (9:16) — export reframe, not a re-render
  historyOpen: false, history: [], sideSearch: "", gallerySearch: "",
  editTab: "frames",              // frames | sound | motion  (video-editor edit mode)
  dragFrom: null,
  dev: { open: false, tab: "log", inspect: null, subtab: "code", source: null, loading: false, autoscroll: true },
};

const SUGGEST = ["the Fourier series", "how neural networks learn", "how RSA encryption works", "eigenvectors intuitively"];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const A = () => "var(--accent)";
const pad2 = (n) => String(n).padStart(2, "0");
const fmt = (x) => `${Math.floor(x / 60)}:${pad2(Math.floor(x % 60))}`;
function thumb(seed) {
  const px = 20 + ((seed * 37) % 60), py = 14 + ((seed * 53) % 40);
  return `position:absolute;inset:0;background:radial-gradient(120% 130% at ${px}% ${py}%, rgba(242,180,65,0.24), transparent 60%), repeating-linear-gradient(0deg, rgba(255,255,255,0.05) 0 1px, transparent 1px 15px), repeating-linear-gradient(90deg, rgba(255,255,255,0.05) 0 1px, transparent 1px 15px), #0B0B10;`;
}
const seedOf = (s) => 1.2 + (String(s).split("").reduce((a, c) => a + c.charCodeAt(0), 0) % 40) * 0.08;

// ---- API ---------------------------------------------------------------------------------
async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
async function loadProjects() { try { state.projects = (await api("GET", "/api/projects")).projects || []; } catch { state.projects = []; } }

function followJob(jobId, onProgress) {
  return new Promise((resolve) => {
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.addEventListener("progress", (e) => { try { const p = JSON.parse(e.data); onProgress(p); refreshDevStatus(p); } catch {} });
    es.addEventListener("log", (e) => { try { const m = JSON.parse(e.data).message; state.gen.log.push(m); if (state.gen.log.length > 3000) state.gen.log.splice(0, state.gen.log.length - 3000); appendDevLog(m); } catch {} });
    es.addEventListener("done", () => { es.close(); resolve(); });
    es.onerror = () => { es.close(); resolve(); };
  });
}

// ---- flows -------------------------------------------------------------------------------
// Shared: a fresh project_dto (from any seed — topic / image / code) -> the outline-review phase.
function enterOutline(p) {
  state.project = p;
  state.outline = p.scenes.map(s => ({ origIndex: s.index, title: s.title, intent: s.intent, enabled: true }));
  state.phase = "outline";
}
async function planTopic(topic) {
  topic = (topic || "").trim(); if (!topic) return;
  state.screen = "studio"; state.phase = "prompt"; state.planning = true; render();
  try { enterOutline(await api("POST", "/api/projects", { topic })); }
  catch (e) { alert("Couldn't plan: " + e.message); state.phase = "prompt"; }
  state.planning = false; render(); loadProjects();
}

// Downscale an image File to a JPEG data-URL (longest edge <= 1568px) — bounds the upload well under
// the server's ~5 MB cap and keeps the vision call cheap. Returns a data:image/jpeg;base64,... string.
function downscale(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const cap = 1568; let w = img.width, h = img.height;
      if (Math.max(w, h) > cap) { const r = cap / Math.max(w, h); w = Math.round(w * r); h = Math.round(h * r); }
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      c.getContext("2d").drawImage(img, 0, 0, w, h);
      resolve(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("couldn't read image")); };
    img.src = url;
  });
}
async function goFromImage(file) {
  if (!file) return;
  if (!/^image\/(png|jpe?g|webp)$/i.test(file.type)) { alert("Please choose a PNG, JPG, or WebP image."); return; }
  state.screen = "studio"; state.phase = "prompt"; state.planning = true; render();
  try {
    const image = await downscale(file);
    enterOutline(await api("POST", "/api/projects/from-image", { image }));
  } catch (e) { alert("Couldn't read that image: " + e.message); state.phase = "prompt"; }
  state.planning = false; render(); loadProjects();
}
async function goFromCode() {
  const t = $("seed-code"), code = t ? t.value.trim() : "";
  if (!code) { alert("Paste some code first."); return; }
  const ls = $("seed-lang"), lang = ls ? ls.value : "auto";
  state.screen = "studio"; state.phase = "prompt"; state.planning = true; render();
  try { enterOutline(await api("POST", "/api/projects/from-code", { code, language: lang === "auto" ? null : lang })); }
  catch (e) { alert("Couldn't read that code: " + e.message); state.phase = "prompt"; }
  state.planning = false; render(); loadProjects();
}
async function approveGenerate() {
  const keep = state.outline.filter(o => o.enabled).map(o => o.origIndex);
  if (!keep.length) return;
  state.phase = "generating"; state.gen = { pct: 0, label: "Reading your idea", sub: "", scenes: {}, log: [], detailsOpen: state.gen.detailsOpen }; render();
  try {
    const { job_id } = await api("POST", `/api/projects/${state.project.id}/build`, { keep, quality: state.quality });
    await followJob(job_id, (pr) => {
      state.gen.pct = Math.round(pr.pct || (pr.done && pr.total ? pr.done / pr.total * 100 : state.gen.pct));
      state.gen.label = pr.label || state.gen.label;
      state.gen.sub = pr.total ? `${pr.done || 0} of ${pr.total} scenes` : state.gen.sub;
      if (pr.scenes) state.gen.scenes = pr.scenes;
      renderGenProgress();
    });
    state.project = await api("GET", `/api/projects/${state.project.id}`);
    state.selected = 0; state.phase = "result";
  } catch (e) { alert("Build failed: " + e.message); state.phase = "outline"; }
  render(); loadProjects();
}
async function openProject(id) {
  try {
    state.project = await api("GET", `/api/projects/${id}`);
    state.screen = "studio"; state.phase = "result"; state.selected = 0; state.historyOpen = false;
    render();
  } catch (e) { alert(e.message); }
}
async function sceneJob(url, body) {
  state.busy = true; render();
  try { const { job_id } = await api("POST", url, body || {}); await followJob(job_id, () => {}); state.project = await api("GET", `/api/projects/${state.project.id}`); }
  catch (e) { alert(e.message); }
  state.busy = false; render();
}
async function structural(url, method, body) {
  state.busy = true; render();
  try { state.project = await api(method, url, body); }
  catch (e) { alert(e.message); }
  state.busy = false; render();
}

// ---- canvas (landing decoration only) ----------------------------------------------------
let RAF = null, fbuf = [], demoStart = 0;
const DEMO = "Explain the Fourier series — how any repeating wave is just a sum of simple sines.";
function sizeCanvas(c) {
  const dpr = window.devicePixelRatio || 1, r = c.getBoundingClientRect(); if (!r.width) return null;
  const w = Math.round(r.width), h = Math.round(r.height);
  if (c._w !== w || c._h !== h) { c.width = w * dpr; c.height = h * dpr; c._w = w; c._h = h; c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0); }
  return { ctx: c.getContext("2d"), w, h };
}
function loop(now) {
  const T = now / 1000;
  const lat = document.querySelector("canvas[data-lattice]"); if (lat) { const s = sizeCanvas(lat); if (s) drawLattice(s.ctx, s.w, s.h, T); }
  const fou = document.querySelector("canvas[data-fourier]"); if (fou) { const s = sizeCanvas(fou); if (s) drawFourier(s.ctx, s.w, s.h, T); tickDemo(T); }
  RAF = requestAnimationFrame(loop);
}
function drawLattice(ctx, w, h, t) {
  ctx.clearRect(0, 0, w, h); const sp = 44;
  ctx.lineWidth = 1; ctx.strokeStyle = "rgba(150,148,140,0.06)";
  for (let x = 0; x <= w; x += sp) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = 0; y <= h; y += sp) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  for (let x = 0; x <= w; x += sp) for (let y = 0; y <= h; y += sp) {
    const a = 0.05 + 0.14 * Math.max(0, Math.sin(t * 0.7 + x * 0.02 + y * 0.02));
    ctx.fillStyle = `rgba(242,180,65,${a})`; ctx.fillRect(x - 1, y - 1, 2, 2);
  }
}
function drawFourier(ctx, w, h, t) {
  const AC = "#F2B441"; ctx.fillStyle = "#0B0B10"; ctx.fillRect(0, 0, w, h);
  const sp = 34; ctx.lineWidth = 1; ctx.strokeStyle = "rgba(255,255,255,0.035)";
  for (let x = 0; x <= w; x += sp) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = 0; y <= h; y += sp) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  const cx = w * 0.28, cy = h * 0.5; ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();
  const amp = h * 0.2; let x = cx, y = cy;
  for (let i = 0; i < 5; i++) {
    const n = 2 * i + 1, r = amp * (4 / (Math.PI * n)), ang = n * t * 0.9 - Math.PI / 2, px = x, py = y;
    ctx.strokeStyle = "rgba(236,234,227,0.14)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.stroke();
    x += r * Math.cos(ang); y += r * Math.sin(ang);
    ctx.strokeStyle = AC; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
    ctx.fillStyle = AC; ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI * 2); ctx.fill();
  }
  const waveX0 = cx + amp + 24; fbuf.unshift(y - cy);
  const maxLen = Math.max(2, Math.floor((w - waveX0) / 2)); if (fbuf.length > maxLen) fbuf.length = maxLen;
  ctx.strokeStyle = "rgba(236,234,227,0.28)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(waveX0, cy + fbuf[0]); ctx.stroke();
  ctx.strokeStyle = AC; ctx.lineWidth = 2.4; ctx.shadowColor = AC; ctx.shadowBlur = 10; ctx.beginPath();
  for (let i = 0; i < fbuf.length; i++) { const px = waveX0 + i * 2, py = cy + fbuf[i]; i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); }
  ctx.stroke(); ctx.shadowBlur = 0;
}
function tickDemo(T) {
  const el = (T - demoStart) % 15, typed = document.querySelector("[data-typed]"), story = document.querySelector("[data-storyboard]");
  const status = document.querySelector("[data-demostatus]"), flabel = document.querySelector("[data-fourierlabel]");
  if (!typed) return;
  if (el < 4.2) { typed.textContent = DEMO.slice(0, Math.floor((el / 4.2) * DEMO.length)); if (story) story.style.opacity = "0"; if (status) status.textContent = "Reading your prompt"; if (flabel) flabel.textContent = "Warming up"; }
  else if (el < 6) { typed.textContent = DEMO; if (story) story.style.opacity = "1"; if (status) status.textContent = "Building the storyboard"; if (flabel) flabel.textContent = "Scene 02 · One circle, going round"; }
  else { typed.textContent = DEMO; if (story) story.style.opacity = "1"; if (status) status.textContent = "Animating · Scene 03"; if (flabel) flabel.textContent = "Scene 03 · Stacking the harmonics"; }
}

// ---- render ------------------------------------------------------------------------------
const MONO = "font-family:'Geist Mono',monospace;";
const DISPLAY = "font-family:'Bricolage Grotesque',sans-serif;";
const label = (txt, mb = 16) => `<div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--faint);margin-bottom:${mb}px;">${txt}</div>`;

function render() {
  const app = $("app");
  app.innerHTML = topbar() + (
    state.screen === "landing" ? landing() :
    state.screen === "learn" ? learnScreen() :
    state.screen === "gallery" ? gallery() : studio()
  ) + devToggle() + devConsole();
  wire();
  if (state.dev.open && state.dev.tab === "log") scrollDevLog();
}

// ---- developer console -------------------------------------------------------------------
function devToggle() {
  const active = state.busy || state.phase === "generating";
  return `<div data-act="dev-toggle" title="Developer console" style="position:fixed;right:18px;bottom:18px;z-index:60;display:flex;align-items:center;gap:8px;padding:9px 14px;border-radius:8px;cursor:pointer;background:var(--raise2);border:1px solid ${state.dev.open ? "var(--accent)" : "var(--line2)"};box-shadow:0 12px 32px -14px rgba(0,0,0,0.7);${MONO}font-size:11.5px;letter-spacing:0.08em;text-transform:uppercase;color:${state.dev.open ? "var(--accent)" : "var(--muted)"};">
    <span style="width:7px;height:7px;border-radius:50%;background:${active ? "var(--accent)" : "var(--faint)"};${active ? "animation:lt-pulse 1.2s ease-in-out infinite;" : ""}"></span>Dev</div>`;
}

function logLineHtml(msg) {
  const m = String(msg);
  let c = "var(--muted)";
  if (/\[llm#\d+\]\s+ok/.test(m)) c = "var(--ok)";
  else if (/\[llm#\d+\]\s+err|\[error\]|failed|Error/i.test(m)) c = "var(--danger)";
  else if (/\[llm#\d+\]/.test(m)) c = "var(--accent)";
  else if (/retry/i.test(m)) c = "#E8A13A";
  else if (/^\s*->/.test(m) || /^\s{2,}/.test(m)) c = "var(--text)";
  return `<div style="padding:2px 0;color:${c};white-space:pre-wrap;word-break:break-word;">${esc(m)}</div>`;
}

function devStatsHtml(p) {
  const log = state.gen.log;
  const started = log.filter(l => /\[llm#\d+\]\s+·/.test(l)).length;   // request lines
  const okd = log.filter(l => /\[llm#\d+\]\s+ok/.test(l)).length;
  const errd = log.filter(l => /\[llm#\d+\]\s+err/.test(l)).length;
  const scenes = (p && p.scenes) || state.gen.scenes || {};
  const chips = Object.entries(scenes).map(([i, st]) => {
    const done = /done/i.test(st), fail = /fail/i.test(st), rend = /render/i.test(st) || /retry/i.test(st);
    const col = done ? "var(--ok)" : fail ? "var(--danger)" : rend ? "var(--accent)" : "var(--faint)";
    return `<span title="Scene ${(+i) + 1}: ${esc(st)}" style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:5px;border:1px solid var(--line);${MONO}font-size:10.5px;color:${col};"><span style="width:6px;height:6px;border-radius:50%;background:${col};"></span>${pad2((+i) + 1)}</span>`;
  }).join("");
  const stat = (n, l, c) => `<div style="text-align:center;"><div style="${MONO}font-size:16px;color:${c};">${n}</div><div style="${MONO}font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);margin-top:2px;">${l}</div></div>`;
  return `<div id="dev-status">
    <div style="display:flex;gap:22px;justify-content:flex-start;padding:12px 16px;border-bottom:1px solid var(--line);">
      ${stat(started, "hits", "var(--accent)")}${stat(okd, "ok", "var(--ok)")}${stat(errd, "err", errd ? "var(--danger)" : "var(--faint)")}
    </div>
    ${chips ? `<div style="display:flex;flex-wrap:wrap;gap:6px;padding:12px 16px;border-bottom:1px solid var(--line);">${chips}</div>` : ""}
  </div>`;
}

function devConsole() {
  if (!state.dev.open) return "";
  const d = state.dev;
  const tabBtn = (k, l) => `<div data-act="dev-tab" data-v="${k}" style="${MONO}font-size:11px;letter-spacing:0.1em;text-transform:uppercase;cursor:pointer;padding:6px 2px;color:${d.tab === k ? "var(--text)" : "var(--muted)"};border-bottom:1.5px solid ${d.tab === k ? "var(--accent)" : "transparent"};">${l}</div>`;
  let inner;
  if (d.tab === "log") {
    const lines = state.gen.log.length ? state.gen.log.map(logLineHtml).join("") : `<div style="color:var(--faint);">No activity yet. Start or edit a build and every LLM hit, retry, and render step streams here live.</div>`;
    inner = `${devStatsHtml(state.project)}
      <div id="dev-log" class="lt-scroll" style="flex:1;overflow-y:auto;padding:12px 16px;${MONO}font-size:11.5px;line-height:1.5;min-height:0;">${lines}</div>
      <div style="flex:0 0 auto;display:flex;gap:8px;padding:10px 16px;border-top:1px solid var(--line);">
        <div data-act="dev-clear" class="lt-link" style="${MONO}font-size:11px;color:var(--muted);cursor:pointer;">Clear</div>
        <div style="flex:1;"></div>
        <div data-act="dev-autoscroll" class="lt-link" style="${MONO}font-size:11px;color:${d.autoscroll ? "var(--accent)" : "var(--muted)"};cursor:pointer;">${d.autoscroll ? "▾ Auto-scroll on" : "Auto-scroll off"}</div>
      </div>`;
  } else {
    inner = devScenesTab();
  }
  return `<div class="lt-snap" style="position:fixed;top:56px;right:0;bottom:0;width:min(560px,94vw);z-index:55;background:var(--bg2);border-left:1px solid var(--line2);display:flex;flex-direction:column;box-shadow:-24px 0 60px -30px rgba(0,0,0,0.8);">
    <div style="flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--line);">
      <div style="display:flex;align-items:center;gap:9px;"><span style="width:8px;height:8px;border-radius:2px;background:var(--accent);"></span><span style="${DISPLAY}font-size:15px;font-weight:600;color:var(--text);">Developer console</span></div>
      <div data-act="dev-toggle" style="width:28px;height:28px;border-radius:6px;display:grid;place-items:center;cursor:pointer;color:var(--muted);font-size:14px;">✕</div>
    </div>
    <div style="flex:0 0 auto;display:flex;gap:22px;padding:0 16px;border-bottom:1px solid var(--line);">${tabBtn("log", "Live log")}${tabBtn("scenes", "Scenes & prompts")}</div>
    ${inner}
  </div>`;
}

function devScenesTab() {
  const scenes = (state.project && state.project.scenes) || [];
  const d = state.dev;
  if (!scenes.length) return `<div style="padding:20px 16px;${MONO}font-size:12px;color:var(--faint);">No scenes yet — plan and build a video first.</div>`;
  const list = scenes.map((s, i) => `<div data-act="dev-inspect" data-i="${s.index}" style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;cursor:pointer;${d.inspect === s.index ? "background:var(--raise);" : ""}">
      <span style="${MONO}font-size:11px;color:var(--accent);">${pad2(i + 1)}</span>
      <span style="flex:1;min-width:0;font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(s.title)}</span>
      <span style="width:7px;height:7px;border-radius:50%;background:${s.built ? "var(--ok)" : "var(--faint)"};"></span>
    </div>`).join("");
  let detail;
  if (d.inspect == null) {
    detail = `<div style="padding:20px 16px;${MONO}font-size:12px;color:var(--faint);">Select a scene to inspect its generated code and the exact prompt the model was given.</div>`;
  } else if (d.loading) {
    detail = `<div style="padding:20px 16px;${MONO}font-size:12px;color:var(--muted);">Loading…</div>`;
  } else if (!d.source) {
    detail = `<div style="padding:20px 16px;${MONO}font-size:12px;color:var(--danger);">Couldn't load this scene's source.</div>`;
  } else {
    const src = d.source;
    const body = d.subtab === "code" ? (src.code || "(no code — scene not generated yet)")
      : d.subtab === "system" ? src.system_prompt
      : d.subtab === "user" ? src.user_prompt
      : d.subtab === "spec" ? (src.spec || "(no spec)")
      : (src.narration || []).join("\n") || "(no narration)";
    const sub = (k, l) => `<div data-act="dev-subtab" data-v="${k}" style="${MONO}font-size:10.5px;letter-spacing:0.06em;text-transform:uppercase;cursor:pointer;padding:5px 9px;border-radius:5px;${d.subtab === k ? "background:var(--accent);color:var(--ink);" : "color:var(--muted);border:1px solid var(--line);"}">${l}</div>`;
    detail = `<div style="flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);">
        <span style="${DISPLAY}font-size:14px;font-weight:600;color:var(--text);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(src.title)}</span>
        <button class="lt-btnp" data-act="dev-rerun" style="padding:6px 12px;border-radius:5px;border:none;background:var(--accent);color:var(--ink);${MONO}font-size:11px;font-weight:600;cursor:pointer;">↻ Rerun</button>
      </div>
      <div style="flex:0 0 auto;display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px;">${sub("code", "Code")}${sub("system", "System prompt")}${sub("user", "User prompt")}${sub("spec", "Spec")}${sub("narr", "Narration")}</div>
      <pre class="lt-scroll" style="flex:1;overflow:auto;margin:0;padding:12px 14px;${MONO}font-size:11px;line-height:1.55;color:var(--text);white-space:pre;min-height:0;background:var(--bg);border-top:1px solid var(--line);">${esc(body)}</pre>`;
  }
  return `<div style="flex:1;display:flex;min-height:0;">
    <div class="lt-scroll" style="flex:0 0 178px;overflow-y:auto;padding:8px;border-right:1px solid var(--line);min-height:0;">${list}</div>
    <div style="flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;">${detail}</div>
  </div>`;
}

function scrollDevLog() { const el = $("dev-log"); if (el && state.dev.autoscroll) el.scrollTop = el.scrollHeight; }
function appendDevLog(msg) {
  if (!state.dev.open || state.dev.tab !== "log") return;
  const el = $("dev-log"); if (!el) return;
  if (el.children.length === 1 && el.firstChild.style && el.firstChild.style.color === "var(--faint)") el.innerHTML = "";
  el.insertAdjacentHTML("beforeend", logLineHtml(msg));
  const s = $("dev-status"); if (s) s.outerHTML = devStatsHtml(state.project);
  scrollDevLog();
}
function refreshDevStatus(p) {
  if (!state.dev.open || state.dev.tab !== "log") return;
  const s = $("dev-status"); if (s) s.outerHTML = devStatsHtml(p);
}
async function loadSource(index) {
  state.dev.inspect = index; state.dev.loading = true; state.dev.source = null; render();
  try { state.dev.source = await api("GET", `/api/projects/${state.project.id}/scenes/${index}/source`); }
  catch { state.dev.source = null; }
  state.dev.loading = false; render();
}

function topbar() {
  const tab = (id, txt, on) => `<div data-act="tab-${id}" style="${MONO}font-size:11px;letter-spacing:0.1em;text-transform:uppercase;cursor:pointer;padding-bottom:3px;color:${on ? "var(--text)" : "var(--muted)"};border-bottom:1.5px solid ${on ? "var(--accent)" : "transparent"};">${txt}</div>`;
  return `<div style="height:56px;flex:0 0 56px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid var(--line);background:var(--bg2);position:relative;z-index:40;">
    <div data-act="home" style="display:flex;align-items:center;gap:11px;cursor:pointer;">
      <div style="width:24px;height:24px;position:relative;">
        <div style="position:absolute;inset:0;border:1.5px solid var(--accent);border-radius:3px;"></div>
        <div style="position:absolute;left:33%;top:0;bottom:0;width:1px;background:var(--accent);opacity:0.6;"></div>
        <div style="position:absolute;left:66%;top:0;bottom:0;width:1px;background:var(--accent);opacity:0.6;"></div>
        <div style="position:absolute;top:33%;left:0;right:0;height:1px;background:var(--accent);opacity:0.6;"></div>
        <div style="position:absolute;top:66%;left:0;right:0;height:1px;background:var(--accent);opacity:0.6;"></div>
      </div>
      <span style="${DISPLAY}font-weight:600;font-size:18px;letter-spacing:-0.02em;color:var(--text);">Lattice</span>
    </div>
    <div style="display:flex;align-items:center;gap:26px;">
      ${tab("home", "Home", state.screen === "landing")}${tab("learn", "Learn", state.screen === "learn")}${tab("studio", "Teach", state.screen === "studio")}${tab("gallery", "Gallery", state.screen === "gallery")}
    </div>
    <div style="display:flex;align-items:center;gap:12px;">
      <div data-act="replay-intro" title="Replay intro" style="width:34px;height:34px;border-radius:6px;border:1px solid var(--line);display:grid;place-items:center;cursor:pointer;color:var(--muted);font-size:15px;">↺</div>
      <div data-act="theme" title="Toggle theme" style="width:34px;height:34px;border-radius:6px;border:1px solid var(--line);display:grid;place-items:center;cursor:pointer;color:var(--muted);font-size:14px;">${state.theme === "dark" ? "☾" : "☀"}</div>
      <div style="width:26px;height:26px;border-radius:50%;background:var(--raise2);border:1px solid var(--line2);display:grid;place-items:center;font-size:11px;${MONO}color:var(--text);">AD</div>
    </div>
  </div>`;
}

function suggestRow(actName) {
  return `<div style="display:flex;align-items:center;gap:16px;margin-top:16px;${MONO}font-size:11.5px;letter-spacing:0.06em;color:var(--faint);flex-wrap:wrap;">
    <span style="text-transform:uppercase;">Try</span>
    ${SUGGEST.map(s => `<span class="lt-link" data-act="${actName}" data-v="${esc(s)}" style="cursor:pointer;color:var(--muted);">${esc(s)}</span>`).join("")}
  </div>`;
}

function landing() {
  const ex = state.projects.slice(0, 4);
  const exHtml = ex.length ? ex.map((p, i) => `
    <div class="lt-thumb" data-act="open" data-id="${esc(p.id)}" style="cursor:pointer;">
      <div style="position:relative;aspect-ratio:16/10;border-radius:6px;overflow:hidden;background:#0B0B10;"><div style="${thumb(seedOf(p.id))}"></div></div>
      <div style="display:flex;gap:9px;align-items:baseline;margin-top:11px;">
        <span style="${MONO}font-size:11px;color:var(--accent);">${pad2(i + 1)}</span>
        <span style="${DISPLAY}font-size:15px;font-weight:500;color:var(--text);line-height:1.2;letter-spacing:-0.01em;">${esc(p.topic)}</span>
      </div>
    </div>`).join("") : `<div style="grid-column:1/-1;${MONO}font-size:12px;color:var(--faint);">No videos yet — make your first above.</div>`;
  return `<div class="lt-scroll" style="flex:1;overflow-y:auto;position:relative;">
    <canvas data-lattice style="position:absolute;top:0;left:0;width:100%;height:560px;opacity:0.4;pointer-events:none;"></canvas>
    <div style="position:relative;max-width:1200px;margin:0 auto;padding:64px 40px 0;">
      <div class="lt-fade" style="display:flex;align-items:center;gap:10px;${MONO}font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:var(--muted);margin-bottom:26px;"><span style="width:22px;height:1px;background:var(--accent);"></span>Made-to-order explainers</div>
      <h1 class="lt-fade" style="${DISPLAY}font-size:clamp(44px,7.4vw,88px);line-height:0.98;letter-spacing:-0.035em;font-weight:600;margin:0 0 24px;color:var(--text);max-width:14ch;">Turn any idea into an <span style="color:var(--accent);">explainer video</span>.</h1>
      <p class="lt-fade" style="font-size:19px;line-height:1.5;color:var(--muted);max-width:48ch;margin:0 0 30px;">Describe a concept in a sentence. Lattice storyboards it, animates every idea, and narrates the whole thing — start to finish, no design or editing.</p>
      <div class="lt-fade" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:640px;margin:0 0 30px;">
        <div class="lt-thumb" data-act="go-learn" style="cursor:pointer;border:1px solid var(--line2);border-radius:12px;background:var(--raise);padding:22px;">
          <div style="font-size:26px;margin-bottom:10px;">📚</div>
          <div style="${DISPLAY}font-size:20px;font-weight:600;color:var(--text);margin-bottom:5px;">Learn</div>
          <div style="font-size:14px;color:var(--muted);line-height:1.45;">Ask about any concept — get a short animated explainer made for you. Just watch.</div>
        </div>
        <div class="lt-thumb" data-act="go-teach" style="cursor:pointer;border:1px solid var(--line2);border-radius:12px;background:var(--raise);padding:22px;">
          <div style="font-size:26px;margin-bottom:10px;">🎓</div>
          <div style="${DISPLAY}font-size:20px;font-weight:600;color:var(--text);margin-bottom:5px;">Teach</div>
          <div style="font-size:14px;color:var(--muted);line-height:1.45;">Build a lesson from a topic, image, or code — then edit scenes, sound, and timing in the studio.</div>
        </div>
      </div>
      <div class="lt-fade" style="max-width:640px;">
        <div style="display:flex;align-items:stretch;border:1px solid var(--line2);border-radius:8px;background:var(--raise);overflow:hidden;">
          <input id="landing-input" placeholder="Explain how neural networks learn…" style="flex:1;background:transparent;border:none;outline:none;font-size:16px;color:var(--text);padding:16px 18px;min-width:0;" />
          <button class="lt-btnp" data-act="landing-go" style="border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:15px;padding:0 24px;cursor:pointer;">Create video →</button>
        </div>
        ${suggestRow("sugg-landing")}
      </div>
      <div class="lt-fade" style="margin-top:54px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--bg2);">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid var(--line);${MONO}font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);"><span data-demostatus>Live · from prompt to preview</span><span>Fourier series</span></div>
        <div style="display:grid;grid-template-columns:0.82fr 1.18fr;min-height:340px;">
          <div style="padding:26px;border-right:1px solid var(--line);display:flex;flex-direction:column;">
            ${label("Your prompt")}
            <div style="font-size:20px;line-height:1.42;color:var(--text);font-weight:450;min-height:88px;"><span data-typed></span><span style="color:var(--accent);animation:lt-blink 1s step-end infinite;">▏</span></div>
            <div data-storyboard style="opacity:0;transition:opacity .5s ease;margin-top:20px;">
              <div style="${MONO}font-size:10.5px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:12px;">Storyboard · 6 scenes</div>
              ${["A wave nobody could explain", "One circle, going round", "Stacking the harmonics"].map((t, i) => `<div style="display:flex;gap:10px;align-items:baseline;margin-bottom:9px;"><span style="${MONO}font-size:11px;color:var(--faint);">${pad2(i + 1)}</span><span style="font-size:13.5px;color:var(--muted);">${t}</span></div>`).join("")}
            </div>
          </div>
          <div style="position:relative;background:#0B0B10;"><canvas data-fourier style="position:absolute;inset:0;width:100%;height:100%;display:block;"></canvas><div style="position:absolute;left:16px;bottom:14px;${MONO}font-size:11px;letter-spacing:0.08em;color:rgba(236,234,227,0.65);"><span data-fourierlabel>Scene 03 · Stacking the harmonics</span></div></div>
        </div>
      </div>
      <div style="margin:64px 0 0;">
        <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:22px;"><span style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--faint);">Watch a full one</span><span style="flex:1;height:1px;background:var(--line);"></span><span style="${MONO}font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);">92s · start to finish</span></div>
        <video id="lt-fullvideo" src="/static/fourier.mp4" poster="/static/fourier-poster.jpg" autoplay muted loop playsinline controls preload="metadata" style="width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#0B0B10;border:1px solid var(--line);border-radius:12px;"></video>
      </div>
      <div style="margin:64px 0 80px;">
        <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:22px;"><span style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--faint);">Made with Lattice</span><span style="flex:1;height:1px;background:var(--line);"></span></div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:22px;">${exHtml}</div>
      </div>
    </div>
  </div>`;
}

function sidebar() {
  const q = state.sideSearch.toLowerCase();
  const rows = state.projects.filter(p => (p.topic || "").toLowerCase().includes(q)).map(p => `
    <div class="lt-row" data-act="open" data-id="${esc(p.id)}" style="display:flex;align-items:center;gap:11px;padding:8px;border-radius:6px;cursor:pointer;${state.project && state.project.id === p.id ? "background:var(--raise);" : ""}">
      <div style="flex:0 0 44px;height:28px;border-radius:4px;overflow:hidden;position:relative;background:#0B0B10;"><div style="${thumb(seedOf(p.id))}"></div></div>
      <div style="flex:1;min-width:0;"><div style="font-size:13px;color:var(--text);font-weight:450;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(p.topic)}</div><div style="${MONO}font-size:10.5px;color:var(--faint);margin-top:1px;">${p.scenes || 0} scenes</div></div>
    </div>`).join("") || `<div style="${MONO}font-size:11px;color:var(--faint);padding:8px;">No projects yet.</div>`;
  return `<div style="flex:0 0 268px;display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--bg2);min-height:0;">
    <div style="padding:16px 16px 12px;"><button class="lt-btnp" data-act="new" style="width:100%;display:flex;align-items:center;justify-content:center;gap:8px;padding:11px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14px;cursor:pointer;">＋ New video</button></div>
    <div style="padding:0 16px 10px;"><div style="display:flex;align-items:center;gap:8px;padding:9px 11px;border-radius:6px;background:var(--raise);"><span style="color:var(--faint);font-size:13px;">⌕</span><input id="side-search" value="${esc(state.sideSearch)}" placeholder="Search projects" style="flex:1;background:transparent;border:none;outline:none;font-size:13px;color:var(--text);min-width:0;" /></div></div>
    ${label("Recent", 6).replace("margin-bottom:6px", "margin:8px 16px 6px")}
    <div class="lt-scroll" style="flex:1;overflow-y:auto;padding:2px 10px 10px;min-height:0;">${rows}</div>
    <div style="padding:14px 16px;border-top:1px solid var(--line);">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;"><span style="${MONO}font-size:10.5px;letter-spacing:0.1em;text-transform:uppercase;color:var(--muted);">Credits</span><span style="font-size:12px;color:var(--text);font-weight:500;${MONO}">∞</span></div>
      <div style="height:4px;border-radius:4px;background:var(--raise2);overflow:hidden;"><div style="height:100%;width:100%;border-radius:4px;background:var(--accent);"></div></div>
    </div>
  </div>`;
}

function studio() {
  const badges = { prompt: ["Draft", "var(--muted)"], outline: ["Storyboard", "var(--accent)"], generating: ["Generating", "var(--accent)"], result: ["Ready", "var(--ok)"] };
  const [bTxt, bCol] = badges[state.phase] || badges.prompt;
  const title = state.project ? state.project.topic : "Untitled video";
  let dl = "";
  if (state.phase === "result") {
    dl = `<button class="lt-btnp" data-act="dl-toggle" style="display:flex;align-items:center;gap:8px;padding:9px 16px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:13.5px;cursor:pointer;">↓ Download</button>`;
    const reel = state.format === "reel";
    if (state.downloadOpen) dl += `<div class="lt-snap" style="position:absolute;top:48px;right:0;width:248px;background:var(--raise);border:1px solid var(--line2);border-radius:8px;padding:14px;box-shadow:0 24px 60px -24px rgba(0,0,0,0.8);z-index:30;">
      ${label("Export", 10)}
      ${segmented("fmt", [["youtube", "YouTube"], ["reel", "Reel"]], state.format)}
      <div style="${MONO}font-size:10.5px;color:var(--faint);margin:7px 2px 2px;">${reel ? "1080&times;1920 &middot; 9:16 &middot; Shorts / TikTok" : "1920&times;1080 &middot; 16:9"}</div>
      <div style="height:1px;background:var(--line);margin:10px 0 4px;"></div>
      <div data-act="sub-toggle" style="display:flex;align-items:center;justify-content:space-between;padding:6px 2px;cursor:pointer;"><span style="font-size:13.5px;color:var(--text);">Burn in subtitles</span>${toggle(state.subtitles)}</div>
      <div style="height:1px;background:var(--line);margin:8px 0;"></div>
      <div class="lt-btnp" data-act="do-download" style="padding:10px;border-radius:6px;background:var(--accent);color:var(--ink);text-align:center;font-size:13.5px;cursor:pointer;font-weight:600;">Download MP4</div>
    </div>`;
  }
  const body = state.phase === "prompt" ? phasePrompt() : state.phase === "outline" ? phaseOutline() : state.phase === "generating" ? phaseGenerating() : phaseResult();
  return `<div style="flex:1;display:flex;min-height:0;">${sidebar()}
    <div class="lt-scroll" style="flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden;">
      <div style="flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:14px 26px;border-bottom:1px solid var(--line);">
        <div style="display:flex;align-items:center;gap:14px;min-width:0;"><span style="${DISPLAY}font-size:17px;font-weight:600;letter-spacing:-0.015em;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(title)}</span><span style="${MONO}font-size:10.5px;letter-spacing:0.08em;text-transform:uppercase;padding:3px 8px;border:1px solid var(--line);border-radius:4px;color:${bCol};white-space:nowrap;">${bTxt}</span></div>
        <div style="display:flex;align-items:center;gap:12px;position:relative;">${dl}</div>
      </div>
      <div class="lt-scroll" id="phase-body" style="flex:1;overflow-y:auto;min-height:0;">${body}</div>
    </div>
  </div>`;
}
function toggle(on) { return `<div style="width:36px;height:21px;border-radius:11px;padding:2px;cursor:pointer;background:${on ? "var(--accent)" : "var(--raise2)"};display:flex;${on ? "justify-content:flex-end;" : ""}"><div style="width:17px;height:17px;border-radius:50%;background:#fff;"></div></div>`; }
function segmented(name, opts, cur) { return `<div style="display:flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;">${opts.map(([k, l], i) => `<div data-act="${name}" data-v="${k}" style="padding:7px 13px;font-size:12.5px;cursor:pointer;${i ? "border-left:1px solid var(--line);" : ""}${cur === k ? "background:var(--accent);color:var(--ink);font-weight:500;" : "color:var(--muted);"}">${l}</div>`).join("")}</div>`; }

function phasePrompt() {
  if (state.planning) {
    const caps = {
      image: ["Reading your image…", "Looking at what it shows, then planning each scene."],
      code: ["Reading your code…", "Breaking it into a line-by-line walkthrough."],
    };
    const [ttl, sub] = caps[state.inputMode] || ["Sketching your storyboard…", "Reading your idea and planning each scene. This usually takes a few seconds."];
    return `<div class="lt-fade" style="max-width:520px;margin:0 auto;padding:110px 32px;display:flex;flex-direction:column;align-items:center;text-align:center;">
      <div style="width:42px;height:42px;border-radius:50%;border:2px solid var(--line2);border-top-color:var(--accent);animation:lt-spin 0.8s linear infinite;"></div>
      <div style="${DISPLAY}font-size:23px;font-weight:600;color:var(--text);margin-top:26px;letter-spacing:-0.02em;">${ttl}</div>
      <div style="color:var(--muted);font-size:14.5px;margin-top:8px;max-width:38ch;">${sub}</div>
    </div>`;
  }
  const subById = {
    describe: "Give Lattice a topic or a question. It handles the storyboard, the animation, and the narration.",
    image: "Upload a diagram, chart, screenshot, or a photo of code. Lattice works out the concept and explains it.",
    code: "Paste a function or snippet. Lattice walks through it line by line — what each part does and why.",
  };
  let card;
  if (state.inputMode === "image") {
    card = `<div id="seed-drop" style="border:1.5px dashed var(--line2);border-radius:10px;background:var(--raise);padding:46px 18px;text-align:center;transition:border-color .15s ease;">
      <input id="seed-file" type="file" accept="image/png,image/jpeg,image/webp" style="display:none;" />
      <div style="font-size:15.5px;color:var(--muted);margin-bottom:18px;">Drop an image here, or choose a file</div>
      <button class="lt-btnp" data-act="seed-pick" style="padding:11px 22px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14px;cursor:pointer;">Choose image</button>
      <div style="${MONO}font-size:11px;color:var(--faint);margin-top:18px;">PNG, JPG or WebP · diagram, chart, screenshot, or photo of code</div>
    </div>`;
  } else if (state.inputMode === "code") {
    const langs = ["auto", "python", "javascript", "typescript", "java", "c", "cpp", "go", "rust", "ruby", "sql"];
    const langOpts = langs.map(l => `<option value="${l}">${l === "auto" ? "Auto-detect" : l}</option>`).join("");
    card = `<div style="border:1px solid var(--line2);border-radius:10px;background:var(--raise);padding:18px;">
      <textarea id="seed-code" placeholder="Paste a function or snippet…" spellcheck="false" style="width:100%;min-height:186px;resize:vertical;background:transparent;border:none;outline:none;${MONO}font-size:13.5px;line-height:1.6;color:var(--text);"></textarea>
      <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-top:12px;flex-wrap:wrap;">
        <div><div style="${MONO}font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Language</div>
          <select id="seed-lang" style="background:var(--raise2);border:1px solid var(--line2);border-radius:6px;color:var(--text);font-size:13px;padding:8px 10px;outline:none;cursor:pointer;">${langOpts}</select></div>
        <button class="lt-btnp" data-act="seed-code-go" style="display:flex;align-items:center;gap:8px;padding:12px 22px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14.5px;cursor:pointer;">Generate walkthrough →</button>
      </div>
    </div>`;
  } else {
    card = `<div style="border:1px solid var(--line2);border-radius:10px;background:var(--raise);padding:18px;">
      <textarea id="prompt-text" placeholder="e.g. Explain the Fourier series — how any repeating wave is just a sum of simple sines…" style="width:100%;min-height:104px;resize:none;background:transparent;border:none;outline:none;font-size:17px;line-height:1.5;color:var(--text);"></textarea>
      <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-top:10px;flex-wrap:wrap;">
        <div style="display:flex;gap:22px;flex-wrap:wrap;">
          <div><div style="${MONO}font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Length</div>${segmented("len", [["short", "Short"], ["standard", "Standard"], ["deep", "Deep"]], state.length)}</div>
          <div><div style="${MONO}font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Quality</div>${segmented("qual", [["high", "High"], ["draft", "Draft"]], state.quality)}</div>
        </div>
        <button class="lt-btnp" data-act="storyboard" style="display:flex;align-items:center;gap:8px;padding:12px 22px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14.5px;cursor:pointer;">Storyboard it →</button>
      </div>
    </div>`;
  }
  return `<div class="lt-fade" style="max-width:720px;margin:0 auto;padding:72px 32px;">
    <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:16px;">Step 1 · The idea</div>
    <h2 style="${DISPLAY}font-size:38px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0 0 10px;line-height:1.02;">What do you want to explain?</h2>
    <p style="color:var(--muted);font-size:16px;margin:0 0 22px;max-width:52ch;">${subById[state.inputMode] || subById.describe}</p>
    <div style="margin-bottom:20px;">${segmented("mode", [["describe", "Describe"], ["image", "Image"], ["code", "Code"]], state.inputMode)}</div>
    ${card}
    ${state.inputMode === "describe" ? suggestRow("sugg-prompt") : ""}
  </div>`;
}

// The AI's chosen visual THEME (palette + fonts + object looks), shown at the review gate so the
// user checks it BEFORE building. Reads state.project.style (project_dto exposes it).
function themePanel() {
  const st = state.project && state.project.style;
  const wrap = "border:1px solid var(--line2);border-radius:10px;background:var(--raise);padding:16px 18px;margin-bottom:24px;";
  const head = `<div style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:12px;">Video theme</div>`;
  if (!st || (!Object.keys(st.palette || {}).length && !st.fonts)) {
    return `<div style="${wrap}">${head}<div style="${MONO}font-size:12px;color:var(--faint);">Using the default Lattice theme (clean dark, amber accent).</div></div>`;
  }
  const swatches = Object.entries(st.palette || {}).map(([name, hex]) => `
    <div style="display:flex;align-items:center;gap:8px;">
      <span style="width:22px;height:22px;border-radius:5px;background:${esc(hex)};border:1px solid var(--line2);flex:0 0 auto;"></span>
      <span style="display:flex;flex-direction:column;line-height:1.2;"><span style="font-size:12.5px;color:var(--text);text-transform:capitalize;">${esc(name)}</span><span style="${MONO}font-size:10px;color:var(--faint);">${esc(hex)}</span></span>
    </div>`).join("");
  const objs = Object.keys(st.object_styles || {}).length
    ? `<div style="margin-top:12px;${MONO}font-size:11px;color:var(--faint);">Objects: <span style="color:var(--muted);">${esc(Object.entries(st.object_styles).map(([k, v]) => `${k} → ${v}`).join(" · "))}</span></div>` : "";
  const fonts = st.fonts ? `<div style="margin-top:10px;font-size:12.5px;color:var(--muted);"><span style="${MONO}font-size:11px;color:var(--faint);">Type:</span> ${esc(st.fonts)}</div>` : "";
  return `<div style="${wrap}">${head}
    <div style="display:flex;flex-wrap:wrap;gap:16px 22px;">${swatches || `<span style="${MONO}font-size:12px;color:var(--faint);">no palette</span>`}</div>
    ${fonts}${objs}
    <div style="margin-top:12px;${MONO}font-size:10.5px;color:var(--faint);">This palette + type is applied consistently to every scene.</div>
  </div>`;
}

function phaseOutline() {
  const rows = state.outline.map((sc, i) => `
    <div draggable="true" data-drag="${i}" style="display:flex;gap:14px;align-items:flex-start;padding:16px 4px;border-bottom:1px solid var(--line);${sc.enabled ? "" : "opacity:0.45;"}">
      <div style="flex:0 0 auto;display:flex;align-items:baseline;gap:12px;padding-top:3px;cursor:grab;"><span style="font-size:13px;line-height:1;color:var(--faint);">⠿</span><span style="${MONO}font-size:13px;color:var(--accent);min-width:20px;">${pad2(i + 1)}</span></div>
      <div style="flex:1;min-width:0;">
        <input value="${esc(sc.title)}" data-act="ol-title" data-i="${i}" style="width:100%;background:transparent;border:none;outline:none;${DISPLAY}font-size:16px;font-weight:600;letter-spacing:-0.01em;color:var(--text);margin-bottom:3px;" />
        <input value="${esc(sc.intent)}" data-act="ol-desc" data-i="${i}" style="width:100%;background:transparent;border:none;outline:none;font-size:13px;color:var(--muted);" />
      </div>
      <div style="flex:0 0 auto;display:flex;align-items:center;gap:8px;"><div data-act="ol-toggle" data-i="${i}" title="Include">${toggle(sc.enabled)}</div><div data-act="ol-remove" data-i="${i}" title="Remove" style="width:30px;height:30px;border-radius:5px;display:grid;place-items:center;cursor:pointer;color:var(--faint);font-size:13px;">✕</div></div>
    </div>`).join("");
  const n = state.outline.filter(o => o.enabled).length;
  return `<div class="lt-fade" style="max-width:780px;margin:0 auto;padding:38px 32px 64px;">
    <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:14px;">Step 2 · Review theme &amp; storyboard</div>
    <h2 style="${DISPLAY}font-size:32px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0 0 8px;line-height:1.03;">Here's the plan for your video</h2>
    <p style="color:var(--muted);font-size:15px;margin:0 0 24px;">Check the theme and scenes the AI chose. Reorder or drop any scene. Nothing has been made yet.</p>
    ${themePanel()}
    <div style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin:6px 0 2px;">Storyboard</div>
    <div style="border-top:1px solid var(--line);">${rows}</div>
    <div data-act="ol-add" style="display:flex;align-items:center;gap:10px;padding:16px 4px;border-top:1px solid var(--line);color:var(--muted);font-size:13.5px;cursor:pointer;"><span style="color:var(--accent);font-size:15px;">＋</span> Add a scene</div>
    <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:26px;flex-wrap:wrap;">
      <span style="${MONO}font-size:12px;color:var(--faint);">${n} scenes · ~${Math.max(1, Math.round(n * 0.55))} min</span>
      <div style="display:flex;gap:10px;"><button data-act="back-prompt" style="padding:11px 16px;border-radius:6px;border:1px solid var(--line2);background:transparent;color:var(--text);font-weight:500;font-size:14px;cursor:pointer;">Back</button><button class="lt-btnp" data-act="approve" style="padding:11px 22px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14.5px;cursor:pointer;">Approve &amp; generate</button></div>
    </div>
  </div>`;
}

function phaseGenerating() {
  return `<div class="lt-fade" style="max-width:520px;margin:0 auto;padding:60px 32px;display:flex;flex-direction:column;align-items:center;" id="gen-root">${genInner()}</div>`;
}
function genInner() {
  const g = state.gen, pct = Math.max(0, Math.min(100, g.pct));
  const sceneRows = Object.entries(g.scenes || {}).map(([i, st]) => {
    const done = /done/i.test(st), fail = /fail/i.test(st);
    return `<div style="display:flex;align-items:center;gap:12px;padding:11px 14px;border-bottom:1px solid var(--line);"><span style="flex:0 0 auto;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:11px;${done ? "background:var(--accent);color:var(--ink);" : fail ? "border:1px solid var(--danger);color:var(--danger);" : "border:1px solid var(--accent);color:var(--accent);animation:lt-pulse 1.4s ease-in-out infinite;"}">${done ? "✓" : fail ? "!" : "•"}</span><span style="font-size:13.5px;color:var(--text);">Scene ${(+i) + 1} — ${esc(st)}</span></div>`;
  }).join("");
  return `<div style="position:relative;width:132px;height:210px;">
      <div style="position:absolute;inset:0;border-radius:10px;border:1px solid var(--line2);background:var(--raise);overflow:hidden;">
        <div style="position:absolute;left:0;right:0;bottom:0;height:${Math.max(5, pct)}%;overflow:hidden;transition:height .3s linear;">
          <div style="position:absolute;left:50%;top:-24px;width:200px;height:200px;border-radius:42%;background:var(--accent);opacity:0.9;animation:lt-wave 7s linear infinite;"></div>
          <div style="position:absolute;left:50%;top:-20px;width:200px;height:200px;border-radius:44%;background:var(--accent-deep);opacity:0.6;animation:lt-wave2 9s linear infinite;"></div>
        </div>
      </div>
      <div style="position:absolute;inset:0;display:grid;place-items:center;"><span style="${MONO}font-size:28px;font-weight:500;color:var(--text);mix-blend-mode:difference;">${pct}%</span></div>
    </div>
    <div style="margin-top:30px;text-align:center;"><div style="${DISPLAY}font-size:22px;font-weight:600;color:var(--text);letter-spacing:-0.02em;">${esc(g.label)}</div><div style="font-size:14px;color:var(--muted);margin-top:6px;">${esc(g.sub)}</div></div>
    <div data-act="gen-details" style="margin-top:26px;${MONO}font-size:11.5px;letter-spacing:0.06em;color:var(--muted);cursor:pointer;display:flex;align-items:center;gap:7px;">${g.detailsOpen ? "▾" : "▸"} Details</div>
    ${g.detailsOpen ? `<div class="lt-snap" style="margin-top:16px;width:100%;max-width:400px;border:1px solid var(--line);border-radius:8px;overflow:hidden;">${sceneRows || `<div style="padding:14px;${MONO}font-size:12px;color:var(--faint);">Starting…</div>`}</div>` : ""}`;
}
function renderGenProgress() { const r = $("gen-root"); if (r) r.innerHTML = genInner(); }

// duration proxy for the timeline (no backend duration yet): narration length ~ scene length.
function sceneDur(s) {
  const words = (s.narration || []).join(" ").trim().split(/\s+/).filter(Boolean).length;
  return Math.max(3, words / 2.6 + 1.0);
}
// A Filmora/Kinemaster-style timeline: clips sized to duration on a video track + an audio track, a
// ruler, and a playhead. Click a clip to select/edit; drag to reorder; per-clip ↻ regenerate / 🗑 delete.
function timeline(scenes) {
  const PXPS = 46;                                   // px per second
  const durs = scenes.map(sceneDur);
  const starts = []; let acc = 0; for (const d of durs) { starts.push(acc); acc += d; }
  const total = acc || 1;
  state.tl = { starts, pxps: PXPS };                 // wire() reads this to move the playhead
  const W = Math.max(660, total * PXPS + 60);
  let ticks = "";
  for (let t = 0; t <= total + 0.01; t += 5) ticks += `<div style="position:absolute;left:${t * PXPS}px;top:0;bottom:0;border-left:1px solid var(--line);"></div><span style="position:absolute;left:${t * PXPS + 4}px;top:3px;${MONO}font-size:9.5px;color:var(--faint);">${fmt(t)}</span>`;
  const mini = "display:grid;place-items:center;width:22px;height:22px;border-radius:5px;background:rgba(0,0,0,0.62);border:1px solid var(--line2);color:#fff;font-size:11px;cursor:pointer;";
  const clips = scenes.map((s, i) => {
    const on = i === state.selected, left = starts[i] * PXPS, w = Math.max(24, durs[i] * PXPS - 4);
    const acts = on ? `<div style="position:absolute;top:4px;right:4px;display:flex;gap:4px;">
        <span data-act="regen" title="Regenerate scene" style="${mini}">↻</span>
        <span data-act="delete" title="Delete scene" style="${mini}border-color:rgba(240,85,59,0.5);color:var(--danger);">🗑</span></div>` : "";
    return `<div draggable="true" data-drag2="${i}" data-act="select" data-i="${i}" style="position:absolute;left:${left}px;width:${w}px;top:0;bottom:0;border-radius:6px;overflow:hidden;cursor:pointer;border:2px solid ${on ? "var(--accent)" : "var(--line2)"};background:#0B0B10;">
      <div style="${thumb(seedOf(s.sid || s.index))}"></div>
      <div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0.05),rgba(0,0,0,0.6));"></div>
      <span style="position:absolute;top:5px;left:7px;${MONO}font-size:10px;color:#fff;text-shadow:0 1px 2px #000;">${pad2(i + 1)}</span>
      <span style="position:absolute;bottom:5px;left:7px;right:7px;font-size:11px;color:#fff;text-shadow:0 1px 2px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(s.title)}</span>
      ${s.built ? "" : `<span style="position:absolute;bottom:5px;right:7px;${MONO}font-size:9px;color:var(--danger);">unbuilt</span>`}${acts}
    </div>`;
  }).join("");
  const audio = scenes.map((s, i) => {
    const left = starts[i] * PXPS, w = Math.max(24, durs[i] * PXPS - 4);
    let bars = ""; const n = Math.max(3, Math.floor((w - 10) / 5));
    for (let b = 0; b < n; b++) { const h = 22 + (((s.index + 1) * 7 + b * 13) % 62); bars += `<span style="display:inline-block;width:2px;height:${h}%;margin-right:3px;background:var(--accent);opacity:0.5;border-radius:1px;"></span>`; }
    return `<div data-act="select" data-i="${i}" title="Narration" style="position:absolute;left:${left}px;width:${w}px;top:0;bottom:0;border-radius:5px;background:var(--raise2);border:1px solid ${i === state.selected ? "var(--accent)" : "var(--line)"};display:flex;align-items:center;padding:0 6px;overflow:hidden;cursor:pointer;">${bars}</div>`;
  }).join("");
  return `<div style="margin-top:22px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
      <span style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);">Timeline · ${scenes.length} scenes · ${fmt(total)}</span>
      <span style="${MONO}font-size:11px;color:var(--faint);">drag to reorder · click a clip to edit</span>
    </div>
    <div class="lt-scroll" style="overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--bg2);">
      <div style="position:relative;width:${W}px;min-width:100%;padding:0 0 8px;">
        <div style="position:relative;height:20px;border-bottom:1px solid var(--line);">${ticks}</div>
        <div style="${MONO}font-size:8.5px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);padding:6px 0 3px 6px;">Video</div>
        <div style="position:relative;height:56px;margin:0 0 2px;">${clips}<div data-act="insert-end" title="Add scene" style="position:absolute;left:${total * PXPS + 6}px;width:42px;top:0;bottom:0;border:1px dashed var(--line2);border-radius:6px;display:grid;place-items:center;color:var(--muted);cursor:pointer;">＋</div></div>
        <div style="${MONO}font-size:8.5px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);padding:6px 0 3px 6px;">🔊 Narration</div>
        <div style="position:relative;height:28px;">${audio}</div>
        <div id="playhead" style="position:absolute;top:20px;bottom:8px;left:${(starts[state.selected] || 0) * PXPS}px;width:2px;background:var(--accent);pointer-events:none;box-shadow:0 0 6px var(--accent);"><div style="position:absolute;top:-3px;left:-4px;width:10px;height:8px;background:var(--accent);border-radius:2px;"></div></div>
      </div>
    </div>
  </div>`;
}
// ---- Learn mode (student): ask / image / code -> auto plan+build -> watch (no editing) --------
function startLearn() { state.screen = "learn"; state.learnPhase = "input"; state.learnTopic = ""; render(); }
// Shared: a freshly-PLANNED project (from topic / image / code) -> auto-build at cheap Draft -> watch.
async function learnBuildAndWatch(p) {
  state.project = p; state.screen = "learn"; state.learnPhase = "generating";
  state.gen.label = "Building your lesson";
  render();
  try {
    const keep = (p.scenes || []).map(s => s.index);                               // auto-approve every scene
    const { job_id } = await api("POST", `/api/projects/${p.id}/build`, { keep, quality: "draft" }); // watch-only -> cheap
    await followJob(job_id, (pr) => {
      state.gen.pct = Math.round(pr.pct || (pr.done && pr.total ? pr.done / pr.total * 100 : state.gen.pct));
      state.gen.label = pr.label || state.gen.label;
      state.gen.sub = pr.total ? `${pr.done || 0} of ${pr.total} scenes` : state.gen.sub;
      if (pr.scenes) state.gen.scenes = pr.scenes;
      renderGenProgress();
    });
    state.project = await api("GET", `/api/projects/${p.id}`);
    state.selected = 0; state.learnPhase = "watch";
  } catch (e) { alert("Couldn't build the lesson: " + e.message); state.learnPhase = "input"; }
  render(); loadProjects();
}
function learnPlanning(label) { state.learnPhase = "generating"; state.gen = { pct: 0, label, sub: "", scenes: {}, log: [], detailsOpen: false }; render(); }
async function learnGo(topic) {
  topic = (topic || "").trim(); if (!topic) return;
  learnPlanning("Planning your lesson");
  try { await learnBuildAndWatch(await api("POST", "/api/projects", { topic })); }
  catch (e) { alert("Couldn't plan: " + e.message); state.learnPhase = "input"; render(); }
}
async function learnGoImage(file) {
  if (!file) return;
  if (!/^image\/(png|jpe?g|webp)$/i.test(file.type)) { alert("Use a PNG, JPG, or WebP image."); return; }
  learnPlanning("Reading your image");
  try { const image = await downscale(file); await learnBuildAndWatch(await api("POST", "/api/projects/from-image", { image })); }
  catch (e) { alert("Couldn't read that image: " + e.message); state.learnPhase = "input"; render(); }
}
async function learnGoCode() {
  const t = $("learn-code"), code = t ? t.value.trim() : "";
  if (!code) { alert("Paste some code first."); return; }
  const ls = $("learn-lang"), lang = ls ? ls.value : "auto";
  learnPlanning("Reading your code");
  try { await learnBuildAndWatch(await api("POST", "/api/projects/from-code", { code, language: lang === "auto" ? null : lang })); }
  catch (e) { alert("Couldn't read that code: " + e.message); state.learnPhase = "input"; render(); }
}
function learnScreen() {
  if (state.learnPhase === "generating") {
    return `<div class="lt-scroll" style="flex:1;overflow-y:auto;"><div id="gen-root" class="lt-fade" style="max-width:520px;margin:0 auto;padding:80px 32px;display:flex;flex-direction:column;align-items:center;">${genInner()}</div></div>`;
  }
  if (state.learnPhase === "watch" && state.project) {
    const p = state.project, built = (p.scenes || []).filter(s => s.built).length;
    return `<div class="lt-scroll" style="flex:1;overflow-y:auto;"><div class="lt-fade" style="max-width:900px;margin:0 auto;padding:40px 32px 80px;">
      <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:12px;">Your lesson</div>
      <h1 style="${DISPLAY}font-size:30px;font-weight:600;letter-spacing:-0.02em;color:var(--text);margin:0 0 20px;line-height:1.1;">${esc(p.topic)}</h1>
      <div style="border-radius:10px;overflow:hidden;background:#0B0B10;border:1px solid var(--line);"><div style="position:relative;aspect-ratio:16/9;"><video src="/api/projects/${p.id}/final?t=${Date.now()}" controls autoplay playsinline style="width:100%;height:100%;object-fit:contain;"></video></div></div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:20px;flex-wrap:wrap;">
        <span style="${MONO}font-size:12px;color:var(--faint);">${built} scenes · narrated</span>
        <div style="display:flex;gap:10px;">
          <button class="lt-btnp" data-act="learn-again" style="padding:11px 18px;border-radius:6px;border:1px solid var(--line2);background:transparent;color:var(--text);font-weight:500;font-size:14px;cursor:pointer;">Learn something else</button>
          <button class="lt-btnp" data-act="learn-edit" style="padding:11px 18px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14px;cursor:pointer;">Open in studio to edit →</button>
        </div>
      </div>
    </div></div>`;
  }
  const mode = state.learnInputMode || "describe";
  const langs = ["auto", "python", "javascript", "typescript", "java", "c", "cpp", "go", "rust", "ruby", "sql"];
  let card;
  if (mode === "image") {
    card = `<div id="learn-drop" style="border:1.5px dashed var(--line2);border-radius:12px;background:var(--raise);padding:44px 18px;text-align:center;transition:border-color .15s ease;">
      <input id="learn-file" type="file" accept="image/png,image/jpeg,image/webp" style="display:none;" />
      <div style="font-size:15.5px;color:var(--muted);margin-bottom:18px;">Drop a screenshot of code or a diagram — or choose a file</div>
      <button class="lt-btnp" data-act="learn-pick" style="padding:12px 22px;border-radius:7px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14px;cursor:pointer;">Choose image</button>
      <div style="${MONO}font-size:11px;color:var(--faint);margin-top:18px;">PNG, JPG or WebP · we read it and explain it</div>
    </div>`;
  } else if (mode === "code") {
    card = `<div style="border:1px solid var(--line2);border-radius:12px;background:var(--raise);padding:18px;">
      <textarea id="learn-code" placeholder="Paste code to have it explained, line by line…" spellcheck="false" style="width:100%;min-height:150px;resize:vertical;background:transparent;border:none;outline:none;${MONO}font-size:13.5px;line-height:1.6;color:var(--text);"></textarea>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;flex-wrap:wrap;">
        <select id="learn-lang" style="background:var(--raise2);border:1px solid var(--line2);border-radius:6px;color:var(--text);font-size:13px;padding:8px 10px;outline:none;cursor:pointer;">${langs.map(l => `<option value="${l}">${l === "auto" ? "Auto-detect" : l}</option>`).join("")}</select>
        <button class="lt-btnp" data-act="learn-code-go" style="padding:13px 26px;border-radius:7px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:15px;cursor:pointer;">Explain this code →</button>
      </div>
    </div>`;
  } else {
    card = `<div style="border:1px solid var(--line2);border-radius:12px;background:var(--raise);padding:18px;">
      <textarea id="learn-input" placeholder="e.g. How does gradient descent find the minimum? · Explain the Fourier series" style="width:100%;min-height:96px;resize:none;background:transparent;border:none;outline:none;font-size:17px;line-height:1.5;color:var(--text);"></textarea>
      <div style="display:flex;justify-content:flex-end;margin-top:12px;">
        <button class="lt-btnp" data-act="learn-go" style="padding:13px 26px;border-radius:7px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:15px;cursor:pointer;">Learn this →</button>
      </div>
    </div>`;
  }
  return `<div class="lt-scroll" style="flex:1;overflow-y:auto;"><div class="lt-fade" style="max-width:680px;margin:0 auto;padding:80px 32px;">
    <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:16px;">Learn</div>
    <h1 style="${DISPLAY}font-size:44px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0 0 12px;line-height:1.0;">What do you want to learn?</h1>
    <p style="color:var(--muted);font-size:17px;margin:0 0 24px;max-width:50ch;">Ask a question, drop a screenshot of code or a diagram, or paste code — and get a short animated explainer.</p>
    <div style="margin-bottom:18px;">${segmented("learn-mode", [["describe", "Ask"], ["image", "Image"], ["code", "Code"]], mode)}</div>
    ${card}
    ${mode === "describe" ? suggestRow("sugg-learn") : ""}
  </div></div>`;
}
function phaseResult() {
  const scenes = (state.project && state.project.scenes) || [];
  const sel = scenes[state.selected] || scenes[0];
  const pid = state.project.id;
  const bust = Date.now();
  const player = sel && sel.built ? `<video id="main-player" src="/api/projects/${pid}/scenes/${sel.index}/preview?t=${bust}" controls playsinline style="width:100%;height:100%;object-fit:contain;background:#0B0B10;"></video>` : `<div style="position:absolute;inset:0;display:grid;place-items:center;${MONO}font-size:12px;color:var(--faint);">Scene not rendered</div>`;
  return `<div class="lt-fade" style="max-width:1140px;margin:0 auto;padding:26px 26px 64px;">
    <div style="width:100%;max-width:calc(54vh * 16 / 9);margin:0 auto;border-radius:8px;overflow:hidden;background:#0B0B10;border:1px solid var(--line);"><div style="position:relative;aspect-ratio:16/9;">${player}</div></div>
    ${timeline(scenes)}
    ${sel ? editorPanel(sel) : ""}
  </div>`;
}
// The video-editor edit-mode switch: Frames (visuals) · Sound (narration) · Motion (re-animate).
const EDIT_TABS = [
  ["frames", "🎞", "Frames", "Visuals"],
  ["sound", "🔊", "Sound", "Narration"],
  ["motion", "🎬", "Motion", "Re-animate"],
];
function editTabBar() {
  return `<div style="display:flex;gap:6px;padding:5px;border:1px solid var(--line2);border-radius:9px;background:var(--raise);margin-bottom:16px;">
    ${EDIT_TABS.map(([k, ic, l, sub]) => { const on = state.editTab === k; return `<div data-act="edit-tab" data-v="${k}" style="flex:1;display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:6px;cursor:pointer;${on ? "background:var(--accent);" : ""}">
      <span style="font-size:16px;line-height:1;filter:${on ? "grayscale(1) brightness(0);" : "none"};">${ic}</span>
      <span style="display:flex;flex-direction:column;line-height:1.15;min-width:0;">
        <span style="font-size:13.5px;font-weight:600;color:${on ? "var(--ink)" : "var(--text)"};">${l}</span>
        <span style="${MONO}font-size:9.5px;letter-spacing:0.06em;text-transform:uppercase;color:${on ? "rgba(14,14,18,0.62)" : "var(--faint)"};">${sub}</span>
      </span></div>`; }).join("")}
  </div>`;
}
function editTabBody(sel) {
  const primary = "padding:0 18px;height:42px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:13.5px;cursor:pointer;white-space:nowrap;";
  const hint = `${MONO}font-size:11.5px;line-height:1.5;color:var(--faint);margin-bottom:12px;`;
  if (state.editTab === "sound") {
    return `<div class="lt-snap">
      <div style="${hint}">Edit the spoken narration — one line per beat. Saving re-voices the scene with the new script.</div>
      <div style="border:1px solid var(--line2);border-radius:8px;background:var(--raise2);padding:12px 14px;">
        <textarea id="narr-input" placeholder="What the narrator says over this scene…" style="width:100%;min-height:120px;resize:vertical;background:transparent;border:none;outline:none;font-size:14px;line-height:1.6;color:var(--text);">${esc((sel.narration || []).join("\n"))}</textarea>
      </div>
      <div style="display:flex;justify-content:flex-end;margin-top:12px;">
        <button class="lt-btnp" data-act="save-narr" style="${primary}">🔊 Save &amp; re-voice</button>
      </div>
    </div>`;
  }
  if (state.editTab === "motion") {
    return `<div class="lt-snap">
      <div style="${hint}">Regenerate the animation for a fresh take on how this scene moves. Leave the box blank for a new roll, or describe the motion you want.</div>
      <input id="motion-input" placeholder="Optional: e.g. slower reveal, pan across the graph, build up piece by piece" style="width:100%;height:42px;padding:0 13px;border-radius:6px;border:1px solid var(--line2);background:var(--raise2);outline:none;font-size:13.5px;color:var(--text);margin-bottom:12px;" />
      <div style="display:flex;justify-content:flex-end;">
        <button class="lt-btnp" data-act="motion-apply" style="${primary}">🎬 Regenerate motion</button>
      </div>
    </div>`;
  }
  // frames (default): change what's on screen
  return `<div class="lt-snap">
    <div style="${hint}">Change what's on screen — colors, labels, what's shown, layout. Describe the change in plain words.</div>
    <div style="display:flex;gap:8px;">
      <input id="tweak-input" placeholder="e.g. make the wave amber · label the axes · move the graph up" style="flex:1;height:42px;padding:0 13px;border-radius:6px;border:1px solid var(--line2);background:var(--raise2);outline:none;font-size:13.5px;color:var(--text);min-width:0;" />
      <button class="lt-btnp" data-act="tweak" style="${primary}">🎞 Apply</button>
    </div>
  </div>`;
}
function editorPanel(sel) {
  const versions = state.historyOpen ? (state.history || []) : null;
  const util = "display:flex;align-items:center;gap:7px;padding:8px 14px;border-radius:6px;border:1px solid var(--line2);background:transparent;color:var(--text);font-weight:500;font-size:12.5px;cursor:pointer;";
  const danger = "display:flex;align-items:center;gap:7px;padding:8px 14px;border-radius:6px;border:1px solid rgba(240,85,59,0.32);background:transparent;color:var(--danger);font-weight:500;font-size:12.5px;cursor:pointer;";
  return `<div class="lt-snap" style="margin-top:22px;display:grid;grid-template-columns:340px 1fr;gap:22px;border-top:1px solid var(--line2);padding-top:22px;">
    <div>
      <div style="position:relative;aspect-ratio:16/9;border-radius:6px;overflow:hidden;background:#0B0B10;">${sel.built ? `<video src="/api/projects/${state.project.id}/scenes/${sel.index}/preview?t=${Date.now()}" controls playsinline style="width:100%;height:100%;object-fit:contain;"></video>` : `<div style="${thumb(seedOf(sel.sid || sel.index))}"></div>`}<span style="position:absolute;top:8px;left:9px;font-size:10.5px;${MONO}color:rgba(236,234,227,0.8);pointer-events:none;">Scene ${state.selected + 1}</span></div>
      <div style="${DISPLAY}font-size:19px;font-weight:600;color:var(--text);letter-spacing:-0.015em;margin-top:14px;">${esc(sel.title)}</div>
      <div style="${MONO}font-size:11px;color:var(--faint);margin-top:3px;">scene ${state.selected + 1} of ${state.project.scenes.length}</div>
    </div>
    <div style="min-width:0;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;"><span style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);">Edit studio</span>${state.busy ? `<span style="${MONO}font-size:11px;color:var(--accent);display:flex;align-items:center;gap:6px;"><span style="width:7px;height:7px;border-radius:50%;background:var(--accent);animation:lt-pulse 1.2s ease-in-out infinite;"></span>working…</span>` : ""}</div>
      ${editTabBar()}
      ${editTabBody(sel)}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px;padding-top:16px;border-top:1px solid var(--line);">
        <button class="lt-act" style="${util}" data-act="insert-after">＋ Insert after</button>
        <button class="lt-act" style="${util}" data-act="history">↺ History</button>
        <button class="lt-act" style="${danger}" data-act="delete">🗑 Delete</button>
      </div>
      ${versions ? `<div class="lt-snap" style="margin-top:14px;border:1px solid var(--line);border-radius:6px;overflow:hidden;"><div style="padding:9px 14px;${MONO}font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);background:var(--raise);">Version history</div>${versions.length ? versions.map(v => `<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-top:1px solid var(--line);"><div><div style="font-size:13px;color:var(--text);">v${v.version}${v.label ? " · " + esc(v.label) : ""}</div></div><div data-act="rollback" data-v="${v.version}" style="${MONO}font-size:11px;color:var(--accent);padding:5px 10px;border:1px solid var(--line2);border-radius:5px;cursor:pointer;">Restore</div></div>`).join("") : `<div style="padding:12px 14px;${MONO}font-size:12px;color:var(--faint);">No saved versions yet.</div>`}</div>` : ""}
    </div>
  </div>`;
}

function gallery() {
  const q = state.gallerySearch.toLowerCase();
  const items = state.projects.filter(p => (p.topic || "").toLowerCase().includes(q));
  const grid = items.map((p, i) => `
    <div class="lt-thumb" data-act="open" data-id="${esc(p.id)}" style="cursor:pointer;">
      <div style="position:relative;aspect-ratio:16/9;border-radius:6px;overflow:hidden;background:#0B0B10;"><div style="${thumb(seedOf(p.id))}"></div></div>
      <div style="display:flex;gap:10px;align-items:baseline;margin-top:12px;"><span style="${MONO}font-size:11px;color:var(--accent);">${pad2(i + 1)}</span><div style="min-width:0;"><div style="${DISPLAY}font-size:15.5px;font-weight:500;color:var(--text);line-height:1.2;letter-spacing:-0.01em;">${esc(p.topic)}</div><div style="${MONO}font-size:10.5px;color:var(--faint);margin-top:4px;">${p.scenes || 0} scenes${p.built ? " · ready" : ""}</div></div></div>
    </div>`).join("");
  return `<div class="lt-scroll" style="flex:1;overflow-y:auto;"><div style="max-width:1140px;margin:0 auto;padding:44px 40px 80px;">
    <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:30px;">
      <div>${label(`${items.length} projects`, 12)}<h1 style="${DISPLAY}font-size:40px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0;line-height:1;">Your videos</h1></div>
      <div style="display:flex;align-items:center;gap:8px;padding:10px 13px;border-radius:6px;background:var(--raise);border:1px solid var(--line);width:300px;max-width:100%;"><span style="color:var(--faint);font-size:14px;">⌕</span><input id="gallery-search" value="${esc(state.gallerySearch)}" placeholder="Search your videos" style="flex:1;background:transparent;border:none;outline:none;font-size:14px;color:var(--text);min-width:0;" /></div>
    </div>
    ${items.length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(256px,1fr));gap:26px 24px;">${grid}</div>` : `<div style="text-align:center;padding:80px 0;color:var(--faint);${MONO}font-size:13px;">No videos yet — make one in the Studio.</div>`}
  </div></div>`;
}

// ---- events ------------------------------------------------------------------------------
function wire() {
  const app = $("app");
  app.onclick = (e) => { const el = e.target.closest("[data-act]"); if (el) handle(el.dataset.act, el); };
  // Enter-to-submit for key inputs
  const li = $("landing-input"); if (li) li.onkeydown = (e) => { if (e.key === "Enter") planTopic(li.value); };
  const le = $("learn-input"); if (le) le.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); learnGo(le.value); } };
  const lf = $("learn-file"); if (lf) lf.onchange = (e) => { const f = e.target.files && e.target.files[0]; if (f) learnGoImage(f); };
  const ld = $("learn-drop");
  if (ld) {
    ld.ondragover = (e) => { e.preventDefault(); ld.style.borderColor = "var(--accent)"; };
    ld.ondragleave = () => { ld.style.borderColor = "var(--line2)"; };
    ld.ondrop = (e) => { e.preventDefault(); ld.style.borderColor = "var(--line2)"; const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) learnGoImage(f); };
  }
  const tw = $("tweak-input"); if (tw) tw.onkeydown = (e) => { if (e.key === "Enter") handle("tweak"); };
  const mo = $("motion-input"); if (mo) mo.onkeydown = (e) => { if (e.key === "Enter") handle("motion-apply"); };
  // timeline playhead follows the player: global time = selected scene's start + player currentTime
  const mv = $("main-player");
  if (mv && state.tl) {
    const move = () => { const ph = $("playhead"); if (ph) ph.style.left = (((state.tl.starts[state.selected] || 0) + (mv.currentTime || 0)) * state.tl.pxps) + "px"; };
    mv.ontimeupdate = move; move();
  }
  const ss = $("side-search"); if (ss) ss.oninput = (e) => { state.sideSearch = e.target.value; rerenderSidebarList(); };
  const gs = $("gallery-search"); if (gs) gs.oninput = (e) => { state.gallerySearch = e.target.value; render(); const g = $("gallery-search"); if (g) { g.focus(); g.setSelectionRange(g.value.length, g.value.length); } };
  // image seed: file picker + drag-drop on the dropzone
  const sf = $("seed-file"); if (sf) sf.onchange = (e) => { const f = e.target.files && e.target.files[0]; if (f) goFromImage(f); };
  const drop = $("seed-drop");
  if (drop) {
    drop.ondragover = (e) => { e.preventDefault(); drop.style.borderColor = "var(--accent)"; };
    drop.ondragleave = () => { drop.style.borderColor = "var(--line2)"; };
    drop.ondrop = (e) => { e.preventDefault(); drop.style.borderColor = "var(--line2)"; const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) goFromImage(f); };
  }
  // outline drag-reorder
  app.querySelectorAll("[data-drag]").forEach(el => {
    el.ondragstart = () => { state.dragFrom = +el.dataset.drag; };
    el.ondragover = (e) => e.preventDefault();
    el.ondrop = (e) => { e.preventDefault(); const to = +el.dataset.drag; reorderOutline(state.dragFrom, to); };
  });
  app.querySelectorAll("[data-drag2]").forEach(el => {
    el.ondragstart = () => { state.dragFrom = +el.dataset.drag2; };
    el.ondragover = (e) => e.preventDefault();
    el.ondrop = (e) => { e.preventDefault(); const to = +el.dataset.drag2; if (state.dragFrom != null && state.dragFrom !== to) structural(`/api/projects/${state.project.id}/scenes/reorder`, "POST", { frm: state.dragFrom, to }); };
  });
}
function rerenderSidebarList() {
  const q = state.sideSearch.toLowerCase();
  document.querySelectorAll("#app .lt-row[data-act='open']").forEach(row => {
    row.style.display = row.textContent.toLowerCase().includes(q) ? "" : "none";
  });
}
function reorderOutline(from, to) { if (from == null || from === to) return; const a = state.outline; const [m] = a.splice(from, 1); a.splice(to, 0, m); render(); }

function handle(act, el) {
  const i = el ? +el.dataset.i : undefined, v = el ? el.dataset.v : undefined, id = el ? el.dataset.id : undefined;
  const pid = state.project && state.project.id;
  switch (act) {
    case "replay-intro": if (window.playLatticeIntro) window.playLatticeIntro(); break;
    case "home": state.screen = "landing"; render(); break;
    case "tab-home": state.screen = "landing"; render(); break;
    case "tab-learn": state.screen = "learn"; if (state.learnPhase === "generating") state.learnPhase = "input"; render(); break;
    case "tab-studio": state.screen = "studio"; render(); break;
    case "tab-gallery": state.screen = "gallery"; render(); break;
    case "theme": state.theme = state.theme === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", state.theme); break;
    case "open": openProject(id); break;
    case "new": state.screen = "studio"; state.phase = "prompt"; state.project = null; state.outline = []; render(); break;
    case "landing-go": planTopic($("landing-input").value); break;
    case "sugg-landing": { const el2 = $("landing-input"); if (el2) el2.value = "Explain " + v; break; }
    case "sugg-prompt": { const el2 = $("prompt-text"); if (el2) el2.value = "Explain " + v; break; }
    case "go-teach": state.screen = "studio"; state.phase = "prompt"; state.project = null; state.outline = []; render(); break;
    case "go-learn": startLearn(); break;
    case "learn-mode": state.learnInputMode = v; render(); break;
    case "learn-pick": { const f = $("learn-file"); if (f) f.click(); break; }
    case "learn-code-go": learnGoCode(); break;
    case "learn-go": learnGo($("learn-input").value); break;
    case "learn-again": state.learnPhase = "input"; state.learnTopic = ""; state.project = null; render(); break;
    case "learn-edit": state.screen = "studio"; state.phase = "result"; state.selected = 0; render(); break;
    case "sugg-learn": { const el2 = $("learn-input"); if (el2) el2.value = "Explain " + v; break; }
    case "len": state.length = v; render(); break;
    case "qual": state.quality = v; render(); break;
    case "mode": state.inputMode = v; render(); break;
    case "seed-pick": { const f = $("seed-file"); if (f) f.click(); break; }
    case "seed-code-go": goFromCode(); break;
    case "storyboard": planTopic($("prompt-text").value); break;
    case "ol-title": break; case "ol-desc": break; // uncontrolled, cosmetic
    case "ol-toggle": state.outline[i].enabled = !state.outline[i].enabled; render(); break;
    case "ol-remove": state.outline.splice(i, 1); render(); break;
    case "ol-add": state.outline.push({ origIndex: -1, title: "New scene", intent: "Describe what happens here.", enabled: true }); render(); break;
    case "back-prompt": state.phase = "prompt"; render(); break;
    case "approve": approveGenerate(); break;
    case "gen-details": state.gen.detailsOpen = !state.gen.detailsOpen; renderGenProgress(); break;
    case "select": state.selected = i; state.historyOpen = false; render(); break;
    case "regen": sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/regenerate`, { quality: state.quality }); break;
    case "edit-tab": state.editTab = v; render(); break;
    case "motion-apply": { const t = $("motion-input"); const val = t ? t.value.trim() : "";
      if (val) sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/tweak`, { instruction: "Re-animate this scene: " + val, quality: state.quality });
      else sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/regenerate`, { quality: state.quality });
      break; }
    case "tweak": { const t = $("tweak-input"); const val = t ? t.value.trim() : ""; if (val) sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/tweak`, { instruction: val, quality: state.quality }); break; }
    case "save-narr": { const t = $("narr-input"); const lines = t ? t.value.split("\n").filter(x => x.trim()) : []; if (lines.length) sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/narration`, { lines, quality: state.quality }); break; }
    case "insert-after": promptInsert(state.selected + 1); break;
    case "insert-end": promptInsert((state.project.scenes || []).length); break;
    case "delete": if (confirm("Delete this scene?")) structural(`/api/projects/${pid}/scenes/${curIdx()}`, "DELETE"); break;
    case "history": openHistory(); break;
    case "rollback": structural(`/api/projects/${pid}/scenes/${curIdx()}/rollback`, "POST", { version: +v }); break;
    case "dl-toggle": state.downloadOpen = !state.downloadOpen; render(); break;
    case "sub-toggle": state.subtitles = !state.subtitles; render(); break;
    case "fmt": state.format = v; render(); break;
    case "do-download": window.open(`/api/projects/${pid}/download?subtitles=${state.subtitles ? "burn" : "none"}&format=${state.format}`, "_blank"); state.downloadOpen = false; render(); break;
    case "dev-toggle": state.dev.open = !state.dev.open; render(); break;
    case "dev-tab": state.dev.tab = v; render(); break;
    case "dev-clear": state.gen.log = []; render(); break;
    case "dev-autoscroll": state.dev.autoscroll = !state.dev.autoscroll; render(); break;
    case "dev-inspect": if (state.project) loadSource(+el.dataset.i); break;
    case "dev-subtab": state.dev.subtab = v; render(); break;
    case "dev-rerun": if (state.dev.source) { const idx = state.dev.inspect; state.dev.tab = "log"; render(); sceneJob(`/api/projects/${pid}/scenes/${idx}/regenerate`, { quality: state.quality }); } break;
  }
}
function curIdx() { const s = (state.project.scenes || [])[state.selected]; return s ? s.index : state.selected; }
async function openHistory() {
  state.historyOpen = !state.historyOpen;
  if (state.historyOpen) { try { state.history = (await api("GET", `/api/projects/${state.project.id}/scenes/${curIdx()}/history`)).versions || []; } catch { state.history = []; } }
  render();
}
function promptInsert(pos) {
  const title = prompt("New scene title:"); if (!title) return;
  const intent = prompt("What should it show/explain?") || title;
  sceneJob(`/api/projects/${state.project.id}/scenes/insert`, { pos, title, intent, quality: state.quality });
}

// ---- init --------------------------------------------------------------------------------
(async function init() {
  document.documentElement.setAttribute("data-theme", state.theme);
  demoStart = performance.now() / 1000;
  RAF = requestAnimationFrame(loop);
  render();
  await loadProjects();
  render();
})();
