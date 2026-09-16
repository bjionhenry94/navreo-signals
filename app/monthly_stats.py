#!/usr/bin/env python3
"""client_monthly_stats writer — the month-by-month row every client's Campaign
Dashboard reads.

Why a writer and not a web-request computation: the Render web instance is
512 MB and a month-by-month rebuild costs one scoped Smartlead
day-wise-overall-stats call PER MONTH PER CLIENT plus a replies sweep. That is
cron work. `/app/dashboard.html` only ever SELECTs from the table this fills.

Data paths — all reused, nothing new invented:

  sent / replied / bounced  server._daywise_series(), the exact same scoped
                            Smartlead call `_report_range_stats` makes. For a
                            shared-workspace client (Amplifyy, Arnic,
                            TouchPoint, Altius Reach, ThunderBird, …) the call
                            is scoped by that client's SCORECARD CAMPAIGN IDS
                            on the Navreo key — the one filter that gives a
                            shared client its real line instead of the fleet's.
                            An own-workspace client reads its own workspace
                            with its own key (client == workspace there).
  positive / meetings       the replies archive under
                            server._AH_POSITIVE_CATS (the analytics hub's
                            category-NAME mapping, never raw reply text), with
                            the hub's Call Booked dedupe: calendly bookings
                            count once per booking DAY, legacy Call Booked
                            leads once per campaign and never on top of a
                            calendly booking for the same lead.
  campaigns_active          campaigns that first-contacted anyone in the month,
                            from the campaign_contact_months() RPC (PostgREST
                            has aggregates disabled — see the migration).
  first month               earliest contact_history.first_contacted_at across
                            the client's campaigns, from the same RPC.

Idempotent: every run upserts on (client, month) so re-running only refreshes.
Called from app/run_daily.py after the capacity write.
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

# Smartlead's shared 200/min budget — the same pacing _report_range_stats uses
# between its per-campaign calls.
_CALL_PAUSE_S = 0.15
_MAX_MONTHS = 60  # hard ceiling: a bad first-contact date can't fan out forever
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_S = 3
_RETRY_429_S = 35  # Smartlead's 200/min bucket — wait it out, don't burn a retry


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _month_end(d: date) -> date:
    return _next_month(d) - timedelta(days=1)


def _months_between(first: date, last: date) -> list:
    out, m = [], _month_start(first)
    stop = _month_start(last)
    while m <= stop and len(out) < _MAX_MONTHS:
        out.append(m)
        m = _next_month(m)
    return out


def _retry(fn, what: str):
    """One retry on a transient failure (429 / 5xx / network), per the cron
    contract. A second failure returns None and the leg degrades to zeros —
    a missing month is re-filled by tomorrow's run, never written as a lie."""
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transient = any(t in msg for t in ("429", "500", "502", "503", "504",
                                               "timed out", "timeout", "Connection"))
            print(f"  ! {what} attempt={attempt} failed: {type(e).__name__}: {msg[:160]}",
                  flush=True)
            if attempt < _RETRY_ATTEMPTS and transient:
                # a 429 is Smartlead's shared 200/min budget talking — wait out
                # a whole bucket rather than burn the retry a second later
                time.sleep(_RETRY_429_S if "429" in msg else _RETRY_BACKOFF_S)
                continue
            return None


def _client_campaigns() -> dict:
    """{client_label: {"ws": workspace, "ids": [str campaign ids]}} off the
    cached campaign_scorecard — the one client-label authority every other
    surface reads. DRAFTED campaigns never sent, so they are excluded (same
    rule as _report_range_stats); __unassigned campaigns belong to no client
    and must not inflate anyone's totals."""
    rows = server.sb_get_all(
        "campaign_scorecard?select=smartlead_campaign_id,workspace,name,status,client"
        "&order=smartlead_campaign_id") or []
    out = {}
    for r in rows:
        cid = str(r.get("smartlead_campaign_id") or "")
        if not cid or cid.startswith("hr-"):
            continue
        if str(r.get("status") or "").upper() == "DRAFTED":
            continue
        ws = r.get("workspace") or "navreo"
        label = r.get("client") or server._client_win_label(ws, r.get("name") or "")
        if not label or label == server._CLIENT_UNASSIGNED:
            continue
        ent = out.setdefault(label, {"ws": ws, "ids": []})
        ent["ids"].append(cid)
        if ws != "navreo":
            ent["ws"] = ws
    return out


# contact_history is ~1.7M rows and a client's heaviest campaigns carry
# 100k+ each, so one RPC call over ALL of a client's ids hits Postgres'
# statement timeout (measured: >150 Navreo ids, and even 50 Arnic ids, die at
# ~18.5s). Chunk small and split on failure rather than lose the client.
_RPC_CHUNK = 20


def _contact_months(ids: list) -> dict:
    """{month_iso: set(campaign_id)} from the campaign_contact_months RPC.

    Adaptive chunking: a chunk that fails (statement timeout on a heavy
    campaign shows up as a 500) is split in half and retried, down to a single
    campaign. A single campaign that still cannot be aggregated is skipped and
    shouted to the log — one unreadable campaign must not cost the client its
    whole month history."""
    by_month = {}
    nums = [int(c) for c in ids if str(c).isdigit()]

    def pull(chunk: list) -> bool:
        rows = _retry(lambda c=chunk: server.sb("POST", "rpc/campaign_contact_months",
                                                {"p_ids": c}, prefer="return=representation"),
                      f"campaign_contact_months x{len(chunk)}")
        if rows is None:
            return False
        for r in rows:
            m = str(r.get("month") or "")[:10]
            if m:
                by_month.setdefault(m, set()).add(str(r.get("smartlead_campaign_id")))
        return True

    stack = [nums[i:i + _RPC_CHUNK] for i in range(0, len(nums), _RPC_CHUNK)]
    while stack:
        chunk = stack.pop()
        if not chunk:
            continue
        if pull(chunk):
            continue
        if len(chunk) == 1:
            print(f"  ! contact months unavailable for campaign {chunk[0]} — skipped",
                  flush=True)
            continue
        half = len(chunk) // 2
        stack.append(chunk[:half])
        stack.append(chunk[half:])
    return by_month


def _positives_by_month(id_set: set, start_iso: str) -> tuple:
    """({month: positives}, {month: meetings}) for the client's campaigns from
    `start_iso` onward, under the analytics hub's category mapping + Call
    Booked dedupe. One paged replies read covers every month."""
    import urllib.parse
    pos_cats = urllib.parse.quote(",".join(server._AH_POSITIVE_CATS))
    rows = _retry(lambda: server.sb_get_all(
        "replies?select=smartlead_campaign_id,email,category,replied_at,src:raw->>source"
        f"&category=in.({pos_cats})&replied_at=gte.{start_iso}&order=id"), "replies sweep")
    if rows is None:
        return {}, {}
    pos_seen, cal_events, cal_emails, legacy = set(), set(), set(), set()
    pos_by = {}
    for r in rows:
        cid = str(r.get("smartlead_campaign_id"))
        if cid not in id_set:
            continue
        when = str(r.get("replied_at") or "")
        if len(when) < 7:
            continue
        month = when[:7] + "-01"
        em = (r.get("email") or "").strip().lower()
        k = (month, cid, em)
        if k not in pos_seen:
            pos_seen.add(k)
            pos_by[month] = pos_by.get(month, 0) + 1
        if r.get("category") == "Call Booked":
            if r.get("src") == "calendly":
                cal_emails.add(em)
                cal_events.add((month, cid, em, when[:10]))
            else:
                legacy.add((month, cid, em))
    mtg_by = {}
    for (month, _cid, _em, _day) in cal_events:
        mtg_by[month] = mtg_by.get(month, 0) + 1
    for (month, _cid, em) in legacy:
        if em in cal_emails:
            continue
        mtg_by[month] = mtg_by.get(month, 0) + 1
    return pos_by, mtg_by


def _month_volume(ws: str, ids: list, m: date) -> dict:
    """{sent,replied,bounced} for ONE calendar month, via the same scoped
    day-wise call _report_range_stats makes. The endpoint reports day+month
    with no year, so the window is kept inside a single month — that keeps the
    (day, month) key _daywise_series builds unambiguous. (A multi-month window
    here would ALIAS: 2025-01 and 2026-01 land on the same key.)

    Scoped by the client's campaign ids on its workspace key for EVERY client,
    not just the shared-workspace ones. A workspace-wide call sweeps in
    campaigns that are not on the client's scorecard, so the client's line
    stopped matching the Analytics hub's lifetime Sent (which is the sum over
    exactly these ids). Proven 2026-07-29: the campaign_ids filter is real."""
    s, e = m.isoformat(), _month_end(m).isoformat()
    days = []
    d = m
    end = _month_end(m)
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    key = server.ws_key(ws)
    if not key:
        return {"sent": 0, "replied": 0, "bounced": 0}
    ser = _retry(lambda: server._daywise_series(
        key, days, s, e, campaign_ids=ids), f"daywise {ws} {s}")
    time.sleep(_CALL_PAUSE_S)
    if not ser:
        return {"sent": 0, "replied": 0, "bounced": 0}
    return {k: sum(v or 0 for v in (ser.get(k) or [])) for k in ("sent", "replied", "bounced")}


_BACKWALK_EMPTY_STOP = 4  # consecutive silent months that end the back-walk


def _first_active_month(ws: str, ids: list, seed: date) -> date:
    """The client's TRUE first campaign month.

    `contact_history.first_contacted_at` only knows about leads THIS system
    uploaded, so for an own-workspace client whose campaigns predate us it
    reports far too late a start (measured 2026-09-16: Asteri's history began
    2025-06 but contact_history said 2026-04, costing the client 9 months and
    57% of its sent). So take the contact-history month as a SEED and walk
    backwards a month at a time while Smartlead still shows volume, stopping
    after `_BACKWALK_EMPTY_STOP` silent months in a row (a campaign can pause
    for a month mid-flight) or at the `_MAX_MONTHS` ceiling.

    Returns the seed unchanged when nothing earlier ever sent."""
    first, empty, m = seed, 0, seed
    for _ in range(_MAX_MONTHS):
        m = _month_start(m - timedelta(days=1))
        if _month_volume(ws, ids, m)["sent"] > 0:
            first, empty = m, 0
        else:
            empty += 1
            if empty >= _BACKWALK_EMPTY_STOP:
                break
    return first


def write_client_monthly_stats(client=None) -> dict:
    """Compute and upsert client_monthly_stats for `client` (or every client).

    Every month from the client's FIRST campaign month (earliest
    contact_history.first_contacted_at across its campaigns) to the current
    month is written, so the dashboard's history starts exactly where the
    client's outbound did. Idempotent."""
    t0 = time.time()
    fleet = _client_campaigns()
    if client:
        fleet = {k: v for k, v in fleet.items() if k == client}
        if not fleet:
            print(f"[monthly-stats] no campaigns for client {client!r}", flush=True)
            return {"ok": False, "clients": 0, "rows": 0, "error": "unknown client"}
    today = date.today()
    written, per_client = 0, {}
    for label, ent in sorted(fleet.items()):
        ids, ws = ent["ids"], ent["ws"]
        cmonths = _contact_months(ids)
        if not cmonths:
            print(f"[monthly-stats] {label}: no contact history — skipped", flush=True)
            continue
        seed = date.fromisoformat(min(cmonths))
        first = _first_active_month(ws, ids, seed)
        if first != seed:
            print(f"[monthly-stats] {label}: history starts {first.isoformat()}, "
                  f"not {seed.isoformat()} (contact_history predates this system)",
                  flush=True)
        months = _months_between(first, today)
        pos_by, mtg_by = _positives_by_month(set(ids), first.isoformat())
        rows = []
        for m in months:
            key = m.isoformat()
            vol = _month_volume(ws, ids, m)
            rows.append({
                "client": label, "month": key,
                "sent": vol["sent"], "replied": vol["replied"], "bounced": vol["bounced"],
                "positive": int(pos_by.get(key, 0)), "meetings": int(mtg_by.get(key, 0)),
                "campaigns_active": len(cmonths.get(key) or ()),
                "updated_at": server._dtmod.datetime.now(
                    server._dtmod.timezone.utc).isoformat(timespec="seconds"),
            })
        ok = _retry(lambda r=rows: server.sb(
            "POST", "client_monthly_stats?on_conflict=client,month", r,
            prefer="resolution=merge-duplicates,return=minimal"), f"upsert {label}")
        if ok is None:
            print(f"[monthly-stats] {label}: upsert FAILED ({len(rows)} rows)", flush=True)
            continue
        written += len(rows)
        per_client[label] = {"months": len(rows), "first": months[0].isoformat(),
                             "sent": sum(r["sent"] for r in rows)}
        print(f"[monthly-stats] {label}: {len(rows)} months from {months[0].isoformat()} "
              f"(sent {per_client[label]['sent']:,})", flush=True)
    out = {"ok": True, "clients": len(per_client), "rows": written,
           "secs": int(time.time() - t0), "per_client": per_client}
    print(f"[monthly-stats] wrote {written} rows for {len(per_client)} clients "
          f"in {out['secs']}s", flush=True)
    return out


if __name__ == "__main__":
    write_client_monthly_stats(sys.argv[1] if len(sys.argv) > 1 else None)
