#!/usr/bin/env python3
"""Isolated cron for the live-confirmed collision census.

server.collision_live_recount() downloads one full Smartlead leads-export per
ACTIVE campaign and holds them in memory to find same-client collisions — far
too heavy for the shared 512MB web instance, where it OOM-crash-looped the box
~120s after every boot (see the server_boot_ledger: instances died at ~120s,
exactly _collision_live_loop's sleep(120)). Running it HERE, in its own cron
process with the whole 512MB to itself, keeps the web instance stable.

/api/collisions serves the value this writes to app_activity_log (actor
'collision_live'); it falls back to the daily contact_history census until a
run lands. Idempotent — safe to run any time. Scheduled every 6h in render.yaml
(navreo-collision-census).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


def main():
    r = server.collision_live_recount(persist=True)
    print(f"[collision-census] total={r.get('total')} "
          f"scanned={r.get('campaigns_scanned')}/{r.get('campaigns_total')} "
          f"complete={r.get('complete')} unreachable={r.get('unreachable')} "
          f"per_client={r.get('per_client')}")
    # A run that reached <85% of campaigns did NOT persist (it would publish an
    # undercount over a good value); surface that as a non-zero exit so the cron
    # log flags it, matching the caps crons' "silence != success" convention.
    if not r.get("complete"):
        sys.exit(1)


if __name__ == "__main__":
    main()
