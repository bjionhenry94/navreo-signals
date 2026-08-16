#!/usr/bin/env python3
"""Deterministic "Move all sending to variant X" optimisation card.

Goal (Bjion, 2026-08-16, scale-winner parity loop): when the Messaging tab
shows the BEST "Send 100% of Email X to it" button, that recommendation must
be visible ON THE CAMPAIGN VIEW - the campaigns page row ("Review N" badge +
inline panel) and the campaign page's action cards - not only in the
optimisation cockpit.

The truth already lives in `optimiser_notifications`: build_notifications.py's
scale-winner parity section maintains one live `action_type='scale_winner'`
row per campaign whose pill shows (all workspaces), and auto-resolves it when
the verdict changes or the traffic moves. This module mirrors those rows into
`campaign_insights` - the table campaigns.html actually renders - as one card
per campaign, and self-clears the card when its source row stops being live.

Why campaign_insights and not optimiser_notifications (same reasoning as
subsequence_optimisations.py, the module this one is patterned on):
  - campaigns.html reads campaign_insights; optimiser_notifications only feeds
    the Why? receipts and the optimisation cockpit.
  - Rows are keyed by (scope, insight_key); the morning crunch (/lilly-optimiser)
    supersedes only its OWN keys, so insight_key='scale-winner' survives every
    crunch untouched.

Card grammar: the act line is catalogue Type 3 VERBATIM ("Move all sending to
variant {X} on email {n}") so the campaign view speaks the same vocabulary as
the crunch. The "variant {X}" / "email {n}" tokens also let the card's Why?
digest match the live scale_winner notification row, which swaps the card's
primary button to the real 1-click action (variant-action-wire's adaptive
primary). Dedupe: if the crunch has already written its own live Type 3 card
for the campaign (act starts "Move all sending to variant"), this module
skips/clears its card - the crunch card carries the fuller analysis, this one
is the deterministic backstop.

Writes ONLY the 'scale-winner' rows in `campaign_insights` - never any other
insight_key, never any other table. No Smartlead calls at all. Idempotent:
safe to run every tick.

Usage:
  python app/scale_winner_insights.py            # mirror + upsert/clear
  python app/scale_winner_insights.py --dry-run  # print, no writes
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-scale-winner-cards/1.0"

INSIGHT_KEY = "scale-winner"
GENERATED_BY = "scale-winner parity (deterministic)"
EXPIRES_DAYS = 3   # short box + 3h re-assert: a stale card self-expires within
                   # 3 days if the cron ever stops running
TITLE_RE = re.compile(r"^Send 100% of Email (\d+) to Version (.+)$")


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
    """Supabase PostgREST call - reads notifications, writes campaign_insights."""
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def live_scale_rows() -> dict[str, dict]:
    """{campaign_id: newest live scale_winner notification row}. status=new only:
    an acknowledged/resolved row means a human or the generator has moved on,
    and the card must drop with it (server.py's per-campaign optimisations
    array uses the same status=eq.new bar)."""
    rows = sb("GET", "optimiser_notifications?action_type=eq.scale_winner"
                     "&status=eq.new&order=created_at.desc"
                     "&select=id,campaign_id,campaign_name,client,title,detail,"
                     "suggested_action,smartlead_url,created_at") or []
    out: dict[str, dict] = {}
    for r in rows if isinstance(rows, list) else []:
        cid = str(r.get("campaign_id") or "")
        if cid and cid not in out:   # newest first - keep one per campaign
            out[cid] = r
    return out


def crunch_type3_scopes() -> set[str]:
    """Campaigns where the morning crunch already shows its own live Type 3
    card ("Move all sending to variant ..." under a different insight_key).
    This module's card would be a duplicate there - the crunch card wins."""
    rows = sb("GET", "campaign_insights?status=eq.live"
                     f"&insight_key=neq.{INSIGHT_KEY}&select=scope,payload") or []
    out = set()
    for r in rows if isinstance(rows, list) else []:
        act = str(((r.get("payload") or {}).get("act")) or "")
        if act.startswith("Move all sending to variant"):
            out.add(str(r.get("scope")))
    return out


def build_payload(n: dict, email_num: str, label: str) -> dict:
    cid = str(n["campaign_id"])
    detail = str(n.get("detail") or "").strip()
    # bold = the evidence sentence(s); the standing mechanics line lives in note
    bold = detail
    tail = " The 1-click button on the Messaging tab moves all of Email 1 to it."
    if bold.endswith(tail.strip()):
        bold = bold[: -len(tail.strip())].strip()
    return {
        "kind": INSIGHT_KEY,
        "tag": "act",                        # amber / Medium badge on the card
        "owner": "Lilly",
        "client": n.get("client") or "Navreo",
        "act": f"Move all sending to variant {label} on email {email_num}",
        "bold": bold or (f"Version {label} is this campaign's proven best opener, "
                         f"but it is not getting all of Email {email_num}'s traffic."),
        "note": ("This is the same verdict as the BEST pill on the campaign's "
                 "Messaging tab. The 1-click button there moves all of the step's "
                 "traffic to the winner - nothing changes until someone actions it. "
                 "The card clears itself once the traffic has moved or the verdict "
                 "changes."),
        "stats": {},
        "campaign_name": n.get("campaign_name") or f"Campaign {cid}",
        "smartlead_url": n.get("smartlead_url") or "",
    }


def existing_live_cards() -> dict[str, str]:
    """{scope: id} for every live 'scale-winner' card currently on the book."""
    rows = sb("GET", f"campaign_insights?insight_key=eq.{INSIGHT_KEY}&status=eq.live"
                     "&select=id,scope") or []
    return {str(r["scope"]): r["id"] for r in rows if isinstance(r, dict)}


def refresh(dry_run: bool = False) -> dict:
    """Mirror live scale_winner notifications into campaign_insights cards,
    and self-clear cards whose source row is gone. Returns a summary dict."""
    src = live_scale_rows()
    dupes = crunch_type3_scopes()
    existing = existing_live_cards()
    now = _now_iso()
    expires = (datetime.now(timezone.utc)
               + timedelta(days=EXPIRES_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    added = refreshed = cleared = skipped = 0
    want: dict[str, dict] = {}
    for cid, n in src.items():
        m = TITLE_RE.match(str(n.get("title") or ""))
        if not m:
            continue   # never card a row whose title we can't parse
        if cid in dupes:
            skipped += 1
            continue   # the crunch already shows its own Type 3 card here
        want[cid] = build_payload(n, m.group(1), m.group(2))

    for cid, payload in want.items():
        fp = hashlib.md5(f"{cid}:{INSIGHT_KEY}:{payload['act']}".encode()).hexdigest()
        if dry_run:
            print(f"  would card {cid}: {payload['act']}")
            continue
        if cid in existing:
            sb("PATCH", f"campaign_insights?id=eq.{existing[cid]}",
               {"payload": payload, "expires_at": expires, "data_fingerprint": fp})
            refreshed += 1
        else:
            sb("POST", "campaign_insights",
               {"scope": cid, "insight_key": INSIGHT_KEY, "payload": payload,
                "data_fingerprint": fp, "generated_by": GENERATED_BY,
                "status": "live", "expires_at": expires})
            added += 1

    # Self-clear: card with no live source row (verdict changed, traffic moved,
    # human marked it done) or now shadowed by a crunch Type 3 card.
    for scope, rid in existing.items():
        if scope not in want:
            if not dry_run:
                sb("PATCH", f"campaign_insights?id=eq.{rid}",
                   {"status": "expired", "superseded_at": now})
            cleared += 1

    print(f"  scale-winner cards: {len(want)} wanted (+{added} new, {refreshed} "
          f"refreshed, {cleared} cleared, {skipped} left to the crunch's own card)"
          + (" (dry-run: no writes)" if dry_run else ""))
    return {"wanted": len(want), "added": added, "refreshed": refreshed,
            "cleared": cleared, "skipped_crunch_dupe": skipped}


def main() -> int:
    dry = "--dry-run" in sys.argv
    summary = refresh(dry_run=dry)
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
