#!/usr/bin/env python3
"""Notion <-> Smartlead <-> Supabase pipeline-status sync — Render Cron Job.

One reconcile pass per run, per client in app/booked_sync_clients.json,
enforcing Bjion's full mapping ruling (2026-08-16):

  FORWARD  (Notion -> Smartlead), per forward_map:
           Meeting-Ready -> Meeting Request; Meeting-Booked / No-Showed /
           Call Attended / Paid -> Call Booked (+ PAUSED in every campaign
           that could still send); Contact in the future -> Contact In Future;
           Disqualified -> Not a qualified lead (SL has no literal
           "Disqualified"). Called / No response / everything else: no change.
           Category writes land only on campaigns where the lead REPLIED.
  REVERSE  (Smartlead -> Notion), per reverse_map + the status ladder:
           Call Booked -> Meeting-Booked; Meeting Request -> Meeting-Ready;
           Interested / Information Request -> Positive Response;
           Contact In Future -> Contact in the future; Not a qualified lead ->
           Disqualified. Any other category never writes to Notion.

Hard rules (do not relax):
  * The ladder is one-way UP (status_rank in config). Reverse never moves a
    row down, and never touches the human tier (Called and above).
  * Notion is the truer source (Bjion ruling 2026-08-16): reverse re-fires for
    a lead only when Smartlead shows something HIGHER than we ever pushed
    before (last_pushed in state) — so a deliberate human downgrade in Notion
    sticks unless genuinely new evidence arrives.
  * Pause, never delete. Pausing happens only for pause_values (booked tier).
    No emails are ever composed or sent.
  * No-Notion-row leads (Bjion ruling 2026-08-16): a lead with a POSITIVE
    Smartlead category (auto_create_categories) and no row is AUTO-CREATED at
    its mapped status, with name/company/reply metadata filled. Non-positive
    evidence never creates a row: booked-tier gets ledgered as unmatched,
    lower tiers are just counted.

State: Supabase `booked_leads` (one row per client+email; jsonb
`campaigns_paused` holds {"paused": [...], "cat_map": {cid: category_id},
"last_pushed": status, "done_for": status, ...}) and append-only
`booked_sync_ledger` (every action + a run_summary row per client per run).

Env:
  BOOKED_SYNC_DRY=1   full pass, ledger rows flagged dry_run, ZERO writes to
                      Notion or Smartlead (and no booked_leads upserts).
  BOOKED_SYNC_FULL=1  ignore the done_for fast-path and re-verify every mapped
                      lead (also automatic on the first run after each 6-hour
                      boundary, so new campaign uploads of an already-mapped
                      lead get caught within 6h).

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


def strip_html(text: str) -> str:
    """Reply bodies arrive as raw HTML — Notion's Full-Reply wants readable text."""
    import html as _html
    import re as _re
    if not text:
        return ""
    text = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return _re.sub(r"[ \t]+", " ", _re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def _rt(content, link=None, bold=False):
    o = {"type": "text", "text": {"content": content}}
    if link:
        o["text"]["link"] = {"url": link}
    if bold:
        o["annotations"] = {"bold": True}
    return o


def template_blocks(email: str, meta: dict) -> list[dict]:
    """The approved lead-page body (Bjion 2026-08-17): Snapshot table of the
    property-less trio, the sent email + their reply as quotes, then the
    Smartlead/setter conversation links. Sections without data are omitted."""
    def heading(t):
        return {"type": "heading_3", "heading_3": {"rich_text": [_rt(t)]}}
    def trow(label, val):
        return {"type": "table_row",
                "table_row": {"cells": [[_rt(label, bold=True)], [_rt(val or "—")]]}}
    children = [
        heading("📋 Lead Snapshot"),
        {"type": "table", "table": {"table_width": 2, "has_column_header": False,
                                    "has_row_header": False, "children": [
            trow("Title", meta.get("title")),
            trow("Company Size", meta.get("company_size")),
            trow("Geography", meta.get("geography")),
        ]}},
    ]
    if meta.get("sent_body"):
        children += [
            heading(f"📤 First email we sent — {str(meta.get('sent_at') or '')[:10] or '—'}"),
            {"type": "quote", "quote": {"rich_text": [
                _rt("Subject: " + (meta.get("sent_subject") or "—") + "\n\n", bold=True),
                _rt(strip_html(meta["sent_body"])[:1900])]}},
        ]
    if meta.get("reply_body"):
        children += [
            heading(f"📥 Their reply — {str(meta.get('replied_at') or '')[:10] or '—'}"),
            {"type": "quote", "quote": {"rich_text": [
                _rt(strip_html(meta["reply_body"])[:1900])]}},
        ]
    children.append(heading("🔗 Open the conversation"))
    if meta.get("lead_map_id"):
        children.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
            _rt("Smartlead inbox", link="https://app.smartlead.ai/app/master-inbox?"
                                        f"action=INBOX&leadMap={meta['lead_map_id']}"),
            _rt("  — the live thread in Smartlead")]}})
    children.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        _rt("Setter", link="https://navreo-signals.onrender.com/app/setter.html#/r/"
                           + urllib.parse.quote(email, safe="")),
        _rt("  — the conversation in our reply tool")]}})
    return children


def enrich_meta(meta: dict, cfg: dict, email: str, sl_key: str,
                camp_ids: set[int], reply_campaign_id=None) -> dict:
    """Best-effort fill of Title/Geography/Company Size/lead_map/sent-email for
    the body template, from the Smartlead lead record + our Supabase caches."""
    import re as _re
    lead = sl_json("GET", f"/leads/?email={urllib.parse.quote(email)}", sl_key)
    if not (isinstance(lead, dict) and lead.get("id")):
        return meta
    meta.setdefault("name", " ".join(x for x in (lead.get("first_name"),
                                                 lead.get("last_name")) if x))
    meta.setdefault("company", lead.get("company_name"))
    meta.setdefault("linkedin", lead.get("linkedin_profile") or None)
    meta.setdefault("website", lead.get("website") or None)
    cf = lead.get("custom_fields") or {}
    meta["title"] = _re.split(r"\s*(?:--|\||–|—)\s*",
                              cf.get("Title") or "")[0].strip(" ,;")[:120]
    meta["geography"] = lead.get("location") or ""
    dom = _re.sub(r"^https?://(www\.)?", "",
                  meta.get("website") or "").split("/")[0].lower()
    if dom:
        comp = server.sb("GET", f"companies?domain=eq.{urllib.parse.quote(dom)}"
                                "&select=employee_range,employee_count&limit=1") or []
        if comp:
            meta["company_size"] = comp[0].get("employee_range") or (
                str(comp[0]["employee_count"]) if comp[0].get("employee_count") else None)
    member = None
    if reply_campaign_id is not None:
        member = next((m for m in lead.get("lead_campaign_data") or []
                       if m.get("campaign_id") == int(reply_campaign_id)), None)
    member = member or next((m for m in lead.get("lead_campaign_data") or []
                             if _is_client_membership(
                                 m, cfg["smartlead_client_id"], camp_ids)), None)
    if member:
        meta["lead_map_id"] = member.get("campaign_lead_map_id")
        try:
            hist = sl_json("GET", f"/campaigns/{member['campaign_id']}"
                                  f"/leads/{lead['id']}/message-history", sl_key)
            sent = next((h for h in (hist or {}).get("history", [])
                         if h.get("type") == "SENT"), None)
            if sent:
                meta["sent_subject"] = sent.get("subject")
                meta["sent_body"] = sent.get("email_body")
                meta["sent_at"] = sent.get("time")
        except Exception as e:  # noqa: BLE001 — sent email is best-effort
            log(f"WARN sent-email fetch {email}: {e}")
    return meta


def notion_create_row(cfg: dict, email: str, status: str, meta: dict) -> str:
    """Create a pipeline row for an auto-added positive lead: lean properties
    (email texts live in the BODY template, never in properties — Bjion ruling
    2026-08-17), then the body blocks. Returns page id."""
    def rt(text):
        return {"rich_text": [{"text": {"content": (text or "")[:1900]}}]}
    props = {
        cfg["email_prop"]: {"email": email},
        cfg["status_prop"]: {"select": {"name": status}},
        "Lead-Name": {"title": [{"text": {"content": meta.get("name") or email}}]},
    }
    if meta.get("company"):
        props["Company Name"] = rt(meta["company"])
    if meta.get("campaign_name"):
        props["Campaign Name"] = rt(meta["campaign_name"])
    if meta.get("replied_at"):
        props["Time of Reply"] = {"date": {"start": meta["replied_at"]}}
    if meta.get("linkedin"):
        props["LinkedIn URL"] = {"url": meta["linkedin"]}
    if meta.get("website"):
        props["Website"] = {"url": meta["website"]}
    data = server.http_json("POST", f"{NOTION_BASE}/pages", _notion_headers(),
                            {"parent": {"database_id": cfg["notion_database_id"]},
                             "properties": props})
    if not isinstance(data, dict) or data.get("object") == "error":
        raise RuntimeError(f"Notion page create failed: {str(data)[:300]}")
    page_id = data.get("id", "")
    try:
        server.http_json("PATCH", f"{NOTION_BASE}/blocks/{page_id}/children",
                         _notion_headers(), {"children": template_blocks(email, meta)})
    except Exception as e:  # noqa: BLE001 — body is decoration; the row exists
        log(f"WARNING body template failed for {email}: {e}")
    return page_id


def notion_set_status(page_id: str, prop_name: str, prop_type: str, value: str):
    body = {"properties": {prop_name: {prop_type or "select": {"name": value}}}}
    data = server.http_json("PATCH", f"{NOTION_BASE}/pages/{page_id}", _notion_headers(), body)
    if not isinstance(data, dict) or data.get("object") == "error":
        raise RuntimeError(f"Notion page update failed: {str(data)[:300]}")


# ---------- Smartlead ----------
def sl_json(method: str, path: str, key: str, body=None):
    """Smartlead call with polite pacing + 429 backoff (their limit bites after
    ~30 rapid calls; a forward sweep over a large client would otherwise die)."""
    sep = "&" if "?" in path else "?"
    url = f"{SL_BASE}{path}{sep}api_key={key}"
    for attempt, delay in ((1, 5), (2, 20), (3, 45), (4, 0)):
        try:
            out = server.http_json(method, url, {}, body)
            time.sleep(0.4)
            return out
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) and delay:
                log(f"smartlead 429 — backing off {delay}s (attempt {attempt})")
                time.sleep(delay)
                continue
            raise


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
            # A null config client_id must NEVER match Smartlead's null client_id —
            # in the main workspace that is every Navreo-own campaign (the
            # thunderbird 2026-08-17 incident). Name-token clients get their
            # campaign set from the scorecard alone.
            if cfg["smartlead_client_id"] is not None:
                ids |= {c["id"] for c in camps
                        if c.get("client_id") == cfg["smartlead_client_id"]}
    except Exception as e:  # noqa: BLE001 — scorecard set alone is still usable
        log(f"WARNING smartlead campaign list failed, using scorecard only: {e}")
    return ids, status_by_id


# ---------- pure planners (unit-tested in test_booked_sync.py) ----------
def rank_of(status: str | None, cfg: dict) -> int:
    return cfg["status_rank"].get(status or "", -1)


def _is_client_membership(m: dict, client_id, campaign_ids: set[int]) -> bool:
    """A lead_campaign_data entry belongs to this client if Smartlead says so
    directly, or (client_id null on old rows) the campaign is in our known set.
    Config client_id None (own-workspace / name-token clients) must NEVER match
    Smartlead's null client_id — only the known campaign set counts there."""
    cid = m.get("campaign_id")
    if client_id is None:
        return cid in campaign_ids
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
                    target_category: int, client_id: int, campaign_ids: set[int],
                    recorded: dict) -> list[int]:
    """Campaigns where the lead replied and neither Smartlead's live category nor
    our own record already matches the target. Once we've written a target for a
    campaign it is never re-asserted (a later human change in Smartlead sticks).
    No reply campaign -> no category write (attribution must be real)."""
    out = []
    for m in memberships:
        cid = m.get("campaign_id")
        if (cid in reply_campaigns and _is_client_membership(m, client_id, campaign_ids)
                and m.get("lead_category_id") != target_category
                and recorded.get(str(cid)) != target_category):
            out.append(cid)
    return sorted(out)


def plan_reverse(sl_targets: dict, notion_by_email: dict, last_pushed: dict,
                 cfg: dict):
    """sl_targets: email -> (best mapped Notion status, has_positive_category).
    -> (updates [(email, page_id, prop_type, current, target)],
        creates [(email, target)], unmatched_booked [email],
        unmatched_lower_count, noops)

    A row is updated only when the target outranks BOTH the row's current
    status (ladder is one-way up; human tier is unreachable — targets top out
    at Meeting-Booked) and whatever we last pushed for that email (so a human
    downgrade in Notion sticks unless genuinely new evidence arrives).
    No-row leads with positive evidence are planned as creates (Bjion ruling);
    non-positive no-row leads never create anything."""
    updates, creates, unmatched_booked, unmatched_lower, noops = [], [], [], 0, 0
    booked_rank = rank_of("Meeting-Booked", cfg)
    # Human-parked terminal states: only an actual booking may lift these —
    # a mere reply category must never overturn a Disqualified / Contact-later.
    parked = {"Disqualified", "Contact in the future"}
    for email in sorted(sl_targets):
        target, positive = sl_targets[email]
        t_rank = rank_of(target, cfg)
        row = notion_by_email.get(email)
        if row is None:
            if positive:
                creates.append((email, target))
            elif t_rank >= booked_rank:
                unmatched_booked.append(email)
            else:
                unmatched_lower += 1
            continue
        if row["status"] in parked and t_rank < booked_rank:
            noops += 1
            continue
        if t_rank > rank_of(row["status"], cfg) and t_rank > rank_of(
                last_pushed.get(email), cfg):
            updates.append((email, row["page_id"], row["status_type"],
                            row["status"], target))
        else:
            noops += 1
    return updates, creates, unmatched_booked, unmatched_lower, noops


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


def state_marks(st: dict) -> dict:
    marks = (st or {}).get("campaigns_paused") or {}
    return {"paused": marks} if isinstance(marks, list) else dict(marks)  # legacy shape


# ---------- per-client pass ----------
def run_client(client: str, cfg: dict, full_verify: bool) -> dict:
    sl_key = server.KEYS.get(cfg["smartlead_key_env"], "")
    if not sl_key:
        raise RuntimeError(f"missing {cfg['smartlead_key_env']}")
    counts = {"paused": 0, "categorised": 0, "notion_updated": 0,
              "notion_created": 0, "unmatched_notion": 0, "unmatched_lower": 0,
              "unmatched_smartlead": 0, "errors": 0}
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
                                  "edited": pg.get("last_edited_time"),
                                  "created": pg.get("created_time") or "",
                                  "has_frp": "Full-Reply" in (pg.get("properties") or {})}
    log(f"[{client}] notion rows with email: {len(notion_by_email)}")
    camp_ids, camp_status = client_campaigns(cfg, sl_key)
    log(f"[{client}] client campaigns known: {len(camp_ids)}")
    if not camp_ids:
        raise RuntimeError("no client campaigns resolved — refusing to run reverse/forward")
    state = load_state(client)
    # attribution + reverse evidence: this client's replies with their categories
    reply_rows = server.sb_get_all(
        f"replies?smartlead_campaign_id=in.({','.join(map(str, sorted(camp_ids)))})"
        "&select=email,smartlead_campaign_id,category,replied_at") or []
    reply_camps: dict[str, set[int]] = {}
    for r in reply_rows:
        if r.get("email"):
            reply_camps.setdefault(r["email"].strip().lower(), set()).add(
                int(r["smartlead_campaign_id"]))

    # -- FORWARD: Notion status -> Smartlead category (+ pause for booked tier)
    fwd_rows = {e: r for e, r in notion_by_email.items()
                if r["status"] in cfg["forward_map"]}
    log(f"[{client}] notion rows with a forward mapping: {len(fwd_rows)}")
    for email, row in sorted(fwd_rows.items()):
        st = state.get(email) or {}
        marks = state_marks(st)
        if marks.get("done_for") == row["status"] and not full_verify:
            continue
        target_cat = cfg["forward_map"][row["status"]]
        pause_wanted = row["status"] in cfg["pause_values"]
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
                                   cfg["smartlead_client_id"], camp_ids,
                                   already_paused) if pause_wanted else []
            for cid in to_pause:
                if not DRY:
                    sl_json("POST", f"/campaigns/{cid}/leads/{lead_id}/pause", sl_key, {})
                counts["paused"] += 1
                rec("paused_in_campaign", email, "notion->smartlead",
                    before=row["status"], after=f"campaign {cid} paused",
                    detail={"campaign_id": cid, "lead_id": lead_id})
            cat_map = {str(k): v for k, v in (marks.get("cat_map") or {}).items()}
            # legacy shape: category_set was a list of cids set to Call Booked
            for cid in marks.get("category_set") or []:
                cat_map.setdefault(str(cid), cfg["call_booked_category_id"])
            cat_targets = [] if target_cat is None else plan_categories(
                memberships, reply_camps.get(email, set()),
                target_cat, cfg["smartlead_client_id"], camp_ids, cat_map)
            for cid in cat_targets:
                if not DRY:
                    sl_json("POST", f"/campaigns/{cid}/leads/{lead_id}/category",
                            sl_key, {"category_id": target_cat,
                                     "pause_lead": pause_wanted})
                counts["categorised"] += 1
                cat_map[str(cid)] = target_cat
                rec("category_set", email, "notion->smartlead",
                    before=row["status"], after=f"campaign {cid} -> category {target_cat}",
                    detail={"campaign_id": cid, "lead_id": lead_id,
                            "category_id": target_cat})
            upsert_state(client, email, {
                "source": st.get("source") or "notion",
                "notion_page_id": row["page_id"], "booked_at": row["edited"],
                "smartlead_lead_id": str(lead_id),
                "campaigns_paused": {**marks,
                                     "paused": sorted(already_paused | set(to_pause)),
                                     "cat_map": cat_map,
                                     "done_for": row["status"]}})
        except Exception as e:  # noqa: BLE001 — one bad lead must not kill the run
            counts["errors"] += 1
            rec("error_forward", email, "notion->smartlead", detail={"error": str(e)[:300]})
            log(f"[{client}] ERROR forward {email}: {e}")

    # -- REVERSE: Smartlead categories / Calendly meetings -> Notion status
    sl_targets: dict[str, tuple] = {}  # email -> (target status, has_positive)
    auto_create = set(cfg.get("auto_create_categories") or [])
    newest_evidence: dict[str, str] = {}  # email -> latest replied_at seen

    def offer(email: str, category_name: str, seen_at: str | None = None):
        target = cfg["reverse_map"].get(category_name)
        if not target:
            return
        email = email.strip().lower()
        if seen_at and seen_at > newest_evidence.get(email, ""):
            newest_evidence[email] = seen_at
        prev_target, prev_pos = sl_targets.get(email, (None, False))
        best = target if rank_of(target, cfg) > rank_of(prev_target, cfg) else prev_target
        sl_targets[email] = (best, prev_pos or category_name in auto_create)

    for r in reply_rows:
        if r.get("email") and r.get("category"):
            offer(r["email"], r["category"], r.get("replied_at"))
    for r in server.sb_get_all(
            f"meetings?client_id=eq.{cfg['supabase_client_id']}"
            "&select=raw_attendee_email") or []:
        if r.get("raw_attendee_email"):
            offer(r["raw_attendee_email"], "Call Booked")
    log(f"[{client}] smartlead-derived targets: {len(sl_targets)}")

    last_pushed = {}
    for email, st in state.items():
        marks = state_marks(st)
        # legacy rows predate last_pushed — they were booked-tier pushes
        last_pushed[email] = marks.get("last_pushed") or "Meeting-Booked"

    updates, creates, unmatched_booked, unmatched_lower, noops = plan_reverse(
        sl_targets, notion_by_email, last_pushed, cfg)
    counts["unmatched_lower"] = unmatched_lower
    for email, page_id, ptype, current, target in updates:
        try:
            if not DRY:
                notion_set_status(page_id, cfg["status_prop"], ptype, target)
            counts["notion_updated"] += 1
            rec("notion_status_update", email, "smartlead->notion",
                before=current, after=target, detail={"page_id": page_id})
            marks = state_marks(state.get(email) or {})
            upsert_state(client, email, {
                "source": (state.get(email) or {}).get("source") or "smartlead",
                "notion_page_id": page_id,
                "booked_at": datetime.now(timezone.utc).isoformat(),
                "campaigns_paused": {**marks, "last_pushed": target}})
        except Exception as e:  # noqa: BLE001
            counts["errors"] += 1
            rec("error_reverse", email, "smartlead->notion", detail={"error": str(e)[:300]})
            log(f"[{client}] ERROR reverse {email}: {e}")
    # Clients with a live Make createAPage writer (make_first_grace) give Make
    # first right of creation — we only backstop leads it MISSED (evidence >2h
    # old). Clients with no Make writer get created immediately: waiting would
    # just delay the row for nothing (the Touchpoint lesson, 2026-08-17).
    grace_cutoff = (datetime.now(timezone.utc).timestamp() - 2 * 3600
                    if cfg.get("make_first_grace") else float("inf"))
    deferred = 0
    for email, target in creates:
        if (state.get(email) or {}).get("source") == "smartlead_created":
            continue  # created on an earlier pass (row hidden/deleted since) — once only
        seen = newest_evidence.get(email)
        try:
            fresh = seen and datetime.fromisoformat(
                seen.replace("Z", "+00:00")).timestamp() > grace_cutoff
        except ValueError:
            fresh = False
        if fresh:
            deferred += 1  # Make's webhook is likely still in flight — next run
            continue
        try:
            meta = {}
            detail_rows = server.sb(
                "GET",
                f"replies?email=eq.{urllib.parse.quote(email)}"
                f"&smartlead_campaign_id=in.({','.join(map(str, sorted(camp_ids)))})"
                "&select=reply_body,replied_at,smartlead_campaign_id"
                "&order=replied_at.desc&limit=1") or []
            if detail_rows:
                d = detail_rows[0]
                meta["reply_body"] = d.get("reply_body")
                meta["replied_at"] = d.get("replied_at")
                name_rows = server.sb(
                    "GET", "campaign_scorecard?smartlead_campaign_id="
                    f"eq.{d['smartlead_campaign_id']}&select=name&limit=1") or []
                if name_rows:
                    meta["campaign_name"] = name_rows[0].get("name")
            enrich_meta(meta, cfg, email, sl_key, camp_ids,
                        detail_rows[0]["smartlead_campaign_id"] if detail_rows else None)
            page_id = "" if DRY else notion_create_row(cfg, email, target, meta)
            counts["notion_created"] += 1
            rec("notion_row_created", email, "smartlead->notion", after=target,
                detail={"page_id": page_id, "campaign": meta.get("campaign_name")})
            upsert_state(client, email, {
                "source": "smartlead_created", "notion_page_id": page_id,
                "booked_at": meta.get("replied_at")
                or datetime.now(timezone.utc).isoformat(),
                "campaigns_paused": {"last_pushed": target}})
        except Exception as e:  # noqa: BLE001
            counts["errors"] += 1
            rec("error_create", email, "smartlead->notion", detail={"error": str(e)[:300]})
            log(f"[{client}] ERROR create {email}: {e}")
    for email in unmatched_booked:
        if (state.get(email) or {}).get("source") == "smartlead_unmatched":
            continue  # already on record — don't re-ledger every run
        counts["unmatched_notion"] += 1
        rec("unmatched_no_notion_row", email, "smartlead->notion")
        upsert_state(client, email, {
            "source": "smartlead_unmatched",
            "booked_at": datetime.now(timezone.utc).isoformat(),
            "campaigns_paused": {}})
    counts["creates_deferred"] = deferred
    log(f"[{client}] reverse: {len(updates)} updates, {len(creates)} creates "
        f"({deferred} deferred to Make's grace window), {noops} noops, "
        f"{unmatched_lower} lower-tier no-row")

    # -- TEMPLATE BACKSTOP: rows created by Make's webhook arrive with properties
    # only — give recent untemplated rows the body template (capped per run).
    from datetime import timedelta
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    swept = 0
    for email, row in sorted(notion_by_email.items()):
        if swept >= 15:
            break
        if (row.get("created") or "") < recent_cutoff:
            continue
        marks = state_marks(state.get(email) or {})
        if marks.get("templated"):
            continue
        try:
            kids = server.http_json(
                "GET", f"{NOTION_BASE}/blocks/{row['page_id']}/children?page_size=8",
                _notion_headers())
            texts = " ".join(
                "".join(t.get("plain_text", "") for t in
                        (b.get(b.get("type", ""), {}) or {}).get("rich_text", []))
                for b in (kids or {}).get("results", []))
            if "Lead Snapshot" in texts:
                pass  # already templated (e.g. by the backfill or a create)
            else:
                detail = server.sb(
                    "GET", f"replies?email=eq.{urllib.parse.quote(email)}"
                    f"&smartlead_campaign_id=in.({','.join(map(str, sorted(camp_ids)))})"
                    "&select=reply_body,replied_at,smartlead_campaign_id"
                    "&order=replied_at.desc&limit=1") or []
                meta = {}
                if detail:
                    meta["reply_body"] = detail[0].get("reply_body")
                    meta["replied_at"] = detail[0].get("replied_at")
                enrich_meta(meta, cfg, email, sl_key, camp_ids,
                            detail[0]["smartlead_campaign_id"] if detail else None)
                if not DRY:
                    server.http_json("PATCH",
                                     f"{NOTION_BASE}/blocks/{row['page_id']}/children",
                                     _notion_headers(),
                                     {"children": template_blocks(email, meta)})
                    if row.get("has_frp"):  # keep email text out of properties
                        server.http_json("PATCH", f"{NOTION_BASE}/pages/{row['page_id']}",
                                         _notion_headers(),
                                         {"properties": {"Full-Reply": {"rich_text": []}}})
                counts["templated"] = counts.get("templated", 0) + 1
                rec("body_templated", email, "smartlead->notion",
                    detail={"page_id": row["page_id"]})
            swept += 1
            upsert_state(client, email, {
                "source": (state.get(email) or {}).get("source") or "notion",
                "notion_page_id": row["page_id"],
                "campaigns_paused": {**marks, "templated": True}})
        except Exception as e:  # noqa: BLE001 — one bad page must not kill the run
            counts["errors"] += 1
            log(f"[{client}] ERROR template-backstop {email}: {e}")

    rec("run_summary", detail={**counts, "full_verify": full_verify,
                               "notion_rows": len(notion_by_email),
                               "forward_rows": len(fwd_rows),
                               "sl_targets": len(sl_targets)})
    ledger(entries)
    return counts


def main() -> int:
    if not server.KEYS.get("NOTION_API_KEY"):
        log("NOTION_API_KEY missing — booked-sync idle (add it to the navreo-secrets "
            "env group; see booked-sync-orchestrator skill Step 0). Exiting 0.")
        return 0
    raw = json.loads(CONFIG_PATH.read_text())
    defaults = raw.pop("_defaults", {})
    only = {c.strip() for c in os.environ.get("BOOKED_SYNC_ONLY", "").split(",") if c.strip()}
    cfgs = {}
    for client, entry in raw.items():
        if only and client not in only:
            continue
        merged = {**defaults, **entry}
        if merged.get("notion_database_id", "").startswith("PENDING"):
            log(f"[{client}] skipped — notion_database_id not provisioned yet")
            continue
        cfgs[client] = merged
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
