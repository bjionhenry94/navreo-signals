#!/usr/bin/env python3
"""Learning-loop decision ledger helper.

Any skill that mutates a campaign, sequence, list or setting should append one
row here BEFORE (or immediately after) the mutation. One function, zero deps
beyond requests + the service key already in ~/.navreo-keys.env.

Usage:
    from learning_ledger import log_decision
    log_decision(
        actor="skill:lilly-optimiser",
        platform="smartlead",            # smartlead | heyreach | signals-app
        campaign_id="1868379",
        change_type="copy-edit",          # copy-edit | variant-added | schedule-change |
                                          # leads-added | pause | resume | cap-change | other
        rationale="proposal 42: add variant D alongside incumbent",
        proposal_id=42,                   # optional: links the change to its proposal
        diff={"before": "...", "after": "..."},
    )

The idem_key is deterministic (same change logged twice = one row), so calling
this in a retried skill run is safe.
"""
import hashlib
import json
import os
import urllib.request
from datetime import date

SUPABASE_URL = "https://fnykldftbkrccihdjayl.supabase.co"


def _service_key() -> str:
    env_path = os.path.expanduser("~/.navreo-keys.env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("SUPABASE_SERVICE_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("SUPABASE_SERVICE_KEY not found in ~/.navreo-keys.env")


def log_decision(actor: str, platform: str, campaign_id: str, change_type: str,
                 rationale: str = "", proposal_id: int | None = None,
                 diff: dict | None = None) -> None:
    idem = hashlib.md5(
        f"{platform}|{campaign_id}|{change_type}|{json.dumps(diff or {}, sort_keys=True)}|{date.today()}".encode()
    ).hexdigest()
    row = {
        "idem_key": idem, "actor": actor, "platform": platform,
        "campaign_id": str(campaign_id), "change_type": change_type,
        "rationale": rationale[:2000], "proposal_id": proposal_id,
        "diff": diff, "source": actor,
    }
    key = _service_key()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/decision_ledger",
        data=json.dumps(row).encode(),
        headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()
