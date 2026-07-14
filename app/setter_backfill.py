"""One-time backfill: sweep the last 7 days of `replies` rows in the four
core-four categories for campaigns assigned to ENABLED setter agents, and
queue any of them run_poll never saw because they arrived before the agent's
campaign was assigned (see setter.py's campaign_assigned_at skip in
run_poll).

BUILD ONLY. This script is standalone - it is never imported by server.py,
never wired to a route, and never run automatically. A human runs it once,
by hand, after reading the --dry-run output. It reuses setter.py's own
helpers (_SB, _load_agents, _load_settings, _agent_for_campaign,
_existing_row, process_reply, CORE_FOUR) so the queueing logic is identical
to run_poll's - the only deliberate difference is the campaign_assigned_at
bypass documented on select_candidates() below (ruling 2026-07-14).

Idempotent: every candidate is checked against setter_queue via
_existing_row before it is queued, so re-running this script (even after a
partial run, or after run_poll has since caught up on some of the same rows)
never double-queues anything.

NETWORK: hits real Supabase (read on `replies`/`setter_agents`, write on
`setter_queue` via process_reply) and real OpenAI/Smartlead/Calendly through
process_reply's normal pipeline - but ONLY when run with --execute. Without
--execute (the default) this script makes zero writes: no process_reply
call, no PATCH, no POST.

Usage:
    python3 setter_backfill.py                # dry run (default) - prints candidates + summary, writes nothing
    python3 setter_backfill.py --dry-run       # same as above, explicit
    python3 setter_backfill.py --execute       # actually queues the candidates via process_reply
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402
from setter import (  # noqa: E402
    WORKSPACE, _load_agents, _load_settings, _agent_for_campaign, _existing_row,
    process_reply, CORE_FOUR, _SB,
)

LOOKBACK_DAYS = 7


# ── keys + a tiny Supabase/OpenAI client (self-contained, no import of server.py) ──
# Mirrors setter_eval.py's own load_keys/http_json/make_sb exactly, so this
# script has zero dependency on server.py and the same env-first /
# ~/.navreo-keys.env fallback the rest of the app's standalone scripts use.

def load_keys() -> dict:
    keys = {}
    env_file = Path.home() / ".navreo-keys.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        if v:
            keys[k] = v
    return keys


def http_json(method: str, url: str, headers: dict, body: dict = None, timeout: float = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "navreo-setter-backfill/1.0", "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        import certifi, ssl  # same trust store server.py uses (macOS python lacks system certs)
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return {"error": json.loads(raw)}
        except Exception:  # noqa: BLE001
            return {"error": raw.decode(errors="replace")}


def make_sb(keys: dict):
    url = keys.get("SUPABASE_URL")
    key = keys.get("SUPABASE_SERVICE_ROLE_KEY")

    def sb(method: str, path: str, body=None, prefer: str = ""):
        if not url or not key:
            return None
        return http_json(method, f"{url}/rest/v1/{path}",
                         {"apikey": key, "Authorization": f"Bearer {key}",
                          "Prefer": prefer or "return=minimal"}, body)
    return sb


def select_candidates(enabled_agents: list, campaign_ids: list):
    """Pulls `replies` rows from the last LOOKBACK_DAYS days, category in
    CORE_FOUR, for the given campaign ids - same agent/campaign selection
    run_poll uses, ordered by replied_at asc, with NO 15-row cap (a backfill
    has to actually finish in one pass).

    Deliberately SKIPS the campaign_assigned_at check run_poll enforces
    (ruling 2026-07-14): this one-time pass intentionally reaches back past
    assignment stamps to sweep up positive replies that arrived before an
    agent was assigned to their campaign - exactly the backlog run_poll's own
    assigned_at rule is designed to leave alone. This bypass exists ONLY
    here; run_poll must never adopt it.

    Returns (candidates, skipped_dupe, total_seen) where `candidates` is the
    de-duped (via _existing_row) list of (reply_dict, agent) tuples actually
    actionable, `skipped_dupe` is how many otherwise-matching rows were
    already in setter_queue, and `total_seen` is candidates + skipped_dupe.
    """
    if not campaign_ids:
        return [], 0, 0
    # "Z" instead of "+00:00": this script's raw http_json doesn't URL-encode
    # the query string, and an unencoded "+" reaches PostgREST as a space.
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)).isoformat().replace("+00:00", "Z")
    ids_csv = ",".join(campaign_ids)
    # category filtered client-side below (like run_poll does), not pushed
    # into the query - category names contain spaces ("Information Request"),
    # which would need PostgREST's own quote-the-value-then-percent-encode
    # dance to filter on server-side; simpler and just as cheap to pull the
    # window and check membership in CORE_FOUR here. limit is generous (not
    # the poll's 15-per-tick cap) since a backfill has to actually finish.
    # Exactly run_poll's column list - replies has no first_name/last_name/
    # company_domain columns, and asking PostgREST for a missing column 400s
    # the whole request (which is how the first dry run silently saw 0 rows).
    rows = _SB("GET", f"replies?workspace=eq.{WORKSPACE}&smartlead_campaign_id=in.({ids_csv})"
                      f"&replied_at=gte.{since}&order=replied_at.asc&limit=5000"
                      f"&select=id,smartlead_campaign_id,email,replied_at,category,"
                      f"reply_subject,reply_body,smartlead_message_id")
    if not isinstance(rows, list):
        raise RuntimeError(f"replies fetch did not return a list (got {type(rows).__name__}: "
                           f"{str(rows)[:200]}) - refusing to report 0 candidates on a failed read")

    candidates = []
    skipped_dupe = 0
    total_seen = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("category") not in CORE_FOUR:
            continue
        cid = r.get("smartlead_campaign_id")
        email = (r.get("email") or "").strip().lower()
        mid = str(r.get("smartlead_message_id") or r.get("message_id") or r.get("id") or "")
        if not cid or not email or not mid:
            continue
        agent = _agent_for_campaign(cid, require_enabled=True, agents=enabled_agents)
        if not agent:
            continue
        total_seen += 1
        if _existing_row(WORKSPACE, cid, email, mid):
            skipped_dupe += 1
            continue
        candidates.append((r, cid, email, mid, agent))
    return candidates, skipped_dupe, total_seen


def _reply_dict(r: dict, cid, email: str, mid: str) -> dict:
    """Same field shape run_poll builds for process_reply - see setter.py's
    run_poll loop body."""
    return {
        "workspace": WORKSPACE, "campaign_id": cid, "email": email,
        "first_name": r.get("first_name"), "last_name": r.get("last_name"),
        "company_domain": r.get("company_domain"), "subject": r.get("reply_subject") or r.get("subject"),
        "body": r.get("reply_body") or r.get("body") or "",
        "replied_at": r.get("replied_at"), "message_id": mid,
        "category": r.get("category"), "is_test": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true",
                        help="Actually queue the candidates via process_reply. Without this flag nothing is written.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Explicit dry run (this is also the default with no flags). Wins over --execute if both are passed.")
    args = parser.parse_args()
    execute = bool(args.execute) and not args.dry_run

    keys = load_keys()
    sb = make_sb(keys)
    setter.configure(sb=sb, http_json=http_json, keys=keys, log_activity=lambda *a, **k: None)
    # `from setter import _SB` above captured setter._SB's value at import
    # time (None - configure() hadn't run yet). Rebind the module-level name
    # in THIS file to the now-configured callable, so select_candidates()'s
    # bare `_SB(...)` calls (resolved at call time from this module's own
    # globals) hit the real thing instead of the stale None.
    global _SB
    _SB = setter._SB

    agents = _load_agents()
    enabled_agents = [a for a in agents if a.get("enabled", True) and (a.get("campaign_ids") or [])]
    campaign_ids = sorted({str(c) for a in enabled_agents for c in (a.get("campaign_ids") or [])})
    settings = _load_settings()

    candidates, skipped_dupe, total_seen = select_candidates(enabled_agents, campaign_ids)

    print(f"[setter_backfill] lookback={LOOKBACK_DAYS}d  campaigns={len(campaign_ids)}  "
         f"mode={'EXECUTE' if execute else 'DRY-RUN'}")
    print(f"[setter_backfill] {total_seen} matching replies found, {skipped_dupe} already in "
         f"setter_queue, {len(candidates)} actionable\n")

    for r, cid, email, mid, agent in candidates:
        print(f"  {r.get('replied_at')}  campaign={cid}  email={email}  "
             f"category={r.get('category')}  message_id={mid}  agent={agent.get('id')}")

    queued = 0
    errors = 0
    if execute:
        for r, cid, email, mid, agent in candidates:
            reply = _reply_dict(r, cid, email, mid)
            try:
                row = process_reply(reply, agent, settings)
                if (row or {}).get("status") == "error":
                    errors += 1
                else:
                    queued += 1
            except Exception as e:  # noqa: BLE001 - one bad reply must never stop the backfill
                errors += 1
                print(f"[setter_backfill] error queueing {email}/{cid}: {e}", file=sys.stderr)

    print(f"\n[setter_backfill] summary: candidates={len(candidates)} "
         f"skipped_as_duplicate={skipped_dupe} queued={queued} errors={errors}")
    if not execute:
        print("[setter_backfill] dry run - nothing was written. Re-run with --execute to queue the candidates above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
