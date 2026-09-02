"""Server-side upload gate for leads that entered Smartlead around the tool.

Owner ruling 2026-09-02: "Force it to go through our safety checks."

The chat-side gate (lilly-upload-gate) and the tool's own push paths write a
`list_upload_qa_runs` row before anything reaches Smartlead. Lists loaded any
other way — the Smartlead UI, Clay, an ungated chat push — never touch it; the
5-minute daily sync then discovers those leads and files them in
`contact_history` with source='daily_sync'. Between 29 Jul and 2 Sep 2026 that
route carried ~154k leads past the gate. In the seven days to 2 Sep alone the
gate's own checks would have stopped ~16k of 59k: 6,349 on suppressed domains,
9,950 contacted by the same client inside the prior 30 days, 68 who had already
replied positively.

Nothing can stop a Smartlead UI upload from here, so this is the enforcement
that binds: every new daily_sync lead in a campaign with no gate record is run
through the server-runnable checks, and any that fail are PAUSED in Smartlead
(reversible, stops the sequence at once). One `list_upload_qa_runs` row is
written per campaign batch so the upload is documented like a gated one, and
one `intake_gate_verdicts` row per lead so nothing is evaluated twice and the
health check can grade it.

Checks (the ones that protect reputation and are answerable from our own data):
  suppressed_email / suppressed_domain — the client's suppression list
  recontact_30d   — same email, same client, another campaign, first contacted
                    within the 30 days before this one (CROSS_CLIENT_ALLOWED
                    pairs excepted, per the chat gate's config)
  positive_replier — already Interested / Meeting Request / Call Booked /
                     Information Request anywhere for this client
  dnc_replier     — replied "Do Not Contact" anywhere
  invalid_email   — verification cache says the address is bad
Paid verification (MillionVerifier) is NOT run here: no spend without a ruling.

Rides pg_cron `intake-gate-tick` (every 30 min) → /api/cron/intake-gate.
A watermark on first_contacted_at is carried in the run's own activity-log row,
so each lead is looked at once; the first ever run starts one hour back rather
than sweeping the historical backlog (that is an explicit `since=` call, and a
decision, not a default).
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import server

ENDPOINT = "/api/cron/intake-gate"
LIST_SOURCE = "intake-gate (smartlead direct)"
POSITIVE_CATS = ("Interested", "Call Booked", "Meeting Request", "Information Request")
DNC_CATS = ("Do Not Contact",)
BAD_VERIFICATIONS = ("bad", "invalid", "catch_all_invalid")   # people.email_verification values in use
RECONTACT_DAYS = 30
CROSS_CLIENT_ALLOWED = {frozenset(("navreo", "arnic"))}   # mirrors lilly-upload-gate
MAX_LEADS_PER_RUN = 20000
MAX_PAUSES_PER_RUN = 2500
GATE_RUN_WINDOW_DAYS = 3       # a tool push this close to the arrivals = they were gated
CHUNK = 100                    # emails per PostgREST in.() — keeps URLs under the limit
HISTORY_CHUNK = 40             # recontact lookup fans out per email; keep it inside the 8s statement timeout


def log(msg: str):
    print(f"[intake-gate] {msg}", file=sys.stderr)


def _q(s) -> str:
    return urllib.parse.quote(str(s), safe="")


def _in(vals) -> str:
    """PostgREST in.(...) list, percent-encoded. Encoding is load-bearing twice
    over: a category like "Call Booked" carries a space urllib refuses outright,
    and a plus-addressed email would otherwise decode to a space server-side."""
    return urllib.parse.quote(",".join('"' + str(v).replace('"', '') + '"' for v in vals), safe=",")


def _get(path: str) -> list:
    """Strict read for the checks: a failed lookup must FAIL the run, never pass
    as "no hits" — for a gate, an unreadable suppression list means nothing is
    known to be safe. The run records the error and the watermark stays put."""
    rows = server.sb("GET", path)
    if not isinstance(rows, list):
        raise RuntimeError(f"read failed: {path.split('?', 1)[0]}")
    return rows


# Follow-up / reply campaigns exist to recontact people who already replied, so
# the recontact and positive-replier checks do not apply to them (suppression,
# DNC and bad-address checks still do). Matched on the campaign name.
import re
FOLLOWUP_NAME_RE = re.compile(r"reply|follow[- ]?up|subsequence|nurture", re.I)


def _sl_pause(cid, lead_id, key) -> bool:
    """POST /campaigns/{cid}/leads/{lead_id}/pause with the same pacing and 429
    backoff as sync_booked.sl_json. True on success."""
    url = f"{server.SMARTLEAD_BASE}/campaigns/{cid}/leads/{lead_id}/pause?api_key={key}"
    for attempt, delay in ((1, 5), (2, 20), (3, 45), (4, 0)):
        try:
            server.http_json("POST", url, {}, {})
            time.sleep(0.4)
            return True
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) and delay:
                log(f"smartlead 429 — backing off {delay}s (attempt {attempt})")
                time.sleep(delay)
                continue
            log(f"pause failed cid={cid} lead={lead_id}: {str(e)[:160]}")
            return False
    return False


def _last_watermark() -> str | None:
    rows = server.sb("GET", "app_activity_log?action=eq.intake_gate&select=payload"
                            "&order=ts.desc&limit=1")
    # A PostgREST error comes back as a dict, and dict[0] raised KeyError(0) on
    # the very first live call (2026-09-02 08:24, logged as error "0"). Falling
    # back to the 1h default is safe: already-judged leads are skipped by
    # _already_judged, so a watermark that steps back never double-pauses.
    if isinstance(rows, list) and rows and isinstance(rows[0].get("payload"), dict):
        return rows[0]["payload"].get("watermark")
    return None


def _gated_campaigns(cids, lo_iso, hi_iso) -> set:
    """Campaigns with a real gate run near these arrivals — the tool pushed
    them, and the daily sync is merely re-discovering gated leads."""
    out = set()
    for i in range(0, len(cids), CHUNK):
        chunk = cids[i:i + CHUNK]
        rows = _get("list_upload_qa_runs?select=campaign_id"
                    f"&campaign_id=in.({_in(chunk)})&rows_uploaded=gt.0"
                    f"&list_source=not.like.{_q('intake-gate%')}"
                    f"&run_at=gte.{_q(lo_iso)}&run_at=lte.{_q(hi_iso)}")
        out |= {str(r.get("campaign_id")) for r in rows if r.get("campaign_id") is not None}
    return out


def _already_judged(cid, emails) -> set:
    out = set()
    for i in range(0, len(emails), CHUNK):
        chunk = emails[i:i + CHUNK]
        rows = _get("intake_gate_verdicts?select=email"
                    f"&smartlead_campaign_id=eq.{cid}&email=in.({_in(chunk)})")
        out |= {(r.get("email") or "").lower() for r in rows}
    return out


def _check_batch(leads: list, campaign_name: str = "") -> dict:
    """-> {email_lower: [flags]} for one campaign's batch. Every lookup is a
    handful of in.() reads; nothing here calls Smartlead or spends money."""
    flags: dict = {l["email"].lower(): [] for l in leads}
    by_email = {l["email"].lower(): l for l in leads}
    emails = list(by_email)
    domains = sorted({(l.get("company_domain") or "").lower() for l in leads
                      if l.get("company_domain")})
    client = leads[0].get("client_id")
    cid = str(leads[0]["smartlead_campaign_id"])
    followup = bool(FOLLOWUP_NAME_RE.search(campaign_name or ""))

    def client_ok(row_client):
        return row_client is None or row_client == client

    for i in range(0, len(emails), CHUNK):
        chunk = emails[i:i + CHUNK]
        for s in _get("suppressions?select=email,client_id"
                      f"&email=in.({_in(chunk)})"):
            e = (s.get("email") or "").lower()
            if e in flags and client_ok(s.get("client_id")):
                flags[e].append("suppressed_email")
        # recontact: same email, same client, another campaign, first contacted
        # inside the 30 days before THIS arrival
        cats = _in(POSITIVE_CATS + DNC_CATS)
        for r in _get("replies?select=email,category,client_id"
                      f"&email=in.({_in(chunk)})&category=in.({cats})"):
            e = (r.get("email") or "").lower()
            if e not in flags or not client_ok(r.get("client_id")):
                continue
            tag = "dnc_replier" if r.get("category") in DNC_CATS else "positive_replier"
            if tag == "positive_replier" and followup:
                continue
            if tag not in flags[e]:
                flags[e].append(tag)
        for p in _get("people?select=email,email_verification"
                      f"&email=in.({_in(chunk)})"
                      f"&email_verification=in.({_in(BAD_VERIFICATIONS)})"):
            e = (p.get("email") or "").lower()
            if e in flags:
                flags[e].append("invalid_email")
    if not followup:
        # recontact: same email, SAME client, another campaign, first contacted
        # inside the 30 days before the earliest arrival in this batch. Filtered
        # server-side on client + window so the read stays small: an unfiltered
        # per-email history fan-out timed out at 150 emails on 2026-09-02.
        earliest = min((l.get("first_contacted_at") or "9999") for l in leads)
        lo_all = (datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                  - timedelta(days=RECONTACT_DAYS)).isoformat()
        client_f = f"&client_id=eq.{_q(client)}" if client else "&client_id=is.null"
        for i in range(0, len(emails), HISTORY_CHUNK):
            chunk = emails[i:i + HISTORY_CHUNK]
            for r in _get("contact_history?select=email,smartlead_campaign_id,first_contacted_at"
                          f"&email=in.({_in(chunk)})&smartlead_campaign_id=neq.{cid}"
                          f"{client_f}&first_contacted_at=gte.{_q(lo_all)}"):
                e = (r.get("email") or "").lower()
                me = by_email.get(e)
                if not me or not r.get("first_contacted_at"):
                    continue
                mine = me.get("first_contacted_at") or ""
                lo = (datetime.fromisoformat(mine.replace("Z", "+00:00"))
                      - timedelta(days=RECONTACT_DAYS)).isoformat()
                if lo <= r["first_contacted_at"] < mine and "recontact_30d" not in flags[e]:
                    flags[e].append("recontact_30d")
    for i in range(0, len(domains), CHUNK):
        chunk = domains[i:i + CHUNK]
        hit = {(s.get("domain") or "").lower() for s in
               _get("suppressions?select=domain,client_id"
                    f"&domain=in.({_in(chunk)})")
               if client_ok(s.get("client_id"))}
        if hit:
            for l in leads:
                d = (l.get("company_domain") or "").lower()
                if d in hit:
                    flags[l["email"].lower()].append("suppressed_domain")
    return flags


def run(dry_run: bool = False, since: str | None = None) -> dict:
    """One sweep. dry_run: evaluate + count, pause nothing, write nothing.
    since: explicit lower bound (ISO) — for a deliberate backlog sweep only."""
    t0 = time.time()
    now = datetime.now(timezone.utc)
    watermark = since or _last_watermark() or (now - timedelta(hours=1)).isoformat()
    out = {"ok": True, "dry_run": dry_run, "since": watermark, "scanned": 0,
           "skipped_gated": 0, "skipped_judged": 0, "evaluated": 0, "flagged": 0,
           "paused": 0, "pause_failed": 0, "allowed": 0, "campaigns": 0,
           "by_flag": {}, "per_campaign": [], "watermark": watermark}
    try:
        rows = server.sb_get_all(
            "contact_history?select=email,company_domain,client_id,workspace,"
            "smartlead_campaign_id,smartlead_lead_id,status,first_contacted_at"
            f"&source=eq.daily_sync&first_contacted_at=gt.{_q(watermark)}"
            "&order=first_contacted_at.asc,id.asc")
        if rows is None:
            # sb_get_all returns None when a page fails outright. Treat that as a
            # failed run, never as "no arrivals": the watermark must not advance
            # and the health check must see it (2026-09-02: a reset connection
            # first surfaced here as a clean ok/scanned=0).
            out["ok"] = False
            out["error"] = "contact_history read failed (Supabase unreachable or timed out)"
            out["elapsed_s"] = round(time.time() - t0, 1)
            return out
        rows = [r for r in rows if r.get("email") and r.get("smartlead_campaign_id")]
        rows = rows[:MAX_LEADS_PER_RUN]
        out["scanned"] = len(rows)
        if not rows:
            out["elapsed_s"] = round(time.time() - t0, 1)
            return out
        new_wm = max(r["first_contacted_at"] for r in rows)
        by_cid: dict = {}
        for r in rows:
            by_cid.setdefault(str(r["smartlead_campaign_id"]), []).append(r)
        lo = (datetime.fromisoformat(min(r["first_contacted_at"] for r in rows).replace("Z", "+00:00"))
              - timedelta(days=GATE_RUN_WINDOW_DAYS)).isoformat()
        hi = (datetime.fromisoformat(new_wm.replace("Z", "+00:00")) + timedelta(days=1)).isoformat()
        gated = _gated_campaigns(list(by_cid), lo, hi)
        names = {}
        for i in range(0, len(by_cid), CHUNK):
            chunk = list(by_cid)[i:i + CHUNK]
            for c in server.sb("GET", "campaigns?select=smartlead_campaign_id,name"
                                      f"&smartlead_campaign_id=in.({_in(chunk)})") or []:
                names[str(c.get("smartlead_campaign_id"))] = c.get("name") or ""
        pauses_left = MAX_PAUSES_PER_RUN
        for cid, leads in by_cid.items():
            if cid in gated:
                out["skipped_gated"] += len(leads)
                continue
            judged = set() if dry_run else _already_judged(cid, [l["email"] for l in leads])
            leads = [l for l in leads if l["email"].lower() not in judged]
            out["skipped_judged"] += len(judged)
            if not leads:
                continue
            out["campaigns"] += 1
            flags = _check_batch(leads, names.get(cid, ""))
            flagged = [l for l in leads if flags[l["email"].lower()]]
            out["evaluated"] += len(leads)
            out["flagged"] += len(flagged)
            for fl in flags.values():
                for f in fl:
                    out["by_flag"][f] = out["by_flag"].get(f, 0) + 1
            paused = failed = 0
            verdicts = []
            key = server.ws_key(leads[0].get("workspace")) if not dry_run else ""
            for l in leads:
                fl = flags[l["email"].lower()]
                action = "allowed"
                if fl:
                    if dry_run:
                        action = "would_pause"
                    elif not l.get("smartlead_lead_id"):
                        action, failed = "pause_failed", failed + 1
                    elif pauses_left <= 0:
                        action = "pause_deferred"   # next tick picks it up (not judged)
                    elif _sl_pause(cid, l["smartlead_lead_id"], key):
                        action, paused, pauses_left = "paused", paused + 1, pauses_left - 1
                    else:
                        action, failed = "pause_failed", failed + 1
                if action != "pause_deferred":
                    verdicts.append({"workspace": l.get("workspace"), "client_id": l.get("client_id"),
                                     "smartlead_campaign_id": int(cid),
                                     "smartlead_lead_id": l.get("smartlead_lead_id"),
                                     "email": l["email"], "flags": fl, "action": action,
                                     "detail": {"status_at_gate": l.get("status"),
                                                "first_contacted_at": l.get("first_contacted_at")}})
            out["paused"] += paused
            out["pause_failed"] += failed
            out["allowed"] += len(leads) - len(flagged)
            summary = {"campaign_id": cid, "campaign": names.get(cid, "")[:80],
                       "followup_exempt": bool(FOLLOWUP_NAME_RE.search(names.get(cid, ""))),
                       "leads": len(leads), "flagged": len(flagged), "paused": paused,
                       "pause_failed": failed}
            out["per_campaign"].append(summary)
            if dry_run:
                continue
            qa = server.sb("POST", "list_upload_qa_runs",
                           [{"campaign_id": cid, "campaign_name": names.get(cid, ""),
                             "list_source": LIST_SOURCE, "rows_in": len(leads),
                             "rows_uploaded": len(leads) - paused,
                             "checks": {"pipeline": "intake-gate: suppressions + recontact-30d + "
                                                    "positive/DNC repliers + verification cache",
                                        "flag_counts": {f: sum(1 for v in flags.values() if f in v)
                                                        for f in {x for v in flags.values() for x in v}},
                                        "note": "leads reached Smartlead without a gate run; "
                                                "flagged leads paused in place"},
                             "overrides": [], "recontact_hits": {"paused": paused, "pause_failed": failed},
                             "verdict": "enforced" if paused else ("blocked" if failed else "pass"),
                             "report_path": f"intake_gate_verdicts campaign {cid}"}],
                           prefer="return=representation")
            qa_id = qa[0].get("id") if isinstance(qa, list) and qa else None
            for v in verdicts:
                v["qa_run_id"] = qa_id
            for i in range(0, len(verdicts), 500):
                server.sb("POST", "intake_gate_verdicts?on_conflict=smartlead_campaign_id,email",
                          verdicts[i:i + 500],
                          prefer="resolution=merge-duplicates,return=minimal")
        if not dry_run:
            out["watermark"] = new_wm
        out["elapsed_s"] = round(time.time() - t0, 1)
        return out
    except Exception as e:  # noqa: BLE001 — record, never raise into the cron thread
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["elapsed_s"] = round(time.time() - t0, 1)
        return out


def run_and_log(dry_run: bool = False, since: str | None = None) -> dict:
    res = run(dry_run=dry_run, since=since)
    if not dry_run:
        payload = {k: v for k, v in res.items() if k != "per_campaign"}
        payload["per_campaign"] = res.get("per_campaign", [])[:25]
        server.log_activity(ENDPOINT, payload, actor="cron",
                            action="intake_gate" if res.get("ok") else "intake_gate_failed",
                            entity="contact_history")
    return res


if __name__ == "__main__":   # local: python3 intake_gate.py [--dry] [--since ISO]
    args = sys.argv[1:]
    dry = "--dry" in args
    since = args[args.index("--since") + 1] if "--since" in args else None
    import json
    print(json.dumps(run(dry_run=dry, since=since), indent=1, default=str))
