"""What the UI shows when something fails (frontend/static/feedback.js).

The reported bug: Download opened the API address in a new tab, so a failure showed up as a page of
`{"detail": ...}`. These run the real file in node against a fake browser, and guard the rest of the UI
so a raw alert(), a bare API link or a video with no error message can't come back.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent.parent / "frontend" / "static"
FEEDBACK = STATIC / "feedback.js"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")

HARNESS = r"""
const vm = require("vm");
const src = require("fs").readFileSync(process.argv[1], "utf8");
const sc = JSON.parse(process.argv[2]);
const log = { toasts: [], anchors: [], fetched: [], replaced: [], signedOut: 0, prevented: 0, listeners: {}, winListeners: {} };

function el(tag) {
  const e = { tag, style: {}, children: [], dataset: {}, attrs: {}, textContent: "", clicks: 0, removed: false };
  e.setAttribute = (k, v) => { e.attrs[k] = v; };
  e.getAttribute = (k) => (k in e.attrs ? e.attrs[k] : null);
  e.appendChild = (c) => { e.children.push(c); if (e.id === "lt-toasts") log.toasts.push(c); return c; };
  e.remove = () => { e.removed = true; };
  e.click = () => { e.clicks++; };
  e.replaceWith = (n) => { log.replaced.push({ role: n.attrs.role, text: n.textContent }); };
  if (tag === "a") log.anchors.push(e);
  return e;
}
const body = el("body");
const hosts = {};
const document = {
  body,
  createElement: (t) => el(t),
  getElementById: (id) => hosts[id] || null,
  addEventListener: (t, f) => { log.listeners[t] = f; },
};
const origAppend = body.appendChild;
body.appendChild = (c) => { if (c.tag === "div" && !hosts["lt-toasts"]) { c.id = "lt-toasts"; hosts["lt-toasts"] = c; } return origAppend(c); };
const win = { addEventListener: (t, f) => { log.winListeners[t] = f; }, signedOut: () => { log.signedOut++; } };
const fetchImpl = async (url, opts) => {
  log.fetched.push({ url, credentials: opts && opts.credentials, accept: opts && opts.headers && opts.headers.Accept });
  if (sc.fetch === "network") throw new TypeError("Failed to fetch");
  return {
    ok: sc.fetch.status < 400, status: sc.fetch.status,
    json: async () => { if (sc.fetch.body === undefined) throw new Error("not json"); return sc.fetch.body; },
    blob: async () => ({ size: 3 }),
  };
};
const ctx = { document, window: win, fetch: fetchImpl, URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
              setTimeout: () => 0, String, Object, JSON };
vm.createContext(ctx);
vm.runInContext(src, ctx);

(async () => {
  const out = {};
  const w = ctx.window;
  for (const step of sc.steps) {
    if (step.op === "notify") w.notify(step.msg, step.kind);
    if (step.op === "friendly") (out.friendly = out.friendly || []).push(w.friendlyMessage(step.err));
    if (step.op === "download") out.result = await w.downloadFile(step.url, step.name);
    if (step.op === "videoFailed") w.videoFailed({ dataset: {}, replaceWith: (n) => log.replaced.push({ role: n.attrs.role, text: n.textContent }) });
    if (step.op === "fileName") (out.names = out.names || []).push(w.fileName(step.title, step.fallback));
    if (step.op === "click") {
      const target = { closest: () => ({ getAttribute: (k) => ({ "data-dl": step.dl, "data-name": step.name })[k] }) };
      log.listeners.click({ target, preventDefault: () => { log.prevented++; } });
      await new Promise((r) => setImmediate(r));
    }
    if (step.op === "unhandled") log.winListeners.unhandledrejection({ reason: step.reason });
  }
  console.log(JSON.stringify({ out, toasts: log.toasts.map((t) => ({ text: t.textContent, bad: t.style.cssText.includes("#7a2e2e") })),
    anchors: log.anchors.map((a) => ({ download: a.download, href: a.href, clicks: a.clicks, removed: a.removed })),
    fetched: log.fetched, replaced: log.replaced, signedOut: log.signedOut, prevented: log.prevented }));
})();
"""


def run(steps, fetch=None):
    out = subprocess.run(["node", "-e", HARNESS, "--", str(FEEDBACK), json.dumps({"steps": steps, "fetch": fetch})],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# --- the reported case ------------------------------------------------------------------------
@needs_node
def test_a_download_that_fails_shows_the_reason_and_never_opens_an_error_page():
    r = run([{"op": "download", "url": "/api/projects/cc3f5d07/download?subtitles=none&format=youtube", "name": "x.mp4"}],
            fetch={"status": 409, "body": {"detail": "no final video to export - build the project first", "code": "not_ready"}})
    assert r["out"]["result"] is False
    assert r["toasts"][0]["text"] == "no final video to export - build the project first" and r["toasts"][0]["bad"]
    assert r["anchors"] == []                                           # nothing was downloaded or navigated to
    assert r["fetched"][0]["credentials"] == "include" and r["fetched"][0]["accept"] == "*/*"    # JSON, not an HTML page


@needs_node
def test_a_download_that_works_is_saved_under_the_chosen_name():
    r = run([{"op": "download", "url": "/api/projects/p/download", "name": "how-load-balancing-works.mp4"}],
            fetch={"status": 200, "body": None})
    assert r["out"]["result"] is True and r["toasts"] == []
    assert r["anchors"] == [{"download": "how-load-balancing-works.mp4", "href": "blob:x", "clicks": 1, "removed": True}]


@needs_node
def test_a_download_with_no_connection_says_so():
    r = run([{"op": "download", "url": "/api/x", "name": "x.mp4"}], fetch="network")
    assert r["out"]["result"] is False and "Couldn't reach the server" in r["toasts"][0]["text"]


@needs_node
def test_a_download_after_the_session_expired_signs_the_user_out_cleanly():
    r = run([{"op": "download", "url": "/api/x", "name": "x.mp4"}], fetch={"status": 401, "body": {"detail": "sign in required"}})
    assert r["signedOut"] == 1 and r["anchors"] == []


@needs_node
def test_a_failure_with_no_message_still_says_something_useful():
    r = run([{"op": "download", "url": "/api/x", "name": "x.mp4"}], fetch={"status": 500})        # body is not JSON
    assert r["toasts"][0]["text"] == "That video isn't ready to download yet."


@needs_node
def test_download_links_are_handled_without_navigating_the_browser():
    r = run([{"op": "click", "dl": "/api/decks/d1/video", "name": "lattice-deck.mp4"}], fetch={"status": 200, "body": None})
    assert r["prevented"] == 1 and r["fetched"][0]["url"] == "/api/decks/d1/video"
    assert r["anchors"][0]["download"] == "lattice-deck.mp4"


# --- messages ---------------------------------------------------------------------------------
@needs_node
def test_a_toast_is_text_not_markup():
    evil = '<img src=x onerror="steal()">'
    r = run([{"op": "notify", "msg": evil}])
    assert r["toasts"][0]["text"] == evil               # set through textContent, so it can never run


@needs_node
def test_internal_looking_messages_are_replaced_by_a_generic_sentence():
    raw = [{"message": "Traceback (most recent call last):\n  File"}, {"message": "error in /srv/lattice/engine.py"},
           {"message": "x" * 400}, {"message": ""}, {"message": "undefined"}, {"message": "C:\\Users\\Dev\\secret"}]
    r = run([{"op": "friendly", "err": e} for e in raw])
    assert set(r["out"]["friendly"]) == {"Something went wrong. Please try again."}


@needs_node
def test_normal_and_network_messages_are_kept_or_translated():
    r = run([{"op": "friendly", "err": {"message": "You've used all 5 videos for the last 24 hours."}},
             {"op": "friendly", "err": {"message": "Failed to fetch"}},
             {"op": "friendly", "err": {"message": "x", "status": 0}}])
    f = r["out"]["friendly"]
    assert f[0] == "You've used all 5 videos for the last 24 hours."
    assert f[1] == f[2] == "Couldn't reach the server. Check your connection and try again."


@needs_node
def test_an_uncaught_promise_failure_becomes_a_toast():
    r = run([{"op": "unhandled", "reason": {"message": "Failed to fetch"}}])
    assert "Couldn't reach the server" in r["toasts"][0]["text"]


@needs_node
def test_a_video_that_cannot_play_is_replaced_by_a_message():
    r = run([{"op": "videoFailed"}])
    assert r["replaced"][0]["role"] == "alert" and "isn't available yet" in r["replaced"][0]["text"]


@needs_node
def test_file_names_come_from_the_title():
    r = run([{"op": "fileName", "title": "How load balancing works!"}, {"op": "fileName", "title": "", "fallback": "lattice-reel"},
             {"op": "fileName", "title": "!!!"}])
    assert r["out"]["names"] == ["how-load-balancing-works.mp4", "lattice-reel.mp4", "lattice-video.mp4"]


# --- guards over the rest of the UI ----------------------------------------------------------
UI_SCRIPTS = ("app.js", "learn.js", "decks.js")


@pytest.mark.parametrize("name", UI_SCRIPTS)
def test_the_ui_never_uses_the_browsers_alert_or_opens_an_api_address(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    assert "alert(" not in text, f"{name}: use notify() so the message is readable and consistent"
    assert "window.open(" not in text, f"{name}: a new tab on an API address shows raw JSON when it fails; use downloadFile()"


@pytest.mark.parametrize("name", UI_SCRIPTS)
def test_every_video_from_the_api_says_so_when_it_cannot_play(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    for m in re.finditer(r"<video\b[^>]*", text):
        tag = m.group(0)
        if "/static/" in tag:                                  # the bundled landing video is not an API stream
            continue
        assert 'onerror="videoFailed(this)"' in tag, f"{name}: <video> without an error message: {tag[:80]}"


@pytest.mark.parametrize("name", UI_SCRIPTS)
def test_download_links_never_point_the_browser_at_the_api(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    for m in re.finditer(r"<a\b[^>]*>", text):
        tag = m.group(0)
        assert not (re.search(r"href=\"\$\{U\(", tag) or "download" in tag.split("data-")[0]), f"{name}: {tag[:90]}"


def test_the_feedback_helpers_load_before_any_script_that_uses_them():
    html = (STATIC.parent / "index.html").read_text(encoding="utf-8")
    order = [m.group(1) for m in re.finditer(r'<script[^>]*src="/static/([^"]+)"', html)]
    assert order.index("config.js") < order.index("feedback.js") < min(order.index(n) for n in ("decks.js", "learn.js", "app.js"))


def test_a_failed_http_call_carries_its_status_and_a_network_failure_is_readable():
    text = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "{ status: r.status }" in text and "{ status: 0 }" in text
