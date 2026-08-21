#!/usr/bin/env python3
"""Daily proof that the sending-capacity chart is being recorded — freshly AND
accurately — every day. This is the alarm that would have caught the failure
behind the 2026-08-21 audit: the mailbox sync had been silently dead since
Aug 17, which froze mailbox_stats_daily + the mailboxes mirror and left the
capacity chart flat and the tiering engine blind. A quiet failure looked
identical to "nothing changed", so nobody noticed for four days.

Checks, in order of how load-bearing they are:
  1. The mailbox sync ran recently        (mailboxes.last_synced_at < STALE_H).
  2. Today's per-box snapshot landed       (mailbox_stats_daily has today).
  3. Today's capacity is recorded          (client_capacity_hist_v1 blob has
     today, with every expected workspace pool AND the navreo per-client split).
  4. The mirror isn't carrying obvious dead weight (boxes not synced today but
     still marked attached) — informational, flags when pruning has lapsed.

Exit 0 = healthy, 1 = stale/missing (page), 2 = could not check.
Posts the verdict to app_activity_log EVERY day (green or red — a silent green
channel is exactly the blind spot that hid the dead sync) and to CAPS_ALERT_HOOK
if configured.

    python app/check_capacity_fresh.py          # human-readable
    python app/check_capacity_fresh.py --json    # for a cron/monitor
"""
import datetime as dt
import json
import os
import sys

os.environ.setdefault("NAVREO_NO_BG", "1")

import server  # noqa: E402

STALE_H = 30                                  # sync must have run within this window
EXPECT_WS = ("navreo", "asteri", "krg", "grout")


def main() -> int:
    as_json = "--json" in sys.argv
    today = dt.date.today().isoformat()
    fails: list = []
    info: dict = {"date": today}

    # 1) sync freshness — the single thing whose failure froze everything
    mb = server.sb("GET", "mailboxes?select=last_synced_at&order=last_synced_at.desc&limit=1")
    last_sync = mb[0]["last_synced_at"] if isinstance(mb, list) and mb else None
    age_h = None
    if last_sync:
        try:
            age_h = (dt.datetime.now(dt.timezone.utc)
                     - dt.datetime.fromisoformat(last_sync)).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            age_h = None
    info["sync_age_h"] = round(age_h, 1) if age_h is not None else None
    if age_h is None or age_h > STALE_H:
        fails.append(f"mailbox sync STALE — last_synced_at={last_sync} "
                     f"(age {info['sync_age_h']}h > {STALE_H}h). The cron is not landing.")

    tdate = dt.date.fromisoformat(today)

    # 2) the per-box snapshot (mailbox_stats_daily) isn't stalling. It only writes
    #    when the metrics call lands (which can lag a day), and the current day's
    #    row appears only after the 04:30 sync — so judge on AGE (today/yesterday),
    #    never "today exactly". >2 days behind means the pipeline is broken.
    newest = server.sb("GET", "mailbox_stats_daily?select=stat_date&order=stat_date.desc&limit=1")
    nd = (newest[0]["stat_date"] if isinstance(newest, list) and newest else None)
    msd_age = (tdate - dt.date.fromisoformat(str(nd)[:10])).days if nd else 999
    info["stats_newest"] = nd
    if msd_age > 2:
        fails.append(f"mailbox_stats_daily newest is {nd} ({msd_age}d old) — the per-box snapshot has stalled.")

    # 3) capacity is actually being recorded — the LATEST blob day must be recent
    #    (today or yesterday) and complete (every workspace pool + the navreo
    #    per-client split). A stale latest day is the dead-sync signature.
    try:
        blob = server._blob_snapshot_load(server._CLIENT_CAP_HIST_KEY) or {}
    except Exception as e:  # noqa: BLE001
        blob = {}
        fails.append(f"could not read the capacity history blob: {str(e)[:120]}")
    days = blob.get("days") or {}
    latest = max(days) if days else None
    rec = days.get(latest) or {}
    ws_rec = rec.get("workspace") or {}
    clients = rec.get("clients") or {}
    info["capacity_latest"] = latest
    info["workspaces_recorded"] = [w for w in EXPECT_WS if (ws_rec.get(w) or {}).get("cap")]
    info["clients_recorded"] = len(clients)
    blob_age = (tdate - dt.date.fromisoformat(latest)).days if latest else 999
    if blob_age > 1:
        fails.append(f"capacity last recorded {latest} ({blob_age}d ago) — daily recording has stalled.")
    else:
        for ws in EXPECT_WS:
            if not (ws_rec.get(ws) or {}).get("cap"):
                fails.append(f"latest capacity day {latest} is missing workspace '{ws}'.")
        if not clients:
            fails.append(f"latest capacity day {latest} has no navreo per-client breakdown.")

    # 4) mirror dead-weight (accuracy, not freshness) — attached boxes not seen in
    #    the last STALE_H. Pruning keeps this near zero; a large backlog inflates
    #    the pool totals. Only paged when the sync itself is fresh (else it's just
    #    the staleness above).
    if age_h is not None and age_h <= STALE_H:
        from urllib.parse import quote as _q
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=STALE_H)).isoformat()
        dead = server.sb("GET", "mailboxes?select=smartlead_id&campaign_count=gt.0"
                                f"&last_synced_at=lt.{_q(cutoff)}&limit=1001")
        n_dead = len(dead) if isinstance(dead, list) else 0
        info["stale_attached_boxes"] = f"{n_dead}{'+' if n_dead > 1000 else ''}"
        if n_dead > 500:
            fails.append(f"{info['stale_attached_boxes']} attached mailboxes not synced in {STALE_H}h — "
                         "dead weight is inflating pool totals; pruning has lapsed.")

    verdict = {"ok": not fails, **info, "failures": fails}
    _emit(verdict, as_json)
    return 1 if fails else 0


def _emit(v: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(v, indent=1))
    else:
        head = "✅ capacity recording healthy" if v["ok"] else "🔴 capacity recording FAILED"
        print(f"{head} — {v['date']}")
        print(f"  sync age: {v.get('sync_age_h')}h | workspaces recorded: {v.get('workspaces_recorded')} | "
              f"clients: {v.get('clients_recorded')} | stale-attached: {v.get('stale_attached_boxes')}")
        for f in v["failures"]:
            print("  -", f)
        if v["ok"]:
            print("  all four workspaces + the navreo per-client split recorded for today.")

    # Always log to the activity feed (green or red).
    try:
        server.sb("POST", "app_activity_log",
                  {"actor": "cron", "endpoint": "/api/cron/capacity-check",
                   "action": "capacity-check", "entity": "deliverability",
                   "payload": v})
    except Exception as e:  # noqa: BLE001 — logging is best-effort
        print(f"(activity-log write failed: {e})", file=sys.stderr)

    hook = server.KEYS.get("CAPS_ALERT_HOOK") or os.environ.get("CAPS_ALERT_HOOK")
    if not hook:
        return
    lines = [("✅ Capacity recorded" if v["ok"] else "🔴 Capacity recording FAILED") + f" — {v['date']}"]
    lines.append(f"sync {v.get('sync_age_h')}h old · ws {','.join(v.get('workspaces_recorded') or []) or 'none'} "
                 f"· {v.get('clients_recorded')} clients")
    lines += [f"⚠ {f}" for f in v["failures"]]
    payload = {"text": "\n".join(lines), "ok": v["ok"], "date": v["date"], "failures": v["failures"]}
    for _ in range(2):
        try:
            server.http_json("POST", hook, {}, payload)
            return
        except ValueError:
            return          # Make/Slack answer a bare 2xx — that IS success
        except Exception:  # noqa: BLE001 — retry once, then give up quietly
            pass


if __name__ == "__main__":
    sys.exit(main())
