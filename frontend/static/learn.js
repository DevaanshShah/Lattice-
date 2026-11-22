// Lattice — Learn (student chat tutor). Text is the default turn; a video only renders on request.
//
// Self-contained on purpose, same pattern as decks.js: everything lives behind window.LatticeLearn so
// app.js needs one hook in render() and one in handle(). Borrows app.js's globals (api, esc, MONO,
// DISPLAY, followJob, render) at CALL time, never at load time, so script order can't bite us.
//
// The constraint that shapes this whole screen: a video takes real time to render (even the cheap
// deck path is ~30-60s), but a chat turn has to feel instant. So every reply is TEXT by default, and
// a video only gets queued when the backend's OWN judgement (returned with the answer, not guessed
// here) says the idea is worth animating, or the student explicitly asks via the video-mode toggle.
//
// No fabricated data: there is no login yet, so there is no "signed in as" strip, no captions track
// (nothing generates one), and assistant replies render exactly once they arrive — no fake typing
// animation standing in for a real stream the backend doesn't do.
"use strict";

(function () {
  const L = {
    tid: null,             // current thread id, or null = the empty/start state
    thread: null,           // GET /api/learn/threads/{tid} dto
    threads: [],            // sidebar list
    threadsLoaded: false,
    search: "",
    // The draft textarea is UNCONTROLLED like app.js's own inputs (see its top-of-file comment): read
    // via $("learn-draft").value at send time, never synced into state on keystroke. A video renders
    // in the background while the composer stays usable, so re-renders can land mid-typing — an
    // innerHTML rebuild driven by live state would blow away whatever the student was typing.
    videoMode: false,       // composer's video toggle: send goes straight to /video, skipping chat
    pendingImage: null,     // a data-URL waiting to go with the next message (photo of the problem)
    codeMode: false,        // wrap the next draft in a fence so the model reads it as code
    refining: null,         // {mid, title, version}
    busy: false,
    jobs: {},               // message_id -> {pct, label}
  };

  // Skips a render if the composer currently has focus, so a background video's progress tick can
  // never stomp a keystroke mid-type. The next unfocused tick (or the final "ready" state) catches up.
  function safeRender() {
    const el = document.activeElement;
    if (el && el.id === "learn-draft") return;
    render();
  }

  const SUGGEST = [
    { label: "How does attention work in transformers?", tag: "CS" },
    { label: "Walk me through gradient descent", tag: "ML" },
    { label: "Why does e show up in growth and decay?", tag: "Math" },
  ];
  const REFINE_CHIPS = ["Slower", "Add real numbers", "Simpler wording"];

  function relTime(ts) {
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
    return new Date(ts * 1000).toLocaleDateString();
  }

  // app.js's own render() is synchronous (it concatenates screen HTML straight into innerHTML), so
  // screen() below must be too — an async screen() would stringify its Promise into the page instead
  // of the markup. This kicks the fetch off in the background and re-renders once it lands, the same
  // "fire, then render() when it resolves" shape every other async flow in this app already uses.
  let threadsLoading = false;
  function ensureThreads() {
    if (L.threadsLoaded || threadsLoading) return;
    threadsLoading = true;
    api("GET", "/api/learn/threads").then(r => { L.threads = r.threads || []; })
      .catch(() => { L.threads = []; })
      .finally(() => { L.threadsLoaded = true; threadsLoading = false; render(); });
  }

  // ---------------------------------------------------------------------------- sidebar
  function sidebar() {
    const q = L.search.toLowerCase();
    const rows = L.threads.filter(t => t.title.toLowerCase().includes(q)).map(t => `
      <div data-act="learn-open" data-id="${esc(t.id)}" style="display:flex;flex-direction:column;gap:3px;
        padding:10px 11px;border-radius:7px;cursor:pointer;margin-bottom:2px;
        background:${L.tid === t.id ? "var(--raise)" : "transparent"};">
        <div style="font-size:13px;color:var(--text);font-weight:450;white-space:nowrap;overflow:hidden;
          text-overflow:ellipsis;line-height:1.3;">${esc(t.title)}</div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="${MONO}font-size:10px;color:var(--faint);">${relTime(t.last_at)}</span>
          ${t.videos > 0 ? `<span style="display:inline-flex;align-items:center;gap:4px;${MONO}
            font-size:10px;color:var(--accent);"><span style="font-size:9px;">&#9654;</span>
            ${t.videos} video${t.videos > 1 ? "s" : ""}</span>` : ""}
        </div>
      </div>`).join("");
    return `<div style="flex:0 0 282px;display:flex;flex-direction:column;border-right:1px solid var(--line);
        background:var(--bg2);min-height:0;">
      <div style="padding:16px 16px 10px;">
        <button data-act="learn-new" style="width:100%;display:flex;align-items:center;justify-content:center;
          gap:8px;padding:11px;border-radius:6px;border:none;background:var(--accent);color:var(--ink);
          font-family:inherit;font-weight:600;font-size:13.5px;cursor:pointer;">+ New question</button>
      </div>
      <div style="padding:0 16px 10px;">
        <div style="display:flex;align-items:center;gap:8px;padding:9px 11px;border-radius:6px;background:var(--raise);">
          <span style="color:var(--faint);font-size:13px;">&#9906;</span>
          <input id="learn-search" value="${esc(L.search)}"
            placeholder="Search your threads" style="flex:1;background:transparent;border:none;outline:none;
            font-family:inherit;font-size:13px;color:var(--text);min-width:0;" />
        </div>
      </div>
      <div style="padding:10px 16px 6px;${MONO}font-size:10px;letter-spacing:0.16em;text-transform:uppercase;
        color:var(--faint);">Recent threads</div>
      <div class="lt-scroll" style="flex:1;overflow-y:auto;padding:2px 10px 10px;min-height:0;">
        ${rows || `<div style="padding:14px 6px;font-size:12.5px;color:var(--faint);">No threads yet</div>`}
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------------------- empty state
  function emptyMain() {
    return `<div class="lt-scroll" style="flex:1;overflow-y:auto;min-height:0;display:flex;flex-direction:column;justify-content:center;">
      <div style="max-width:720px;width:100%;margin:0 auto;padding:32px 40px;">
        <div style="display:flex;align-items:center;gap:10px;${MONO}font-size:10.5px;letter-spacing:0.16em;
          text-transform:uppercase;color:var(--muted);margin-bottom:24px;">
          <span style="width:22px;height:1px;background:var(--accent);"></span>Learn &middot; one-to-one tutor</div>
        <div style="${DISPLAY}font-size:clamp(32px,5vw,48px);line-height:1.05;letter-spacing:-0.03em;font-weight:600;
          margin:0 0 18px;color:var(--text);max-width:15ch;">What do you want to understand?</div>
        <p style="font-size:16px;line-height:1.55;color:var(--muted);max-width:56ch;margin:0 0 30px;">
          Ask anything — answers come back as text, right away. When an idea is worth
          <span style="color:var(--text);">seeing</span>, Lattice will offer a short video. That takes
          about a minute, so making one is always your call.</p>
        <div style="${MONO}font-size:10.5px;letter-spacing:0.14em;text-transform:uppercase;color:var(--faint);
          margin-bottom:12px;">Start with</div>
        <div style="display:flex;flex-direction:column;border-top:1px solid var(--line);">
          ${SUGGEST.map(st => `<div data-act="learn-sugg" data-v="${esc(st.label)}" style="display:flex;
            align-items:center;justify-content:space-between;gap:14px;padding:15px 4px;border-bottom:1px solid var(--line);
            cursor:pointer;color:var(--muted);">
            <span style="font-size:15px;color:var(--text);font-weight:450;">${esc(st.label)}</span>
            <span style="${MONO}font-size:11px;color:var(--faint);">${esc(st.tag)}</span></div>`).join("")}
        </div>
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------------------- message rendering
  function offerCard(m) {
    if (!m.offer) return "";
    return `<div data-act="learn-offer" data-id="${m.id}" style="margin-top:16px;display:flex;align-items:center;
        justify-content:space-between;gap:18px;max-width:420px;padding:12px 15px;border-radius:8px;
        border:1px solid var(--line2);cursor:pointer;">
      <span style="display:flex;align-items:center;gap:10px;min-width:0;">
        <span style="font-size:14px;color:var(--accent);">&#9654;</span>
        <span style="display:flex;flex-direction:column;gap:2px;min-width:0;">
          <span style="${MONO}font-size:10.5px;letter-spacing:0.12em;text-transform:uppercase;color:var(--muted);">
            Worth seeing</span>
          <span style="font-size:14px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
            ${esc(m.offer.label)}</span></span></span>
      <span style="font-family:inherit;color:var(--accent);font-size:15px;">&#8594;</span>
    </div>`;
  }

  function videoBlock(m) {
    const box = "border:1px solid var(--line2);border-radius:10px;overflow:hidden;background:var(--raise);max-width:640px;";
    if (m.status === "failed") {
      return `<div style="${box}padding:16px 18px;">
        <div style="${MONO}font-size:11px;color:var(--danger,#F0553B);">Couldn't make that video&nbsp;&mdash;
          ${esc((m.error || "").slice(0, 140) || "planning failed")}</div></div>`;
    }
    if (m.status !== "ready") {
      const j = L.jobs[m.id] || { pct: 5, label: "Starting" };
      return `<div style="${box}">
        <div style="padding:16px 18px 6px;display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <span style="display:inline-flex;align-items:center;gap:9px;${MONO}font-size:10.5px;letter-spacing:0.12em;
            text-transform:uppercase;color:var(--text);">
            <span style="width:8px;height:8px;border-radius:50%;background:var(--accent);"></span>
            Making your video</span>
          <span style="${MONO}font-size:11px;color:var(--faint);">~1 min</span>
        </div>
        <div style="padding:12px 18px 18px;">
          <div style="height:3px;border-radius:3px;background:var(--raise2);overflow:hidden;">
            <div style="height:100%;width:${j.pct}%;background:var(--accent);transition:width .3s;"></div></div>
          <div style="${MONO}font-size:11px;color:var(--faint);margin-top:9px;">${esc(j.label || "")}</div>
        </div>
      </div>`;
    }
    return `<div style="${box}">
      <video src="${U(`/api/learn/threads/${encodeURIComponent(L.tid)}/video/${encodeURIComponent(m.id)}`)}"
        controls style="display:block;width:100%;aspect-ratio:16/9;background:#000;"></video>
      <div style="padding:13px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
        <div style="display:flex;align-items:baseline;gap:12px;min-width:0;">
          <span style="${DISPLAY}font-size:15px;font-weight:600;letter-spacing:-0.01em;color:var(--text);">${esc(m.title)}</span>
          <span style="${MONO}font-size:10.5px;color:var(--faint);white-space:nowrap;">v${m.version || 1}</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <a href="${U(`/api/learn/threads/${encodeURIComponent(L.tid)}/video/${encodeURIComponent(m.id)}`)}" download
            style="padding:8px 13px;border-radius:6px;border:1px solid var(--line);color:var(--muted);
            text-decoration:none;${MONO}font-size:11px;letter-spacing:0.06em;text-transform:uppercase;">Download</a>
          <div data-act="learn-refine-start" data-id="${m.id}" style="display:flex;align-items:center;gap:7px;
            padding:8px 13px;border-radius:6px;border:1px solid var(--line);color:var(--muted);${MONO}font-size:11px;
            letter-spacing:0.06em;text-transform:uppercase;cursor:pointer;">&#8635; Refine</div>
        </div>
      </div>
      ${m.update_note ? `<div style="padding:0 16px 15px;display:flex;align-items:center;gap:9px;${MONO}
          font-size:10.5px;letter-spacing:0.08em;text-transform:uppercase;color:var(--accent);">
          <span>Updated</span><span style="color:var(--muted);text-transform:none;letter-spacing:0;font-size:12px;">
          ${esc(m.update_note)}</span></div>` : ""}
    </div>`;
  }

  function messageView(m) {
    const isUser = m.role === "user";
    const wrap = `display:flex;flex-direction:column;${isUser ? "align-items:flex-end;" : "align-items:flex-start;"}margin-bottom:26px;`;
    const label = `${MONO}font-size:10px;letter-spacing:0.16em;text-transform:uppercase;margin-bottom:9px;
      color:${isUser ? "var(--faint)" : "var(--accent)"};`;
    let body;
    if (m.kind === "video") {
      body = videoBlock(m);
    } else if (isUser) {
      const ref = m.ref_to ? `<div style="align-self:flex-end;display:flex;align-items:center;gap:7px;margin-bottom:6px;
        padding:5px 10px;border-radius:6px;border:1px solid var(--line);background:var(--raise);${MONO}
        font-size:10.5px;color:var(--muted);"><span style="color:var(--accent);">&#8635;</span>
        revising &middot; ${esc(m.ref_to)}</div>` : "";
      body = `${ref}<div style="align-self:flex-end;max-width:80%;background:var(--raise2);border:1px solid var(--line);
        border-radius:9px;padding:12px 15px;font-size:15px;line-height:1.5;color:var(--text);">${esc(m.text)}</div>`;
    } else {
      body = `<div style="font-size:15.5px;line-height:1.68;color:var(--text);white-space:pre-wrap;max-width:64ch;">
        ${esc(m.text)}</div>${offerCard(m)}`;
    }
    return `<div style="${wrap}"><div style="${label}">${isUser ? "You" : "Lattice"}</div>${body}</div>`;
  }

  function threadMain() {
    const msgs = (L.thread.messages || []).map(messageView).join("");
    return `<div class="lt-scroll" id="learn-thread" style="flex:1;overflow-y:auto;min-height:0;">
      <div style="max-width:760px;margin:0 auto;padding:30px 40px 40px;">${msgs}</div>
    </div>`;
  }

  function composer() {
    const refining = L.refining;
    const busy = L.busy;
    const banner = refining ? `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;
        margin-bottom:10px;padding:9px 13px;border-radius:7px;border:1px solid var(--accent);
        background:color-mix(in srgb, var(--accent) 8%, transparent);">
      <div style="display:flex;align-items:center;gap:12px;min-width:0;flex-wrap:wrap;">
        <span style="${MONO}font-size:10.5px;letter-spacing:0.1em;text-transform:uppercase;color:var(--accent);
          white-space:nowrap;">&#8635; Refining</span>
        <span style="font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
          ${esc(refining.title)} &middot; v${refining.version}</span>
        <div style="display:flex;gap:7px;flex-wrap:wrap;">
          ${REFINE_CHIPS.map(c => `<span data-act="learn-refine-chip" data-v="${esc(c)}" style="padding:5px 10px;
            border-radius:5px;border:1px solid var(--line2);font-size:12px;color:var(--muted);cursor:pointer;
            white-space:nowrap;">${esc(c)}</span>`).join("")}
        </div>
      </div>
      <div data-act="learn-refine-cancel" style="flex:0 0 auto;width:24px;height:24px;border-radius:5px;
        display:grid;place-items:center;cursor:pointer;color:var(--faint);font-size:12px;">&times;</div>
    </div>` : "";
    const placeholder = refining ? "Describe the change… e.g. slow down the softmax step"
      : L.videoMode ? "Describe the video you want to see…" : "Ask anything…";
    const hint = refining ? "This re-renders the video above as a new version."
      : L.videoMode ? "&#9654; Video mode on &middot; this will render as a ~1 min video"
      : L.pendingImage ? "Image attached &middot; ask about it and the answer comes back as text"
      : L.codeMode ? "Code mode on &middot; paste a snippet and ask what it does"
      : "Text answers are instant &middot; tap &#9654; to get a video (~1 min)";
    // A photo of the problem, or a pasted snippet, is a LEARNER's gesture: it wants an answer now,
    // not a four-minute render. Both ride the ordinary chat turn.
    const chip = L.pendingImage ? `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <img src="${L.pendingImage}" alt="" style="width:34px;height:34px;object-fit:cover;border-radius:5px;
        border:1px solid var(--line2);" />
      <span style="${MONO}font-size:11px;color:var(--muted);">Image attached</span>
      <span data-act="learn-attach-clear" title="Remove" style="cursor:pointer;color:var(--faint);
        font-size:13px;padding:0 4px;">&times;</span>
    </div>` : "";
    return `<div style="flex:0 0 auto;border-top:1px solid var(--line);background:var(--bg2);padding:14px 40px 16px;">
      <div style="max-width:760px;margin:0 auto;">
        ${banner}
        ${chip}
        <div style="display:flex;align-items:flex-end;gap:10px;border:1px solid var(--line2);border-radius:9px;
          background:var(--raise);padding:8px 8px 8px 6px;">
          ${refining ? "" : `<div data-act="learn-videomode" title="Answer with a video (~1 min)"
            style="flex:0 0 auto;width:38px;height:38px;border-radius:7px;display:grid;place-items:center;cursor:pointer;
            ${L.videoMode ? "background:var(--accent);color:var(--ink);" : "background:transparent;color:var(--muted);border:1px solid var(--line);"}">
            <span style="font-size:13px;">&#9654;</span></div>`}
          ${refining ? "" : `<div data-act="learn-attach" title="Attach an image"
            style="flex:0 0 auto;width:38px;height:38px;border-radius:7px;display:grid;place-items:center;cursor:pointer;
            background:transparent;color:${L.pendingImage ? "var(--accent)" : "var(--muted)"};border:1px solid var(--line);">
            <span style="font-size:14px;">&#128206;</span></div>
          <div data-act="learn-codemode" title="Send the draft as code"
            style="flex:0 0 auto;width:38px;height:38px;border-radius:7px;display:grid;place-items:center;cursor:pointer;
            ${L.codeMode ? "background:var(--accent);color:var(--ink);" : "background:transparent;color:var(--muted);border:1px solid var(--line);"}">
            <span style="${MONO}font-size:12px;">&lt;/&gt;</span></div>`}
          <textarea id="learn-draft" placeholder="${esc(placeholder)}" rows="1"
            style="flex:1;resize:none;background:transparent;border:none;outline:none;font-family:inherit;font-size:15px;
            line-height:1.5;color:var(--text);padding:9px 4px;max-height:120px;min-width:0;"></textarea>
          <button data-act="learn-send" ${busy ? "disabled" : ""} style="flex:0 0 auto;width:38px;height:38px;
            border-radius:7px;border:none;background:var(--accent);color:var(--ink);font-size:16px;cursor:pointer;
            opacity:${busy ? 0.6 : 1};">&#8593;</button>
        </div>
        <div style="${MONO}font-size:10.5px;letter-spacing:0.04em;color:var(--faint);margin-top:9px;">${hint}</div>
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------------------- actions
  // Deliberately builds its own <input>: the wiring file (app.js) differs between checkouts, and
  // the id "learn-file" is already claimed there by the old Learn screen.
  function pickImage() {
    const el = document.createElement("input");
    el.type = "file";
    el.accept = "image/png,image/jpeg,image/webp";
    el.onchange = async () => {
      const f = el.files && el.files[0];
      if (!f) return;
      if (!/^image\/(png|jpe?g|webp)$/i.test(f.type)) { alert("Use a PNG, JPG, or WebP image."); return; }
      try {
        L.pendingImage = typeof downscale === "function" ? await downscale(f) : await asDataUrl(f);
        render();
      } catch (e) { alert("Couldn't read that image: " + e.message); }
    };
    el.click();
  }

  function asDataUrl(file) {          // fallback if app.js's downscale() isn't loaded
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = () => rej(new Error("unreadable file"));
      r.readAsDataURL(file);
    });
  }

  async function openThread(tid) {
    L.busy = true; render();
    try {
      L.tid = tid; L.thread = await api("GET", `/api/learn/threads/${tid}`);
      L.refining = null; L.videoMode = false;
    } catch (e) { alert("Couldn't open that thread: " + e.message); L.tid = null; L.thread = null; }
    finally { L.busy = false; render(); scrollThread(); }
  }

  function scrollThread() {
    [40, 160].forEach(d => setTimeout(() => { const el = $("learn-thread"); if (el) el.scrollTop = el.scrollHeight; }, d));
  }

  async function watchVideo(mid, jobId) {
    await followJob(jobId, (p) => { L.jobs[mid] = { pct: p.pct, label: p.label }; safeRender(); });
    try { L.thread = await api("GET", `/api/learn/threads/${L.tid}`); } catch {}
    delete L.jobs[mid];
    L.threadsLoaded = false;      // video count in the sidebar just changed
    safeRender(); scrollThread();
  }

  async function send() {
    const box = $("learn-draft");
    const raw = ((box && box.value) || "").trim();
    if (!raw || L.busy) return;
    if (L.refining) return sendRefine(raw);
    // fenced so the model reads it as code rather than prose; the learner still sees their own text
    const text = L.codeMode ? "```\n" + raw + "\n```" : raw;
    const image = L.pendingImage;
    if (box) box.value = "";
    L.pendingImage = null; L.codeMode = false;
    L.busy = true; render();
    try {
      if (L.videoMode) {
        if (!L.tid) { const t = await api("POST", "/api/learn/threads", { message: text }); L.tid = t.id; L.thread = t; }
        const r = await api("POST", `/api/learn/threads/${L.tid}/video`, { prompt: text });
        L.thread = await api("GET", `/api/learn/threads/${L.tid}`);
        L.videoMode = false; render(); scrollThread();
        watchVideo(r.message_id, r.job_id);
      } else if (!L.tid) {
        const t = await api("POST", "/api/learn/threads", { message: text, image });
        L.tid = t.id; L.thread = t; L.threadsLoaded = false;
      } else {
        L.thread = await api("POST", `/api/learn/threads/${L.tid}/messages`, { message: text, image });
      }
    } catch (e) {
      alert("Couldn't send that: " + e.message);
      if (box) box.value = raw;
      L.pendingImage = image;            // hand the attachment back so a retry keeps it
    }
    finally { L.busy = false; render(); scrollThread(); }
  }

  async function useOffer(mid) {
    if (L.busy) return;
    L.busy = true; render();
    try {
      const r = await api("POST", `/api/learn/threads/${L.tid}/video`, { message_id: mid });
      L.thread = await api("GET", `/api/learn/threads/${L.tid}`);
      render(); scrollThread();
      watchVideo(r.message_id, r.job_id);
    } catch (e) { alert("Couldn't start that video: " + e.message); }
    finally { L.busy = false; render(); }
  }

  async function sendRefine(instruction) {
    const ref = L.refining; const box = $("learn-draft");
    if (box) box.value = "";
    L.busy = true; L.refining = null; render();
    try {
      const r = await api("POST", `/api/learn/threads/${L.tid}/messages/${ref.mid}/refine`, { instruction });
      L.thread = await api("GET", `/api/learn/threads/${L.tid}`);
      render(); scrollThread();
      watchVideo(r.message_id, r.job_id);
    } catch (e) { alert("Couldn't refine that video: " + e.message); }
    finally { L.busy = false; render(); }
  }

  function setSearch(v) {
    L.search = v; render();
    const el = $("learn-search"); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }

  window.LatticeLearn = {
    screen() {
      ensureThreads();
      const main = !L.tid || !L.thread ? emptyMain() : threadMain();
      return `<div style="flex:1;display:flex;min-height:0;">${sidebar()}
        <div style="flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;">${main}${composer()}</div>
      </div>`;
    },
    handle(act, el) {
      if (!act || act.lastIndexOf("learn-", 0) !== 0) return false;
      const id = (el && el.dataset && el.dataset.id) || "";
      const v = (el && el.dataset && el.dataset.v) || "";
      switch (act) {
        case "learn-new": L.tid = null; L.thread = null; L.refining = null; L.videoMode = false; render(); return true;
        case "learn-open": openThread(id); return true;
        case "learn-sugg": { const box = $("learn-draft"); if (box) box.value = v; send(); return true; }
        case "learn-videomode": L.videoMode = !L.videoMode; render(); return true;
        case "learn-send": send(); return true;
        case "learn-attach": pickImage(); return true;
        case "learn-attach-clear": L.pendingImage = null; render(); return true;
        case "learn-codemode": L.codeMode = !L.codeMode; render(); return true;
        case "learn-offer": useOffer(id); return true;
        case "learn-refine-start": {
          const m = (L.thread.messages || []).find(x => x.id === id);
          if (m) L.refining = { mid: id, title: m.title, version: m.version || 1 };
          render(); return true;
        }
        case "learn-refine-cancel": L.refining = null; render(); return true;
        case "learn-refine-chip": { const box = $("learn-draft"); if (box) box.value = v; render(); return true; }
        default: return false;
      }
    },
    // app.js's wire() has no generic input-binding mechanism (see its own top-of-file comment: inputs
    // are uncontrolled, read at action time) — these two are exposed so its wire() can hook the
    // learn-draft Enter-to-send and learn-search oninput exactly like it already does for
    // learn-input/gallery-search, without learn.js needing a parallel wiring system of its own.
    send, setSearch,
    reset() { L.tid = null; L.thread = null; L.refining = null; L.videoMode = false; },
    // Reopen a remembered thread on return. Quiet on failure (deleted thread, other account): the
    // user just lands on the empty start state instead of an alert they didn't ask for.
    // L.tid is only set once the thread has loaded: a message typed in the meantime starts a new
    // thread instead of posting into one that may turn out not to exist.
    restore(tid) {
      if (!tid) return;
      api("GET", `/api/learn/threads/${encodeURIComponent(tid)}`)
        .then(t => { if (!L.tid) { L.tid = t.id; L.thread = t; render(); } })
        .catch(() => {});
    },
    _state: L,
  };
})();
