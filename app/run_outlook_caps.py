#!/usr/bin/env python3
"""Daily Outlook/Azure reply-rate cap tiering.

The twin of run_google_caps.py, and its separateness is the point: Outlook
boxes top out around 4/day where Google boxes run 20-30, so one engine could
never serve both. Same code path (provider_reply_caps), different profile.

This replaces the standalone audit service's Outlook engine
(navreo-email-deliverability-audit, POST /api/reply-caps), which ignored the
Outlook/Azure filter its own UI advertised and set 132 Navreo GOOGLE boxes to
4/day and 2/day on 2026-07-26 — cutting fleet capacity by roughly 2,000
sends/day. Scoping the query to account_type=OUTLOOK makes that class of
collision impossible, and excludes the 600 Maildoso boxes (SMTP) for free.

Runs AFTER sync_mailboxes.py — it scores off mailbox_stats_daily's trailing-30d
columns, so firing it before the day's snapshot lands would re-tier the whole
fleet on yesterday's numbers.

    python app/run_outlook_caps.py            # apply
    python app/run_outlook_caps.py --preview  # plan only, writes nothing
"""
import json
import sys

import server


def main() -> int:
    mode = "preview" if "--preview" in sys.argv else "apply"
    r = server.outlook_reply_caps(mode)
    if not r.get("ok"):
        print("FAILED:", r.get("error"), file=sys.stderr)
        return 1
    print(f"[outlook-caps] mode={mode} domains={r['domains']} "
          f"skipped={len(r.get('skipped') or [])} "
          f"boxesToChange={r['mailboxesToChange']} tiers={json.dumps(r.get('tierCount'))}")
    if mode == "apply":
        print(f"[outlook-caps] changed={r.get('changed', 0)} "
              f"failed={len(r.get('failed') or [])}")
        for f in (r.get("failed") or [])[:20]:
            print("  FAIL", f["email"], f["error"], file=sys.stderr)
        server.log_activity("/api/cron/outlook-reply-caps",
                            payload={"changed": r.get("changed", 0),
                                     "failed": r.get("failed"),
                                     "domains": r.get("domains"),
                                     "tierCount": r.get("tierCount")},
                            actor="cron", action="reply-caps", entity="deliverability")
    return 0


if __name__ == "__main__":
    sys.exit(main())
