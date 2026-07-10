"""Upload-gate review page + decision logic for the signals tool.

Rendered at GET /qa-gate/<id>; actions POST to /api/qa-gate/<id>/<action>.
Runs live in the Supabase table qa_gate_runs (run jsonb + decisions jsonb);
server.py owns storage, this module owns rendering + pure decision logic.
Derived from lilly-upload-gate/scripts/render_report.py (keep in sync).
"""
import json, html, re, sys, pathlib, datetime

CHECK_LABELS = {
    "schema": "Required fields",
    "normalisation": "Name & company cleaning",
    "variable_fill": "Email variables filled",
    "recontact": "Already contacted / suppressed",
    "email_verification": "Email deliverability",
}
FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "job_title": "Job title",
    "company_name": "Company name", "company_website": "Company website",
    "company_size": "Company size", "company_location": "Company location",
    "personal_location": "Personal location", "data_source": "Data source",
    "email": "Email", "contact_history": "Contact history", "suppressions": "Suppression list",
    "Icebreaker": "Icebreaker",
}
# how each check's flags can be resolved on the page. Nobody hand-types lead data
# into a QA page: if a fix can't be automated, the realistic actions are drop the
# lead, drop all flagged leads, or approve (override) — so only "click" and "none".
FIX_MODE = {
    "schema": "none",            # data can't be conjured — drop or approve
    "normalisation": "click",    # one-click apply the suggested clean value
    "variable_fill": "none",     # icebreakers come from the icebreaker skills, not typing
    "recontact": "none",
    "email_verification": "none",
}
PILL = {"PASS": "g", "FAIL": "r", "OVERRIDDEN": "a", "RESOLVED": "g"}
PAGE_SIZE = 5
FONT_URL = "/app/fonts/AcidGrotesk-Normal.otf"


def esc(x):
    return html.escape(str(x))


def _date(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return str(iso)


def humanise(f):
    """Plain-English issue text (+ suggested fix value where one is known)."""
    d, check, field = f["detail"], f["check"], f["field"]
    if check == "schema":
        return f"{FIELD_LABELS.get(field, field)} is missing.", None
    if check == "normalisation":
        m = re.search(r": '(.*?)' -> '(.*?)'$", d) or re.search(r": \"(.*?)\" -> \"(.*?)\"$", d)
        kind = ("has extra spaces" if "whitespace" in d else
                "is written in all caps" if "shouting" in d else
                "carries a legal suffix" if "legal suffix" in d else "needs cleaning")
        return f"{FIELD_LABELS.get(field, field)} {kind}.", (m.group(2) if m else None)
    if check == "variable_fill":
        return f"{{{{{field}}}}} is empty — the email would send with a gap.", None
    if check == "recontact":
        if field == "suppressions":
            return f"On the suppression list — {d.split(':', 1)[-1].strip().replace('_', ' ')}.", None
        try:
            entries = json.loads(d)
            lines = [f"“{e['campaign'].strip()}” ({e.get('client','?')}) — {_date(e.get('first_contacted_at'))}"
                     for e in entries]
            head = f"Already emailed in {len(entries)} campaign{'s' if len(entries) > 1 else ''}: "
            return head + " · ".join(lines), None
        except (ValueError, KeyError, TypeError):
            return d, None
    if check == "email_verification":
        if "invalid" in d.lower():
            return "The verifier says this address doesn't exist — it would bounce.", None
        if "cap" in d.lower():
            return "Not verified — this run's verification call cap was reached first.", None
        if "no verdict" in d.lower():
            return "The verifier returned no verdict for this address.", None
        return d, None
    return d, None


def normalise_run(run):
    """Make any reasonably-shaped gate run renderable. Skills assemble run JSON
    with drifting shapes (top-level campaign_id vs campaign{}, results without
    detail text); the page must degrade gracefully, never 502."""
    run = dict(run or {})
    camp = run.get("campaign") if isinstance(run.get("campaign"), dict) else {}
    camp = dict(camp)
    if not camp.get("id"):
        camp["id"] = run.get("campaign_id") or "?"
    if not camp.get("name"):
        camp["name"] = run.get("campaign_name") or f"Campaign {camp['id']}"
    run["campaign"] = camp
    run["run_at"] = str(run.get("run_at") or "")
    res = {}
    for k, v in (run.get("results") or {}).items():
        v = dict(v) if isinstance(v, dict) else {"status": str(v)}
        st = str(v.get("status") or "FAIL").upper()
        v["status"] = st if st in ("PASS", "FAIL", "OVERRIDDEN", "RESOLVED") else             ("PASS" if st in ("OK", "GREEN") else "FAIL")
        v.setdefault("detail", "")
        res[k] = v
    run["results"] = res
    flags = []
    for f in (run.get("flags") or []):
        f = dict(f) if isinstance(f, dict) else {}
        f.setdefault("check", next(iter(res), "schema"))
        f.setdefault("email", "?")
        f.setdefault("field", "")
        f["detail"] = str(f.get("detail") or "")
        flags.append(f)
    run["flags"] = flags
    run["rows"] = run.get("rows") or []
    run["checklist"] = run.get("checklist") or []
    if not isinstance(run.get("rows_in"), int):
        run["rows_in"] = len(run["rows"])
    return run


def resolve(d, decisions):
    """Map decisions onto flags. Returns (state_by_flag_id, dropped_emails, fixed_lookup)."""
    d = normalise_run(d)
    dropped = {x["email"] for x in decisions if x["action"] == "dropped"}
    fixed = {(x["email"], x["field"]): x for x in decisions if x["action"] == "fixed"}
    ov = {x["id"]: x for x in decisions if x["action"] == "overridden"}
    verified = {x["email"]: x for x in decisions if x["action"] == "verified"}
    state = {}
    for i, f in enumerate(d["flags"]):
        if f["email"] in dropped:
            state[i] = ("dropped", None)
        elif (f["email"], f["field"]) in fixed:
            state[i] = ("fixed", fixed[(f["email"], f["field"])])
        elif f["check"] == "email_verification" and f["email"] in verified:
            state[i] = ("verified", verified[f["email"]])
        elif i in ov:
            state[i] = ("overridden", ov[i])
        else:
            state[i] = ("open", None)
    return state, dropped, fixed


def working_rows(d, decisions):
    """The corrected upload list: drops removed, fixes applied."""
    d = normalise_run(d)
    dropped = {x["email"] for x in decisions if x["action"] == "dropped"}
    fixes = [x for x in decisions if x["action"] == "fixed"]
    rows = [dict(r) for r in d.get("rows", []) if r["email"] not in dropped]
    for fx in fixes:
        for r in rows:
            if r["email"] == fx["email"]:
                r[fx["field"]] = fx["value"]
    return rows


def gate_state(d, decisions):
    d = normalise_run(d)
    state, _, _ = resolve(d, decisions)
    open_fail = any(st == "open" and
                    d["results"].get(d["flags"][i]["check"], {}).get("status", "FAIL") == "FAIL"
                    for i, (st, _) in state.items())
    if open_fail:
        return "BLOCKED"
    confirmed = {x["item"] for x in decisions if x["action"] == "confirmed"}
    if any(it not in confirmed for it in d.get("checklist", [])):
        return "CONFIRM CHECKLIST"
    return "CLEARED WITH OVERRIDES" if any(x["action"] == "overridden" for x in decisions) else "CLEARED"


def render(d, decisions=None, live=False, api_base="", list_id=None):
    d = normalise_run(d)
    decisions = decisions or []
    state, dropped, _ = resolve(d, decisions)
    stamp = d["run_at"][:19].replace(":", "-")
    n_open = sum(1 for st, _ in state.values() if st == "open")
    n_fixed = sum(1 for st, _ in state.values() if st == "fixed")
    n_ov = sum(1 for st, _ in state.values() if st == "overridden")
    n_up = d["rows_in"] - len(dropped)

    # per-check status after decisions
    statuses = {}
    for k, v in d["results"].items():
        ids = [i for i, f in enumerate(d["flags"]) if f["check"] == k]
        if v["status"] != "FAIL" or not ids:
            statuses[k] = v["status"]
        elif any(state[i][0] == "open" for i in ids):
            statuses[k] = "FAIL"
        elif any(state[i][0] == "overridden" for i in ids):
            statuses[k] = "OVERRIDDEN"
        else:
            statuses[k] = "RESOLVED"
    gate = gate_state(d, decisions)
    gate_pill = "r" if gate == "BLOCKED" else ("a" if gate in ("CONFIRM CHECKLIST",) or "OVERRIDES" in gate else "g")
    gate_line = ("Fix, drop, or override every flag below to clear the upload." if gate == "BLOCKED"
                 else "All flags resolved — tick the routine checklist to clear the upload."
                 if gate == "CONFIRM CHECKLIST"
                 else "Nothing left to resolve — the upload may proceed.")
    if gate != "BLOCKED" and d["rows_in"] - len(dropped) == 0:
        gate_line += " ⚠ 0 leads remain — clearing this gate uploads nothing."
    confirmed = {x["item"]: x for x in decisions if x["action"] == "confirmed"}

    cid = str(d["campaign"]["id"])
    sl_url = f"https://app.smartlead.ai/app/email-campaign/{cid}/analytics" if cid.isdigit() else None
    list_id = list_id or d.get("list_id")
    links = ""
    if sl_url:
        links += f"<a class='btn sm' href='{sl_url}' target='_blank'>View in Smartlead</a>"
    if list_id:
        links += (f"<a class='btn sm' href='/app/lists.html#{esc(list_id)}' "
                  f"target='_blank'>View list</a>")
    links_html = f"<div class='uplinks'>{links}</div>" if links else ""
    uploaded = next((x for x in decisions if x.get("action") == "upload"), None)
    if uploaded:
        up_html = ("<span class='pill a'><span class='dot'></span>Force-uploaded ⚠ · "
                   f"{esc(uploaded.get('by') or '')}</span>" if uploaded["mode"] == "forced" else
                   "<span class='pill g'><span class='dot'></span>Upload approved ✓ · "
                   f"{esc(uploaded.get('by') or '')}</span>")
        up_html = f"<div class='upwrap'>{up_html}{links_html}</div>"
    elif live:
        up_html = """
      <div class="upwrap">
        <div class="splitbtn">
          <button class="btn primary" id="upload-btn">Upload</button>
          <button class="btn primary caret" id="upload-caret">▾</button>
        </div>
        <div class="upmenu" id="upmenu" style="display:none">
          <button class="upopt" data-mode="approve"><b>Approve &amp; upload</b>
            <span>refuses while any check is failing</span></button>
          <button class="upopt" data-mode="force"><b>Force upload</b>
            <span>bypass the gate — only if the gate itself is broken</span></button>
        </div>
        <div class="upmsg small" id="upmsg"></div>
        __LINKS__
      </div>"""
        up_html = up_html.replace("__LINKS__", links_html)
    else:
        up_html = f"<div class='upwrap'>{links_html}</div>" if links else ""

    aud = d.get("list_audit")
    aud_html = ""
    if aud:
        acol = "#195C3F" if aud["score"] >= 70 else ("#6B4A00" if aud["score"] >= 50 else "#861E10")
        aud_html = (f"<div class='audscore'><div class='eyebrow'>List quality</div>"
                    f"<div class='num-hero' style='color:{acol}'>{aud['score']}</div>"
                    f"<div class='small muted'>{aud['on_icp']} of {aud['sampled']} sampled on-ICP</div></div>")

    # sticky routine checklist: auto ticks per check + manual confirmations
    ck_auto = "".join(
        f"<span class='ck-item {'done' if statuses[k] in ('PASS', 'RESOLVED', 'OVERRIDDEN') else ''}'>"
        f"{'✓' if statuses[k] in ('PASS', 'RESOLVED', 'OVERRIDDEN') else '○'} {esc(CHECK_LABELS.get(k, k))}</span>"
        for k in d["results"])
    ck_manual = ""
    for item in d.get("checklist", []):
        if item in confirmed:
            c = confirmed[item]
            ck_manual += (f"<span class='ck-item done'>✓ {esc(item)}"
                          f"{' · ' + esc(c['by']) if c.get('by') else ''}</span>")
        elif live:
            ck_manual += (f"<label class='ck-item todo'><input type='checkbox' class='ck' "
                          f"data-item='{esc(item)}'> {esc(item)}</label>")
        else:
            ck_manual += f"<span class='ck-item'>○ {esc(item)}</span>"
    checklist_bar = (f"<div class='card sunken stickyck'><div class='ckrow'>{ck_auto}"
                     f"{'<span class=ckdiv></span>' + ck_manual if ck_manual else ''}</div></div>"
                     if (d.get('checklist') or True) else "")

    stats = f"""
<div class="stats">
  <div class="stat"><div class="lab">Leads uploading</div><div class="num-hero">{n_up}</div>
    <div class="hint">{f"{len(dropped)} dropped from {d['rows_in']}" if dropped else f"all {d['rows_in']} kept"}</div></div>
  <div class="stat"><div class="lab">Flags open</div><div class="num-hero">{n_open}</div>
    <div class="hint">of {len(d['flags'])} found</div></div>
  <div class="stat"><div class="lab">Fixed</div><div class="num-hero">{n_fixed}</div>
    <div class="hint">applied to the list</div></div>
  <div class="stat"><div class="lab">Overridden</div><div class="num-hero">{n_ov}</div>
    <div class="hint">recorded in the audit</div></div>
</div>"""

    cards = ""
    for k, v in d["results"].items():
        fl = [(i, f) for i, f in enumerate(d["flags"]) if f["check"] == k]
        if not fl:
            continue  # clean checks live in the sticky strip's ticks — no empty card
        seen_fixpair = set()
        clickable = 0
        rows_html = ""
        for i, f in fl:
            text, suggest = humanise(f)
            st, dec = state[i]
            mode = FIX_MODE.get(k, "none")
            if st == "dropped":
                status_html = "<span class='pill n'>Lead dropped</span>"
                act = ""
            elif st == "fixed":
                status_html = f"<span class='pill g'><span class='dot'></span>Fixed</span>"
                act = f"<div class='ovnote'>now “{esc(dec['value'])}”{' · ' + esc(dec['by']) if dec.get('by') else ''}</div>"
            elif st == "verified":
                status_html = "<span class='pill g'><span class='dot'></span>Verified</span>"
                act = f"<div class='ovnote'>ListMint: {esc(dec.get('result', 'valid'))}</div>"
            elif st == "overridden":
                status_html = "<span class='pill a'><span class='dot'></span>Approved</span>"
                parts = [x for x in (dec.get("reason"), dec.get("by")) if x]
                act = f"<div class='ovnote'>{esc(' · '.join(parts))}</div>" if parts else ""
            else:
                approvable = k != "email_verification"  # deliverability is verify-or-drop, never approved
                status_html = "<span class='muted small'>○ Open</span>"
                drop_btn = (f"<button class='btn sm drop' data-email='{esc(f['email'])}' "
                            f"data-check='{esc(k)}'>Drop lead</button>")
                appr_btn = f"<button class='btn sm approve' data-id='{i}'>Approve</button>"
                if not live:
                    act = ""
                elif mode == "click" and suggest:
                    pair = (f["email"], f["field"])
                    dup = pair in seen_fixpair
                    seen_fixpair.add(pair)
                    clickable += 1  # label counts FLAGS resolved, not unique fields
                    act = (f"<div class='acts'><button class='btn sm fix' data-id='{i}' "
                           f"data-value='{esc(suggest)}'>✓ Fix → {esc(suggest)}</button>"
                           f"{drop_btn}{appr_btn}</div>")
                elif approvable:
                    act = f"<div class='acts'>{drop_btn}{appr_btn}</div>"
                else:
                    act = (f"<div class='acts'>{drop_btn}"
                           f"<span class='muted small'>blocked until verified — approve is unavailable here</span></div>")
            rows_html += (f"<tr data-check='{esc(k)}'><td class='ctl'>{status_html}</td>"
                          f"<td><div class='who'>{esc(f['email'])}</div>"
                          f"<div class='what'>{text if k == 'recontact' else esc(text)}</div>{act}</td></tr>")
        open_ids = [i for i, _ in fl if state[i][0] == "open"]
        n_card_open = len(open_ids)
        open_emails = sorted({f["email"] for i, f in fl if state[i][0] == "open"})
        bulk = ""
        if live and clickable >= 2:
            bulk += f"<button class='btn sm fixall' data-check='{esc(k)}'>✓ Fix all {clickable}</button>"
        if live and k == "email_verification" and open_emails:
            chat_prompt = ("Please verify these emails via lilly-email-verification and "
                           "re-run the upload gate — the upload is blocked until they have "
                           "a clean bill: " + ", ".join(open_emails))
            bulk += (f"<button class='btn sm copyprompt' data-prompt='{esc(chat_prompt)}'>"
                     f"Copy chat prompt</button>")
        if live and n_card_open >= 2:
            bulk += (f"<button class='btn sm dropall' data-check='{esc(k)}'>Drop {len(open_emails)} "
                     f"lead{'s' if len(open_emails) != 1 else ''}</button>")
            if k != "email_verification":
                ids_attr = ",".join(map(str, open_ids))
                bulk += (f"<button class='btn sm approveall' data-ids='{ids_attr}'>"
                         f"Approve all {n_card_open}</button>")
        fixall = bulk
        if fl:
            body = (f"<table class='tbl flagtbl' data-check='{esc(k)}'>"
                    f"<tr><th style='width:110px'>Status</th><th>Prospect &amp; issue</th></tr>{rows_html}</table>"
                    f"<div class='pager' data-check='{esc(k)}'></div>")
        hint = (" Rule of thumb: same offer, or contacted in the last 90 days → drop; "
                "approve only for a genuinely new offer.") if k == "recontact" else (
                " Tip: icebreaker gaps can be auto-filled by the icebreaker skill — "
                "consider recycling these leads instead of dropping.") if k == "variable_fill" else (
                f" ⛔ The upload is blocked until these leads are verified: "
                f"{', '.join(open_emails) if open_emails else '—'}. Copy the chat "
                "prompt to run verification in chat, or drop them. Approve is not "
                "available on this check.") if k == "email_verification" and open_emails else ""
        cards += (f"<div class='card' id='card-{esc(k)}'><div class='checkhead'><h2>{esc(CHECK_LABELS.get(k, k))}</h2>"
                  f"<span class='pill {PILL[statuses[k]]}'><span class='dot'></span>{statuses[k]}</span>"
                  f"<span class='spacer'></span>{fixall}</div>"
                  f"<p class='sub' style='margin-bottom:10px'>{esc(v['detail'])}{esc(hint)}</p>{body}</div>")

    approvable_ids = [i for i, (st, _) in state.items()
                      if st == "open" and d["flags"][i]["check"] != "email_verification"]
    ev_open = sorted({d["flags"][i]["email"] for i, (st, _) in state.items()
                      if st == "open" and d["flags"][i]["check"] == "email_verification"})
    ev_note = (f'<span class="muted small">⛔ {len(ev_open)} lead'
               f'{"s" if len(ev_open) != 1 else ""} blocked until email-verified — '
               f'see Email deliverability</span>' if ev_open else "")
    approve_bar = (f"""
  <div class="toolbar">
    <span class="eyebrow">Bulk actions</span>
    {f'<button class="btn sm" id="approve-everything" data-ids="{",".join(map(str, approvable_ids))}">Approve everything open ({len(approvable_ids)})</button>' if approvable_ids else ''}
    <button class="btn sm" id="drop-everything">Drop every flagged lead</button>
    {ev_note}
  </div>""" if live and n_open else "") if live else """
  <div class="card sunken"><div class="eyebrow" style="margin-bottom:6px">Read-only copy</div>
  <p class="sub">This is a saved snapshot. Serve it with <span class="mono">serve_review.py</span>
  to fix, drop, or override flags on the page.</p></div>"""

    script = """
<script>
const PAGE = %d;
document.querySelectorAll('.flagtbl').forEach(tbl => {
  const rows = [...tbl.querySelectorAll('tr')].slice(1);
  if (rows.length <= PAGE) return;
  const pager = document.querySelector(".pager[data-check='" + tbl.dataset.check + "']");
  let page = 0; const pages = Math.ceil(rows.length / PAGE);
  function show() {
    rows.forEach((r, i) => r.style.display = (i >= page*PAGE && i < (page+1)*PAGE) ? '' : 'none');
    pager.innerHTML = "<button class='btn sm' " + (page===0?'disabled':'') + " data-d='-1'>‹ Prev</button>" +
      "<span class='muted small'>Page " + (page+1) + " of " + pages + " · " + rows.length + " flags</span>" +
      "<button class='btn sm' " + (page===pages-1?'disabled':'') + " data-d='1'>Next ›</button>";
    pager.querySelectorAll('button').forEach(b => b.onclick = () => { page += +b.dataset.d; show(); });
  }
  show();
});
function actor() {
  let a = localStorage.getItem('gateActor');
  while (!a || !a.trim()) {
    a = prompt('Your name — recorded on every decision you make here:') || '';
  }
  localStorage.setItem('gateActor', a.trim());
  return a.trim();
}
const API_BASE = '__API_BASE__';
async function api(path, body, btn) {
  path = API_BASE + path;
  body.by = actor();
  if (btn) { btn.disabled = true; btn.textContent = 'Working…'; }
  const r = await fetch(path, { method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  if (r.ok) location.reload();
  else {
    alert('That didn\\u2019t save: ' + await r.text());
    if (btn) location.reload();
  }
}
document.addEventListener('click', e => {
  const t = e.target;
  if (t.classList.contains('fix')) api('/api/fix', {id: +t.dataset.id, value: t.dataset.value});
  if (t.classList.contains('fixall')) api('/api/fixall', {check: t.dataset.check});
  if (t.classList.contains('drop')) {
    if (confirm('Remove this lead from the upload? Every flag on them is resolved by the drop.'))
      api('/api/drop', {email: t.dataset.email, check: t.dataset.check});
  }
  if (t.classList.contains('dropall')) {
    if (confirm('Remove EVERY lead flagged in this check from the upload?'))
      api('/api/dropall', {check: t.dataset.check});
  }
  if (t.classList.contains('approve')) api('/api/override', {ids: [+t.dataset.id]});
  if (t.classList.contains('approveall') || t.id === 'approve-everything')
    api('/api/override', {ids: t.dataset.ids.split(',').map(Number)}, t);
  if (t.classList.contains('copyprompt')) {
    navigator.clipboard.writeText(t.dataset.prompt);
    t.textContent = 'Copied ✓';
    setTimeout(() => { t.textContent = 'Copy chat prompt'; }, 1800);
  }
  if (t.id === 'drop-everything') {
    if (confirm('Remove EVERY lead that still has an open flag from the upload?'))
      api('/api/dropall', {});
  }
});
document.addEventListener('change', e => {
  if (e.target.classList && e.target.classList.contains('ck') && e.target.checked)
    api('/api/confirm', {item: e.target.dataset.item});
});
const upBtn = document.getElementById('upload-btn');
if (upBtn) {
  const menu = document.getElementById('upmenu'), msg = document.getElementById('upmsg');
  document.getElementById('upload-caret').onclick = () =>
    menu.style.display = menu.style.display === 'none' ? '' : 'none';
  document.addEventListener('click', e => {
    if (!e.target.closest('.upwrap')) menu.style.display = 'none';
  });
  async function doUpload(mode) {
    menu.style.display = 'none';
    if (mode === 'force' &&
        !confirm('Force upload bypasses EVERY remaining check and is recorded in the audit as forced. Continue?')) return;
    const r = await fetch(API_BASE + '/api/upload', { method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ mode, by: actor() }) });
    if (r.ok) { location.reload(); return; }
    let info = null;
    try { info = await r.json(); } catch (err) { msg.textContent = await r.text(); return; }
    msg.textContent = info.message;
    const card = document.getElementById('card-' + info.first_fail);
    if (card) {
      card.scrollIntoView({behavior: 'smooth', block: 'center'});
      card.classList.add('attention');
      setTimeout(() => card.classList.remove('attention'), 2600);
    }
  }
  upBtn.onclick = () => doUpload('approve');
  document.querySelectorAll('.upopt').forEach(b => b.onclick = () => doUpload(b.dataset.mode));
}
</script>""" % PAGE_SIZE

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Upload gate — {esc(d['campaign']['name'])}</title>
<style>{CSS.replace('__FONT__', FONT_URL)}</style></head><body>
<div class="main">
  <div class="pagehead">
    <div>
      <div class="eyebrow">Upload gate</div>
      <h1>{esc(d['campaign']['name'])}</h1>
      <p class="sub" style="margin-top:6px">Gate
        <span class="pill {gate_pill}"><span class="dot"></span>{esc(gate)}</span>
        &nbsp;{esc(gate_line)}</p>
    </div>
    <div class="pagehead-right">
      {aud_html}
      <div class="pagehead-far">
        {up_html}
        <div class="freshness">Run <b>{esc(d['run_at'][:19])} UTC</b><br>Campaign <b>{f"<a href='{sl_url}' target='_blank'>{esc(cid)}</a>" if sl_url else esc(cid)}</b></div>
      </div>
    </div>
  </div>
  {checklist_bar}
  {stats}
  {approve_bar}
  {cards}
  <p class="muted mono" style="margin-top:20px">lilly-upload-gate · audit trail: list_upload_qa_runs · run {esc(stamp)}</p>
</div>
{script.replace("__API_BASE__", api_base)}</body></html>"""


CSS = """
@font-face { font-family: "Acid Grotesk"; src: url("__FONT__") format("opentype");
  font-weight: 400; font-style: normal; font-display: swap; }
:root {
  --orange:#FF4D00; --orange-600:#DB4100; --orange-700:#A83100; --orange-100:#FFE4D6;
  --ink:#14110E; --ink-2:#3A332C; --ink-3:#6B6055; --brown-400:#A89684; --cream:#F9F0E7;
  --bg:#FFFFFF; --bg-sunken:#F7F7F6; --card:#FFFFFF; --line:#ECECEA; --line-2:#DDDDDA;
  --green:#2E7D5B; --green-bg:#E2F1E9; --amber:#8F6600; --amber-bg:#F8EAC4;
  --red:#C2371F; --red-bg:#F7DCD5;
  --font-sans:"DM Sans","Helvetica Neue",system-ui,sans-serif;
  --font-display:"Acid Grotesk","DM Sans",sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,"SF Mono",monospace;
  --radius:12px; --focus:0 0 0 3px rgba(255,77,0,0.32);
}
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:var(--font-sans); background:var(--bg); color:var(--ink);
  line-height:1.45; letter-spacing:-0.015em; -webkit-font-smoothing:antialiased; }
.main { max-width:1080px; margin:0 auto; padding:28px 38px 80px; }
h1 { font-family:var(--font-display); font-weight:400; font-size:28px; letter-spacing:-0.03em; }
h2 { font-size:16px; font-weight:600; letter-spacing:-0.01em; }
.eyebrow { font-size:11px; font-weight:500; letter-spacing:0.12em; text-transform:uppercase; color:var(--ink-3); }
.sub { font-size:13.5px; color:var(--ink-2); }
.muted { color:var(--ink-3); }
.small { font-size:12px; }
.mono { font-family:var(--font-mono); letter-spacing:0; font-size:12px; }
.num-hero { font-family:var(--font-display); font-weight:400; font-size:34px; line-height:1; letter-spacing:-0.02em; }
.pagehead { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:6px; }
.freshness { text-align:right; font-size:11.5px; color:var(--ink-3); line-height:1.5; }
.freshness b { color:var(--ink-2); font-weight:600; }
.card { background:var(--card); border:1px solid var(--line); border-radius:var(--radius); padding:16px 18px; margin:14px 0; }
.card.sunken { background:var(--bg-sunken); }
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0 24px; }
.stat { border:1px solid var(--line); border-radius:var(--radius); padding:16px 18px; }
.stat .lab { font-size:12px; color:var(--ink-3); font-weight:500; margin-bottom:8px; }
.stat .hint { font-size:11.5px; color:var(--brown-400); margin-top:6px; }
.pill { font-size:11px; font-weight:500; padding:3px 9px; border-radius:999px; display:inline-flex; align-items:center; gap:5px; }
.pill .dot { width:6px; height:6px; border-radius:999px; background:currentColor; }
.pill.g { background:var(--green-bg); color:#195C3F; }
.pill.a { background:var(--amber-bg); color:#6B4A00; }
.pill.r { background:var(--red-bg); color:#861E10; }
.pill.n { background:#F2F2F0; color:var(--ink-2); }
.btn { border:1px solid var(--line-2); background:transparent; color:var(--ink);
  border-radius:999px; padding:8px 16px; font:500 13px var(--font-sans);
  cursor:pointer; display:inline-flex; align-items:center; gap:7px; white-space:nowrap; }
.btn:hover { background:var(--bg-sunken); }
.btn:focus-visible { outline:none; box-shadow:var(--focus); }
.btn.primary { background:var(--orange); border-color:var(--orange); color:var(--cream); }
.btn.primary:hover { background:var(--orange-600); }
.btn.sm { padding:5px 12px; font-size:11.5px; }
.btn[disabled] { opacity:0.55; cursor:not-allowed; }
.btn.fix, .btn.fixall { border-color:#C4E2D3; background:var(--green-bg); color:#195C3F; }
.btn.fix:hover, .btn.fixall:hover { background:#D3EADD; }
table.tbl { width:100%; border-collapse:collapse; font-size:13px; }
.tbl th { text-align:left; font-size:11px; font-weight:500; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--ink-3); padding:9px 12px; border-bottom:1px solid var(--line); }
.tbl td { padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
.tbl tr:last-child td { border-bottom:none; }
.tbl td.ctl { width:110px; }
.who { font-weight:600; font-size:13px; }
.what { font-size:13px; color:var(--ink-2); margin-top:2px; line-height:1.5; }
.acts { display:flex; gap:8px; margin-top:8px; align-items:center; flex-wrap:wrap; }
.toolbar { display:flex; gap:10px; align-items:center; margin:0 0 4px; flex-wrap:wrap; }
.pagehead-right { display:flex; gap:22px; align-items:flex-start; }
.pagehead-far { display:flex; flex-direction:column; gap:10px; align-items:flex-end; position:relative; }
.upwrap { position:relative; text-align:right; }
.splitbtn { display:inline-flex; }
.splitbtn .btn.primary { border-radius:999px 0 0 999px; }
.splitbtn .btn.caret { border-radius:0 999px 999px 0; border-left:1px solid rgba(255,255,255,0.35); padding:8px 11px; }
.upmenu { position:absolute; right:0; top:calc(100% + 6px); z-index:80; width:280px;
  background:var(--card); border:1px solid var(--line-2); border-radius:12px;
  box-shadow:0 10px 30px rgba(20,17,14,0.12); overflow:hidden; }
.upopt { display:block; width:100%; text-align:left; background:none; border:none;
  padding:11px 14px; cursor:pointer; font-family:var(--font-sans); }
.upopt:hover { background:var(--bg-sunken); }
.upopt b { display:block; font-size:13px; color:var(--ink); font-weight:600; }
.upopt span { display:block; font-size:11.5px; color:var(--ink-3); margin-top:2px; }
.upmsg { color:var(--red); max-width:280px; margin-top:6px; }
.uplinks { display:flex; gap:8px; margin-top:8px; justify-content:flex-end; }
a.btn { text-decoration:none; }
.attention { outline:2px solid var(--orange); outline-offset:2px; transition:outline 0.3s; }
.audscore { text-align:right; }
.audscore .num-hero { margin:2px 0; }
.stickyck { position:sticky; top:0; z-index:60; padding:10px 18px; }
.ckrow { display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
.ck-item { font-size:12px; color:var(--ink-3); display:inline-flex; align-items:center; gap:5px; }
.ck-item.done { color:#195C3F; font-weight:500; }
.ck-item.todo { color:var(--ink-2); cursor:pointer; }
.ckdiv { width:1px; height:16px; background:var(--line-2); }
.ovnote { font-size:12px; color:var(--ink-3); font-style:italic; margin-top:3px; }
.pager { display:flex; align-items:center; justify-content:space-between; padding-top:10px; }
.empty { text-align:center; color:var(--brown-400); font-size:13px; padding:24px 0; }
.checkhead { display:flex; align-items:center; gap:10px; margin-bottom:4px; }
.checkhead .spacer { flex:1; }
.ovbox { position:sticky; top:12px; z-index:50; box-shadow:0 6px 24px rgba(20,17,14,0.08); }
.ovrow { display:flex; gap:10px; }
.ovrow input { flex:1; padding:8px 14px; font:400 13px var(--font-sans); color:var(--ink);
  background:var(--card); border:1px solid var(--line-2); border-radius:999px; }
.ovrow input:focus { outline:none; box-shadow:var(--focus); }
input[type=checkbox] { accent-color:var(--ink); width:14px; height:14px; }
::selection { background:var(--orange-100); }
"""


# ── decision logic (pure: mutates nothing but the returned decisions list) ──

def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def apply_action(run, decisions, action, body):
    """Apply one review action. Returns (http_status, payload_dict, new_decisions).
    new_decisions is None when nothing changed (error paths)."""
    run = normalise_run(run)
    dec = list(decisions or [])
    flags = run["flags"]
    by = (body.get("by") or "").strip()
    if not by:
        return 400, {"error": "a reviewer name ('by') is required on every decision"}, None

    def ok():
        return 200, {"ok": True, "gate": gate_state(run, dec)}, dec

    if action in ("fix", "fixall"):
        todo = []
        if action == "fixall":
            check, seen = body.get("check"), set()
            for i, f in enumerate(flags):
                if f["check"] != check or (f["email"], f["field"]) in seen:
                    continue
                _, suggest = humanise(f)
                if suggest:
                    seen.add((f["email"], f["field"]))
                    todo.append((i, suggest))
            if not todo:
                return 400, {"error": "no suggested fixes in that check"}, None
        else:
            i, value = body.get("id"), (body.get("value") or "").strip()
            if not (isinstance(i, int) and 0 <= i < len(flags)) or not value:
                return 400, {"error": "invalid flag id or empty value"}, None
            todo = [(i, value)]
        existing = {(x["email"], x["field"]): x for x in dec if x["action"] == "fixed"}
        for i, value in todo:
            f = flags[i]
            pair = (f["email"], f["field"])
            resolved = [j for j, g in enumerate(flags)
                        if (g["email"], g["field"]) == pair and g["check"] == f["check"]]
            if pair in existing and action == "fixall":
                continue  # bulk never clobbers a deliberate manual re-fix
            if pair in existing:
                existing[pair].update({"value": value, "at": _now(), "by": by,
                                       "flag_ids": resolved})
            else:
                x = {"action": "fixed", "id": i, "email": f["email"], "field": f["field"],
                     "value": value, "flag_ids": resolved, "at": _now(), "by": by}
                dec.append(x)
                existing[pair] = x
        return ok()

    if action == "dropall":
        check = body.get("check")
        state, _, _ = resolve(run, dec)
        emails = {flags[i]["email"] for i, (st, _) in state.items()
                  if st == "open" and (not check or flags[i]["check"] == check)}
        if not emails:
            return 400, {"error": "no open flags to drop"}, None
        done = {x["email"] for x in dec if x["action"] == "dropped"}
        for e in sorted(emails):
            if e not in done:
                dec.append({"action": "dropped", "email": e, "check": check,
                            "at": _now(), "by": by})
        return ok()

    if action == "drop":
        email = (body.get("email") or "").strip()
        if not any(r["email"] == email for r in run.get("rows", [])):
            return 400, {"error": "unknown email"}, None
        if email not in {x["email"] for x in dec if x["action"] == "dropped"}:
            dec.append({"action": "dropped", "email": email,
                        "check": body.get("check"), "at": _now(), "by": by})
        return ok()

    if action == "confirm":
        item = (body.get("item") or "").strip()
        if item not in run.get("checklist", []):
            return 400, {"error": "unknown checklist item"}, None
        if item not in {x["item"] for x in dec if x["action"] == "confirmed"}:
            dec.append({"action": "confirmed", "item": item, "at": _now(), "by": by})
        return ok()

    if action == "override":
        ids, reason = body.get("ids"), (body.get("reason") or "").strip() or None
        if not ids or not all(isinstance(i, int) and 0 <= i < len(flags) for i in ids):
            return 400, {"error": "invalid flag ids"}, None
        # deliverability is verify-or-drop, NEVER approved
        if any(flags[i]["check"] == "email_verification" for i in ids):
            return 400, {"error": "unverified emails can't be approved — re-run "
                         "verification in chat (copy the chat prompt) or drop those leads"}, None
        state, _, _ = resolve(run, dec)
        bad = [i for i in ids if state[i][0] not in ("open", "overridden")]
        if bad:
            return 400, {"error": f"flags {bad} are already fixed/dropped — nothing to approve"}, None
        existing = {x["id"]: x for x in dec if x["action"] == "overridden"}
        for i in ids:
            if i in existing:
                existing[i].update({"reason": reason, "at": _now(), "by": by})
            else:
                f = flags[i]
                dec.append({"action": "overridden", "id": i, "check": f["check"],
                            "email": f["email"], "field": f["field"],
                            "reason": reason, "at": _now(), "by": by})
        return ok()

    if action == "upload":
        mode = body.get("mode")
        if mode not in ("approve", "force"):
            return 400, {"error": "mode must be 'approve' or 'force'"}, None
        if any(x.get("action") == "upload" for x in dec):
            return 200, {"ok": True, "already": True}, None
        g = gate_state(run, dec)
        if mode == "approve" and g in ("BLOCKED", "CONFIRM CHECKLIST"):
            state, _, _ = resolve(run, dec)
            open_by_check = {}
            for i, (st, _) in state.items():
                if st == "open":
                    k = run["flags"][i]["check"]
                    open_by_check[k] = open_by_check.get(k, 0) + 1
            first = next((k for k in run["results"] if open_by_check.get(k)), None)
            msg = ("Can't upload yet — " + ", ".join(
                f"{n} open in {CHECK_LABELS.get(k, k)}" for k, n in open_by_check.items())
                + ". Fix, drop, verify, or approve them first."
                if open_by_check else "Can't upload yet — the routine checklist isn't confirmed.")
            return 409, {"blocked": True, "gate": g, "open": open_by_check,
                         "first_fail": first, "message": msg}, None
        dec.append({"action": "upload", "mode": "forced" if mode == "force" else "approved",
                    "gate_at_upload": g, "at": _now(), "by": by})
        return ok()

    return 404, {"error": "unknown action"}, None
