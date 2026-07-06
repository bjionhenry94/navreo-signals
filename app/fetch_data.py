#!/usr/bin/env python3
"""Read-only data collector for the Navreo Campaign Management prototype.

Pulls real data into app/data/*.json for the static pages to render.
STRICTLY GET-only against the Smartlead API — never POST/PUT/DELETE
(sequence saves via API reset variant stats; this script cannot do that
by construction: there is no write helper).

Sources:
  - Smartlead API (key: SMARTLEAD_API_KEY in ~/.navreo-keys.env)
  - ~/.claude/skills/lilly-theirstack-setup/briefs/*.json   (hiring signals)
  - ~/.claude/skills/lilly-signal/routines/*.json           (signal routines)
  - ~/.navreo-cache/lilly-dm-runs.log                       (DM-finder runs)
  - ~/.navreo-cache/lilly-icebreaker-v2-runs.log            (icebreaker runs)
  - ./sl_audit_issues.json                                  (lead hygiene audit)

Usage:  python3 app/fetch_data.py [--detail-cap N]
"""

import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

BASE = "https://server.smartlead.ai/api/v1"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
HOME = Path.home()

RATE_SLEEP = 0.35  # ~170 req/min, under the 200/min cap
DETAIL_CAP = 20    # campaigns that get sequences/leads/daily pulls
LEAD_SAMPLE_LIMIT = 100

MERGE_VARS_OF_INTEREST = [
    "Icebreaker", "Why", "Pain", "CaseStudy", "HowWeCanHelp", "Offer",
]


def load_api_key() -> str:
    env_file = HOME / ".navreo-keys.env"
    for line in env_file.read_text().splitlines():
        m = re.match(r"^(?:export\s+)?SMARTLEAD_API_KEY=(\S+)", line.strip())
        if m:
            return m.group(1).strip("\"'")
    sys.exit("SMARTLEAD_API_KEY not found in ~/.navreo-keys.env")


API_KEY = load_api_key()


def get(endpoint: str, params: dict | None = None):
    """GET-only HTTP helper with rate-limit pacing and one retry."""
    params = dict(params or {})
    params["api_key"] = API_KEY
    url = f"{BASE}{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in (1, 2):
        try:
            time.sleep(RATE_SLEEP)
            req = urllib.request.Request(url, headers={"User-Agent": "navreo-prototype-collector/1.0 (curl-compatible)"})
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001 — retry once on any transport error
            if attempt == 2:
                print(f"  ! GET {endpoint} failed: {e}")
                return None
            time.sleep(3)
    return None


def as_list(data, *keys) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def to_int(val) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def positive_count(stats: dict) -> int:
    for field in ("positive_reply_count", "positiveReplyCount",
                  "interested_count", "interestedCount", "interested",
                  "campaign_lead_stats.interested"):
        val = stats.get(field)
        if val is not None:
            return to_int(val)
    nested = stats.get("campaign_lead_stats") or {}
    return to_int(nested.get("interested"))


# ──────────────────────────────────────────────────────────────────────────
# Smartlead pulls
# ──────────────────────────────────────────────────────────────────────────

def fetch_campaigns() -> list[dict]:
    print("Campaigns list...")
    campaigns, offset = [], 0
    while True:
        page = as_list(get("/campaigns", {"limit": 100, "offset": offset}),
                       "data", "campaigns", "result")
        campaigns.extend(page)
        if len(page) < 100:
            break
        offset += 100
    print(f"  {len(campaigns)} campaigns")
    return campaigns


def fetch_analytics(campaign_id: int) -> dict:
    data = get(f"/campaigns/{campaign_id}/analytics") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    return data if isinstance(data, dict) else {}


def normalise_analytics(raw: dict) -> dict:
    return {
        "sent": to_int(raw.get("sent_count") or raw.get("sent")),
        "opens": to_int(raw.get("open_count") or raw.get("opened") or raw.get("unique_open_count")),
        "replies": to_int(raw.get("reply_count") or raw.get("replied")),
        "positives": positive_count(raw),
        "bounces": to_int(raw.get("bounce_count") or raw.get("bounced")),
        "unsubscribes": to_int(raw.get("unsubscribed_count") or raw.get("unsubscribed")),
        "total_leads": to_int(raw.get("total_count") or raw.get("campaign_lead_stats", {}).get("total") if isinstance(raw.get("campaign_lead_stats"), dict) else raw.get("total_count")),
        "completed_leads": to_int((raw.get("campaign_lead_stats") or {}).get("completed") if isinstance(raw.get("campaign_lead_stats"), dict) else 0),
    }


def fetch_campaign_detail(campaign_id: int) -> dict:
    detail: dict = {}

    # NOTE the GET/SAVE asymmetry from the lilly-bot audit: GET returns
    # `sequence_variants` + `delayInDays` (camelCase); the save shape is
    # different — and irrelevant here, this collector never saves.
    sequences = as_list(get(f"/campaigns/{campaign_id}/sequences"), "data", "sequences")
    variant_index = {}  # seq_variant_id -> (seq_number, label)
    detail["sequences"] = []
    for s in sequences:
        seq_num = to_int(s.get("seq_number") or 1)
        delay = s.get("seq_delay_details") or {}
        variants = []
        for v in (s.get("sequence_variants") or []):
            variant_index[v.get("id")] = (seq_num, str(v.get("variant_label") or "A"))
            variants.append({
                "id": v.get("id"),
                "label": str(v.get("variant_label") or "A"),
                "subject": v.get("subject") or "",
                "body": v.get("email_body") or "",
                "distribution_pct": v.get("variant_distribution_percentage"),
            })
        detail["sequences"].append({
            "seq_number": seq_num,
            "seq_delay_days": to_int(delay.get("delayInDays") if isinstance(delay, dict) else delay),
            "variants": variants,
        })

    # Per-step stats (incl. positive_reply_count) via sequence-analytics
    step_rows = as_list(get(f"/campaigns/{campaign_id}/sequence-analytics",
                            {"start_date": "2024-01-01",
                             "end_date": date.today().isoformat()}), "data")
    seq_id_to_num = {s.get("id"): to_int(s.get("seq_number") or i + 1)
                     for i, s in enumerate(sequences)}
    detail["step_stats"] = [
        {
            "seq_number": seq_id_to_num.get(r.get("email_campaign_seq_id"), i + 1),
            "sent": to_int(r.get("sent_count")),
            "opens": to_int(r.get("open_count")),
            "replies": to_int(r.get("reply_count")),
            "positives": to_int(r.get("positive_reply_count")),
            "bounces": to_int(r.get("bounce_count")),
        }
        for i, r in enumerate(step_rows)
    ]

    # Per-variant stats recovered by aggregating /statistics rows
    # (API sequence saves reset native variant stats — this is the recovery
    # path the smartlead-api-realities memory documents).
    agg: dict = {}
    daily: dict = {}
    offset = 0
    while offset < 1000:
        page = get(f"/campaigns/{campaign_id}/statistics",
                   {"limit": 100, "offset": offset})
        rows = as_list(page, "data")
        for r in rows:
            vid = r.get("seq_variant_id")
            a = agg.setdefault(vid, {"sent": 0, "opens": 0, "replies": 0, "bounces": 0})
            a["sent"] += 1
            a["opens"] += 1 if to_int(r.get("open_count")) else 0
            a["replies"] += 1 if r.get("reply_time") else 0
            a["bounces"] += 1 if r.get("is_bounced") else 0
            # daily series comes free from the same rows
            if r.get("sent_time"):
                day = daily.setdefault(r["sent_time"][:10], {"sent": 0, "replies": 0})
                day["sent"] += 1
            if r.get("reply_time"):
                day = daily.setdefault(r["reply_time"][:10], {"sent": 0, "replies": 0})
                day["replies"] += 1
        total = to_int((page or {}).get("total_stats")) if isinstance(page, dict) else 0
        offset += 100
        if len(rows) < 100 or offset >= total:
            break
    detail["variant_stats"] = [
        {
            "seq_number": variant_index.get(vid, (0, "?"))[0],
            "label": variant_index.get(vid, (0, "?"))[1],
            "variant_id": vid,
            **counts,
        }
        for vid, counts in agg.items()
    ]
    detail["variant_stats_sampled"] = offset  # rows scanned (cap 1000)

    leads_raw = as_list(get(f"/campaigns/{campaign_id}/leads",
                            {"limit": LEAD_SAMPLE_LIMIT, "offset": 0}), "data")
    sample, fill_counts = [], {}
    for row in leads_raw:
        lead = row.get("lead") or row
        cf = lead.get("custom_fields") or {}
        if isinstance(cf, str):
            try:
                cf = json.loads(cf)
            except ValueError:
                cf = {}
        for key in set(list(cf.keys()) + MERGE_VARS_OF_INTEREST):
            filled = bool(str(cf.get(key) or "").strip())
            tot, ok = fill_counts.get(key, (0, 0))
            fill_counts[key] = (tot + 1, ok + (1 if filled else 0))
        sample.append({
            "first_name": lead.get("first_name") or "",
            "last_name": lead.get("last_name") or "",
            "email": lead.get("email") or "",
            "company": cf.get("company_name") or lead.get("company_name") or "",
            "title": cf.get("Title") or cf.get("title") or cf.get("Position") or "",
            "linkedin": lead.get("linkedin_profile") or cf.get("LinkedIn") or cf.get("linkedin_url") or "",
            "website": lead.get("website") or lead.get("company_url") or "",
            "size": cf.get("CompanySize") or cf.get("Employees") or cf.get("company_size") or "",
            "source": cf.get("Source") or cf.get("Signal") or cf.get("SignalSource") or "",
            "status": row.get("status") or lead.get("status") or "",
            "category": row.get("lead_category_id") or "",
            "custom_fields": {k: cf.get(k) or "" for k in MERGE_VARS_OF_INTEREST if k in cf},
        })
    detail["leads_sample"] = sample[:40]
    detail["lead_sample_size"] = len(leads_raw)
    detail["fill_rates"] = {
        k: round(100 * ok / tot) for k, (tot, ok) in fill_counts.items() if tot
    }

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    detail["daily"] = [
        {"date": d, "sent": v["sent"], "replies": v["replies"]}
        for d, v in sorted(daily.items()) if d >= cutoff
    ]
    return detail


def fetch_email_accounts() -> list[dict]:
    print("Email accounts...")
    accounts, offset = [], 0
    while offset < 15000:
        page = as_list(get("/email-accounts/", {"limit": 100, "offset": offset}),
                       "data", "email_accounts", "result")
        accounts.extend(page)
        if len(page) < 100:
            break
        offset += 100
    print(f"  {len(accounts)} accounts")
    out = []
    for a in accounts:
        warmup = a.get("warmup_details") or {}
        out.append({
            "id": a.get("id"),
            "email": a.get("from_email") or a.get("username") or "",
            "name": a.get("from_name") or "",
            "domain": (a.get("from_email") or "").split("@")[-1],
            "smtp_ok": not a.get("is_smtp_failure", False),
            "imap_ok": not a.get("is_imap_failure", False),
            "daily_limit": to_int(a.get("message_per_day")),
            "warmup_status": (warmup.get("status") or a.get("warmup_status") or "").upper(),
            "warmup_reputation": warmup.get("warmup_reputation") or "",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Local skill state
# ──────────────────────────────────────────────────────────────────────────

def read_theirstack_briefs() -> list[dict]:
    briefs = []
    for f in sorted((HOME / ".claude/skills/lilly-theirstack-setup/briefs").glob("*.json")):
        try:
            b = json.loads(f.read_text())
        except ValueError:
            continue
        briefs.append({
            "brief_id": b.get("brief_id") or f.stem,
            "name": b.get("brief_name") or f.stem,
            "client": b.get("client") or "",
            "signal_type": "hiring",
            "skill": "lilly-theirstack-setup",
            "filter": b.get("filter") or {},
            "dm_titles": (b.get("dm_finder") or {}).get("target_titles") or [],
            "max_dms_per_company": (b.get("dm_finder") or {}).get("max_dms_per_company"),
            "smartlead_campaign_id": (b.get("infrastructure") or {}).get("smartlead_campaign_id"),
            "schedule_cron": b.get("schedule_cron") or "",
            "created_at": b.get("created_at") or "",
        })
    return briefs


def read_signal_routines() -> list[dict]:
    routines = []
    for f in sorted((HOME / ".claude/skills/lilly-signal/routines").glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        sig = r.get("signal") or {}
        routines.append({
            "routine_id": r.get("routine_id") or f.stem,
            "name": sig.get("label") or f.stem,
            "signal_type": sig.get("type") or "",
            "skill": "lilly-signal",
            "source": sig.get("source") or "",
            "dm_titles": (r.get("decision_makers") or {}).get("roles") or [],
            "daily_credit_cap": r.get("daily_credit_cap"),
            "smartlead_campaign_id": (r.get("destination") or {}).get("campaign_id"),
            "schedule_cron": (r.get("schedule") or {}).get("cron") or "",
            "last_run_at": (r.get("state") or {}).get("last_run_at"),
        })
    return routines


def read_run_log(path: Path, kind: str) -> list[dict]:
    if not path.exists():
        return []
    runs = []
    for line in path.read_text().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4:
            runs.append({"kind": kind, "date": parts[0], "fields": parts[1:]})
    return runs


def read_audit_issues() -> dict:
    path = PROJECT_DIR / "sl_audit_issues.json"
    if not path.exists():
        return {"total": 0, "by_type": {}, "by_campaign": {}}
    issues = json.loads(path.read_text())
    by_type, by_campaign = {}, {}
    for i in issues:
        by_type[i.get("fix_type", "?")] = by_type.get(i.get("fix_type", "?"), 0) + 1
        cid = str(i.get("campaign_id", "?"))
        by_campaign[cid] = by_campaign.get(cid, 0) + 1
    return {"total": len(issues), "by_type": by_type, "by_campaign": by_campaign}


# ──────────────────────────────────────────────────────────────────────────
# Notifications (lilly-optimiser rules, computed from the snapshot)
# ──────────────────────────────────────────────────────────────────────────

def build_notifications(campaigns, details, audit) -> list[dict]:
    notes = []
    by_id = {c["id"]: c for c in campaigns}

    # Variant-level rules need sequence data -> detail campaigns only
    for cid, d in details.items():
        c = by_id.get(cid if isinstance(cid, int) else int(cid), {})
        name = c.get("name", f"Campaign {cid}")
        for v in d.get("variant_stats", []):
            if v["sent"] >= 800 and v["replies"] == 0:
                notes.append({
                    "priority": "high", "campaign_id": cid, "campaign": name,
                    "title": f"Replace dead Email {v['seq_number']} variant {v['label']}",
                    "detail": f"Variant {v['label']} has {v['sent']:,} sends with zero replies. "
                              "Offer-discovery rule: a variant is judged at 800 sends; this one is dragging the campaign average.",
                    "rule": "dead-variant (lilly-optimiser)",
                    "numbers": {"sent": v["sent"], "replies": v["replies"]},
                })

    # Campaign-level rules run on analytics -> every ACTIVE campaign
    for c in campaigns:
        if c.get("status") != "ACTIVE":
            continue
        cid, name, a = c["id"], c["name"], c.get("analytics", {})
        sent, positives = a.get("sent", 0), a.get("positives", 0)
        if sent >= 15000 and (positives == 0 or sent / max(positives, 1) > 2500):
            notes.append({
                "priority": "high", "campaign_id": cid, "campaign": name,
                "title": "Whole offer is underperforming",
                "detail": f"{sent:,} emails for {positives} positives "
                          f"({'no positives yet' if positives == 0 else format(round(sent / positives), ',') + ' emails per positive'}). "
                          "Kill-threshold rule: pivot the offer, not the copy.",
                "rule": "kill-threshold (lilly-optimiser)",
                "numbers": {"sent": sent, "positives": positives},
            })
        elif sent >= 1500 and a.get("replies", 0) / max(sent, 1) < 0.005:
            notes.append({
                "priority": "medium", "campaign_id": cid, "campaign": name,
                "title": "Reply rate below deliverability floor",
                "detail": f"{a.get('replies', 0)} replies on {sent:,} sends "
                          f"({100 * a.get('replies', 0) / max(sent, 1):.2f}%) - under the 1% fleet benchmark and under 0.5% raw. "
                          "Check copy angle and inbox placement.",
                "rule": "reply-rate floor (DFY benchmark)",
                "numbers": {"sent": sent, "replies": a.get("replies", 0)},
            })

        total, completed = a.get("total_leads", 0), a.get("completed_leads", 0)
        if total >= 200 and completed / total >= 0.75:
            notes.append({
                "priority": "medium", "campaign_id": cid, "campaign": name,
                "title": "Add leads - campaign is 75%+ through its list",
                "detail": f"{completed:,} of {total:,} leads completed "
                          f"({round(100 * completed / total)}%). 75%-rule: the only recommended action is adding leads.",
                "rule": "email-1 75% (lilly-optimiser)",
                "numbers": {"total": total, "completed": completed},
            })

    for cid, count in sorted(audit.get("by_campaign", {}).items(),
                             key=lambda kv: -kv[1])[:3]:
        c = by_id.get(int(cid)) if cid.isdigit() else None
        notes.append({
            "priority": "low", "campaign_id": cid,
            "campaign": (c or {}).get("name", f"Campaign {cid}"),
            "title": f"{count} lead-hygiene fixes pending",
            "detail": "Name-casing / icebreaker fixes flagged by the lead audit "
                      "(lilly-qa step 5d). Dirty fields propagate into {{Icebreaker}} and {{Why}}.",
            "rule": "field hygiene (lilly-qa 5d)",
            "numbers": {"issues": count},
        })

    order = {"high": 0, "medium": 1, "low": 2}
    notes.sort(key=lambda n: order[n["priority"]])
    return notes


# ──────────────────────────────────────────────────────────────────────────

def main() -> None:
    detail_cap = DETAIL_CAP
    if "--detail-cap" in sys.argv:
        detail_cap = int(sys.argv[sys.argv.index("--detail-cap") + 1])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    raw_campaigns = fetch_campaigns()
    campaigns = []
    for c in raw_campaigns:
        campaigns.append({
            "id": c.get("id"),
            "name": c.get("name") or f"Campaign {c.get('id')}",
            "status": c.get("status") or "",
            "created_at": (c.get("created_at") or "")[:10],
            "analytics": {},
        })

    # analytics for every non-drafted campaign (cheap, 1 call each)
    print("Per-campaign analytics...")
    for c in campaigns:
        if c["status"] in ("ACTIVE", "PAUSED", "COMPLETED", "STOPPED"):
            c["analytics"] = normalise_analytics(fetch_analytics(c["id"]))

    # detail pulls for the most recent ACTIVE campaigns
    active = [c for c in campaigns if c["status"] == "ACTIVE"]
    active.sort(key=lambda c: c["created_at"], reverse=True)
    detail_ids = [c["id"] for c in active[:detail_cap]]
    print(f"Detail pulls for {len(detail_ids)} active campaigns...")
    details = {}
    for cid in detail_ids:
        print(f"  campaign {cid}")
        details[cid] = fetch_campaign_detail(cid)

    accounts = fetch_email_accounts()

    signals = {
        "theirstack_briefs": read_theirstack_briefs(),
        "signal_routines": read_signal_routines(),
        "dm_runs": read_run_log(HOME / ".navreo-cache/lilly-dm-runs.log", "dm-finder"),
        "icebreaker_runs": read_run_log(HOME / ".navreo-cache/lilly-icebreaker-v2-runs.log", "icebreaker"),
    }
    audit = read_audit_issues()
    notifications = build_notifications(campaigns, details, audit)

    healthy = sum(1 for a in accounts
                  if a["smtp_ok"] and a["imap_ok"])
    mailboxes = {
        "accounts": accounts,
        "summary": {
            "total": len(accounts),
            "healthy": healthy,
            "warmup_active": sum(1 for a in accounts if a["warmup_status"] == "ACTIVE"),
            "connection_issues": len(accounts) - healthy,
            "domains": len({a["domain"] for a in accounts if a["domain"]}),
        },
    }

    files = {
        "campaigns.json": campaigns,
        "campaign_details.json": {str(k): v for k, v in details.items()},
        "mailboxes.json": mailboxes,
        "signals.json": signals,
        "notifications.json": notifications,
        "audit.json": audit,
        "meta.json": {
            "fetched_at": started.isoformat(timespec="seconds"),
            "duration_s": round((datetime.now() - started).total_seconds()),
            "workspace": "Navreo",
            "campaign_count": len(campaigns),
            "detail_count": len(details),
            "account_count": len(accounts),
            "notification_count": len(notifications),
        },
    }
    for name, payload in files.items():
        (DATA_DIR / name).write_text(json.dumps(payload, indent=1))
        print(f"wrote data/{name}")

    print(f"\nDone in {files['meta.json']['duration_s']}s — "
          f"{len(campaigns)} campaigns, {len(details)} detailed, "
          f"{len(accounts)} accounts, {len(notifications)} notifications.")


if __name__ == "__main__":
    main()
