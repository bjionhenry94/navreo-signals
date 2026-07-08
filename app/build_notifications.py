#!/usr/bin/env python3
"""Populate Supabase table `optimiser_notifications` with Lilly-Optimiser-style
findings for every ACTIVE Smartlead campaign.

Read-only against Smartlead (GET only — see app/fetch_data.py for the same
constraint and rationale: sequence-save endpoints reset variant stats, so this
script has no write helper for Smartlead at all). Writes ONLY to the
`optimiser_notifications` Supabase table — never campaign_drafts, sources, or
role_feedback (those are owned by app/server.py's sb() callers).

Logic ported from ~/.claude/skills/lilly-optimiser/SKILL.md:
  - Positive categories: Interested, Call Booked, Meeting Request, Information
    Request (exact match — "Information Request", not "Information Requested").
  - Monitor phase: a variant needs 800+ sent before it's judged at all.
  - REPLACE: 800+ sent, zero positives (or < 1 positive per 800 sent).
  - Clear winner (SCALE) / clear loser (DISABLE): computed relative to siblings
    on the same sequence step.
  - Campaign "needs optimisation": ACTIVE + 1,500+ emails sent (the whole
    active+1500 set, per the brief for this script — not just the worst tier).
  - Kill threshold: 15,000+ sent AND still 2,500+ emails per positive.
  - Low reply rate: replied/sent < 1%.
  - Distribution bugs: Bug A = 0% distribution + 0 sends (never configured).
    Bug B = >0% distribution + 0 sends while the campaign is actively sending
    (broken in the UI). Not a bug: 0% distribution WITH sends (intentionally
    disabled later) — skip, treat as a normal disabled variant.
  - "All clear": ACTIVE campaign with no needs_optimisation / actionable
    variant_call (REPLACE, SCALE, DISABLE — KEEP is informational, not
    actionable) / low_reply_flag / distribution_flag.

Known approximations (documented, not silently assumed):
  - Variant-level sent/positive counts come from aggregating up to 1,000
    /statistics rows per campaign (same cap app/fetch_data.py uses). Campaigns
    with more than 1,000 total sends may under-count variant-level splits;
    the campaign-level `needs_optimisation` numbers come straight from the
    /analytics endpoint instead, which IS the source of truth per the skill.
  - Email 2 (and any inline step with a null seq_variant_id) is bucketed into
    one synthetic "Email 2" row per campaign, matching fetch_data.py's
    simplification — it does not attempt to separate Email 2 from Email 3.
  - Detail pulls (/sequences, /statistics) are skipped for campaigns with
    campaign-level sent < 800, since no variant in such a campaign could have
    reached the 800-send judging threshold anyway. This keeps the run inside a
    handful of minutes across ~100 active campaigns without changing any
    finding a full pull would have produced.
  - Low-reply-rate is only flagged once a campaign has 500+ sent, to avoid
    noise on campaigns that just started (a 3-send / 0-reply campaign is not
    an actionable "under 1%" signal).

Row identity for idempotent upserts: unique(campaign_id, finding_type, title).
Titles are built from STABLE identifiers only (campaign id, variant label,
finding category) — never from counts that change every run — so a rerun
updates the same rows (sent/positive/detail/priority) instead of minting new
ones. `status`, `created_at`, and `actioned_at` are deliberately left out of
the upsert body so a rerun never resets a CSM's acknowledged/actioned/dismissed
state or the original created_at.

Usage:  python3 app/build_notifications.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-prototype/1.0 (curl-compatible)"
MGMT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")  # Cloudflare in front
                                                               # of api.supabase.com
                                                               # 403s a bare urllib UA

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
RATE_SLEEP = 0.35  # ~170 req/min, under Smartlead's 200/min cap (matches fetch_data.py)
STATS_ROW_CAP = 1000  # same cap fetch_data.py uses for /statistics aggregation
DETAIL_MIN_SENT = 800  # below this, no variant could reach the judging threshold
LOW_REPLY_MIN_SENT = 500
NEEDS_OPT_MIN_SENT = 1500
KILL_MIN_SENT = 15000
KILL_RATIO = 2500

POSITIVE_CATEGORIES = {"Interested", "Call Booked", "Meeting Request", "Information Request"}

TABLE = "optimiser_notifications"
APP_DIR = Path(__file__).resolve().parent
SQL_FILE = APP_DIR / "optimiser_notifications.sql"

CLIENT_KEYWORDS = [  # order matters — first match wins, mirrors the skill's table
    ("Arnic", "Arnic"),
    ("Amplifyy", "Amplifyy"),
    ("Olivia Duncan", "Olivia Duncan"),
    ("PestCo", "PestCo"),
    ("Valsoft", "Valsoft"),
    ("Corporate Development", "Valsoft"),
    ("Alpine", "Navreo (secondary)"),
    ("Property Management", "Navreo (secondary)"),
    ("Navreo", "Navreo"),
]


# ── secrets ────────────────────────────────────────────────────────────────

def load_keys() -> dict:
    """Env-first with a local-file fallback — same shape as server.py's
    load_keys(). Never printed, never logged."""
    keys = {}
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
for _required in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SMARTLEAD_API_KEY"):
    if not KEYS.get(_required):
        sys.exit(f"{_required} not found in ~/.navreo-keys.env or environment")


# ── HTTP helpers ─────────────────────────────────────────────────────────

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
            # A successful "Prefer: return=minimal" write comes back with an
            # EMPTY body by design (204/201 with no content) — that is not a
            # failure. Only a raised exception / non-2xx status means failure.
            return json.loads(raw) if raw.strip() else []
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        print(f"  ! HTTP {e.code} on {method} {url.split('?')[0]}: {raw[:300]}")
        try:
            return {"_status": e.code, "_error": True, **(json.loads(raw) if raw.strip() else {})}
        except ValueError:
            return {"_status": e.code, "_error": True, "error": raw}


def sb(method: str, path: str, body=None, prefer: str = ""):
    """Supabase PostgREST call — same shape as server.py's sb(), scoped to
    whatever table `path` names. This script only ever calls it with paths
    under `optimiser_notifications`."""
    url = KEYS["SUPABASE_URL"]
    key = KEYS["SUPABASE_SERVICE_ROLE_KEY"]
    try:
        return http_json(method, f"{url}/rest/v1/{path}",
                          {"apikey": key, "Authorization": f"Bearer {key}",
                           "Prefer": prefer or "return=minimal"}, body)
    except Exception as e:  # noqa: BLE001
        print(f"  ! sb {method} {path} failed: {e}")
        return None


def sl_get(endpoint: str, params: dict | None = None):
    """Smartlead GET-only helper, rate-limited with one retry. NEVER call this
    with POST/PUT/DELETE — Smartlead access in this script is read-only by
    construction (there is no write helper)."""
    params = dict(params or {})
    params["api_key"] = KEYS["SMARTLEAD_API_KEY"]
    url = f"{SMARTLEAD_BASE}{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in (1, 2):
        try:
            time.sleep(RATE_SLEEP)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001
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


# ── table bootstrap ─────────────────────────────────────────────────────

DDL = SQL_FILE.read_text() if SQL_FILE.exists() else None


def table_exists() -> bool:
    rows = sb("GET", f"{TABLE}?limit=1")
    return isinstance(rows, list)


def create_table_via_management_api() -> bool:
    """Best-effort DDL execution through Supabase's Management API
    (POST /v1/projects/{ref}/database/query), auth'd with SUPABASE_ACCESS_TOKEN.
    Requires a browser-like User-Agent — api.supabase.com sits behind
    Cloudflare and 403s urllib's default UA."""
    token = KEYS.get("SUPABASE_ACCESS_TOKEN")
    if not token or not DDL:
        return False
    ref = urllib.parse.urlparse(KEYS["SUPABASE_URL"]).hostname.split(".")[0]
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"query": DDL}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": MGMT_UA, "Accept": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            resp.read()
            return True
    except urllib.error.HTTPError as e:
        print(f"  ! Management API DDL failed: {e.code} {e.read().decode()[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ! Management API DDL failed: {e}")
        return False


def ensure_table() -> bool:
    if table_exists():
        print(f"Table `{TABLE}` already exists.")
        return True
    print(f"Table `{TABLE}` not found — attempting to create it via the "
          "Supabase Management API...")
    if create_table_via_management_api() and table_exists():
        print(f"Table `{TABLE}` created successfully.")
        return True
    print(f"\nCould NOT create `{TABLE}` automatically.\n"
          f"Run the SQL in {SQL_FILE} by hand in the Supabase SQL editor, "
          "then re-run this script.")
    return False


# ── Smartlead pulls ─────────────────────────────────────────────────────

def fetch_active_campaigns() -> list[dict]:
    print("Pulling campaign list...")
    campaigns, offset = [], 0
    while True:
        page = as_list(sl_get("/campaigns", {"limit": 100, "offset": offset}),
                       "data", "campaigns", "result")
        campaigns.extend(page)
        if len(page) < 100:
            break
        offset += 100
    active = [c for c in campaigns if c.get("status") == "ACTIVE"]
    print(f"  {len(campaigns)} campaigns total, {len(active)} ACTIVE")
    return active


def fetch_analytics(campaign_id) -> dict:
    data = sl_get(f"/campaigns/{campaign_id}/analytics") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        data = {}
    cls = data.get("campaign_lead_stats") if isinstance(data.get("campaign_lead_stats"), dict) else {}
    return {
        "sent": to_int(data.get("sent_count") or data.get("sent")),
        "opens": to_int(data.get("open_count") or data.get("opened") or data.get("unique_open_count")),
        "replies": to_int(data.get("reply_count") or data.get("replied")),
        "positives": to_int(data.get("positive_reply_count") or data.get("positiveReplyCount")
                             or data.get("interested_count") or cls.get("interested")),
        "total_leads": to_int(data.get("total_count") or cls.get("total")),
        "completed_leads": to_int(cls.get("completed")),
    }


def fetch_sequences(campaign_id) -> dict:
    """Returns {variant_id: {seq_number, label, distribution_pct, is_deleted}}."""
    sequences = as_list(sl_get(f"/campaigns/{campaign_id}/sequences"), "data", "sequences")
    variants = {}
    for s in sequences:
        seq_num = to_int(s.get("seq_number") or 1)
        for v in (s.get("sequence_variants") or []):
            vid = v.get("id")
            if vid is None:
                continue
            variants[vid] = {
                "seq_number": seq_num,
                "label": str(v.get("variant_label") or "A"),
                "distribution_pct": v.get("variant_distribution_percentage"),
                "is_deleted": bool(v.get("is_deleted")),
            }
    return variants


def fetch_variant_stats(campaign_id, variant_index: dict) -> dict:
    """Aggregate up to STATS_ROW_CAP /statistics rows into per-variant sent /
    positive / reply counts. Null seq_variant_id rows (Email 2, or any inline
    step) are bucketed into one synthetic key "__email2__"."""
    agg: dict = {}
    offset = 0
    while offset < STATS_ROW_CAP:
        page = sl_get(f"/campaigns/{campaign_id}/statistics", {"limit": 100, "offset": offset})
        rows = as_list(page, "data")
        for r in rows:
            vid = r.get("seq_variant_id")
            key = vid if vid in variant_index else "__email2__"
            a = agg.setdefault(key, {"sent": 0, "positives": 0, "positive_emails": set(), "replies": 0})
            a["sent"] += 1
            if r.get("reply_time"):
                a["replies"] += 1
            cat = r.get("lead_category") or r.get("category")
            email = (r.get("lead") or {}).get("email") if isinstance(r.get("lead"), dict) else r.get("email")
            if cat in POSITIVE_CATEGORIES and (not email or email not in a["positive_emails"]):
                a["positives"] += 1
                if email:
                    a["positive_emails"].add(email)
        total = to_int((page or {}).get("total_stats")) if isinstance(page, dict) else 0
        offset += 100
        if len(rows) < 100 or offset >= total:
            break
    for a in agg.values():
        a.pop("positive_emails", None)
    return agg


# ── finding builders ────────────────────────────────────────────────────

def infer_client(name: str) -> str:
    for needle, client in CLIENT_KEYWORDS:
        if needle.lower() in (name or "").lower():
            return client
    return "Unknown"


def ratio(sent: int, positives: int):
    """sent/positive ratio, or None when there are zero positives (== infinite,
    rendered as such rather than a misleading number)."""
    return round(sent / positives, 1) if positives > 0 else None


def build_campaign_findings(c: dict, analytics: dict, variant_stats: dict, variant_index: dict) -> list[dict]:
    cid, name = str(c["id"]), c.get("name") or f"Campaign {c['id']}"
    client = infer_client(name)
    sent, positives = analytics["sent"], analytics["positives"]
    findings = []
    actionable = False  # blocks all_clear when any actionable finding exists

    # 1. needs_optimisation — every ACTIVE campaign with 1,500+ sent
    if sent >= NEEDS_OPT_MIN_SENT:
        r = ratio(sent, positives)
        kill = sent >= KILL_MIN_SENT and (positives == 0 or (r is not None and r >= KILL_RATIO))
        findings.append({
            "campaign_id": cid, "campaign_name": name, "client": client,
            "finding_type": "needs_optimisation",
            "priority": "High" if kill else "Medium",
            "title": "Needs optimisation: 1,500+ sent",
            "detail": (f"{sent:,} sent, {positives} positive"
                       + (f", {r:,} sent per positive" if r is not None else ", zero positives so far")
                       + (". Kill-threshold reached (15,000+ sent, still 2,500+/positive) — pivot the offer, not the copy."
                          if kill else ".")),
            "suggested_action": "Kill-threshold pivot — new ICP/mechanism, CSM decision required" if kill
                                 else "Review variant performance and reply rate before adding more leads",
            "sent": sent, "positive": positives, "sent_pos_ratio": r,
        })
        actionable = True

    # 2. variant_call — REPLACE / SCALE / DISABLE / KEEP, grouped by seq_number
    # Campaign-level failure rule (skill, Section 4): a campaign with 1,500+
    # sent and zero positives flags ALL its active variants, even those still
    # under the 800-send monitor-phase threshold, because the whole campaign
    # is failing — UNLESS literally every variant is sub-800, in which case
    # the skill prefers one campaign-level message (the needs_optimisation
    # row above) over listing each tiny variant, so the per-variant loop is
    # skipped entirely in that case.
    campaign_failing = sent >= NEEDS_OPT_MIN_SENT and positives == 0
    any_variant_at_threshold = any(s["sent"] >= DETAIL_MIN_SENT for s in variant_stats.values())
    include_all_variants = campaign_failing and any_variant_at_threshold
    by_seq: dict = {}
    for key, stats in variant_stats.items():
        if stats["sent"] < DETAIL_MIN_SENT and not include_all_variants:
            continue  # monitor phase — too early to judge, skip entirely
        if key == "__email2__":
            seq_num, label, disabled = 2, "Email 2 (combined)", False
        else:
            meta = variant_index.get(key)
            if not meta or meta["is_deleted"] or (meta["distribution_pct"] == 0 and stats["sent"] > 0):
                continue  # disabled variant — never shown per the skill's formatting rule
            seq_num, label, disabled = meta["seq_number"], meta["label"], False
        by_seq.setdefault(seq_num, []).append({"key": key, "label": label, **stats})

    for seq_num, siblings in by_seq.items():
        ranked = sorted(siblings, key=lambda s: (s["positives"] == 0, -s["sent"] if s["positives"] == 0 else
                                                  s["sent"] / s["positives"]))
        best = ranked[0] if any(s["positives"] > 0 for s in ranked) else None
        for s in siblings:
            r = ratio(s["sent"], s["positives"])
            has_performing_sibling = any(o["positives"] > 0 for o in siblings if o["key"] != s["key"])
            if s["positives"] == 0:
                action = "REPLACE" if (campaign_failing or not has_performing_sibling) else "DISABLE"
                priority = "High" if action == "REPLACE" else "Medium"
                detail = f"{s['sent']:,} sent, zero positives. {'Whole offer failing at campaign level — ' if campaign_failing else ''}{'Replace this angle entirely.' if action == 'REPLACE' else 'Siblings are converting — disable this loser.'}"
                actionable = True
            elif best is not None and s["key"] == best["key"] and len(siblings) > 1 and all(
                    o["positives"] == 0 or r <= ratio(o["sent"], o["positives"]) / 2 + 0.001
                    for o in siblings if o["key"] != s["key"] and o["positives"] > 0):
                action, priority = "SCALE", "Medium"
                detail = f"{s['sent']:,} sent, {s['positives']} positive ({r:,}/positive) — clearly outperforming its siblings. Scale distribution, build new variants on this angle."
                actionable = True
            else:
                action, priority = "KEEP", "Low"
                ratio_txt = f"{r:,}/positive" if r is not None else "no positives yet"
                detail = f"{s['sent']:,} sent, {s['positives']} positive ({ratio_txt}). Performing above the replace threshold — no action needed."
                # not actionable — informational only, does not block all_clear
            findings.append({
                "campaign_id": cid, "campaign_name": name, "client": client,
                "finding_type": "variant_call",
                "priority": priority,
                "title": f"Variant call: Email {seq_num} {s['label']}",
                "detail": detail,
                "suggested_action": action,
                "sent": s["sent"], "positive": s["positives"], "sent_pos_ratio": r,
            })

    # 3. low_reply_flag — replied/sent under 1%, once there's enough volume to be a real signal
    if sent >= LOW_REPLY_MIN_SENT:
        reply_rate = analytics["replies"] / sent if sent else 0
        if reply_rate < 0.01:
            findings.append({
                "campaign_id": cid, "campaign_name": name, "client": client,
                "finding_type": "low_reply_flag",
                "priority": "Medium",
                "title": "Low reply rate flag",
                "detail": f"{analytics['replies']} replies on {sent:,} sent ({100 * reply_rate:.2f}%) — under the 1% floor. "
                          "Two usual causes: wrong recipients (off-ICP list) or deliverability (spam placement, reputation, warmup).",
                "suggested_action": "Run a lead list audit (on-ICP vs off-ICP) and check deliverability in parallel",
                "sent": sent, "positive": positives, "sent_pos_ratio": ratio(sent, positives),
            })
            actionable = True

    # 4. distribution_flag — Bug A (0% dist, 0 sends) / Bug B (>0% dist, 0 sends, campaign is sending)
    if sent >= NEEDS_OPT_MIN_SENT:
        campaign_is_sending = sent > 0
        for vid, meta in variant_index.items():
            if meta["is_deleted"]:
                continue
            stats = variant_stats.get(vid, {"sent": 0})
            dist = meta["distribution_pct"]
            if dist == 0 and stats["sent"] == 0:
                bug = "Bug A — 0% distribution, 0 sends (never configured in the UI)"
            elif dist and dist > 0 and stats["sent"] == 0 and campaign_is_sending:
                bug = "Bug B — traffic assigned but 0 sends despite the campaign actively sending (broken in the UI)"
            else:
                continue
            findings.append({
                "campaign_id": cid, "campaign_name": name, "client": client,
                "finding_type": "distribution_flag",
                "priority": "Medium",
                "title": f"Distribution check: Email {meta['seq_number']} {meta['label']}",
                "detail": bug,
                "suggested_action": "Go into the Smartlead UI and set the correct traffic split so this variant gets a non-zero share",
                "sent": stats["sent"], "positive": None, "sent_pos_ratio": None,
            })
            actionable = True

    # 5. recommended_action — roll the actionable findings above into up to 3 rows
    candidates = []
    if any(f["finding_type"] == "needs_optimisation" and f["priority"] == "High" for f in findings):
        candidates.append(("High", "Recommended action: kill-threshold pivot",
                            "This ICP/mechanism likely isn't working at this spend. Ideate a replacement (new ICP, targeting, or channel) — CSM decision required, do not act autonomously."))
    replace_calls = [f for f in findings if f["finding_type"] == "variant_call" and f["suggested_action"] == "REPLACE"]
    if replace_calls:
        labels = ", ".join(f["title"].replace("Variant call: ", "") for f in replace_calls)
        candidates.append(("High" if campaign_failing else "Medium", "Recommended action: replace failing variant(s)",
                            f"Draft new angles for: {labels}. Match template format exactly; change only the problem/offer angle."))
    scale_calls = [f for f in findings if f["finding_type"] == "variant_call" and f["suggested_action"] == "SCALE"]
    if scale_calls:
        labels = ", ".join(f["title"].replace("Variant call: ", "") for f in scale_calls)
        candidates.append(("Medium", "Recommended action: scale winning variant",
                            f"Scale distribution on: {labels}. Build 1 new challenger variant on the same angle at 20% distribution."))
    disable_calls = [f for f in findings if f["finding_type"] == "variant_call" and f["suggested_action"] == "DISABLE"]
    if disable_calls:
        labels = ", ".join(f["title"].replace("Variant call: ", "") for f in disable_calls)
        candidates.append(("Medium", "Recommended action: disable losing variant",
                            f"Disable (never delete): {labels}."))
    if any(f["finding_type"] == "distribution_flag" for f in findings):
        candidates.append(("Medium", "Recommended action: fix distribution bug",
                            "One or more variants have a broken or never-configured traffic split — fix in the Smartlead UI."))
    if any(f["finding_type"] == "low_reply_flag" for f in findings):
        candidates.append(("Medium", "Recommended action: run lead list audit",
                            "Reply rate is under 1% — confirm the enrolled leads match the intended persona, and check deliverability in parallel."))

    order = {"High": 0, "Medium": 1, "Low": 2}
    candidates.sort(key=lambda x: order[x[0]])
    for priority, title, detail in candidates[:3]:
        findings.append({
            "campaign_id": cid, "campaign_name": name, "client": client,
            "finding_type": "recommended_action",
            "priority": priority, "title": title, "detail": detail,
            "suggested_action": detail,
            "sent": sent, "positive": positives, "sent_pos_ratio": ratio(sent, positives),
        })

    # 6. all_clear — nothing actionable found for this campaign
    if not actionable:
        findings.append({
            "campaign_id": cid, "campaign_name": name, "client": client,
            "finding_type": "all_clear",
            "priority": "Low", "title": "All clear",
            "detail": f"{sent:,} sent, {positives} positive. No needs-optimisation, variant, reply-rate, "
                      "or distribution issues detected for this campaign right now.",
            "suggested_action": None,
            "sent": sent, "positive": positives, "sent_pos_ratio": ratio(sent, positives),
        })

    return findings


# ── upsert ───────────────────────────────────────────────────────────────

def upsert_findings(rows: list[dict]) -> int:
    """Upsert in chunks. status/created_at/actioned_at are deliberately left
    out of every row so a rerun never resets CSM state or the original
    created_at — see the module docstring."""
    if not rows:
        return 0
    total = 0
    chunk_size = 200
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        result = sb("POST", f"{TABLE}?on_conflict=campaign_id,finding_type,title",
                    chunk, prefer="resolution=merge-duplicates,return=minimal")
        failed = result is None or (isinstance(result, dict) and result.get("_error"))
        if failed:
            print(f"  ! upsert chunk {i // chunk_size + 1} failed — see error above")
        else:
            total += len(chunk)
    return total


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    if not ensure_table():
        sys.exit(1)

    active = fetch_active_campaigns()
    all_findings: list[dict] = []
    by_type: dict[str, int] = {}

    for i, c in enumerate(active, 1):
        cid, name = c["id"], c.get("name") or f"Campaign {c['id']}"
        print(f"[{i}/{len(active)}] {name} ({cid})")
        analytics = fetch_analytics(cid)
        variant_index, variant_stats = {}, {}
        if analytics["sent"] >= DETAIL_MIN_SENT:
            variant_index = fetch_sequences(cid)
            variant_stats = fetch_variant_stats(cid, variant_index)
        findings = build_campaign_findings(c, analytics, variant_stats, variant_index)
        all_findings.extend(findings)
        for f in findings:
            by_type[f["finding_type"]] = by_type.get(f["finding_type"], 0) + 1

    print(f"\n{len(active)} active campaigns -> {len(all_findings)} findings")
    for ft, n in sorted(by_type.items()):
        print(f"  {ft}: {n}")

    upserted = upsert_findings(all_findings)
    print(f"\nUpserted {upserted} rows into `{TABLE}` (run date {date.today().isoformat()}).")


if __name__ == "__main__":
    main()
