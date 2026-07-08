#!/usr/bin/env python3
"""The daily signals run — what the launchd schedule fires every morning.

For every ACTIVE source on every signal campaign:
  1. pull (fresh companies only: 90-day scan window + lead dedupe + exclusions
     + verified-email gate, paced by the source's leads-per-day)
  2. campaign autopilot ON  -> auto-push every new lead (email -> Smartlead,
     no email -> HeyReach), zero user intervention
     campaign autopilot OFF -> leads wait in the Leads tab for ✓ review

Each run appends a summary to app/data/daily_log.json (last 60 runs kept).
Manual invocation is safe any time - every layer is idempotent.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

LOG = Path(__file__).parent / "data" / "daily_log.json"


def main():
    campaigns = {str(c.get("id")): c for c in server.read_json_list(server.CAMPAIGN_DRAFTS)
                 if not c.get("deleted_at")}  # soft-deleted campaigns never pull
    source_ids = [d["id"] for d in server.read_drafts()
                  if d.get("active", True) and not d.get("deleted_at")
                  and str(d.get("campaign_id")) in campaigns]
    run = {"ts": datetime.now().isoformat(timespec="seconds"), "sources": []}
    print(f"daily run · {len(source_ids)} active sources")

    for sid in source_ids:
        entry = {"id": sid}
        try:
            with server.drafts_lock():  # same mutex the HTTP writers use
                r = server.pull_source({"id": sid})
            entry["pull"] = r.get("note") or r.get("message") or ""
            entry["ok"] = bool(r.get("ok"))
            drafts = server.read_drafts()  # the pull rewrote the file
            src = next((d for d in drafts if d.get("id") == sid), None)
            camp = campaigns.get(str((src or {}).get("campaign_id"))) or {}
            entry["campaign"] = camp.get("name")
            if src and camp.get("autopilot"):
                with server.drafts_lock():
                    drafts = server.read_drafts()  # re-read under the lock
                    src = next((d for d in drafts if d.get("id") == sid), src)
                    pushed = server.auto_push_new_leads(src)
                    server.write_source(src)  # only this source's push stamps changed
                entry["autopushed"] = [p for p in pushed if p["ok"]]
                entry["push_failed"] = [p for p in pushed if not p["ok"]]
            else:
                entry["autopilot"] = False  # leads wait for manual ✓
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the run
            entry["error"] = str(e)[:200]
        run["sources"].append(entry)
        n_push = len(entry.get("autopushed") or [])
        print(f"  {sid} · {entry.get('pull') or entry.get('error') or ''}"
              + (f" · {n_push} auto-pushed" if n_push else "")
              + (" · manual (awaiting review)" if entry.get("autopilot") is False else ""))

    prior = json.loads(LOG.read_text()).get("runs", []) if LOG.exists() else []
    LOG.write_text(json.dumps({"runs": (prior + [run])[-60:]}, indent=1))
    print("run logged.")


if __name__ == "__main__":
    main()
