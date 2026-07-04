// Lattice web client — editorial design, wired to the real FastAPI engine.
// State drives screen/phase; inputs are uncontrolled (read at action time) so typing never re-renders.
"use strict";

const state = {
  screen: "landing",              // landing | studio | gallery
  phase: "prompt",                // prompt | outline | generating | result
  theme: "dark",
  projects: [],                   // GET /api/projects
  project: null,                  // current project_dto
  outline: [],                    // [{origIndex,title,intent,enabled}] before build
  selected: 0,                    // selected scene index in result
  length: "standard", quality: "high",
  gen: { pct: 0, label: "Warming up", sub: "", scenes: {}, log: [], detailsOpen: false },
  planning: false, busy: false, downloadOpen: false, subtitles: false,
  historyOpen: false, history: [], sideSearch: "", gallerySearch: "",
  dragFrom: null,
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
    es.addEventListener("progress", (e) => { try { onProgress(JSON.parse(e.data)); } catch {} });
    es.addEventListener("log", (e) => { try { state.gen.log.push(JSON.parse(e.data).message); } catch {} });
    es.addEventListener("done", () => { es.close(); resolve(); });
    es.onerror = () => { es.close(); resolve(); };
  });
}

// ---- flows -------------------------------------------------------------------------------
async function planTopic(topic) {
  topic = (topic || "").trim(); if (!topic) return;
  state.screen = "studio"; state.phase = "prompt"; state.planning = true; render();
  try {
    const p = await api("POST", "/api/projects", { topic });
    state.project = p;
    state.outline = p.scenes.map(s => ({ origIndex: s.index, title: s.title, intent: s.intent, enabled: true }));
    state.phase = "outline";
  } catch (e) { alert("Couldn't plan: " + e.message); state.phase = "prompt"; }
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
    state.screen === "gallery" ? gallery() : studio()
  );
  wire();
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
      ${tab("home", "Home", state.screen === "landing")}${tab("studio", "Studio", state.screen === "studio")}${tab("gallery", "Gallery", state.screen === "gallery")}
    </div>
    <div style="display:flex;align-items:center;gap:12px;">
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
      <p class="lt-fade" style="font-size:19px;line-height:1.5;color:var(--muted);max-width:48ch;margin:0 0 34px;">Describe a concept in a sentence. Lattice storyboards it, animates every idea, and narrates the whole thing — start to finish, no design or editing.</p>
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
    if (state.downloadOpen) dl += `<div class="lt-snap" style="position:absolute;top:48px;right:0;width:248px;background:var(--raise);border:1px solid var(--line2);border-radius:8px;padding:14px;box-shadow:0 24px 60px -24px rgba(0,0,0,0.8);z-index:30;">
      ${label("Export", 10)}
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
  return `<div class="lt-fade" style="max-width:720px;margin:0 auto;padding:72px 32px;">
    <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:16px;">Step 1 · The idea</div>
    <h2 style="${DISPLAY}font-size:38px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0 0 10px;line-height:1.02;">What do you want to explain?</h2>
    <p style="color:var(--muted);font-size:16px;margin:0 0 28px;max-width:46ch;">Give Lattice a topic or a question. It handles the storyboard, the animation, and the narration.</p>
    <div style="border:1px solid var(--line2);border-radius:10px;background:var(--raise);padding:18px;">
      <textarea id="prompt-text" placeholder="e.g. Explain the Fourier series — how any repeating wave is just a sum of simple sines…" style="width:100%;min-height:104px;resize:none;background:transparent;border:none;outline:none;font-size:17px;line-height:1.5;color:var(--text);"></textarea>
      <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-top:10px;flex-wrap:wrap;">
        <div style="display:flex;gap:22px;flex-wrap:wrap;">
          <div><div style="${MONO}font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Length</div>${segmented("len", [["short", "Short"], ["standard", "Standard"], ["deep", "Deep"]], state.length)}</div>
          <div><div style="${MONO}font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Quality</div>${segmented("qual", [["high", "High"], ["draft", "Draft"]], state.quality)}</div>
        </div>
        <button class="lt-btnp" data-act="storyboard" ${state.planning ? "disabled" : ""} style="display:flex;align-items:center;gap:8px;padding:12px 22px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:14.5px;cursor:pointer;${state.planning ? "opacity:0.6;" : ""}">${state.planning ? "Storyboarding…" : "Storyboard it →"}</button>
      </div>
    </div>
    ${suggestRow("sugg-prompt")}
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
    <div style="${MONO}font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:var(--accent);margin-bottom:14px;">Step 2 · Review the storyboard</div>
    <h2 style="${DISPLAY}font-size:32px;font-weight:600;letter-spacing:-0.03em;color:var(--text);margin:0 0 8px;line-height:1.03;">Here's the plan for your video</h2>
    <p style="color:var(--muted);font-size:15px;margin:0 0 28px;">Reorder or drop any scene. Nothing has been made yet.</p>
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

function phaseResult() {
  const scenes = (state.project && state.project.scenes) || [];
  const sel = scenes[state.selected] || scenes[0];
  const pid = state.project.id;
  const bust = Date.now();
  const player = sel && sel.built ? `<video src="/api/projects/${pid}/scenes/${sel.index}/preview?t=${bust}" controls playsinline style="width:100%;height:100%;object-fit:contain;background:#0B0B10;"></video>` : `<div style="position:absolute;inset:0;display:grid;place-items:center;${MONO}font-size:12px;color:var(--faint);">Scene not rendered</div>`;
  const film = scenes.map((s, i) => `
    <div draggable="true" data-drag2="${i}" data-act="select" data-i="${i}" style="flex:0 0 auto;cursor:pointer;padding:3px;border-radius:8px;border:1.5px solid ${i === state.selected ? "var(--accent)" : "transparent"};">
      <div style="position:relative;width:154px;aspect-ratio:16/9;border-radius:5px;overflow:hidden;background:#0B0B10;"><div style="${thumb(seedOf(s.sid || s.index))}"></div><span style="position:absolute;top:6px;left:7px;font-size:10px;${MONO}color:rgba(236,234,227,0.85);">${pad2(i + 1)}</span>${s.built ? "" : `<span style="position:absolute;bottom:6px;right:7px;font-size:9px;${MONO}color:var(--danger);">unbuilt</span>`}</div>
      <div style="width:154px;font-size:12px;color:var(--muted);margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(s.title)}</div>
    </div>`).join("");
  return `<div class="lt-fade" style="max-width:1140px;margin:0 auto;padding:26px 26px 64px;">
    <div style="width:100%;max-width:calc(54vh * 16 / 9);margin:0 auto;border-radius:8px;overflow:hidden;background:#0B0B10;border:1px solid var(--line);"><div style="position:relative;aspect-ratio:16/9;">${player}</div></div>
    <div style="margin-top:22px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;"><span style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);">Timeline · ${scenes.length} scenes</span><span style="${MONO}font-size:11px;color:var(--faint);">Drag to reorder · click to edit</span></div>
      <div class="lt-scroll" style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;">${film}<div data-act="insert-end" style="flex:0 0 auto;width:154px;aspect-ratio:16/9;border-radius:5px;border:1px dashed var(--line2);display:grid;place-items:center;color:var(--muted);font-size:20px;cursor:pointer;">＋</div></div>
    </div>
    ${sel ? editorPanel(sel) : ""}
  </div>`;
}
function editorPanel(sel) {
  const versions = state.historyOpen ? (state.history || []) : null;
  const actBtn = "flex:1;min-width:118px;padding:10px;border-radius:6px;border:1px solid var(--line2);background:transparent;color:var(--text);font-weight:500;font-size:13px;cursor:pointer;";
  const danger = "flex:1;min-width:118px;padding:10px;border-radius:6px;border:1px solid rgba(240,85,59,0.32);background:transparent;color:var(--danger);font-weight:500;font-size:13px;cursor:pointer;";
  return `<div class="lt-snap" style="margin-top:22px;display:grid;grid-template-columns:340px 1fr;gap:22px;border-top:1px solid var(--line2);padding-top:22px;">
    <div>
      <div style="position:relative;aspect-ratio:16/9;border-radius:6px;overflow:hidden;background:#0B0B10;">${sel.built ? `<video src="/api/projects/${state.project.id}/scenes/${sel.index}/preview?t=${Date.now()}" controls playsinline style="width:100%;height:100%;object-fit:contain;"></video>` : `<div style="${thumb(seedOf(sel.sid || sel.index))}"></div>`}<span style="position:absolute;top:8px;left:9px;font-size:10.5px;${MONO}color:rgba(236,234,227,0.8);pointer-events:none;">Scene ${state.selected + 1}</span></div>
      <div style="${DISPLAY}font-size:19px;font-weight:600;color:var(--text);letter-spacing:-0.015em;margin-top:14px;">${esc(sel.title)}</div>
      <div style="${MONO}font-size:11px;color:var(--faint);margin-top:3px;">scene ${state.selected + 1} of ${state.project.scenes.length}</div>
    </div>
    <div style="min-width:0;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;"><span style="${MONO}font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:var(--faint);">Edit scene</span>${state.busy ? `<span style="${MONO}font-size:11px;color:var(--accent);">working…</span>` : ""}</div>
      <div style="display:flex;gap:8px;margin-bottom:14px;">
        <input id="tweak-input" placeholder="Tell Lattice a change… e.g. make the wave amber" style="flex:1;padding:11px 13px;border-radius:6px;border:1px solid var(--line2);background:var(--raise2);outline:none;font-size:13.5px;color:var(--text);min-width:0;" />
        <button class="lt-btnp" data-act="tweak" style="padding:0 18px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);font-weight:600;font-size:13.5px;cursor:pointer;">Apply</button>
      </div>
      <div style="border:1px solid var(--line);border-radius:6px;background:var(--raise);padding:12px 14px;margin-bottom:16px;">
        <div style="${MONO}font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">Narration</div>
        <textarea id="narr-input" style="width:100%;min-height:72px;resize:vertical;background:transparent;border:none;outline:none;font-size:13.5px;line-height:1.55;color:var(--text);">${esc((sel.narration || []).join("\n"))}</textarea>
        <div style="text-align:right;margin-top:6px;"><span data-act="save-narr" class="lt-link" style="${MONO}font-size:11px;color:var(--muted);cursor:pointer;">Save narration →</span></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="lt-act" style="${actBtn}" data-act="regen">↻ Regenerate</button>
        <button class="lt-act" style="${actBtn}" data-act="insert-after">＋ Insert after</button>
        <button class="lt-act" style="${actBtn}" data-act="history">↺ History</button>
        <button style="${danger}" data-act="delete">🗑 Delete</button>
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
  const tw = $("tweak-input"); if (tw) tw.onkeydown = (e) => { if (e.key === "Enter") handle("tweak"); };
  const ss = $("side-search"); if (ss) ss.oninput = (e) => { state.sideSearch = e.target.value; rerenderSidebarList(); };
  const gs = $("gallery-search"); if (gs) gs.oninput = (e) => { state.gallerySearch = e.target.value; render(); const g = $("gallery-search"); if (g) { g.focus(); g.setSelectionRange(g.value.length, g.value.length); } };
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
    case "home": state.screen = "landing"; render(); break;
    case "tab-home": state.screen = "landing"; render(); break;
    case "tab-studio": state.screen = "studio"; render(); break;
    case "tab-gallery": state.screen = "gallery"; render(); break;
    case "theme": state.theme = state.theme === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", state.theme); break;
    case "open": openProject(id); break;
    case "new": state.screen = "studio"; state.phase = "prompt"; state.project = null; state.outline = []; render(); break;
    case "landing-go": planTopic($("landing-input").value); break;
    case "sugg-landing": { const el2 = $("landing-input"); if (el2) el2.value = "Explain " + v; break; }
    case "sugg-prompt": { const el2 = $("prompt-text"); if (el2) el2.value = "Explain " + v; break; }
    case "len": state.length = v; render(); break;
    case "qual": state.quality = v; render(); break;
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
    case "tweak": { const t = $("tweak-input"); const val = t ? t.value.trim() : ""; if (val) sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/tweak`, { instruction: val, quality: state.quality }); break; }
    case "save-narr": { const t = $("narr-input"); const lines = t ? t.value.split("\n").filter(x => x.trim()) : []; if (lines.length) sceneJob(`/api/projects/${pid}/scenes/${curIdx()}/narration`, { lines, quality: state.quality }); break; }
    case "insert-after": promptInsert(state.selected + 1); break;
    case "insert-end": promptInsert((state.project.scenes || []).length); break;
    case "delete": if (confirm("Delete this scene?")) structural(`/api/projects/${pid}/scenes/${curIdx()}`, "DELETE"); break;
    case "history": openHistory(); break;
    case "rollback": structural(`/api/projects/${pid}/scenes/${curIdx()}/rollback`, "POST", { version: +v }); break;
    case "dl-toggle": state.downloadOpen = !state.downloadOpen; render(); break;
    case "sub-toggle": state.subtitles = !state.subtitles; render(); break;
    case "do-download": window.open(`/api/projects/${pid}/download?subtitles=${state.subtitles ? "burn" : "none"}`, "_blank"); state.downloadOpen = false; render(); break;
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
