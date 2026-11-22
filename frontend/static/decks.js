// Lattice — Slides mode (the deck path: HTML slides + Manim only where the topic needs it).
//
// Self-contained on purpose: everything lives behind window.LatticeDecks so app.js needs one hook in
// render() and one in handle(), instead of this being smeared through a 1000-line state machine.
// It borrows app.js's globals (api, esc, MONO, DISPLAY, followJob, render) at CALL time, never at
// load time, so script order can't bite us.
//
// The review step is the whole point. A deck costs ~$0.001 to plan and one LLM call, so the gate is
// not "approve the titles" like the Manim outline — it is READ THE SCRIPT. Every spoken word is on
// screen, with the element each sentence will highlight, before a single frame is rendered.
"use strict";

(function () {
  const D = {
    phase: "prompt",        // prompt | review | building | done
    topic: "",
    deck: null,             // deck_dto
    keep: {},               // index -> bool
    narrate: true,
    transition: true,
    pct: 0, label: "", log: [],
    busy: false,
  };

  const SUGGEST = ["how gradient descent works", "how LLMs predict the next token",
                   "what a Fourier series is", "how backpropagation works"];

  const badge = (kind) => {
    const isMath = kind === "math";
    const c = isMath ? "var(--accent)" : "var(--muted)";
    return `<span style="${MONO}font-size:9.5px;letter-spacing:0.1em;text-transform:uppercase;color:${c};
      border:1px solid ${isMath ? "var(--accent)" : "var(--line2)"};border-radius:3px;padding:2px 6px;">
      ${isMath ? "Manim &middot; animated" : esc(kind)}</span>`;
  };

  // What `focus: n` will actually light up — so the script reads as a storyboard, not index soup.
  function elementsOf(s) {
    if (s.kind === "cards") return (s.cards || []).map(c => c.label);
    if (s.kind === "chips") return (s.chips || []).map(String);
    if (s.kind === "bullets") return (s.bullets || []).map(b => b.label);
    return [];
  }

  function slideCard(s, i) {
    const els = elementsOf(s);
    const on = D.keep[i] !== false;
    const beats = (s.beats || []).map(b => {
      const f = b.focus === undefined ? -1 : b.focus;
      const tag = f >= 0 && els[f]
        ? `<span style="${MONO}font-size:9.5px;color:var(--accent);border:1px solid var(--line2);border-radius:3px;padding:1px 5px;white-space:nowrap;">&#9656; ${esc(els[f])}</span>`
        : `<span style="${MONO}font-size:9.5px;color:var(--faint);padding:1px 5px;">&mdash;</span>`;
      return `<div style="display:flex;gap:9px;align-items:baseline;margin:5px 0;">
        <div style="flex:0 0 auto;">${tag}</div>
        <div style="font-size:13px;color:var(--muted);line-height:1.5;">${esc(b.say)}</div></div>`;
    }).join("");
    return `<div style="border:1px solid ${on ? "var(--line2)" : "var(--line)"};border-radius:9px;padding:14px 16px;
              margin-bottom:10px;background:var(--raise);opacity:${on ? 1 : 0.45};">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
        <div data-act="deck-keep" data-i="${i}" style="width:16px;height:16px;border-radius:4px;cursor:pointer;flex:0 0 auto;
             border:1.5px solid ${on ? "var(--accent)" : "var(--line2)"};background:${on ? "var(--accent)" : "transparent"};
             display:grid;place-items:center;color:var(--ink);font-size:10px;">${on ? "&#10003;" : ""}</div>
        <div style="${DISPLAY}font-weight:600;font-size:14.5px;color:var(--text);flex:1;">${esc(s.title || "Untitled")}</div>
        ${badge(s.kind)}
      </div>
      <div style="padding-left:26px;">${beats || `<div style="${MONO}font-size:11px;color:var(--faint);">no narration</div>`}</div>
    </div>`;
  }

  function toggle(act, on, text) {
    return `<div data-act="${act}" style="display:flex;align-items:center;gap:8px;cursor:pointer;${MONO}font-size:11px;
        letter-spacing:0.06em;text-transform:uppercase;color:${on ? "var(--text)" : "var(--muted)"};">
      <div style="width:30px;height:17px;border-radius:9px;position:relative;flex:0 0 auto;
           background:${on ? "var(--accent)" : "var(--line2)"};transition:background .15s;">
        <div style="position:absolute;top:2px;left:${on ? "15px" : "2px"};width:13px;height:13px;border-radius:50%;
             background:var(--ink);transition:left .15s;"></div>
      </div>${text}</div>`;
  }

  function promptView() {
    return `<div style="max-width:640px;margin:0 auto;padding:64px 24px;">
      ${label("Slides &middot; planned once, no re-rolls")}
      <div style="${DISPLAY}font-size:34px;font-weight:600;letter-spacing:-0.02em;color:var(--text);margin-bottom:10px;">
        What should this deck teach?</div>
      <div style="font-size:14.5px;color:var(--muted);line-height:1.6;margin-bottom:22px;">
        Slides render in CSS &mdash; instant, free, and they cannot land off-frame. Only a real
        function routes to Manim, where the curve is plotted and a dot rolls down it.</div>
      <textarea id="deck-topic" placeholder="e.g. how gradient descent finds the minimum of a loss function"
        style="width:100%;min-height:110px;resize:vertical;padding:14px;border-radius:9px;background:var(--raise);
        border:1px solid var(--line2);color:var(--text);font-size:14.5px;line-height:1.6;outline:none;">${esc(D.topic)}</textarea>
      <div style="display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 20px;">
        ${SUGGEST.map(s => `<span class="lt-link" data-act="deck-sugg" data-v="${esc(s)}"
          style="cursor:pointer;color:var(--muted);font-size:13px;">${esc(s)}</span>`).join("")}
      </div>
      <button class="lt-btnp" data-act="deck-plan" ${D.busy ? "disabled" : ""}
        style="padding:11px 20px;border-radius:7px;border:none;background:var(--accent);color:var(--ink);
        ${MONO}font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;cursor:pointer;
        opacity:${D.busy ? 0.6 : 1};">${D.busy ? "Writing the script&hellip;" : "Plan the deck &rarr;"}</button>
    </div>`;
  }

  function reviewView() {
    const d = D.deck;
    const n = d.slides.filter((_, i) => D.keep[i] !== false).length;
    const nMath = d.slides.filter((s, i) => D.keep[i] !== false && s.kind === "math").length;
    const script = d.slides.filter((_, i) => D.keep[i] !== false)
      .flatMap(s => (s.beats || []).map(b => b.say)).join(" ");
    const words = script.split(/\s+/).filter(Boolean).length;
    return `<div style="max-width:780px;margin:0 auto;padding:40px 24px 80px;">
      ${label("Step 2 &middot; read the script before you spend")}
      <div style="${DISPLAY}font-size:28px;font-weight:600;letter-spacing:-0.02em;color:var(--text);margin-bottom:6px;">
        ${esc(d.title)}</div>
      <div style="${MONO}font-size:11px;color:var(--faint);margin-bottom:20px;">
        ${n} slide${n === 1 ? "" : "s"} &middot; ${nMath} via Manim &middot; ~${words} spoken words
        &middot; ~${Math.round(words / 2.6)}s</div>
      <div style="border:1px solid var(--line);border-radius:9px;padding:14px 16px;margin-bottom:20px;background:var(--bg2);">
        <div style="${MONO}font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);margin-bottom:7px;">
          The whole narration, end to end</div>
        <div style="font-size:13.5px;color:var(--muted);line-height:1.65;">${esc(script)}</div>
      </div>
      ${d.slides.map(slideCard).join("")}
      <div style="display:flex;align-items:center;gap:22px;margin:20px 0;flex-wrap:wrap;">
        ${toggle("deck-narrate", D.narrate, "Narration")}
        ${toggle("deck-transition", D.transition, "Crossfades")}
      </div>
      <div style="display:flex;gap:10px;">
        <button class="lt-btnp" data-act="deck-build" ${n === 0 || D.busy ? "disabled" : ""}
          style="padding:11px 20px;border-radius:7px;border:none;background:var(--accent);color:var(--ink);
          ${MONO}font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;cursor:pointer;
          opacity:${n === 0 || D.busy ? 0.5 : 1};">Generate &rarr;</button>
        <button data-act="deck-back" style="padding:11px 20px;border-radius:7px;background:transparent;
          border:1px solid var(--line2);color:var(--muted);${MONO}font-size:12px;letter-spacing:0.06em;
          text-transform:uppercase;cursor:pointer;">Start over</button>
      </div>
    </div>`;
  }

  function buildingView() {
    return `<div style="max-width:640px;margin:0 auto;padding:80px 24px;">
      ${label("Rendering")}
      <div style="${DISPLAY}font-size:26px;font-weight:600;color:var(--text);margin-bottom:18px;">
        ${esc(D.label || "Starting&hellip;")}</div>
      <div style="height:3px;background:var(--line);border-radius:2px;overflow:hidden;margin-bottom:18px;">
        <div style="height:100%;width:${D.pct}%;background:var(--accent);transition:width .3s;"></div></div>
      <div style="${MONO}font-size:11px;color:var(--faint);line-height:1.9;max-height:220px;overflow:auto;">
        ${D.log.slice(-12).map(m => `<div>${esc(m)}</div>`).join("")}</div>
    </div>`;
  }

  function doneView() {
    return `<div style="max-width:900px;margin:0 auto;padding:40px 24px;">
      ${label("Done")}
      <div style="${DISPLAY}font-size:26px;font-weight:600;color:var(--text);margin-bottom:16px;">${esc(D.deck.title)}</div>
      <video src="${U(`/api/decks/${encodeURIComponent(D.deck.id)}/video`)}" controls autoplay
        style="width:100%;border-radius:10px;border:1px solid var(--line2);background:#000;"></video>
      <div style="display:flex;gap:10px;margin-top:18px;">
        <a href="${U(`/api/decks/${encodeURIComponent(D.deck.id)}/video`)}" download
          style="padding:10px 18px;border-radius:7px;background:var(--accent);color:var(--ink);text-decoration:none;
          ${MONO}font-size:12px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;">Download</a>
        <button data-act="deck-back" style="padding:10px 18px;border-radius:7px;background:transparent;
          border:1px solid var(--line2);color:var(--muted);${MONO}font-size:12px;letter-spacing:0.06em;
          text-transform:uppercase;cursor:pointer;">New deck</button>
      </div>
    </div>`;
  }

  async function plan() {
    const topic = ($("deck-topic") || {}).value || "";
    if (!topic.trim()) return;
    D.topic = topic; D.busy = true; render();
    try {
      D.deck = await api("POST", "/api/decks", { topic });
      D.keep = {}; D.phase = "review";
    } catch (e) {
      alert("Couldn't plan that deck: " + e.message);
    } finally { D.busy = false; render(); }
  }

  async function build() {
    const keep = D.deck.slides.map((_, i) => i).filter(i => D.keep[i] !== false);
    D.busy = true; D.phase = "building"; D.pct = 0; D.log = []; D.label = "Queued"; render();
    try {
      const { job_id } = await api("POST", `/api/decks/${D.deck.id}/build`, {
        keep, narrate: D.narrate, transition: D.transition ? 0.45 : 0,
      });
      await followJob(job_id, (p) => {
        D.pct = p.pct || D.pct; D.label = p.label || D.label;
        if (p.log) D.log = p.log;
        render();
      });
      const job = await api("GET", `/api/jobs/${job_id}`);
      if (job.status === "failed") throw new Error(job.error || "render failed");
      D.deck = await api("GET", `/api/decks/${D.deck.id}`);
      D.phase = "done";
    } catch (e) {
      alert("Deck render failed: " + e.message);
      D.phase = "review";
    } finally { D.busy = false; render(); }
  }

  window.LatticeDecks = {
    screen() {
      return D.phase === "review" ? reviewView()
        : D.phase === "building" ? buildingView()
        : D.phase === "done" && D.deck ? doneView()
        : promptView();
    },
    // Returns true if this module owned the action, so app.js's switch never sees it.
    // This runs BEFORE app.js's switch on every click, so it must bail out on the prefix before it
    // touches anything: a throw in here would take down every action in the app, not just ours.
    handle(act, el) {
      if (!act || act.lastIndexOf("deck-", 0) !== 0) return false;
      const ds = (el && el.dataset) || {};
      const v = ds.v;
      const i = +ds.i;
      switch (act) {
        case "deck-plan": plan(); return true;
        case "deck-build": build(); return true;
        case "deck-sugg": { const t = $("deck-topic"); if (t) t.value = "Explain " + v; return true; }
        case "deck-keep": D.keep[i] = D.keep[i] === false; render(); return true;
        case "deck-narrate": D.narrate = !D.narrate; render(); return true;
        case "deck-transition": D.transition = !D.transition; render(); return true;
        case "deck-back": D.phase = "prompt"; D.deck = null; D.keep = {}; render(); return true;
        default: return false;
      }
    },
    reset() { D.phase = "prompt"; D.deck = null; D.keep = {}; },
    _state: D,
  };
})();
