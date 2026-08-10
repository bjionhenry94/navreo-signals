#!/usr/bin/env python3
"""Deterministic "Add a subsequence" optimisation.

Goal (Bjion, 2026-08-10): NO campaign is live without a subsequence set up.
A subsequence is the automatic follow-up flow a positive reply is moved into
(the "Interested Reply" / "Meeting Request" campaigns). In Smartlead a
subsequence is its OWN campaign carrying a `parent_campaign_id` that points at
the outbound parent (the tool already treats parent_campaign_id as THE
subsequence signal - see server.py's subsequence-stats collator). So:

  a campaign HAS a subsequence  <=>  some campaign's parent_campaign_id == its id

This script audits every ACTIVE, top-level (parent_campaign_id is null) outbound
campaign and, for each one with NO subsequence child, puts a single "Add a
subsequence" card onto that campaign in `campaign_insights` - the exact table
the live campaigns page (app/campaigns.html -> /api/cockpit/insights) renders as
each campaign's "Review N" optimisations. When a campaign later gains a
subsequence (or stops being active), its card self-clears on the next run.

Why campaign_insights and not optimiser_notifications:
  - campaigns.html (the surface the team works from) reads campaign_insights.
  - Its rows are keyed by (scope, insight_key); the morning crunch
    (/lilly-optimiser) supersedes only its OWN keys, so a distinct
    insight_key='subsequence-missing' survives every crunch untouched. Writing
    into optimiser_notifications instead would be reaped daily by
    build_notifications.py's retirement pass (it resolves any status=new row it
    does not itself emit).
  - No schema migration is needed: campaign_insights already has these columns.

Read-only against Smartlead (GET only). Writes ONLY the 'subsequence-missing'
rows in `campaign_insights` - never any other insight_key, never any other
table. Idempotent: safe to run every tick.

Scope: the Navreo Smartlead account (SMARTLEAD_API_KEY) - where the audit and
every current finding live. Client accounts (asteri/krg/grout) keep their own
keys and may follow a different subsequence convention, so they are a
deliberate follow-up, not silently swept here.

Usage:
  python app/subsequence_optimisations.py            # audit + upsert/clear
  python app/subsequence_optimisations.py --dry-run  # audit + print, no writes
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-subsequence-audit/1.0"
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
RATE_SLEEP = 0.35  # under Smartlead's 200/min cap (matches build_notifications.py)

INSIGHT_KEY = "subsequence-missing"
GENERATED_BY = "subsequence-audit (deterministic)"
EXPIRES_DAYS = 3           # short box + daily re-assert: a stale card self-expires
                           # within 3 days if this cron ever stops running
SMARTLEAD_URL_TPL = "https://app.smartlead.ai/app/email-campaign/{cid}/analytics"

# A Smartlead subsequence campaign is created named exactly like these. Every
# such campaign in the Navreo account carries a parent_campaign_id (verified
# 2026-08-10: 554/554 named subsequence campaigns had a parent set), so
# parent_campaign_id is the primary filter; the name check is a belt-and-braces
# guard against a rare orphaned subsequence being mistaken for an outbound.
SUBSEQ_NAMES = ("Interested Reply", "Meeting Request")


def load_keys() -> dict:
    """Env-first with a local-file fallback - same shape as build_notifications.py."""
    keys: dict = {}
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


def http_json(method: str, url: str, headers: dict, body=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else []
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        print(f"  ! HTTP {e.code} on {method} {url.split('?')[0]}: {raw[:200]}")
        return {"_status": e.code, "_error": True}


def sb(method: str, path: str, body=None, prefer: str = ""):
    """Supabase PostgREST call - scoped to campaign_insights only here."""
    url, key = KEYS.get("SUPABASE_URL"), KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        return None
    try:
        return http_json(method, f"{url}/rest/v1/{path}",
                         {"apikey": key, "Authorization": f"Bearer {key}",
                          "Prefer": prefer or "return=minimal"}, body)
    except Exception as e:  # noqa: BLE001
        print(f"  ! sb {method} {path} failed: {e}")
        return None


def sl_get(api_key: str, endpoint: str, params: dict | None = None):
    """Smartlead GET-only helper, rate-limited with retries (429-aware)."""
    params = dict(params or {})
    params["api_key"] = api_key
    url = f"{SMARTLEAD_BASE}{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in (1, 2, 3):
        try:
            time.sleep(RATE_SLEEP)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                print(f"  ! GET {endpoint} failed: {e}")
                return None
            is_429 = isinstance(e, urllib.error.HTTPError) and e.code == 429
            time.sleep(25 if is_429 else 3)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_subseq_name(name: str) -> bool:
    n = (name or "").strip()
    return any(n == s or n.startswith(s + " ") or n.startswith(s + "(") for s in SUBSEQ_NAMES)


def fetch_all_campaigns(api_key: str) -> list[dict]:
    """Full /campaigns list for one account (every status), paginated."""
    out: list[dict] = []
    offset = 0
    while True:
        page = sl_get(api_key, "/campaigns", {"limit": 100, "offset": offset})
        if isinstance(page, dict):
            page = page.get("data") or page.get("campaigns") or page.get("result") or []
        if not isinstance(page, list):
            break
        out.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return out


def audit_missing(campaigns: list[dict]) -> list[dict]:
    """ACTIVE, top-level outbound campaigns with no subsequence child.

    A campaign has a subsequence iff some campaign in the SAME account points its
    parent_campaign_id at it. Children live in the same Smartlead account as
    their parent, so one full-account list is a complete, authoritative check.
    """
    with_subseq = {str(c["parent_campaign_id"]) for c in campaigns
                   if c.get("parent_campaign_id") is not None}
    missing = []
    for c in campaigns:
        if c.get("status") != "ACTIVE":
            continue
        if c.get("parent_campaign_id") is not None:
            continue  # this IS a subsequence (a child), never an outbound parent
        name = c.get("name") or ""
        if _is_subseq_name(name):
            continue  # defensive: an orphaned subsequence is not an outbound campaign
        if str(c["id"]) not in with_subseq:
            missing.append(c)
    return missing


def infer_client(name: str) -> str:
    n = (name or "").lower()
    for label in ("Amplifyy", "Arnic", "ThunderBird", "Qwintiq"):
        if label.lower() in n:
            return label
    return "Navreo"


def build_payload(c: dict, client: str) -> dict:
    cid = str(c["id"])
    name = c.get("name") or f"Campaign {cid}"
    return {
        "kind": INSIGHT_KEY,
        "tag": "decide",                     # High / red badge on the action card
        "owner": "Lilly",
        "client": client,
        "act": "Add a subsequence",
        "bold": ("This campaign is live with no subsequence, so anyone who replies "
                 "interested or asks for a meeting is not being moved into a follow-up flow."),
        "note": ("A subsequence is the automatic follow-up that runs after a positive reply "
                 "- the Interested Reply and Meeting Request steps. Without one, a warm reply "
                 "just sits in the inbox instead of being pushed toward a booked call. Every "
                 "live campaign should have one. Set it up on this campaign in Smartlead."),
        "stats": {},
        "campaign_name": name,
        "smartlead_url": SMARTLEAD_URL_TPL.format(cid=cid),
        "workspace": "navreo",
        "workspace_label": "Navreo",
    }


def existing_live_cards() -> dict[str, str]:
    """{scope: id} for every live 'subsequence-missing' card currently on the book."""
    rows = sb("GET", f"campaign_insights?insight_key=eq.{INSIGHT_KEY}&status=eq.live"
                     "&select=id,scope") or []
    return {str(r["scope"]): r["id"] for r in rows if isinstance(r, dict)}


def refresh(workspaces=("navreo",), dry_run: bool = False) -> dict:
    """Audit + upsert the 'Add a subsequence' cards, and self-clear resolved ones.

    Returns a summary dict {missing, added, refreshed, cleared, campaigns}."""
    api_key = KEYS.get("SMARTLEAD_API_KEY", "")
    if not api_key:
        print("  ! SMARTLEAD_API_KEY missing - cannot audit")
        return {"error": "no_smartlead_key"}

    all_missing: list[dict] = []
    for ws in workspaces:
        # navreo uses the env key; client keys would come from the workspaces
        # table (deliberately out of scope for now - see the module docstring).
        if ws != "navreo":
            continue
        camps = fetch_all_campaigns(api_key)
        miss = audit_missing(camps)
        print(f"[{ws}] {len(camps)} campaigns, "
              f"{sum(1 for c in camps if c.get('status') == 'ACTIVE' and c.get('parent_campaign_id') is None and not _is_subseq_name(c.get('name') or ''))} "
              f"active outbound, {len(miss)} missing a subsequence")
        all_missing.extend(miss)

    missing_ids = {str(c["id"]) for c in all_missing}
    existing = existing_live_cards()
    now = _now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(days=EXPIRES_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    added = refreshed = cleared = 0
    detail = []
    for c in all_missing:
        cid = str(c["id"])
        client = infer_client(c.get("name") or "")
        payload = build_payload(c, client)
        fp = hashlib.md5(f"{cid}:{INSIGHT_KEY}".encode()).hexdigest()
        detail.append({"campaign_id": cid, "name": c.get("name"), "client": client})
        if dry_run:
            continue
        if cid in existing:
            # keep created_at (card age honest); refresh payload + push expiry out
            sb("PATCH", f"campaign_insights?id=eq.{existing[cid]}",
               {"payload": payload, "expires_at": expires, "data_fingerprint": fp})
            refreshed += 1
        else:
            sb("POST", "campaign_insights",
               {"scope": cid, "insight_key": INSIGHT_KEY, "payload": payload,
                "data_fingerprint": fp, "generated_by": GENERATED_BY,
                "status": "live", "expires_at": expires})
            added += 1

    # Self-clear: a live card whose campaign is no longer missing (gained a
    # subsequence, or stopped being active) is expired so it drops off the page.
    for scope, rid in existing.items():
        if scope not in missing_ids:
            if not dry_run:
                sb("PATCH", f"campaign_insights?id=eq.{rid}",
                   {"status": "expired", "superseded_at": now})
            cleared += 1

    print(f"  cards: +{added} new, {refreshed} refreshed, {cleared} cleared"
          + (" (dry-run: no writes)" if dry_run else ""))
    return {"missing": len(all_missing), "added": added, "refreshed": refreshed,
            "cleared": cleared, "campaigns": detail}


def main() -> int:
    dry = "--dry-run" in sys.argv
    summary = refresh(dry_run=dry)
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
