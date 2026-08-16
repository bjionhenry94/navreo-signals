#!/usr/bin/env python3
"""Notion <-> Smartlead <-> Supabase booked-lead sync — Render Cron Job.

One reconcile pass per run, per client in app/data/booked_sync_clients.json:

  FORWARD  (Notion -> Smartlead): every Notion row at a booked-tier Status is
           paused in EVERY campaign where it is still active (no more sends)
           and categorised "Call Booked" on the campaign(s) where it replied.
  REVERSE  (Smartlead -> Notion): every lead with a Call Booked reply (Supabase
           `replies`, campaign-scoped via `campaign_scorecard.client`) or a
           booked meeting (`meetings`) whose Notion row sits BELOW booked tier
           is ratcheted up to the configured target status.

Hard rules (do not relax):
  * Ratchet only — this job never moves any lead AWAY from booked, anywhere.
  * Never writes the human-owned billing statuses (Call Attended / Paid).
  * Pause, never delete. No emails are ever composed or sent.
  * Booked leads with no Notion row are LOGGED as unmatched, never auto-created
    (same person can book under a different email — a human resolves those).

State: Supabase `booked_leads` (one row per client+email, jsonb `campaigns_paused`
holds {"paused": [...], "category_set": [...], "done": bool}) and append-only
`booked_sync_ledger` (every action + a run_summary row per client per run).

Env:
  BOOKED_SYNC_DRY=1   full pass, ledger rows flagged dry_run, ZERO writes to
                      Notion or Smartlead (and no booked_leads upserts).
  BOOKED_SYNC_FULL=1  ignore the done fast-path and re-verify every booked lead
                      (also happens automatically on the first run after each
                      6-hour boundary, so new campaign uploads of an already-
                      booked lead get caught within 6h).

Missing NOTION_API_KEY: logs + exits 0 (cron-safe), nothing else runs.
Run:  python app/sync_booked.py
Exit: 0 on success, 1 on unrecoverable failure.
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402 — reuse KEYS / http_json / sb conventions

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
SL_BASE = "https://server.smartlead.ai/api/v1"
CONFIG_PATH = Path(__file__).resolve().parent / "booked_sync_clients.json"
DRY = os.environ.get("BOOKED_SYNC_DRY", "") == "1"
# Campaign statuses that can never send again — everything else gets the pause
# (an ACTIVE campaign obviously, but also PAUSED/DRAFTED ones that could resume
# or launch later with the lead still enrolled).
TERMINAL_CAMPAIGN_STATUSES = {"COMPLETED", "ARCHIVED", "STOPPED"}


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ---------- Notion ----------
def _notion_headers():
    return {
        "Authorization": f"Bearer {server.KEYS['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
    }


def notion_query_all(database_id: str) -> list[dict]:
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = server.http_json(
            "POST", f"{NOTION_BASE}/databases/{database_id}/query", _notion_headers(), body
        )
        if not isinstance(data, dict) or data.get("object") == "error":
            raise RuntimeError(f"Notion query failed: {str(data)[:300]}")
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")
        time.sleep(0.34)  # Notion rate limit ~3 rps


def prop_email(page: dict, prop_name: str) -> str:
    p = (page.get("properties") or {}).get(prop_name) or {}
    if p.get("type") == "email":
        return (p.get("email") or "").strip().lower()
    for key in ("rich_text", "title"):
        if p.get("type") == key:
            return "".join(t.get("plain_text", "") for t in p.get(key, [])).strip().lower()
    return ""


def prop_status(page: dict, prop_name: str) -> tuple[str, str]:
    """Returns (value_name, property_type) — handles select and status props."""
    p = (page.get("properties") or {}).get(prop_name) or {}
    ptype = p.get("type") or ""
    val = p.get(ptype) if ptype in ("select", "status") else None
    return ((val or {}).get("name") or "", ptype)


def notion_set_status(page_id: str, prop_name: str, prop_type: str, value: str):
    body = {"properties": {prop_name: {prop_type or "select": {"name": value}}}}
    data = server.http_json("PATCH", f"{NOTION_BASE}/pages/{page_id}", _notion_headers(), body)
    if not isinstance(data, dict) or data.get("object") == "error":
        raise RuntimeError(f"Notion page update failed: {str(data)[:300]}")


# ---------- Smartlead ----------
def sl_json(method: str, path: str, key: str, body=None):
    sep = "&" if "?" in path else "?"
    return server.http_json(method, f"{SL_BASE}{path}{sep}api_key={key}", {}, body)


def client_campaigns(cfg: dict, sl_key: str) -> tuple[set[int], dict[int, str]]:
    """-> (client campaign ids, campaign_id -> campaign status for ALL campaigns).
    Ids are the union of the scorecard's label authority and Smartlead's client_id."""
    ids: set[int] = set()
    status_by_id: dict[int, str] = {}
    rows = server.sb_get_all(
        f"campaign_scorecard?client=eq.{urllib.parse.quote(cfg['scorecard_client'])}"
        "&select=smartlead_campaign_id"
    ) or []
    ids |= {int(r["smartlead_campaign_id"]) for r in rows if r.get("smartlead_campaign_id")}
    try:
        camps = sl_json("GET", "/campaigns", sl_key)
        if isinstance(camps, list):
            status_by_id = {c["id"]: (c.get("status") or "").upper() for c in camps}
            ids |= {c["id"] for c in camps if c.get("client_id") == cfg["smartlead_client_id"]}
    except Exception as e:  # noqa: BLE001 — scorecard set alone is still usable
        log(f"WARNING smartlead campaign list failed, using scorecard only: {e}")
    return ids, status_by_id


# ---------- pure planners (unit-tested in test_booked_sync.py) ----------
def _is_client_membership(m: dict, client_id: int, campaign_ids: set[int]) -> bool:
    """A lead_campaign_data entry belongs to this client if Smartlead says so
    directly, or (client_id null on old rows) the campaign is in our known set."""
    cid = m.get("campaign_id")
    return m.get("client_id") == client_id or (m.get("client_id") is None
                                               and cid in campaign_ids)


def plan_pauses(memberships: list[dict], status_by_id: dict[int, str],
                client_id: int, campaign_ids: set[int],
                already_paused: set[int]) -> list[int]:
    """Client campaigns that could still message this lead and that we have not
    already paused. Unknown campaign status counts as pausable (fail safe)."""
    out = []
    for m in memberships:
        cid = m.get("campaign_id")
        if not cid or cid in already_paused:
            continue
        if not _is_client_membership(m, client_id, campaign_ids):
            continue
        if status_by_id.get(cid, "") not in TERMINAL_CAMPAIGN_STATUSES:
            out.append(cid)
    return sorted(out)


def plan_categories(memberships: list[dict], reply_campaigns: set[int],
                    category_id: int, client_id: int,
                    campaign_ids: set[int]) -> list[int]:
    """Campaigns where the lead replied and the category is not yet Call Booked.
    No reply campaign -> no category write (attribution must be real)."""
    out = []
    for m in memberships:
        cid = m.get("campaign_id")
        if (cid in reply_campaigns and _is_client_membership(m, client_id, campaign_ids)
                and m.get("lead_category_id") != category_id):
            out.append(cid)
    return sorted(out)


def plan_reverse(sl_booked: set[str], notion_by_email: dict, cfg: dict):
    """-> (updates [(email, page_id, prop_type, current)], unmatched [email], noop count).
    Ratchet-only: rows already at any booked-tier value are untouched."""
    updates, unmatched, noops = [], [], 0
    for email in sorted(sl_booked):
        row = notion_by_email.get(email)
        if row is None:
            unmatched.append(email)
            continue
        current, ptype = row["status"], row["status_type"]
        if current in cfg["booked_values"]:
            noops += 1
        else:
            updates.append((email, row["page_id"], ptype, current))
    return updates, unmatched, noops


# ---------- state + ledger ----------
def ledger(rows: list[dict]):
    if rows:
        server.sb("POST", "booked_sync_ledger", rows)


def load_state(client: str) -> dict:
    rows = server.sb_get_all(
        f"booked_leads?client=eq.{client}&select=email,campaigns_paused,notion_page_id,source"
    ) or []
    return {r["email"]: r for r in rows}


def upsert_state(client: str, email: str, patch: dict):
    if DRY:
        return
    body = {"client": client, "email": email,
            "updated_at": datetime.now(timezone.utc).isoformat(), **patch}
    server.sb("POST", "booked_leads?on_conflict=client,email", body,
              prefer="resolution=merge-duplicates")


# ---------- per-client pass ----------
def run_client(client: str, cfg: dict, full_verify: bool) -> dict:
    sl_key = server.KEYS.get(cfg["smartlead_key_env"], "")
    if not sl_key:
        raise RuntimeError(f"missing {cfg['smartlead_key_env']}")
    counts = {"paused": 0, "categorised": 0, "notion_ratcheted": 0,
              "unmatched_notion": 0, "unmatched_smartlead": 0, "errors": 0}
    entries: list[dict] = []

    def rec(action, email=None, direction=None, before=None, after=None, detail=None):
        entries.append({"client": client, "email": email, "action": action,
                        "direction": direction, "before_state": before, "after_state": after,
                        "dry_run": DRY, "detail": detail})

    # -- shared pulls
    pages = notion_query_all(cfg["notion_database_id"])
    notion_by_email: dict[str, dict] = {}
    for pg in pages:
        email = prop_email(pg, cfg["email_prop"])
        if not email:
            continue
        status, ptype = prop_status(pg, cfg["status_prop"])
        notion_by_email[email] = {"page_id": pg["id"], "status": status,
                                  "status_type": ptype or "select",
                                  "edited": pg.get("last_edited_time")}
    log(f"[{client}] notion rows with email: {len(notion_by_email)}")
    camp_ids, camp_status = client_campaigns(cfg, sl_key)
    log(f"[{client}] client campaigns known: {len(camp_ids)}")
    if not camp_ids:
        raise RuntimeError("no client campaigns resolved — refusing to run reverse/forward")
    state = load_state(client)

    # -- FORWARD: Notion booked -> pause + categorise in Smartlead
    booked_rows = {e: r for e, r in notion_by_email.items()
                   if r["status"] in cfg["booked_values"]}
    log(f"[{client}] notion booked-tier rows: {len(booked_rows)}")
    # attribution: campaigns where this email actually replied (for the category write)
    reply_camps: dict[str, set[int]] = {}
    for r in server.sb_get_all(
            f"replies?smartlead_campaign_id=in.({','.join(map(str, sorted(camp_ids)))})"
            "&select=email,smartlead_campaign_id") or []:
        if r.get("email"):
            reply_camps.setdefault(r["email"].strip().lower(), set()).add(
                int(r["smartlead_campaign_id"]))

    for email, row in sorted(booked_rows.items()):
        st = state.get(email) or {}
        marks = st.get("campaigns_paused") or {}
        if isinstance(marks, list):  # legacy shape safety
            marks = {"paused": marks}
        if marks.get("done") and not full_verify:
            continue
        try:
            lead = sl_json("GET", f"/leads/?email={urllib.parse.quote(email)}", sl_key)
            lead_id = (lead or {}).get("id")
            if not lead_id:
                if not marks.get("no_smartlead_lead"):
                    counts["unmatched_smartlead"] += 1
                    rec("unmatched_no_smartlead_lead", email, "notion->smartlead",
                        before=row["status"])
                    upsert_state(client, email, {
                        "source": "notion", "notion_page_id": row["page_id"],
                        "booked_at": row["edited"],
                        "campaigns_paused": {**marks, "no_smartlead_lead": True}})
                continue
            memberships = (lead or {}).get("lead_campaign_data") or []
            already_paused = set(marks.get("paused") or [])
            to_pause = plan_pauses(memberships, camp_status,
                                   cfg["smartlead_client_id"], camp_ids, already_paused)
            for cid in to_pause:
                if not DRY:
                    sl_json("POST", f"/campaigns/{cid}/leads/{lead_id}/pause", sl_key, {})
                counts["paused"] += 1
                rec("paused_in_campaign", email, "notion->smartlead",
                    before=row["status"], after=f"campaign {cid} paused",
                    detail={"campaign_id": cid, "lead_id": lead_id})
            cat_targets = plan_categories(memberships, reply_camps.get(email, set()),
                                          cfg["call_booked_category_id"],
                                          cfg["smartlead_client_id"], camp_ids)
            cat_done = set(marks.get("category_set") or [])
            for cid in cat_targets:
                if not DRY:
                    sl_json("POST", f"/campaigns/{cid}/leads/{lead_id}/category",
                            sl_key, {"category_id": cfg["call_booked_category_id"],
                                     "pause_lead": True})
                counts["categorised"] += 1
                cat_done.add(cid)
                rec("category_call_booked", email, "notion->smartlead",
                    after=f"campaign {cid} -> Call Booked",
                    detail={"campaign_id": cid, "lead_id": lead_id})
            paused_all = sorted(already_paused | set(to_pause))
            upsert_state(client, email, {
                "source": st.get("source") or "notion",
                "notion_page_id": row["page_id"], "booked_at": row["edited"],
                "smartlead_lead_id": str(lead_id),
                "campaigns_paused": {"paused": paused_all,
                                     "category_set": sorted(cat_done), "done": True}})
        except Exception as e:  # noqa: BLE001 — one bad lead must not kill the run
            counts["errors"] += 1
            rec("error_forward", email, "notion->smartlead", detail={"error": str(e)[:300]})
            log(f"[{client}] ERROR forward {email}: {e}")

    # -- REVERSE: Smartlead/Calendly booked -> ratchet Notion
    sl_booked: set[str] = set()
    for r in server.sb_get_all(
            f"replies?category=eq.Call%20Booked"
            f"&smartlead_campaign_id=in.({','.join(map(str, sorted(camp_ids)))})"
            "&select=email") or []:
        if r.get("email"):
            sl_booked.add(r["email"].strip().lower())
    for r in server.sb_get_all(
            f"meetings?client_id=eq.{cfg['supabase_client_id']}"
            "&select=raw_attendee_email") or []:
        if r.get("raw_attendee_email"):
            sl_booked.add(r["raw_attendee_email"].strip().lower())
    log(f"[{client}] smartlead/calendly booked emails: {len(sl_booked)}")

    updates, unmatched, noops = plan_reverse(sl_booked, notion_by_email, cfg)
    for email, page_id, ptype, current in updates:
        try:
            if not DRY:
                notion_set_status(page_id, cfg["status_prop"], ptype, cfg["ratchet_target"])
            counts["notion_ratcheted"] += 1
            rec("notion_ratchet", email, "smartlead->notion",
                before=current, after=cfg["ratchet_target"], detail={"page_id": page_id})
            upsert_state(client, email, {"source": "smartlead", "notion_page_id": page_id,
                                         "booked_at": datetime.now(timezone.utc).isoformat()})
        except Exception as e:  # noqa: BLE001
            counts["errors"] += 1
            rec("error_reverse", email, "smartlead->notion", detail={"error": str(e)[:300]})
            log(f"[{client}] ERROR reverse {email}: {e}")
    for email in unmatched:
        if (state.get(email) or {}).get("source") == "smartlead_unmatched":
            continue  # already on record — don't re-ledger every run
        counts["unmatched_notion"] += 1
        rec("unmatched_no_notion_row", email, "smartlead->notion")
        upsert_state(client, email, {
            "source": "smartlead_unmatched",
            "booked_at": datetime.now(timezone.utc).isoformat(),
            "campaigns_paused": {}})
    log(f"[{client}] reverse noops (already booked in Notion): {noops}")

    rec("run_summary", detail={**counts, "full_verify": full_verify,
                               "notion_rows": len(notion_by_email),
                               "booked_rows": len(booked_rows),
                               "sl_booked": len(sl_booked)})
    ledger(entries)
    return counts


def main() -> int:
    if not server.KEYS.get("NOTION_API_KEY"):
        log("NOTION_API_KEY missing — booked-sync idle (add it to the navreo-secrets "
            "env group; see booked-sync-orchestrator skill Step 0). Exiting 0.")
        return 0
    cfgs = json.loads(CONFIG_PATH.read_text())
    now = datetime.now(timezone.utc)
    full_verify = os.environ.get("BOOKED_SYNC_FULL", "") == "1" or (
        now.hour % 6 == 0 and now.minute < 30)
    log(f"booked-sync start dry={DRY} full_verify={full_verify} clients={list(cfgs)}")
    failures = 0
    for client, cfg in cfgs.items():
        try:
            counts = run_client(client, cfg, full_verify)
            log(f"[{client}] done: {counts}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            log(f"[{client}] FAILED: {e}")
            ledger([{"client": client, "action": "run_failed", "dry_run": DRY,
                     "detail": {"error": str(e)[:300]}}])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
