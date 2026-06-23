// Lattice thin web client. Holds NO scene logic — every action is one API call to the engine.
"use strict";

const $ = (id) => document.getElementById(id);
const api = async (method, url, body) => {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};

let state = { pid: null, outline: [], cut: new Set(), project: null };
const quality = () => $("quality").value;

// Raw engine lines stay tucked in the collapsible "Technical details" — never the headline.
function log(msg) {
  $("progress").classList.remove("hidden");
  const pre = $("log");
  pre.textContent += msg + "\n";
  pre.scrollTop = pre.scrollHeight;
}

// The headline: a cylinder that fills + a friendly phase label (Thinking… / Scene k / Merging… / Done).
function showProgress(p) {
  if (!p) return;
  $("progress").classList.remove("hidden");
  const cyl = $("cylinder");
  cyl.className = "cylinder " + (p.phase || "");
  $("liquid").style.height = (p.pct || 0) + "%";
  $("pct").textContent = (p.pct || 0) + "%";
  $("phase-label").textContent = p.label || "";
  $("phase-sub").textContent = p.total ? `${p.done}/${p.total} scenes` : "";
  if (p.scenes) applyJobScenes({ scenes: p.scenes });
}
function resetProgress() {
  showProgress({ phase: "thinking", label: "Thinking…", pct: 0, done: 0, total: 0 });
}

// 1 · Plan -----------------------------------------------------------------------------------
$("plan-btn").onclick = async () => {
  const topic = $("topic").value.trim();
  if (!topic) return;
  $("plan-btn").disabled = true;
  log(`planning outline for: ${topic}`);
  try {
    const p = await api("POST", "/api/projects", { topic });
    state.pid = p.id; state.outline = p.scenes; state.cut = new Set();
    renderOutline();
  } catch (e) { log("error: " + e.message); }
  $("plan-btn").disabled = false;
};

function renderOutline() {
  $("pid-label").textContent = state.pid ? `· project ${state.pid}` : "";
  const ol = $("outline-list");
  ol.innerHTML = "";
  state.outline.forEach((s, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<label><input type="checkbox" checked data-i="${i}" />
      <b>${escapeHtml(s.title)}</b> — <span class="intent">${escapeHtml(s.intent)}</span></label>`;
    li.querySelector("input").onchange = (ev) => {
      const idx = +ev.target.dataset.i;
      ev.target.checked ? state.cut.delete(idx) : state.cut.add(idx);
    };
    ol.appendChild(li);
  });
  $("outline-panel").classList.remove("hidden");
}

// 2 · Build (after approval) -----------------------------------------------------------------
$("build-btn").onclick = async () => {
  const keep = state.outline.map((_, i) => i).filter((i) => !state.cut.has(i));
  if (!keep.length) return log("keep at least one scene");
  $("build-btn").disabled = true;
  log(`rendering ${keep.length} scene(s) at ${quality()} quality…`);
  try {
    const { job_id } = await api("POST", `/api/projects/${state.pid}/build`,
      { keep, quality: quality() });
    await followJob(job_id);
    await refresh();
  } catch (e) { log("error: " + e.message); }
  $("build-btn").disabled = false;
};

// Stream job progress via SSE; fall back to polling if the stream drops.
// `progress` events drive the cylinder; `log` events only feed the hidden details pane.
function followJob(jobId) {
  resetProgress();
  return new Promise((resolve) => {
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.addEventListener("progress", (ev) => { try { showProgress(JSON.parse(ev.data)); } catch {} });
    es.addEventListener("log", (ev) => { try { log("  " + JSON.parse(ev.data).message); } catch {} });
    es.addEventListener("status", (ev) => { try { applyJobScenes(JSON.parse(ev.data)); } catch {} });
    es.addEventListener("done", () => { es.close(); resolve(); });
    es.onerror = () => { es.close(); pollJob(jobId).then(resolve); };
  });
}
async function pollJob(jobId) {
  let cursor = 0;
  for (;;) {
    const j = await api("GET", `/api/jobs/${jobId}/events?cursor=${cursor}`);
    j.events.forEach((e) => log("  " + e.message));
    cursor = j.next_cursor;
    showProgress(j.progress);
    if (j.status === "done" || j.status === "failed") return;
    await new Promise((r) => setTimeout(r, 600));
  }
}
function applyJobScenes(j) {
  if (!j.scenes) return;
  Object.entries(j.scenes).forEach(([i, st]) => {
    const el = document.querySelector(`.scene[data-i="${i}"] .status`);
    if (el) { el.textContent = st; el.className = "status " + st; }
  });
}

// 3 · Scenes ---------------------------------------------------------------------------------
async function refresh() {
  state.project = await api("GET", `/api/projects/${state.pid}`);
  renderScenes();
}

function renderScenes() {
  $("scenes-panel").classList.remove("hidden");
  const root = $("scenes");
  root.innerHTML = "";
  state.project.scenes.forEach((s) => root.appendChild(sceneCard(s)));
}

function sceneCard(s) {
  const el = document.createElement("div");
  el.className = "scene"; el.dataset.i = s.index;
  const st = s.built ? "done" : "queued";
  el.innerHTML = `
    <div class="head">
      <span class="title">${s.index}. ${escapeHtml(s.title)}</span>
      <span class="status ${st}">${st}</span>
    </div>
    ${s.built ? `<video controls src="/api/projects/${state.pid}/scenes/${s.index}/preview?t=${Date.now()}"></video>` : ""}
    <details class="script-details">
      <summary>📝 Script (${(s.narration || []).length} line${s.narration && s.narration.length === 1 ? "" : "s"})</summary>
      <pre class="script">${s.narration && s.narration.length ? escapeHtml(s.narration.join("\n")) : "(not generated yet)"}</pre>
      <a class="dl-link" data-op="dl-script">⬇ download this scene's script</a>
    </details>
    <div class="ops">
      <button class="ghost" data-op="regen">Regenerate</button>
      <button class="ghost" data-op="tweak">Tweak…</button>
      <button class="ghost" data-op="narrate">Edit narration…</button>
      <button class="ghost" data-op="up">↑</button>
      <button class="ghost" data-op="down">↓</button>
      <button class="ghost" data-op="del">Delete</button>
    </div>`;
  el.querySelector('[data-op=regen]').onclick = () => sceneJob(`/api/projects/${state.pid}/scenes/${s.index}/regenerate`, { quality: quality() });
  el.querySelector('[data-op=tweak]').onclick = () => {
    const instruction = prompt("Tweak this scene (e.g. 'move the cache box left'):");
    if (instruction) sceneJob(`/api/projects/${state.pid}/scenes/${s.index}/tweak`, { instruction, quality: quality() });
  };
  el.querySelector('[data-op=narrate]').onclick = () => {
    const text = prompt("New narration (one line per sentence, use \\n):", s.narration.join("\n"));
    if (text) sceneJob(`/api/projects/${state.pid}/scenes/${s.index}/narration`,
      { lines: text.split("\n").filter((l) => l.trim()), quality: quality() });
  };
  el.querySelector('[data-op=dl-script]').onclick = () =>
    downloadFile(`/api/projects/${state.pid}/script?index=${s.index}`, `scene-${s.index}-script.txt`);
  el.querySelector('[data-op=up]').onclick = () => structural("reorder", { frm: s.index, to: Math.max(0, s.index - 1) });
  el.querySelector('[data-op=down]').onclick = () => structural("reorder", { frm: s.index, to: s.index + 1 });
  el.querySelector('[data-op=del]').onclick = () => { if (confirm("Delete this scene?")) structuralDelete(s.index); };
  return el;
}

async function sceneJob(url, body) {
  log(`submitting ${url.split("/").pop()}…`);
  try {
    const { job_id } = await api("POST", url, body);
    await followJob(job_id);
    await refresh();
  } catch (e) { log("error: " + e.message); }
}
async function structural(kind, body) {
  try { state.project = await api("POST", `/api/projects/${state.pid}/scenes/${kind}`, body); renderScenes(); }
  catch (e) { log("error: " + e.message); }
}
async function structuralDelete(index) {
  try { state.project = await api("DELETE", `/api/projects/${state.pid}/scenes/${index}`); renderScenes(); }
  catch (e) { log("error: " + e.message); }
}

// Download -----------------------------------------------------------------------------------
function downloadFile(url, filename) {
  const a = document.createElement("a");
  a.href = url; a.download = filename || "";
  document.body.appendChild(a); a.click(); a.remove();
}

$("download-btn").onclick = () => {
  const mode = $("subtitle-mode").value;
  if (mode === "separate") {
    window.open(`/api/projects/${state.pid}/captions`, "_blank");
    window.open(`/api/projects/${state.pid}/download?subtitles=none`, "_blank");
  } else {
    window.open(`/api/projects/${state.pid}/download?subtitles=${mode}`, "_blank");
  }
};

$("script-btn").onclick = () => {
  if (!state.pid) return;
  const name = (state.project && state.project.topic ? state.project.topic : state.pid)
    .replace(/[^\w]+/g, "-").toLowerCase();
  downloadFile(`/api/projects/${state.pid}/script`, `${name}-script.txt`);
};

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
