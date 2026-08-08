#!/usr/bin/env python3
"""Calendly → replies-archive booking sync (meeting-attribution-truth loop,
2026-08-09).

WHY THIS EXISTS: the platform's meetings truth is `replies.category = 'Call
Booked'`, but most prospects book from the Calendly link WITHOUT sending
another email — no new reply arrives, nothing gets categorised Call Booked,
and the booking is invisible (measured 2026-08-09: 25 of 38 cold-email
Calendly bookings in 60 days had no Call Booked row). This sync makes the
booking itself the source of truth: every Calendly invitee whose email exists
in `contact_history` (i.e. a cold-email prospect, contacted BEFORE they
booked) gets one synthetic Call Booked row per booking event —
  smartlead_message_id = "calendly:<invitee_uuid>"   (idempotency key)
  replied_at           = the invitee's created_at    (the TRUE booking time)
  raw.source           = "calendly"                  (counting rules key on it)
Reschedules are collapsed (an invitee with rescheduled=true is skipped — the
successor event carries the booking); cancelled events still count as booked
(show-up is tracked separately). Internal emails are skipped.

Attribution: the lead's contact_history row with the latest activity at or
before booking names the campaign/workspace/client. DB-only writes — nothing
here ever touches Smartlead or emails anyone.

Run:  python3 app/calendly_sync.py [--days 120] [--dry-run]
Cron: run_daily.py calls run_calendly_sync() when CALENDLY_API_TOKEN is set
      (add it to the Render navreo-secrets group to activate server-side).
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CAL_API = "https://api.calendly.com"
SKIP_DOMAINS = ("navreo.ai",)  # internal bookers are never meetings

_CTX = ssl.create_default_context()
try:  # macOS python.org builds often miss the CA bundle — mirror certifi if present
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    if sys.platform == "darwin":
        _CTX.check_hostname = False
        _CTX.verify_mode = ssl.CERT_NONE


def load_keys() -> dict:
    keys = {}
    env_file = Path.home() / ".navreo-keys.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            m = re.match(r"^(?:export\s+)?([A-Z0-9_]+)=(\S+)", line.strip())
            if m:
                keys[m.group(1)] = m.group(2).strip("\"'")
    for k, v in os.environ.items():
        if v and (k in keys or re.search(r"(_KEY|_TOKEN|_URL)$", k)):
            keys[k] = v
    return keys


KEYS = load_keys()


def _http(method: str, url: str, headers: dict, body=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "User-Agent": "navreo-calendly-sync/1.0", **headers}, method=method)
    with urllib.request.urlopen(req, context=_CTX, timeout=60) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def _cal(url: str):
    return _http("GET", url, {"Authorization": f"Bearer {KEYS['CALENDLY_API_TOKEN']}"})


def _sb(method: str, path: str, body=None):
    url, key = KEYS["SUPABASE_URL"], KEYS["SUPABASE_SERVICE_ROLE_KEY"]
    hdrs = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"}
    return _http(method, f"{url}/rest/v1/{path}", hdrs, body)


def _paged_events(org: str, min_start: str, status: str):
    url = (f"{CAL_API}/scheduled_events?organization={urllib.parse.quote(org, safe='')}"
           f"&count=100&min_start_time={min_start}&status={status}")
    while url:
        page = _cal(url)
        yield from page.get("collection", [])
        url = (page.get("pagination") or {}).get("next_page")


def run_calendly_sync(days: int = 120, dry_run: bool = False) -> dict:
    """Idempotent; safe on any cadence. Returns a summary dict."""
    from datetime import datetime, timedelta, timezone
    if not KEYS.get("CALENDLY_API_TOKEN"):
        return {"ok": False, "skipped": True, "reason": "CALENDLY_API_TOKEN missing"}
    me = _cal(f"{CAL_API}/users/me")["resource"]
    org = me["current_organization"]
    min_start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    invitees = []  # one entry per booking event
    for status in ("active", "canceled"):
        for ev in _paged_events(org, min_start, status):
            for i in _cal(ev["uri"] + "/invitees?count=100").get("collection", []):
                email = (i.get("email") or "").strip().lower()
                if not email or any(email.endswith("@" + d) for d in SKIP_DOMAINS):
                    continue
                if i.get("rescheduled"):  # successor invitee carries the booking
                    continue
                invitees.append({
                    "uuid": i["uri"].rsplit("/", 1)[1], "email": email,
                    "name": i.get("name"), "booked_at": i.get("created_at") or ev["created_at"],
                    "event_name": ev.get("name"), "event_start": ev.get("start_time"),
                    "event_status": ev.get("status")})

    if not invitees:
        return {"ok": True, "events": 0, "inserted": 0, "existing": 0, "unmatched": 0}

    # Existing synthetic rows (idempotency) — one IN query per 100 uuids.
    have = set()
    uuids = [f'"calendly:{i["uuid"]}"' for i in invitees]
    for chunk in (uuids[n:n + 100] for n in range(0, len(uuids), 100)):
        q = urllib.parse.quote(",".join(chunk), safe="")
        rows = _http("GET", f"{KEYS['SUPABASE_URL']}/rest/v1/replies"
                            f"?select=smartlead_message_id&smartlead_message_id=in.({q})&limit=1000",
                     {"apikey": KEYS["SUPABASE_SERVICE_ROLE_KEY"],
                      "Authorization": f"Bearer {KEYS['SUPABASE_SERVICE_ROLE_KEY']}"})
        have |= {r["smartlead_message_id"] for r in rows}

    # contact_history match — the campaign that contacted them before booking.
    emails = sorted({i["email"] for i in invitees})
    hist, past_replies = {}, {}
    for chunk in (emails[n:n + 40] for n in range(0, len(emails), 40)):
        q = urllib.parse.quote(",".join(f'"{e}"' for e in chunk), safe="")
        rows = _http("GET", f"{KEYS['SUPABASE_URL']}/rest/v1/contact_history"
                            f"?select=email,smartlead_campaign_id,workspace,client_id,person_id,"
                            f"first_contacted_at,last_event_at&email=in.({q})&limit=1000",
                     {"apikey": KEYS["SUPABASE_SERVICE_ROLE_KEY"],
                      "Authorization": f"Bearer {KEYS['SUPABASE_SERVICE_ROLE_KEY']}"})
        for r in rows:
            hist.setdefault(r["email"].lower(), []).append(r)
        # Their archived replies: the campaign they actually REPLIED in beats
        # contact_history's latest-event pick (a lead in sibling campaigns got
        # mis-attributed without this — asher/andy.hutt, 2026-08-09).
        rrows = _http("GET", f"{KEYS['SUPABASE_URL']}/rest/v1/replies"
                             f"?select=email,smartlead_campaign_id,replied_at"
                             f"&email=in.({q})&order=replied_at&limit=1000",
                      {"apikey": KEYS["SUPABASE_SERVICE_ROLE_KEY"],
                       "Authorization": f"Bearer {KEYS['SUPABASE_SERVICE_ROLE_KEY']}"})
        for r in rrows:
            past_replies.setdefault(r["email"].lower(), []).append(r)

    # Registered (non-subsequence) campaigns — the only ones that may take
    # meeting credit when a better-evidenced option exists.
    sc = _http("GET", f"{KEYS['SUPABASE_URL']}/rest/v1/campaign_scorecard"
                      f"?select=smartlead_campaign_id&limit=10000",
               {"apikey": KEYS["SUPABASE_SERVICE_ROLE_KEY"],
                "Authorization": f"Bearer {KEYS['SUPABASE_SERVICE_ROLE_KEY']}"})
    scorecard_ids = {str(r["smartlead_campaign_id"]) for r in sc}

    inserted, existing, unmatched = 0, 0, 0
    for i in invitees:
        mid = f"calendly:{i['uuid']}"
        if mid in have:
            existing += 1
            continue
        cands = [h for h in (hist.get(i["email"]) or [])
                 if (h.get("first_contacted_at") or "9999") <= i["booked_at"]]
        if not cands:
            unmatched += 1  # not a cold-email booking (referral/ads/direct)
            continue
        best = max(cands, key=lambda h: h.get("last_event_at") or h.get("first_contacted_at") or "")
        reps = [r for r in (past_replies.get(i["email"]) or []) if r["replied_at"] <= i["booked_at"]]
        # Replied-in campaign beats contact_history's latest-event pick — but
        # subsequence campaigns ("Meeting Request"/"Interested Reply" flows,
        # deliberately off the scorecard) must not take the credit: the meeting
        # belongs to the ORIGINAL campaign whose variant earned it.
        reps_main = [r for r in reps if str(r["smartlead_campaign_id"]) in scorecard_ids]
        if reps_main:
            rep_cid = reps_main[-1]["smartlead_campaign_id"]
            best = dict(next((h for h in cands if h["smartlead_campaign_id"] == rep_cid), best),
                        smartlead_campaign_id=rep_cid)
        else:
            cands_main = [h for h in cands if str(h["smartlead_campaign_id"]) in scorecard_ids]
            if cands_main:
                best = max(cands_main, key=lambda h: h.get("last_event_at") or h.get("first_contacted_at") or "")
            elif reps:
                rep_cid = reps[-1]["smartlead_campaign_id"]
                best = dict(next((h for h in cands if h["smartlead_campaign_id"] == rep_cid), best),
                            smartlead_campaign_id=rep_cid)
        row = {"smartlead_campaign_id": best["smartlead_campaign_id"], "email": i["email"],
               "category": "Call Booked", "replied_at": i["booked_at"],
               "workspace": best.get("workspace"), "client_id": best.get("client_id"),
               "person_id": best.get("person_id"), "smartlead_message_id": mid,
               "reply_subject": f"Calendly booking: {i.get('event_name') or ''}".strip(),
               "reply_body": "",
               "raw": {"source": "calendly", "event_start": i.get("event_start"),
                       "event_status": i.get("event_status"), "invitee_name": i.get("name")}}
        if dry_run:
            print(f"  DRY: would insert {i['email']} -> campaign {row['smartlead_campaign_id']}"
                  f" booked {i['booked_at'][:10]} ({i.get('event_status')})")
        else:
            _sb("POST", "replies", row)
        inserted += 1
    return {"ok": True, "events": len(invitees), "inserted": inserted,
            "existing": existing, "unmatched": unmatched, "dry_run": dry_run}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run_calendly_sync(days=a.days, dry_run=a.dry_run), indent=2))
