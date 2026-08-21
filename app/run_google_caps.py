#!/usr/bin/env python3
"""Daily Google reply-rate cap tiering (owner ruling 2026-07-28).

Runs AFTER sync_mailboxes.py — it scores off mailbox_stats_daily's trailing-30d
columns, so firing it before the day's snapshot lands would re-tier the whole
Google fleet on yesterday's numbers.

Calls the engine in-process rather than curling /api/cron/google-reply-caps:
same code, but no SIGNAL_PULL_TOKEN round-trip and no pg_net timeout to outrun
(the apply writes one Smartlead call per changed box at 0.35s apiece).

    python app/run_google_caps.py            # apply
    python app/run_google_caps.py --preview  # plan only, writes nothing
"""
import json
import sys

import server


def main() -> int:
    mode = "preview" if "--preview" in sys.argv else "apply"
    r = server.google_reply_caps(mode)
    if not r.get("ok"):
        print("FAILED:", r.get("error"), file=sys.stderr)
        return 1
    print(f"[google-caps] mode={mode} domains={r['domains']} "
          f"skipped={len(r.get('skipped') or [])} "
          f"boxesToChange={r['mailboxesToChange']} tiers={json.dumps(r.get('tierCount'))}")
    if mode == "apply":
        print(f"[google-caps] changed={r.get('changed', 0)} "
              f"failed={len(r.get('failed') or [])} parked={r.get('parked')}")
        for f in (r.get("failed") or [])[:20]:
            print("  FAIL", f["email"], f["error"], file=sys.stderr)
        server.log_activity("/api/cron/google-reply-caps",
                            payload={"changed": r.get("changed", 0),
                                     "failed": r.get("failed"),
                                     "parked": r.get("parked"),
                                     "domains": r.get("domains"),
                                     "tierCount": r.get("tierCount")},
                            actor="cron", action="reply-caps", entity="deliverability")
        # Record the estimated daily sending capacity per client now that this
        # engine has moved the caps, so the analytics chart shows a real per-day
        # value instead of carrying yesterday's forward (Bjion 2026-08-21).
        try:
            cap = server.snapshot_navreo_capacity()
            print(f"[google-caps] capacity snapshot: {cap}")
        except Exception as e:  # noqa: BLE001 — snapshot is best-effort, never fail the cron
            print(f"[google-caps] capacity snapshot failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
