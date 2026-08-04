#!/usr/bin/env python3
"""Server-side campaign registration + auto-reconcile.

Why this exists
---------------
Creating a campaign in Smartlead is only half the job. For the tool to show it
with its provenance — the Leads tab, the Sources list, the "pull more" button —
three records have to exist in Supabase:

    campaigns          the row the cockpit lists
    campaign_drafts    doc id `camp-sl-<smartlead_id>`, joins draft -> Smartlead
    sources            doc with campaign_id = the draft id, carrying the
                       provenance, the prospects, and the pool counts

That wiring used to live only client-side: a skill (or an ad-hoc Smartlead
build) had to call ~/.claude/skills/_shared/campaign_register.register(), and a
Stop hook (campaign-register-guard.sh) was the backstop. But a session that
built a campaign and never ran register() left a campaign the tool could not
explain — no Source on the Leads tab, no pull-more pool. That is exactly what
happened to five campaigns created 2026-08-03.

Bjion, 2026-08-03: "Update this so it happens automatically from server-side."

So registration now also happens from the server, with no session in the loop:
`reconcile()` runs on the daily cron, lists every Smartlead campaign across
every enabled workspace, and registers any that the tool doesn't yet know
about — deriving real prospect rows straight from the campaign's own leads
export. The client-side helper and the Stop hook stay as the belt to this
server-side braces; whichever notices an unregistered campaign first wins, and
register() is idempotent so a double-register is a no-op upsert.

This module imports `server` for its Supabase (`server.sb`) and Smartlead
(`server.SMARTLEAD_BASE`, `server.ws_*`, `server._smartlead_get_retry`) layers,
so it shares the app's keys, retries and rate-limit pacing. It performs NO
Smartlead writes — only GETs from Smartlead and upserts to the tool's own
Supabase tables. It never sends anything.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

# What actually feeds a campaign. The first four are SIGNALS — something happened
# out there and the source goes back daily for the next lead; the tool arms a live
# toggle and a daily pull for them. `fixed_list` is a one-off pull that never
# refreshes. A server reconcile can never prove a live signal after the fact, so
# every campaign it adopts is registered as a fixed_list: honest provenance, no
# armed signal toggle, no daily re-pull. See [[sources-fixed-list-type]].
MECHANISMS = ("hiring", "engagement", "followers", "lookalike", "new_exec", "news", "fixed_list")

# Smartlead auto-creates a companion campaign per positive-reply category
# ("Meeting Request", "Interested Reply", ...). They are subsequences, not
# sourced campaigns, and have no list or pool to register. Same filter the
# Stop-hook guard and the signal-launch retro use.
SUBSEQUENCE_NAMES = {
    "meeting request", "interested reply", "information request",
    "out of office", "wrong person", "not interested", "do not contact",
}

# Only adopt campaigns created within this rolling window. The reconcile is a
# safety net for freshly-built campaigns that escaped client-side registration —
# NOT a mass backfill of every campaign that predates the registration rule.
# Comfortably wider than the 3-hourly cron gap so nothing slips between ticks.
RECONCILE_WINDOW_H = 72

# Cap on prospect rows embedded in a source doc. read_drafts() loads every
# source's full doc (prospects included) on the hot Leads path, so an 11k-lead
# campaign must not embed 11k rows. The TRUE lead count is still recorded in the
# pool counts and params; the embedded rows are a real head-of-list sample.
PROSPECT_EMBED_CAP = 1000


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# ── the three writes ───────────────────────────────────────────────────────
def register(smartlead_campaign_id, name, client="navreo", *, mechanism="fixed_list",
             source_name=None, list_id=None, prospects=None, pull_spec=None,
             pool_total=None, pool_pulled=None, icebreaker=None, goal=None,
             status="ACTIVE", workspace=None, dm_titles=None, geos=None,
             sizes=None, industries=None, repull_spec=None, client_name=None):
    """Write campaigns + campaign_drafts + sources for one Smartlead campaign.

    Idempotent: every write is an upsert by id, so re-running is a no-op. The
    server-side twin of ~/.claude/skills/_shared/campaign_register.register(),
    routed through server.sb() instead of the skills' navreo_db.

    Counts: when pool_total/pool_pulled are given they are the source of truth
    for the displayed lead count (so a capped prospect sample still reports the
    campaign's true size); otherwise len(prospects) is used.
    """
    if mechanism not in MECHANISMS:
        raise ValueError(f"mechanism must be one of {MECHANISMS}, got {mechanism!r}. "
                         "A one-off pulled list is 'fixed_list', not a signal name.")
    sid = str(smartlead_campaign_id)
    draft_id = f"camp-sl-{sid}"
    src_id = f"src-{sid}"
    prospects = prospects or []
    workspace = workspace or client
    # displayed count: true pool if known, else the embedded rows
    count = int(pool_pulled) if pool_pulled is not None else len(prospects)

    # campaigns.client_id FKs the clients table. A brand that lives inside the
    # navreo Smartlead account (ThunderBird) has no clients row until its first
    # campaign, so the FK would reject the row and the campaign would vanish from
    # the cockpit while its draft/source (no such FK) survived — a silent split.
    # Self-heal it: the server path owns making a recognised brand real.
    _ensure_client(client, client_name)

    # 1 — the campaigns row the cockpit lists
    server.sb("POST", "campaigns",
              [{"workspace": workspace, "smartlead_campaign_id": int(sid),
                "client_id": client, "name": name, "status": status,
                "created_at_smartlead": _now()}],
              prefer="resolution=merge-duplicates,return=minimal")

    # 1b — seed the scorecard row NOW (signals-campaign-visibility, 2026-08-04).
    # The campaigns page can only OPEN a campaign the scorecard knows (STATE.byId
    # falls back to ghostRow, which reads the scorecard), and the scorecard sync
    # is hourly — so without this seed a freshly registered campaign is invisible
    # on the page for up to an hour. Zeros are honest for a new campaign; the
    # hourly sync overwrites them with Smartlead's own numbers.
    server.sb("POST", "campaign_scorecard?on_conflict=smartlead_campaign_id",
              [{"smartlead_campaign_id": int(sid), "name": name, "status": status,
                "workspace": workspace, "client": client_name or client,
                "sent": 0, "replied": 0, "positives": 0, "bounced": 0,
                "completed": 0, "total": len(prospects),
                "updated_at": _now()}],
              prefer="resolution=merge-duplicates,return=minimal")

    # 2 — the draft doc joining the tool's campaign to Smartlead
    icp = {"geos": geos or [], "sizes": sizes or [], "titles": dm_titles or [],
           "domains": [], "excludes": [], "keywords": "", "industries": industries or []}
    draft = {"id": draft_id, "name": name, "client_id": client,
             "goal": goal or "", "paused": status != "ACTIVE", "platform": "smartlead",
             "autopilot": False, "smartlead_campaign_id": sid,
             "destination": {"smartlead_campaign_id": sid, "platform": "smartlead"},
             "created_at": _now(), "total_matched": count, "icp": icp,
             "sources": [{"dms": count, "idea": source_name or name,
                          "params": pull_spec or {}, "source_id": src_id,
                          "list_id": list_id}]}
    server.sb("POST", "campaign_drafts?on_conflict=id",
              [{"id": draft_id, "doc": draft}],
              prefer="resolution=merge-duplicates,return=minimal")

    # 3 — the source doc: provenance + what is left to pull
    left = None
    if pool_total is not None and pool_pulled is not None:
        left = max(int(pool_total) - int(pool_pulled), 0)
    params = dict(pull_spec or {})
    if repull_spec:
        params["repull"] = repull_spec
    src = {"id": src_id, "campaign_id": draft_id, "client_id": client,
           "name": source_name or name, "type": mechanism, "mechanism": mechanism,
           "list_id": list_id, "total": count,
           "signals_found": pool_pulled if pool_pulled is not None else count,
           "companies_scanned": pool_pulled if pool_pulled is not None else count,
           "left_for_next_run": left,
           "window_exhausted": left == 0 if left is not None else False,
           "imported_at": _now(), "icebreaker": icebreaker or "",
           "titles": dm_titles or [],
           "config": {"countries": geos or [], "headcount": sizes or [],
                      "industries": industries or [], "keywords": ""},
           "params": params, "prospects": prospects}
    # `last_pull` is deliberately omitted for a reconciled import. sources_for_ui
    # overrides a pulled source's `total` with its accumulated signal_leads count;
    # these leads live in Smartlead, not signal_leads, so a `last_pull` would make
    # the Sources card read "0 leads" instead of the true imported count. An
    # import records `imported_at` for provenance instead of a live pull time.
    if mechanism == "fixed_list":
        src["active"] = False  # nothing to keep running; the daily pull skips it

    server.sb("POST", "sources?on_conflict=id",
              [{"id": src_id, "doc": src}],
              prefer="resolution=merge-duplicates,return=minimal")

    return {"campaign": sid, "draft": draft_id, "source": src_id,
            "campaign_url": f"https://navreo-signals.onrender.com/app/campaigns.html#/c/{sid}"}


def is_registered(smartlead_campaign_id) -> bool:
    """True when the draft AND at least one source exist for this Smartlead id.
    Same contract as the skills helper's is_registered."""
    sid = str(smartlead_campaign_id)
    draft = server.sb("GET", f"campaign_drafts?select=id&id=eq.camp-sl-{sid}") or []
    if not draft:
        return False
    srcs = server.sb("GET", "sources?select=doc->>campaign_id&limit=2000") or []
    want = f"camp-sl-{sid}"
    return any((s or {}).get("campaign_id") == want for s in srcs)


# ── deriving real data from a campaign's own leads export ───────────────────
def _brand_label(name: str):
    """The display label for a navreo-account campaign name, off the server's
    ONE brand authority (_SHARED_WS_CLIENTS, first match wins) — the same table
    the scorecard's client column reads, so registration and the campaigns-page
    label can never disagree. Returns None when the name matches no brand."""
    n = (name or "").lower()
    for needle, label in server._SHARED_WS_CLIENTS:
        if needle in n:
            return label
    return None


def _client_for(name: str, workspace: str) -> tuple[str, str]:
    """(client_id, display label) a campaign belongs to. A connected client
    workspace labels as itself; a navreo-account campaign is matched by name
    against the brand authority so a 'ThunderBird …' campaign is ThunderBird,
    not navreo — see [[navreo-own-vs-client-campaigns]]. The clients-table id is
    the label lowercased (navreo, thunderbird, qwintiq …). An unmatched
    navreo-account campaign falls back to navreo (a valid FK; the scorecard
    still labels it by its own rule)."""
    ws = (workspace or "navreo").lower()
    if ws != "navreo":
        for w in server.ws_all():
            if w.get("id") == ws:
                return ws, (w.get("display_label") or w.get("name") or ws.title())
        return ws, ws.title()
    label = _brand_label(name)
    if label and label != "Acme":  # never register a demo brand from a real campaign
        return label.lower(), label
    return "navreo", "Navreo"


def _ensure_client(client_id: str, client_name: str | None) -> None:
    """Upsert a minimal clients row (id + name) if it doesn't exist, so
    campaigns.client_id's FK is always satisfiable. Idempotent; best-effort."""
    if not client_id:
        return
    existing = server.sb("GET", f"clients?select=id&id=eq.{client_id}&limit=1") or []
    if existing:
        return
    server.sb("POST", "clients?on_conflict=id",
              [{"id": client_id, "name": client_name or client_id.title()}],
              prefer="resolution=merge-duplicates,return=minimal")


# Known lead providers, matched as a substring of the lead's custom_fields.Source.
# Free-text Source values ("Head of Sales and Apollo") that happen to name a
# provider still resolve to the clean token; ones that name none resolve to None
# rather than polluting the provenance note with a title fragment.
_PROVIDERS = ("ai_ark", "aiark", "ai ark", "prospeo", "listmint", "clay", "apollo",
              "getleads", "blitz", "ocean", "theirstack", "heyreach", "trigify")


def _provider_hint(raw) -> str | None:
    low = str(raw or "").strip().lower()
    if not low:
        return None
    for p in _PROVIDERS:
        if p in low:
            return p.replace("aiark", "ai_ark").replace("ai ark", "ai_ark")
    return None


def _prospects_from_leads(campaign_id, sl_key: str, cap: int = PROSPECT_EMBED_CAP):
    """Page /campaigns/{id}/leads and map each lead to a prospect row. Returns
    (prospects, total_leads, source_hint). Stops embedding once `cap` rows are
    collected but still reports the campaign's TRUE total_leads (from the API's
    own counter) so the pool counts stay honest for a capped sample."""
    prospects: list = []
    total_leads = None
    source_hint = None
    offset = 0
    while True:
        url = (f"{server.SMARTLEAD_BASE}/campaigns/{campaign_id}/leads"
               f"?api_key={sl_key}&offset={offset}&limit=100")
        page = server._smartlead_get_retry(url) or {}
        if total_leads is None:
            try:
                total_leads = int(page.get("total_leads"))
            except (TypeError, ValueError):
                total_leads = None
        rows = page.get("data") or []
        if not rows:
            break
        for row in rows:
            lead = row.get("lead") or {}
            email = (lead.get("email") or "").strip()
            cf = lead.get("custom_fields") or {}
            if source_hint is None:
                source_hint = _provider_hint(cf.get("Source"))
            if len(prospects) < cap:
                first = (lead.get("first_name") or "").strip()
                last = (lead.get("last_name") or "").strip()
                li = (lead.get("linkedin_profile") or cf.get("LinkedIn") or "").strip()
                domain = (lead.get("website") or "").strip()
                prospects.append({
                    "full_name": (f"{first} {last}").strip() or None,
                    "first_name": first or None, "last_name": last or None,
                    "email": email or None,
                    "title": (cf.get("Title") or "").strip() or None,
                    "company": (lead.get("company_name") or "").strip() or None,
                    "domain": domain or None,
                    "linkedin": li or None,
                    "country": (lead.get("location") or "").strip() or None,
                    "icebreaker": (cf.get("Icebreaker") or "").strip() or None,
                })
        # once we have the cap AND the true total, no need to page further
        if len(prospects) >= cap and total_leads is not None:
            break
        if len(rows) < 100:
            break
        offset += 100
        time.sleep(0.25)  # pace pagination under Smartlead's 200/min cap
    if total_leads is None:
        total_leads = len(prospects)
    return prospects, total_leads, source_hint


def register_from_smartlead(campaign, workspace: str, sl_key: str) -> dict:
    """Adopt one live Smartlead campaign into the tool with real data derived
    from its own leads export. `campaign` is a /campaigns row dict."""
    cid = campaign.get("id")
    name = campaign.get("name") or f"Smartlead campaign {cid}"
    client, client_name = _client_for(name, workspace)
    prospects, total, hint = _prospects_from_leads(cid, sl_key)
    # a representative icebreaker for the source card, if any lead carried one
    icebreaker = next((p["icebreaker"] for p in prospects if p.get("icebreaker")), "")
    pull_spec = {
        "origin": "smartlead_reconcile",
        "reconstructed_at": _now(),
        "note": ("Registered server-side from the campaign's Smartlead leads export; "
                 "no original pull spec was recorded, so the true source pool is "
                 "unknown and the pulled count is used as the pool total."),
        "prospects_total": total,
        "prospects_embedded": len(prospects),
    }
    if hint:
        pull_spec["lead_source_hint"] = hint  # e.g. custom_fields.Source == "ai_ark"
    sl_status = (campaign.get("status") or "").upper()
    status = "ACTIVE" if sl_status in ("ACTIVE", "START", "STARTED", "") else "DRAFTED"
    return register(
        smartlead_campaign_id=cid, name=name, client=client,
        mechanism="fixed_list", source_name=name, list_id=None,
        prospects=prospects, pull_spec=pull_spec,
        pool_total=total, pool_pulled=total,  # pool unknown -> pulled == total
        icebreaker=icebreaker, status=status, workspace=workspace,
        client_name=client_name,
    )


# ── the reconcile the cron calls ────────────────────────────────────────────
def _is_subsequence(campaign: dict) -> bool:
    """A Smartlead subsequence, not a real sourced campaign.

    Smartlead sets parent_campaign_id on every subsequence, so that is the
    authoritative test. The name check is only a fallback for a record that
    somehow reports no parent — and it matches by PREFIX, because Smartlead
    suffixes renamed subsequences ("Interested Reply (Sales tech adoption)"
    is not the exact string "interested reply"; campaign 3758781, 2026-08-04).
    """
    if campaign.get("parent_campaign_id"):
        return True
    name = (campaign.get("name") or "").strip().lower()
    return any(name.startswith(s) for s in SUBSEQUENCE_NAMES)


def _within_window(created_at: str, cutoff: dt.datetime) -> bool:
    if not created_at:
        return False
    try:
        when = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when >= cutoff


def reconcile(window_h: int = RECONCILE_WINDOW_H, only_ids=None) -> dict:
    """Register every recently-created Smartlead campaign the tool doesn't know
    about, across every enabled workspace. Idempotent and best-effort: one bad
    campaign never aborts the rest. Returns a summary dict.

    `only_ids` — restrict to these Smartlead campaign ids and ignore the age
    window (used for a targeted backfill). Pass ints or strs.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_h)
    only = {str(x) for x in only_ids} if only_ids else None
    summary = {"ts": _now(), "checked": 0, "registered": [], "skipped": 0,
               "errors": [], "workspaces": []}

    for w in server.ws_enabled():
        wid = w.get("id")
        wkey = server.ws_key(wid)
        if not wkey:
            summary["workspaces"].append({"id": wid, "note": "no api key"})
            continue
        camps = server._sl_campaigns_for_ws(wkey)
        if camps is None:
            summary["errors"].append(f"{wid}: /campaigns unavailable")
            summary["workspaces"].append({"id": wid, "note": "campaigns unavailable"})
            continue
        ws_reg = 0
        for c in camps:
            cid = c.get("id")
            name = c.get("name") or ""
            if only is not None:
                if str(cid) not in only:
                    continue
            else:
                if _is_subsequence(c):
                    continue
                if not _within_window(c.get("created_at"), cutoff):
                    continue
            summary["checked"] += 1
            try:
                if is_registered(cid):
                    summary["skipped"] += 1
                    continue
                register_from_smartlead(c, wid, wkey)
                summary["registered"].append(
                    {"id": str(cid), "name": name[:80],
                     "client": _client_for(name, wid)[0], "workspace": wid})
                ws_reg += 1
            except Exception as e:  # noqa: BLE001 — one bad campaign must not kill the run
                summary["errors"].append(f"{cid}: {type(e).__name__}: {str(e)[:160]}")
        summary["workspaces"].append({"id": wid, "registered": ws_reg,
                                      "campaigns_seen": len(camps)})

    # durable, queryable record in the same table run_daily's summaries land in
    try:
        server.sb("POST", "signal_cron_runs",
                  {"summary": {"kind": "campaign_register_reconcile",
                               "ok": not summary["errors"],
                               "ts": summary["ts"],
                               "registered": len(summary["registered"]),
                               "checked": summary["checked"],
                               "errors": summary["errors"][:10]}})
    except Exception:  # noqa: BLE001 — observability must never block the reconcile
        pass
    return summary


if __name__ == "__main__":
    import json
    ids = [a for a in sys.argv[1:] if a.isdigit()]
    out = reconcile(only_ids=ids or None)
    print(json.dumps(out, indent=2))
