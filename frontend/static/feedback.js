// What the user sees when something goes wrong, in one place.
//
// The rules this file enforces for the rest of the UI:
//  - an error is a short toast in plain words, never a browser alert() and never raw JSON;
//  - a message that looks like a server internal (a stack trace, a path, a wall of text) is replaced
//    by a generic sentence, whatever the server sent;
//  - a download is fetched first and saved only if it worked. Navigating the browser straight to an API
//    address means a failure shows up as a blank tab of `{"detail": ...}`;
//  - a <video> that can't load says so, instead of showing a black box.
(function () {
  const GENERIC = "Something went wrong. Please try again.";
  const OFFLINE = "Couldn't reach the server. Check your connection and try again.";

  // The text to show for a thrown error. Server messages are already written for people; this is a
  // second line of defence in case an internal one ever slips through.
  function friendlyMessage(e) {
    if (e && e.status === 0) return OFFLINE;
    const m = e && typeof e.message === "string" ? e.message.trim() : "";
    if (!m || /Traceback|^\s*at\s|\.py\b|\/srv\/|\\Users\\|undefined|\[object/.test(m) || m.length > 300) return GENERIC;
    if (/^(Failed to fetch|NetworkError|Load failed)/i.test(m)) return OFFLINE;
    return m;
  }

  function notify(message, kind) {
    try {
      let host = document.getElementById("lt-toasts");
      if (!host) {
        host = document.createElement("div");
        host.id = "lt-toasts";
        host.setAttribute("role", "status");
        host.setAttribute("aria-live", "polite");
        host.style.cssText = "position:fixed;left:0;right:0;bottom:20px;display:flex;flex-direction:column;" +
          "align-items:center;gap:8px;z-index:9999;pointer-events:none;padding:0 16px;";
        document.body.appendChild(host);
      }
      const t = document.createElement("div");
      t.textContent = String(message || GENERIC);               // text, never HTML: a message can't inject markup
      const bad = kind !== "info";
      t.style.cssText = "pointer-events:auto;max-width:460px;padding:12px 16px;border-radius:10px;font:14px/1.45 system-ui,sans-serif;" +
        "box-shadow:0 6px 24px rgba(0,0,0,.35);border:1px solid " + (bad ? "#7a2e2e" : "#33333d") + ";" +
        "background:" + (bad ? "#2a1214" : "#17171c") + ";color:#f4f4f6;";
      host.appendChild(t);
      setTimeout(() => { try { t.remove(); } catch (_) {} }, bad ? 7000 : 3500);
    } catch (_) { /* a toast must never be the thing that breaks the page */ }
  }

  // A file name from a title: "How load balancing works" -> "how-load-balancing-works.mp4".
  function fileName(title, fallback) {
    const s = String(title || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
    return (s || fallback || "lattice-video") + ".mp4";
  }

  async function downloadFile(url, filename) {
    let r;
    try { r = await fetch(url, { credentials: "include", headers: { Accept: "*/*" } }); }
    catch (_) { notify(OFFLINE); return false; }
    if (!r.ok) {
      let msg = "";
      try { msg = (await r.json()).detail || ""; } catch (_) { /* not JSON: fall through to the generic text */ }
      if (r.status === 401 && typeof window.signedOut === "function") window.signedOut();
      notify(msg ? friendlyMessage({ message: msg }) : "That video isn't ready to download yet.");
      return false;
    }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "lattice-video.mp4";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => { try { URL.revokeObjectURL(a.href); } catch (_) {} }, 30000);
    return true;
  }

  // onerror for every <video> that streams from the API.
  function videoFailed(el) {
    try {
      if (!el || (el.dataset && el.dataset.failed)) return;
      const box = document.createElement("div");
      box.setAttribute("role", "alert");
      box.style.cssText = "display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;" +
        "min-height:140px;width:100%;box-sizing:border-box;border-radius:6px;background:#0B0B10;color:#cfcfd6;" +
        "font:14px/1.5 system-ui,sans-serif;";
      box.textContent = "This video isn't available yet. It may still be building, or it didn't finish. Please try again in a moment.";
      el.replaceWith(box);
    } catch (_) { /* nothing to recover */ }
  }

  document.addEventListener("click", (e) => {
    const a = e.target && e.target.closest && e.target.closest("[data-dl]");
    if (!a) return;
    e.preventDefault();
    downloadFile(a.getAttribute("data-dl"), a.getAttribute("data-name") || "lattice-video.mp4");
  });

  // A promise that nobody caught is still a failure the user should hear about, in words.
  window.addEventListener("unhandledrejection", (e) => { notify(friendlyMessage(e && e.reason)); });

  Object.assign(window, { notify, friendlyMessage, downloadFile, videoFailed, fileName });
})();
