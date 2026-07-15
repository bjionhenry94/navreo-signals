"""Recontact review page - GET /recontact/<run_id> (server.py owns storage +
routing + the recontact_runs table, this module owns rendering only - same
split as qa_gate.py). The run row is created on first visit if missing; the
page itself is a self-contained client-side flow against /api/recontact/
scan|buckets|create - this module never touches Supabase itself.
"""
import html


def esc(x):
    return html.escape(str(x))


_STYLE = """
  .main { max-width: 980px; margin: 0 auto; padding: 28px 24px 80px; }
  h1 { font-family: var(--font-display); font-weight: 400; font-size: 28px; letter-spacing: -0.03em; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 14px 0; }
  input[type=text] { padding: 8px 14px; font: 400 13px "DM Sans", sans-serif; color: var(--ink);
    background: var(--card); border: 1px solid var(--line-2); border-radius: 999px; min-width: 260px; }
  .toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-2); }
  table.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
  tr.rowsel { cursor: pointer; }
  tr.rowsel:hover td { background: var(--bg-sunken); }
  tr.rowsel.on td:first-child { border-left: 3px solid var(--orange); }
  .bktile { text-align: center; }
  .bktile .num-hero { margin: 2px 0; }
  #result { margin-top: 10px; }
  .step { opacity: 0.4; pointer-events: none; }
  .step.active { opacity: 1; pointer-events: auto; }
"""

_SCRIPT = """
const RUN_ID = "__RUN_ID__";
let selected = new Set();

async function callApi(path, opts) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch (e) {}
  return { ok: r.ok, status: r.status, body };
}

function tile(label, n) {
  return '<div class="stat bktile"><div class="lab">' + label + '</div>' +
    '<div class="num-hero">' + n + '</div></div>';
}

document.getElementById('scan-btn').onclick = async () => {
  const cid = document.getElementById('camp-id').value.trim();
  if (!cid) return;
  selected = new Set([cid]);
  const status = document.getElementById('scan-status');
  status.textContent = 'Scanning...';
  const r = await callApi('/api/recontact/scan?campaign_id=' + encodeURIComponent(cid));
  if (!r.ok || !Array.isArray(r.body)) {
    status.textContent = (r.body && r.body.error) || 'Scan failed.';
    document.getElementById('scan-results').innerHTML = '';
    return;
  }
  status.textContent = r.body.length + ' similar campaign(s) found. Click a row to include or ' +
    'exclude it - the campaign you scanned is always included.';
  const rows = r.body.map(function (c) {
    return '<tr class="rowsel on" data-id="' + c.campaign_id + '">' +
      '<td><input type="checkbox" checked></td>' +
      '<td>' + (c.name || c.campaign_id) + '</td>' +
      '<td>' + (c.status || '') + '</td>' +
      '<td>' + c.finished + '</td>' +
      '<td>' + c.in_progress + '</td>' +
      '<td>' + c.overlap_count + '</td>' +
      '<td class="muted small">' + (c.match_reason || '') + '</td></tr>';
  }).join('');
  document.getElementById('scan-results').innerHTML = r.body.length ?
    '<table class="tbl"><tr><th></th><th>Campaign</th><th>Status</th><th>Finished</th>' +
    '<th>In progress</th><th>Lead overlap</th><th>Why it matched</th></tr>' + rows + '</table>' :
    '<p class="sub" style="margin-top:10px">No similarly-named campaigns found - you can still ' +
    'continue with just the one you scanned.</p>';
  r.body.forEach(function (c) { selected.add(String(c.campaign_id)); });
  document.querySelectorAll('#scan-results tr.rowsel').forEach(function (tr) {
    tr.onclick = function () {
      const id = tr.dataset.id;
      const cb = tr.querySelector('input');
      if (selected.has(id)) { selected.delete(id); tr.classList.remove('on'); cb.checked = false; }
      else { selected.add(id); tr.classList.add('on'); cb.checked = true; }
    };
  });
  document.getElementById('buckets-card').classList.add('active');
};

document.getElementById('buckets-btn').onclick = async () => {
  const status = document.getElementById('buckets-status');
  if (!selected.size) { status.textContent = 'Pick at least one campaign first.'; return; }
  status.textContent = 'Computing...';
  const include_repliers = document.getElementById('include-repliers').checked;
  const r = await callApi('/api/recontact/buckets', { method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ campaign_ids: [...selected], include_repliers, run_id: RUN_ID }) });
  if (!r.ok || !r.body || r.body.error) {
    status.textContent = (r.body && r.body.error) || 'Could not compute buckets.';
    return;
  }
  status.textContent = '';
  const b = r.body;
  document.getElementById('bucket-tiles').style.display = '';
  document.getElementById('bucket-tiles').innerHTML =
    tile('Eligible', b.eligible) + tile('Still in progress', b.in_progress) +
    tile('Suppressed', b.suppressed) + tile('Already replied', b.replied) +
    tile('Total contacted', b.total);
  const elsewhere = (b.active_elsewhere || []).map(function (x) {
    return x.campaign + ': ' + x.count;
  }).join(', ');
  const sampleRows = (b.sample || []).map(function (s) {
    return '<tr><td>' + s.email + '</td><td>' + s.verdict + '</td></tr>';
  }).join('');
  document.getElementById('sample-wrap').innerHTML =
    (elsewhere ? '<p class="sub" style="margin-top:10px">Active in another live campaign right now: ' +
      elsewhere + '</p>' : '') +
    (sampleRows ? '<table class="tbl" style="margin-top:10px"><tr><th>Email</th><th>Verdict</th></tr>' +
      sampleRows + '</table>' : '');
  document.getElementById('create-card').classList.toggle('active', b.eligible > 0);
};

document.getElementById('create-btn').onclick = async () => {
  const status = document.getElementById('create-status');
  const name = document.getElementById('draft-name').value.trim();
  const include_repliers = document.getElementById('include-repliers').checked;
  status.textContent = 'Creating...';
  const r = await callApi('/api/recontact/create', { method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ campaign_ids: [...selected], include_repliers, name, run_id: RUN_ID }) });
  if (!r.ok || !r.body || !r.body.ok) {
    status.textContent = (r.body && r.body.message) || 'Could not create the draft.';
    return;
  }
  status.textContent = 'Draft created: ' + r.body.id + ' (' + r.body.eligible + ' eligible leads). ' +
    'Open it from the Campaigns tab under unlinked drafts.';
};
"""


def render(run_id: str, seed_campaign_id: str = "") -> str:
    script = _SCRIPT.replace("__RUN_ID__", run_id.replace('"', ""))
    return ("""<!doctype html><html><head><meta charset="utf-8">
<title>Recontact review</title>
<link rel="stylesheet" href="/app/navreo.css">
<style>""" + _STYLE + """</style>
</head><body>
<div class="main">
  <div class="pagehead">
    <div>
      <div class="eyebrow">Recontact</div>
      <h1>Sibling campaign review</h1>
      <p class="sub" style="margin-top:6px">Find campaigns similar to one you pick, then see who is
        safe to recontact.</p>
    </div>
  </div>

  <div class="card">
    <div class="eyebrow">1. Pick a campaign</div>
    <div class="row">
      <input type="text" id="camp-id" placeholder="Smartlead campaign id" value=\"""" + esc(seed_campaign_id) + """\">
      <button class="btn primary sm" id="scan-btn">Scan for siblings</button>
    </div>
    <div id="scan-status" class="muted small"></div>
    <div id="scan-results"></div>
  </div>

  <div class="card step" id="buckets-card">
    <div class="eyebrow">2. Check who is eligible</div>
    <div class="row">
      <label class="toggle"><input type="checkbox" id="include-repliers"> Include people who replied before</label>
      <button class="btn sm" id="buckets-btn">Compute buckets</button>
    </div>
    <div id="buckets-status" class="muted small"></div>
    <div class="stats" id="bucket-tiles" style="display:none"></div>
    <div id="sample-wrap"></div>
  </div>

  <div class="card step" id="create-card">
    <div class="eyebrow">3. Create the recontact draft</div>
    <div class="row">
      <input type="text" id="draft-name" placeholder="Draft campaign name">
      <button class="btn primary sm" id="create-btn">Create draft</button>
    </div>
    <div id="create-status" class="muted small"></div>
  </div>
</div>
<script>""" + script + """</script>
</body></html>""")
