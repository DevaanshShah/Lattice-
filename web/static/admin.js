/* Lattice admin console — usage, spend and per-user activity.
 *
 * Vanilla, like the rest of web/static: no build step, no dependencies, one render() over a plain
 * state object. It polls /api/admin/* on an interval; every number on screen comes from the server,
 * nothing is computed twice in two places.
 */
(function () {
  var TOKEN_KEY = 'lattice_admin_token';
  var POLL_MS = 5000;

  var state = {
    token: localStorage.getItem(TOKEN_KEY) || '',
    denied: false,
    error: '',
    loading: true,
    summary: null,
    users: [],
    jobs: { live: [], finished: [] },
    costs: null,
    projects: [],
    events: [],
    detail: null,        // { id, data } when a user drawer is open
    days: 14,
    lastAt: 0,           // clock of the last successful poll — proof on screen that it is live
  };

  // --- formatting ------------------------------------------------------------------------------
  function money(v) {
    if (v === null || v === undefined) return '—';
    v = Number(v);
    if (!isFinite(v)) return '—';
    if (v === 0) return '$0';
    if (v < 0.01) return '$' + v.toFixed(4);
    if (v < 10) return '$' + v.toFixed(3);
    return '$' + v.toFixed(2);
  }
  function count(v) {
    v = Number(v || 0);
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k';
    return String(v);
  }
  function ago(ts) {
    if (!ts) return '—';
    var s = Date.now() / 1000 - Number(ts);
    if (s < 60) return Math.max(0, Math.round(s)) + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }
  function dur(sec) {
    if (!sec && sec !== 0) return '—';
    sec = Math.round(Number(sec));
    if (sec < 60) return sec + 's';
    return Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
  }
  function pct(v) { return (v === null || v === undefined) ? '—' : Math.round(v * 100) + '%'; }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function shortId(id) { return esc(String(id || '').slice(0, 8)); }
  function dayLabel(ts) {
    var d = new Date(Number(ts) * 1000);
    return (d.getUTCMonth() + 1) + '/' + d.getUTCDate();
  }

  // --- data ------------------------------------------------------------------------------------
  function api(path) {
    var headers = {};
    if (state.token) headers['X-Admin-Token'] = state.token;
    return fetch(path, { headers: headers, credentials: 'same-origin' }).then(function (r) {
      if (r.status === 403) { state.denied = true; throw new Error('forbidden'); }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      state.denied = false;
      return r.json();
    });
  }

  function refresh() {
    return Promise.all([
      api('/api/admin/summary'),
      api('/api/admin/users'),
      api('/api/admin/jobs'),
      api('/api/admin/costs?days=' + state.days),
      api('/api/admin/projects'),
      api('/api/admin/events?limit=120'),
    ]).then(function (r) {
      state.summary = r[0];
      state.users = r[1].users || [];
      state.jobs = r[2] || { live: [], finished: [] };
      state.costs = r[3];
      state.projects = r[4].projects || [];
      state.events = r[5].events || [];
      state.error = '';
      state.loading = false;
      state.lastAt = Date.now() / 1000;
      render();
    }).catch(function (e) {
      state.loading = false;
      if (!state.denied) state.error = e.message || String(e);
      render();
    });
  }

  // --- views -----------------------------------------------------------------------------------
  function gate() {
    return '<div class="a-wrap"><div class="gate">' +
      '<h1 class="a-title">Lattice admin</h1>' +
      '<p>This console shows every user, video and dollar spent, so it is not public.<br>' +
      'Paste the <span class="mono">LATTICE_ADMIN_TOKEN</span> from your <span class="mono">.env</span>, ' +
      'or open it from the machine the server runs on.</p>' +
      '<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">' +
      '<input class="a-in" id="tok" type="password" placeholder="admin token" value="' + esc(state.token) + '">' +
      '<button class="a-btn primary" id="tok-go">Unlock</button></div>' +
      (state.token ? '<div class="warn">That token was rejected.</div>' : '') +
      '</div></div>';
  }

  function tiles() {
    var s = state.summary; if (!s) return '';
    var c = s.cost, u = s.users, j = s.jobs, ct = s.content;
    var prov = s.provider;
    var out = [
      tile('Users', count(u.total), u.active_24h + ' active today · ' + u.new_24h + ' new'),
      tile('Videos made', count(ct.ready), ct.videos + ' projects · ' + ct.decks + ' decks · ' + ct.threads + ' chats'),
      tile('Spend (all time)', money(c.total), c.calls + ' API calls', true),
      tile('Spend today', money(c.d1), 'last 7d ' + money(c.d7)),
      tile('Cost per video', money(c.per_video), j.done + ' builds finished'),
      tile('Tokens', count(c.prompt_tokens + c.completion_tokens),
           count(c.prompt_tokens) + ' in · ' + count(c.completion_tokens) + ' out'),
      tile('Build success', pct(j.success_rate), j.failed + ' failed · avg ' + dur(j.avg_seconds)),
      tile('Running now', String(j.running + j.queued), j.running + ' rendering · ' + j.queued + ' queued'),
    ];
    if (prov && prov.remaining !== undefined) {
      out.push(tile('Provider credits', money(prov.remaining),
                    'used ' + money(prov.used) + ' of ' + money(prov.purchased)));
    } else if (prov && prov.key_used !== undefined) {
      out.push(tile('This API key', money(prov.key_used),
                    prov.key_limit ? 'limit ' + money(prov.key_limit) : 'no limit set'));
    }
    // A ledger with nothing in it reads exactly like a broken dashboard, so say which it is.
    var quiet = !c.calls && !j.total
      ? '<div class="warn" style="background:var(--raise);border-color:var(--line2);color:var(--muted)">' +
        'No spend or builds recorded <em>yet</em> — the ledger only knows what happened after it ' +
        'started, so these stay at zero until the next video is built. Users and content counts ' +
        'above are live already.</div>'
      : '';
    return '<div class="a-grid">' + out.join('') + '</div>' + quiet +
      (c.unpriced_calls ? '<div class="warn">' + c.unpriced_calls + ' call(s) used a model with no ' +
        'price in <span class="mono">core/llm.py MODEL_PRICES</span> and the provider reported no cost, ' +
        'so they counted as $0 — spend above is a floor, not the full number.</div>' : '');
  }

  function tile(k, v, note, accent) {
    return '<div class="tile"><div class="k">' + esc(k) + '</div>' +
      '<div class="v' + (accent ? ' accent' : '') + '">' + esc(v) + '</div>' +
      '<div class="n">' + esc(note || '') + '</div></div>';
  }

  function liveJobs() {
    var live = (state.jobs.live || []).filter(function (j) {
      return j.status === 'running' || j.status === 'queued';
    });
    var rows = live.map(function (j) {
      var p = j.progress || { pct: 0, label: j.status };
      var started = j.started_at || j.created_at;
      return '<tr><td class="mono">' + shortId(j.id) + '</td>' +
        '<td><span class="chip">' + esc(j.kind) + '</span></td>' +
        '<td class="mono">' + shortId(j.project_id) + '</td>' +
        '<td class="mono faint">' + (j.user ? shortId(j.user) : '—') + '</td>' +
        '<td style="min-width:180px"><div class="bar"><i style="width:' + (p.pct || 0) + '%"></i></div>' +
        '<div class="faint" style="margin-top:4px">' + esc(p.label || '') + '</div></td>' +
        '<td class="num muted">' + ago(started) + '</td></tr>';
    }).join('');

    var recent = (state.jobs.finished || []).slice(0, 8).map(function (r) {
      var ok = r.status === 'done';
      return '<tr><td class="mono">' + shortId(r.job_id) + '</td>' +
        '<td><span class="chip">' + esc(r.kind || '—') + '</span></td>' +
        '<td>' + esc((r.topic || r.project || '').slice(0, 42)) + '</td>' +
        '<td class="mono faint">' + (r.user ? shortId(r.user) : '—') + '</td>' +
        '<td class="' + (ok ? 'ok' : 'bad') + '">' + esc(r.status) + '</td>' +
        '<td class="num muted">' + dur(r.seconds) + '</td>' +
        '<td class="num muted">' + ago(r.ts) + '</td></tr>';
    }).join('');

    return panel('Live jobs', live.length ? '' : 'nothing rendering right now',
      (live.length
        ? '<table><thead><tr><th>Job</th><th>Kind</th><th>Project</th><th>User</th><th>Progress</th><th class="num">Started</th></tr></thead><tbody>' + rows + '</tbody></table>'
        : '<div class="empty">Idle — no builds in the queue.</div>')) +
      panel('Recently finished', '', recent
        ? '<table><thead><tr><th>Job</th><th>Kind</th><th>What</th><th>User</th><th>Status</th><th class="num">Took</th><th class="num">When</th></tr></thead><tbody>' + recent + '</tbody></table>'
        : '<div class="empty">No finished jobs recorded yet.</div>');
  }

  function costChart() {
    var d = (state.costs && state.costs.daily) || [];
    if (!d.length) return '<div class="empty">No spend recorded yet.</div>';
    var max = Math.max.apply(null, d.map(function (b) { return b.cost; }).concat([0.0001]));
    var W = 100, H = 46, n = d.length, bw = W / n;
    var bars = d.map(function (b, i) {
      var h = Math.max(b.cost > 0 ? 1.2 : 0, (b.cost / max) * H);
      return '<rect x="' + (i * bw + bw * 0.16).toFixed(2) + '" y="' + (H - h).toFixed(2) +
        '" width="' + (bw * 0.68).toFixed(2) + '" height="' + h.toFixed(2) +
        '" rx="0.6" fill="var(--accent)" opacity="' + (b.cost ? 0.92 : 0.25) + '">' +
        '<title>' + dayLabel(b.ts) + ': ' + money(b.cost) + ' · ' + b.calls + ' calls · ' +
        b.jobs + ' jobs</title></rect>';
    }).join('');
    var labels = d.map(function (b, i) {
      return (i % Math.ceil(n / 7) === 0)
        ? '<span style="flex:1;text-align:center">' + dayLabel(b.ts) + '</span>'
        : '<span style="flex:1"></span>';
    }).join('');
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'style="width:100%;height:132px;display:block">' + bars + '</svg>' +
      '<div class="faint" style="display:flex;font-size:10.5px;margin-top:6px">' + labels + '</div>' +
      '<div class="faint" style="margin-top:8px">peak day ' + money(max) + '</div>';
  }

  function modelTable() {
    var m = (state.costs && state.costs.models) || [];
    if (!m.length) return '<div class="empty">No model calls recorded yet.</div>';
    return '<table><thead><tr><th>Model</th><th class="num">Calls</th><th class="num">Tokens</th>' +
      '<th class="num">Cost</th></tr></thead><tbody>' + m.map(function (r) {
        return '<tr><td class="mono">' + esc(r.model) + (r.priced ? '' :
          ' <span class="chip bad" title="no price in MODEL_PRICES">unpriced</span>') + '</td>' +
          '<td class="num">' + r.calls + '</td>' +
          '<td class="num muted">' + count(r.prompt_tokens + r.completion_tokens) + '</td>' +
          '<td class="num accent">' + money(r.cost) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function surfaceTable() {
    var s = (state.costs && state.costs.surfaces) || [];
    if (!s.length) return '';
    return '<table><thead><tr><th>Surface</th><th class="num">Calls</th><th class="num">Cost</th>' +
      '</tr></thead><tbody>' + s.map(function (r) {
        return '<tr><td><span class="chip ' + esc(r.surface) + '">' + esc(r.surface) + '</span></td>' +
          '<td class="num">' + r.calls + '</td><td class="num accent">' + money(r.cost) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function usersTable() {
    if (!state.users.length) return '<div class="empty">No visitors recorded yet.</div>';
    return '<table><thead><tr><th>User</th><th class="num">Videos</th><th class="num">Decks</th>' +
      '<th class="num">Chats</th><th class="num">Builds</th><th class="num">Failed</th>' +
      '<th class="num">Render</th><th class="num">Tokens</th><th class="num">Cost</th>' +
      '<th class="num">Last seen</th></tr></thead><tbody>' +
      state.users.map(function (u) {
        return '<tr class="click" data-user="' + esc(u.id) + '">' +
          '<td><span class="a-dot ' + (u.online ? '' : 'off') + '"></span>' +
          '<span class="mono">' + esc(u.label || shortId(u.id)) + '</span>' +
          (u.running ? ' <span class="chip accent">' + u.running + ' running</span>' : '') + '</td>' +
          '<td class="num">' + u.videos + '</td><td class="num">' + u.decks + '</td>' +
          '<td class="num">' + u.threads + '</td><td class="num">' + u.builds + '</td>' +
          '<td class="num ' + (u.failed ? 'bad' : 'faint') + '">' + u.failed + '</td>' +
          '<td class="num muted">' + (u.render_minutes ? u.render_minutes + 'm' : '—') + '</td>' +
          '<td class="num muted">' + count(u.tokens) + '</td>' +
          '<td class="num accent">' + money(u.cost) + '</td>' +
          '<td class="num muted">' + ago(u.last_seen) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function projectsTable() {
    if (!state.projects.length) return '<div class="empty">Nothing has been created yet.</div>';
    return '<table><thead><tr><th>What</th><th>Title</th><th>Owner</th><th>Progress</th>' +
      '<th class="num">Cost</th></tr></thead><tbody>' +
      state.projects.slice(0, 40).map(function (p) {
        var cls = p.ready ? 'bar done' : 'bar';
        return '<tr><td><span class="chip ' + esc(p.surface) + '">' + esc(p.surface) + '</span></td>' +
          '<td>' + esc((p.title || p.id).slice(0, 54)) + '</td>' +
          '<td class="mono faint">' + (p.owner ? shortId(p.owner) : '—') + '</td>' +
          '<td style="min-width:150px"><div class="' + cls + '"><i style="width:' + (p.pct || 0) + '%"></i></div>' +
          '<div class="faint" style="margin-top:4px">' + p.built + '/' + p.scenes +
          (p.ready ? ' · ready' : '') + '</div></td>' +
          '<td class="num accent">' + money(p.cost) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function feed() {
    if (!state.events.length) return '<div class="empty">Ledger is empty.</div>';
    return '<div class="feed">' + state.events.map(function (e) {
      var who = e.user ? shortId(e.user) : '—';
      var body;
      if (e.event === 'llm') {
        body = '<span class="accent">' + money(e.cost_usd) + '</span> ' + esc(e.model || '') +
          ' <span class="faint">' + count(e.prompt_tokens) + '→' + count(e.completion_tokens) + '</span>';
      } else if (e.event === 'job') {
        body = '<span class="' + (e.status === 'done' ? 'ok' : 'bad') + '">job ' + esc(e.status) +
          '</span> ' + esc(e.kind || '') + ' <span class="faint">' + dur(e.seconds) + '</span>';
      } else if (e.event === 'create') {
        body = 'created <span class="chip ' + esc(e.surface) + '">' + esc(e.surface) + '</span> ' +
          esc((e.topic || '').slice(0, 46));
      } else {
        body = esc(e.event);
      }
      return '<div><span class="faint">' + ago(e.ts) + '</span> · <span class="mono faint">' + who +
        '</span> · ' + body + '</div>';
    }).join('') + '</div>';
  }

  function drawer() {
    if (!state.detail) return '';
    var d = state.detail.data, u = d && d.user;
    var inner;
    if (!d) {
      inner = '<div class="empty">Loading…</div>';
    } else {
      inner = '<div class="a-head"><h2 class="a-title">' + esc(u.label || shortId(u.id)) + '</h2>' +
        '<div class="a-spacer"></div><button class="a-btn" id="dr-close">Close</button></div>' +
        '<div class="a-grid">' +
        tile('Spend', money(u.cost), u.calls + ' calls') +
        tile('Videos', String(u.videos + u.decks + u.threads), u.done + ' built · ' + u.failed + ' failed') +
        tile('Requests', count(u.requests), 'first seen ' + ago(u.first_seen)) +
        '</div>' +
        '<div style="margin-top:14px;display:flex;gap:8px;align-items:center">' +
        '<input class="a-in" id="dr-label" placeholder="name this user" value="' + esc(u.label || '') + '">' +
        '<button class="a-btn" id="dr-save">Save</button></div>' +
        '<div class="faint mono" style="margin-top:10px;font-size:11px">' + esc(u.id) +
        ' · ' + esc(u.ip || 'no ip') + '<br>' + esc((u.agent || '').slice(0, 120)) + '</div>' +
        panel('Their projects', '', d.projects && d.projects.length
          ? '<table><tbody>' + d.projects.map(function (p) {
              return '<tr><td><span class="chip ' + esc(p.surface) + '">' + esc(p.surface) + '</span></td>' +
                '<td>' + esc((p.title || p.id).slice(0, 40)) + '</td>' +
                '<td style="width:120px"><div class="bar' + (p.ready ? ' done' : '') + '">' +
                '<i style="width:' + (p.pct || 0) + '%"></i></div></td>' +
                '<td class="num accent">' + money(p.cost) + '</td></tr>';
            }).join('') + '</tbody></table>'
          : '<div class="empty">Nothing created.</div>') +
        panel('Models they used', '', (d.models || []).length
          ? '<table><tbody>' + d.models.map(function (m) {
              return '<tr><td class="mono">' + esc(m.model) + '</td><td class="num">' + m.calls +
                '</td><td class="num accent">' + money(m.cost) + '</td></tr>';
            }).join('') + '</tbody></table>'
          : '<div class="empty">No calls.</div>');
    }
    return '<div class="drawer" id="drawer"><div>' + inner + '</div></div>';
  }

  function panel(title, hint, body) {
    return '<div class="panel"><h2>' + esc(title) +
      (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') + '</h2>' + body + '</div>';
  }

  function render() {
    var root = document.getElementById('admin');
    if (state.denied) { root.innerHTML = gate(); wireGate(); return; }
    if (state.loading && !state.summary) {
      root.innerHTML = '<div class="a-wrap"><div class="empty">Loading…</div></div>';
      return;
    }
    var s = state.summary || {};
    var cfg = s.config || {};
    root.innerHTML = '<div class="a-wrap">' +
      '<div class="a-head">' +
        '<h1 class="a-title">Lattice admin</h1>' +
        '<span class="a-sub"><span class="a-dot"></span>live · updated ' +
          new Date(state.lastAt * 1000).toLocaleTimeString() + '</span>' +
        (s.cost && s.cost.since
          ? '<span class="a-sub faint">recording since ' + new Date(s.cost.since * 1000).toLocaleDateString() + '</span>'
          : '') +
        '<div class="a-spacer"></div>' +
        '<span class="a-sub mono">' + esc(cfg.model || '') + '</span>' +
        '<span class="a-sub">' + (cfg.token_protected ? 'token-protected' : 'localhost-only') + '</span>' +
        '<button class="a-btn" id="refresh">Refresh</button>' +
      '</div>' +
      (state.error ? '<div class="warn">' + esc(state.error) + '</div>' : '') +
      tiles() +
      liveJobs() +
      '<div class="cols" style="margin-top:18px">' +
        '<div>' + panel('Spend, last ' + state.days + ' days', 'hover a bar for the day',
                        '<div class="body">' + costChart() + '</div>') +
          panel('Users', state.users.length + ' total · click a row for detail', usersTable()) +
          panel('Everything built', 'newest first', projectsTable()) + '</div>' +
        '<div>' + panel('Cost by model', '', modelTable()) +
          panel('Cost by surface', '', surfaceTable()) +
          panel('Activity', 'raw ledger', feed()) + '</div>' +
      '</div>' +
      '</div>' + drawer();
    wire();
  }

  // --- events ----------------------------------------------------------------------------------
  function wireGate() {
    var go = document.getElementById('tok-go'), inp = document.getElementById('tok');
    function submit() {
      state.token = (inp.value || '').trim();
      localStorage.setItem(TOKEN_KEY, state.token);
      state.denied = false; state.loading = true; render(); refresh();
    }
    if (go) go.onclick = submit;
    if (inp) inp.onkeydown = function (e) { if (e.key === 'Enter') submit(); };
  }

  function wire() {
    var r = document.getElementById('refresh');
    if (r) r.onclick = function () { refresh(); };
    Array.prototype.forEach.call(document.querySelectorAll('tr[data-user]'), function (tr) {
      tr.onclick = function () { openUser(tr.getAttribute('data-user')); };
    });
    var close = document.getElementById('dr-close');
    if (close) close.onclick = function () { state.detail = null; render(); };
    var dr = document.getElementById('drawer');
    if (dr) dr.onclick = function (e) { if (e.target === dr) { state.detail = null; render(); } };
    var save = document.getElementById('dr-save');
    if (save) save.onclick = saveLabel;
  }

  function openUser(uid) {
    state.detail = { id: uid, data: null };
    render();
    api('/api/admin/users/' + encodeURIComponent(uid)).then(function (d) {
      if (state.detail && state.detail.id === uid) { state.detail.data = d; render(); }
    }).catch(function () { state.detail = null; render(); });
  }

  function saveLabel() {
    if (!state.detail) return;
    var uid = state.detail.id;
    var label = (document.getElementById('dr-label') || {}).value || '';
    var headers = { 'Content-Type': 'application/json' };
    if (state.token) headers['X-Admin-Token'] = state.token;
    fetch('/api/admin/users/' + encodeURIComponent(uid) + '/label', {
      method: 'POST', headers: headers, body: JSON.stringify({ label: label }),
    }).then(function () { refresh(); openUser(uid); });
  }

  // --- boot ------------------------------------------------------------------------------------
  render();
  refresh();
  setInterval(function () {
    // Don't fight the user: skip the poll while a drawer is open and they may be typing a label.
    if (!state.detail) refresh();
  }, POLL_MS);
})();
