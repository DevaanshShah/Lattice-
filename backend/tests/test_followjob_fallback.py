"""followJob keeps following a build when the live stream drops.

A proxy, a phone changing networks or a sleeping tab can cut the progress stream mid-build. That used
to resolve as "finished" with no verdict, so a build still running looked done or failed. The UI now
polls the same events by cursor until the job reports a terminal status. These run the real function
from app.js in node against a scripted EventSource and API.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).parent.parent.parent / "frontend" / "static" / "app.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")

HARNESS = r"""
const src = require("fs").readFileSync(process.argv[1], "utf8");
const start = src.indexOf("const JOB_TERMINAL");
const end = src.indexOf("// Ask a running build to stop.");
const scenario = JSON.parse(process.argv[2]);

const logs = [], progresses = [];
const state = { gen: { log: [] }, auth: { required: false } };
const signedIn = () => true;
const appendDevLog = (m) => logs.push(m);
const refreshDevStatus = () => {};
const U = (p) => p;
globalThis.setTimeout = (fn) => fn();                   // no real waiting
let calls = [];
class EventSource {
  constructor(url) { this.listeners = {}; calls.push("sse " + url); setImmediate(() => this.run()); }
  addEventListener(n, f) { this.listeners[n] = f; }
  close() {}
  run() {
    for (const [name, data] of scenario.sse) {
      if (name === "error") return this.onerror();
      this.listeners[name] && this.listeners[name]({ data: JSON.stringify(data) });
    }
  }
}
let poll = 0;
async function api(method, url) {
  calls.push(method + " " + url);
  if (url.includes("/events")) {
    const r = scenario.polls[Math.min(poll++, scenario.polls.length - 1)];
    if (r === "fail") throw new Error("network");
    return r;
  }
  return scenario.job;
}
eval(src.slice(start, end) + "; globalThis.followJob = followJob;");
followJob("j1", (p) => progresses.push(p)).then((final) => {
  console.log(JSON.stringify({ final, logs, progresses, calls }));
});
"""


def run(scenario):
    out = subprocess.run(["node", "-e", HARNESS, "--", str(APP_JS), json.dumps(scenario)],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


DONE_JOB = {"id": "j1", "status": "done"}


def test_a_stream_that_completes_normally_never_polls():
    r = run({"sse": [["log", {"seq": 0, "message": "a"}], ["progress", {"pct": 50}],
                     ["status", DONE_JOB], ["done", {}]], "polls": [], "job": {}})
    assert r["final"] == DONE_JOB and r["logs"] == ["a"]
    assert not any("/events" in c for c in r["calls"])


def test_a_dropped_stream_falls_back_to_polling_and_finishes_with_the_jobs_own_verdict():
    r = run({"sse": [["log", {"seq": 0, "message": "a"}], ["log", {"seq": 1, "message": "b"}], ["error", {}]],
             "polls": [{"status": "running", "next_cursor": 3, "progress": {"pct": 40},
                        "events": [{"seq": 2, "message": "c"}]},
                       {"status": "done", "next_cursor": 4, "progress": {"pct": 100},
                        "events": [{"seq": 3, "message": "d"}]}],
             "job": DONE_JOB})
    assert r["final"] == DONE_JOB                      # the job's own last word, fetched after the poll saw "done"
    assert r["logs"] == ["a", "b", "c", "d"]           # nothing replayed, nothing lost
    assert [p["pct"] for p in r["progresses"]] == [40, 100]
    assert "GET /api/jobs/j1/events?cursor=2" in r["calls"]       # resumed AFTER what the stream delivered


def test_a_failed_job_is_reported_as_failed_not_as_finished():
    failed = {"id": "j1", "status": "failed", "error": "boom"}
    r = run({"sse": [["error", {}]],
             "polls": [{"status": "failed", "next_cursor": 0, "progress": {"pct": 100}, "events": []}],
             "job": failed})
    assert r["final"] == failed


def test_polling_rides_out_a_few_network_blips():
    r = run({"sse": [["error", {}]],
             "polls": ["fail", "fail", {"status": "done", "next_cursor": 0, "events": []}],
             "job": DONE_JOB})
    assert r["final"] == DONE_JOB


def test_a_lost_job_stops_the_poll_instead_of_spinning_forever():
    r = run({"sse": [["error", {}]], "polls": ["fail"], "job": {}})
    assert r["final"] is None                          # server restarted: the caller treats no verdict as a problem


def test_a_stream_cut_after_the_final_status_does_not_poll():
    r = run({"sse": [["status", DONE_JOB], ["error", {}]], "polls": [], "job": {}})
    assert r["final"] == DONE_JOB
    assert not any("/events" in c for c in r["calls"])


def test_the_function_under_test_is_really_the_one_in_app_js():
    text = APP_JS.read_text(encoding="utf-8")
    assert re.search(r"const JOB_TERMINAL = \[\"done\", \"failed\", \"cancelled\"\];", text)
    assert text.index("const JOB_TERMINAL") < text.index("// Ask a running build to stop.")
