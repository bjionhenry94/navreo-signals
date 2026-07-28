#!/usr/bin/env python3
"""Daily proof that the cap engines are actually MOVING caps.

The failure this exists to catch is silent: the standalone Outlook service
returned {"changed": 0, "skipped": true, "reason": "Run a domain-health pull
first..."} every morning from 2026-07-26 to 07-28 and nobody noticed for three
days, because a quiet run and a broken run look identical from the outside.

So this checks two different things, and the second is the one that matters:

  1. Did each engine RUN today?            (an entry in app_activity_log)
  2. Did caps actually CHANGE recently?    (mailbox_stats_daily, day over day)

A quiet day is legitimate — caps only move when reply rates move. What is NOT
legitimate is silence for days on end, so the alarm is a STALENESS window, not
a same-day check: no cap movement in STALE_DAYS days is a FAIL even if every
run "succeeded".

Reports per provider AND per workspace, so a client whose caps have frozen is
visible rather than averaged away inside the Navreo fleet.

    python app/check_caps_moving.py           # human-readable
    python app/check_caps_moving.py --json    # for a cron/monitor

Exit 0 = healthy, 1 = something has stalled, 2 = could not check.
"""
import collections
import datetime as dt
import json
import os
import sys

os.environ.setdefault("NAVREO_NO_BG", "1")

import server  # noqa: E402

STALE_DAYS = 4        # no cap movement in this many days → FAIL
RUN_STALE_HOURS = 30  # no engine run logged in this long → FAIL
LOOKBACK = 10         # days of history to scan


def pull(path, attempts=3):
    out, off = [], 0
    while True:
        page = None
        for i in range(attempts):
            page = server.sb("GET", path, headers={"Range-Unit": "items",
                                                   "Range": f"{off}-{off + 999}"})
            if isinstance(page, list):
                break
        if not isinstance(page, list):
            return None
        out += page
        if len(page) < 1000:
            return out
        off += 1000


def main() -> int:
    as_json = "--json" in sys.argv
    today = dt.date.today()
    since = (today - dt.timedelta(days=LOOKBACK)).isoformat()

    # Cap per box per day. A change between consecutive stat_dates is the
    # engine actually doing its job — this is observed state, not a claim
    # made by the engine about itself.
    rows = pull(f"mailbox_stats_daily?select=smartlead_id,stat_date,message_per_day,"
                f"workspace&stat_date=gte.{since}")
    if rows is None:
        print("FATAL: could not read mailbox_stats_daily", file=sys.stderr)
        return 2
    boxes = pull("mailboxes?select=smartlead_id,account_type,workspace")
    if boxes is None:
        print("FATAL: could not read mailboxes", file=sys.stderr)
        return 2
    provider = {b["smartlead_id"]: ("GOOGLE" if b.get("account_type") == "GMAIL"
                                    else "OUTLOOK" if b.get("account_type") == "OUTLOOK"
                                    else "OTHER") for b in boxes}

    hist = collections.defaultdict(dict)     # sid → {date: cap}
    for r in rows:
        hist[r["smartlead_id"]][r["stat_date"]] = r.get("message_per_day")

    # Same-day movement. mailbox_stats_daily only snapshots once a night, so an
    # apply that runs after the sweep is invisible in the day-over-day history
    # until tomorrow — which reads as "this workspace has never moved" and
    # fires a false alarm on the very day the engine worked. The `mailboxes`
    # mirror IS written immediately by the apply, so a mirror cap that differs
    # from the newest snapshot means caps moved since the sweep. Treated as
    # movement dated today.
    live = {b["smartlead_id"]: b.get("message_per_day")
            for b in pull("mailboxes?select=smartlead_id,message_per_day") or []}

    # last date on which ANY box in the group changed cap
    moved = collections.defaultdict(lambda: None)   # (prov, ws) → date
    counts = collections.Counter()                  # (prov, ws, date) → n
    for b in boxes:
        sid = b["smartlead_id"]
        prov, ws = provider.get(sid, "OTHER"), (b.get("workspace") or "navreo")
        days = sorted(hist.get(sid, {}))
        for a, c in zip(days, days[1:]):
            if hist[sid][a] != hist[sid][c] and hist[sid][c] is not None:
                counts[(prov, ws, c)] += 1
                if moved[(prov, ws)] is None or c > moved[(prov, ws)]:
                    moved[(prov, ws)] = c
        # mirror vs newest snapshot → moved since the nightly sweep
        if days and live.get(sid) is not None and live[sid] != hist[sid][days[-1]]:
            t = today.isoformat()
            counts[(prov, ws, t)] += 1
            if moved[(prov, ws)] is None or t > moved[(prov, ws)]:
                moved[(prov, ws)] = t

    # engine runs
    runs = server.sb("GET", "app_activity_log?select=ts,endpoint,payload&action=eq.reply-caps"
                            "&order=ts.desc&limit=40") or []
    last_run = {}
    for r in runs:
        ep = (r.get("endpoint") or "")
        key = ("GOOGLE" if "google" in ep else "OUTLOOK" if "outlook" in ep else "LEGACY")
        last_run.setdefault(key, r)

    excluded = getattr(server, "CAP_EXCLUDED_WORKSPACES", set())
    groups = sorted({(provider.get(b["smartlead_id"], "OTHER"), b.get("workspace") or "navreo")
                     for b in boxes if provider.get(b["smartlead_id"]) in ("GOOGLE", "OUTLOOK")})

    report, failures = [], []
    for prov, ws in groups:
        last = moved[(prov, ws)]
        age = (today - dt.date.fromisoformat(last)).days if last else None
        skip = ws in excluded
        ok = skip or (age is not None and age <= STALE_DAYS)
        entry = {"provider": prov, "workspace": ws, "last_cap_move": last,
                 "days_since": age, "excluded": skip, "ok": ok,
                 "boxes_moved_on_last_move": counts.get((prov, ws, last), 0) if last else 0}
        report.append(entry)
        if not ok:
            failures.append(f"{prov}/{ws}: no cap movement in "
                            f"{'ever' if age is None else str(age) + ' days'}")

    # The run log is a WARNING channel, never a failure. log_activity writes
    # through best-effort sb() — the 3,457-box apply on 2026-07-28 succeeded
    # and its log row never landed. Treating a missing row as failure would
    # cry wolf on a working engine, and an alert people learn to ignore is
    # worse than no alert. Observed cap movement above is the authority.
    warnings = []
    for key in ("GOOGLE", "OUTLOOK"):
        r = last_run.get(key)
        if not r:
            warnings.append(f"{key}: no run logged (log is best-effort — "
                            f"trust the movement rows above)")
            continue
        try:
            hrs = (dt.datetime.now(dt.timezone.utc)
                   - dt.datetime.fromisoformat(r["ts"])).total_seconds() / 3600
        except Exception:
            hrs = None
        pay = r.get("payload") or {}
        if hrs is not None and hrs > RUN_STALE_HOURS:
            warnings.append(f"{key}: last logged run was {hrs:.0f}h ago")
        # A run that reports itself SKIPPED is the 2026-07-26 failure mode
        # verbatim, and that IS actionable — the engine spoke, and said no.
        if pay.get("skipped"):
            failures.append(f"{key}: last run SKIPPED — {str(pay.get('reason'))[:80]}")

    if as_json:
        print(json.dumps({"ok": not failures, "groups": report,
                          "failures": failures, "warnings": warnings}, indent=1))
        return 1 if failures else 0

    print(f"Cap movement check — {today}\n")
    for e in report:
        tag = "EXCLUDED" if e["excluded"] else ("OK  " if e["ok"] else "STALE")
        print(f"  [{tag:8}] {e['provider']:7} {e['workspace']:7} "
              f"last move {e['last_cap_move'] or 'never':10} "
              f"({e['boxes_moved_on_last_move']} boxes)")
    print()
    for key in ("GOOGLE", "OUTLOOK"):
        r = last_run.get(key)
        print(f"  last {key:7} run: {(r or {}).get('ts', 'never')[:19]} "
              f"{json.dumps((r or {}).get('payload') or {})[:90]}")
    if warnings:
        print("\nWARNINGS (not failures)")
        for w in warnings:
            print("  -", w)
    if failures:
        print("\nFAILURES")
        for f in failures:
            print("  -", f)
        return 1
    print("\nAll engines running and caps moving.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
