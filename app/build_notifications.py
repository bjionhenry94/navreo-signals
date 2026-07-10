#!/usr/bin/env python3
"""Populate Supabase table `optimiser_notifications` with the lilly-optimiser
Priority Report, one row per finding, mirroring the 7-section report in
~/.claude/skills/lilly-optimiser/SKILL.md EXACTLY (v2).

Read-only against Smartlead (GET only - see app/fetch_data.py for the same
constraint and rationale: sequence-save endpoints reset variant stats, so this
script has no write helper for Smartlead at all). Writes ONLY to the
`optimiser_notifications` Supabase table - never campaign_drafts, sources, or
role_feedback (those are owned by app/server.py's sb() callers). It also does
one read-only GET against `clients` to resolve client_id.

Report logic (the skill file is the spec):
  - Gate: ACTIVE campaigns with 1,500+ emails sent enter the report. ACTIVE
    campaigns below 1,500 sent get exactly one all_clear row (section 0) so
    every active campaign stays covered.
  - Positive categories (EXACT equality only): Interested, Call Booked,
    Meeting Request, Information Request. Never "Information Requested",
    never substring matching (which would catch "Not Interested").
  - Section 1 needs_optimisation: >=1 variant with 800+ sent and 0 positives
    (or < 1 per 800), OR campaign sent/pos > 1,500.
  - Section 2 performing: sent/pos <= 1,500.
  - Section 3 lifecycle: completion = sent / (total_leads * 2) * 100, using
    total_leads from the leads endpoint (limit=1). Only 40%+ shown:
    40-94% upload_leads, 95%+ nearing_completion.
  - Section 4 variant_call: ONLY campaigns under 60% completion. Judged
    variants need 800+ sent (monitor phase excluded). REPLACE / clear winner
    (scale_winner) / clear loser (disable_loser). Campaign-level failure rule:
    1,500+ sent with 0 positives = whole offer failing, flagged at campaign
    level. Email 2 (null seq_variant_id rows) is its own row, same 800
    threshold: rewrite if 800+/0 pos, flip if outperforming Email 1. Disabled
    variants (is_deleted, or 0% distribution with >=1 send) excluded. Variant
    positives are reconciled so they never exceed the campaign-level count.
    Campaigns with no actionable variant finding are skipped entirely.
  - Section 5 low_reply_flag: reply_rate = replied/sent*100 from overall
    stats; only under 1%. action_type=run_list_audit.
  - Section 6 distribution_flag: Bug A = 0% distribution + 0 sends (never
    configured). Bug B = >0% distribution + 0 sends while the campaign sends
    (broken in the UI). NOT a bug: 0% distribution with >0 sends
    (intentionally disabled).
  - Section 7 recommended_action: one block per campaign with any action,
    numbered sequentially (block_number). Priority: High = 0 positives past
    800+ sends per variant / kill threshold (15,000+ sent AND ratio >= 2,500,
    action_type=kill_threshold_pivot) / both variants failing
    (replace_variants). Medium = scale winner, disable loser, distribution
    bug, reply rate under 1%. Low = lifecycle only. Ordered High > Medium >
    Low, within tier by sent desc.
  - claude_prompt: Section 7 rows of type replace_variants / scale_winner /
    disable_loser / kill_threshold_pivot / run_list_audit carry a pre-made
    Claude Code prompt (STATIC string assembly, no LLM calls) following the
    skill's Section 5 template, beginning with the mandatory
    "SCOPE - DATA AND DRAFTING ONLY, DO NOT BUILD:" block.
  - api_safe: true ONLY where the executable act is pausing the campaign
    (pause_campaign / kill_threshold_pivot). Everything touching sequences or
    variants is UI-only per the optimiser guardrails.
  - No em-dashes in any generated text (optimiser guardrail).

Documented approximations:
  - Email 2 bucket: all null-seq_variant_id /statistics rows fold into one
    synthetic "Email 2" row per campaign (does not split Email 2 from an
    inline Email 3).
  - Distribution Bug B is skipped for seq>=2 variants when the campaign has
    null-variant-id sends recorded (can't prove the variant got no traffic).
  - Angle summaries come from each variant's subject line + first text line
    of the body (HTML stripped), which is what the data exposes without an
    LLM pass.

Row identity for idempotent upserts: unique(campaign_id, finding_type, title).
Titles are built from STABLE identifiers only (campaign id, variant label,
finding category) - never from counts that change every run - so a rerun
updates the same rows instead of minting new ones. `status`, `created_at`,
and `actioned_at` are deliberately left out of the upsert body so a rerun
never resets a CSM's acknowledged/actioned/dismissed state.

Usage:
  python app/build_notifications.py               # normal idempotent run
  python app/build_notifications.py --reset-once  # ONE-TIME v1->v2 migration
      wipe: deletes ALL existing rows first (allowed only because every row
      is still status=new - no CSM state exists yet). Do NOT use routinely.
"""

from __future__ import annotations

import faulthandler

import html as html_mod
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
STATS_PAGE = 1000  # /statistics page size (skill's response-breakdown workflow uses 1000)
STATS_MAX_ROWS = 60000  # hard safety cap per campaign
REPORT_MIN_SENT = 1500   # campaigns below this get one all_clear row
JUDGE_MIN_SENT = 800     # monitor phase below this
PERFORMING_RATIO = 1500  # sent/pos at or under this = performing
KILL_MIN_SENT = 15000
KILL_RATIO = 2500

POSITIVE_CATEGORIES = {"Interested", "Call Booked", "Meeting Request", "Information Request"}
# Meetings are a SUBSET of positives (both categories are also in
# POSITIVE_CATEGORIES above) - counted separately for Section 7's structured
# variants table so a CSM can see "how many of these positives were a booked
# meeting" per variant. Never counted as extra on top of positives; capped at
# each bucket's own positives count after reconcile_positives runs (see
# reconcile_positives' docstring - the same "never exceed the campaign-level
# count" rule applies one level down).
MEETING_CATEGORIES = {"Call Booked", "Meeting Request"}

TABLE = "optimiser_notifications"
APP_DIR = Path(__file__).resolve().parent
SQL_FILE = APP_DIR / "optimiser_notifications.sql"

SMARTLEAD_URL_TPL = "https://app.smartlead.ai/app/email-campaign/{cid}/analytics"

CLIENT_KEYWORDS = [  # order matters - first match wins, mirrors the skill's table
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

# /lilly-strategy slugs per client (kill-threshold nudge line)
CLIENT_SLUG = {
    "Arnic": "arnic", "Amplifyy": "amplifyy", "Navreo": "navreo",
    "Navreo (secondary)": "navreo", "Olivia Duncan": "olivia-duncan",
    "PestCo": "pestco", "Valsoft": "valsoft", "Unknown": "unknown",
}

# Client context table from the skill (Section 2 of the task body) - used to
# assemble claude_prompt statically. No em-dashes anywhere.
CLIENT_CONTEXT = {
    "Navreo": {
        "offer": "Done-for-you outbound pipeline building on a pay-per-lead model.",
        "persona": "VP/Head/Director of Sales at software dev agencies, AI transformation firms, digital transformation firms, 51-200 employees.",
        "rules": ["Template: icebreaker + GTM noise + personalised video CTA + pay-per-lead or guarantee."],
    },
    "Arnic": {
        "offer": "Sales enablement content and onboarding systems for SaaS sales teams.",
        "persona": "Heads of Sales at 100-200 employee SaaS companies (best converting persona).",
        "rules": [
            "Always say \"sales onboarding\" / \"sales content\" explicitly.",
            "Case study = GitLab + Meta together with all numbers in every mention.",
            "Renewal urgency as of May 2026.",
        ],
    },
    "Amplifyy": {
        "offer": "Amazon brand growth agency (DFY Amazon channel management).",
        "persona": "Head of E-commerce at companies already selling on Amazon.",
        "rules": [
            "Never say \"commission\", always \"performance basis\".",
            "Never stack lead magnet + gift card in the same email.",
        ],
    },
    "Navreo (secondary)": {
        "offer": "Property management vertical (Navreo secondary).",
        "persona": "Property management decision makers. Limited context, note this in the task.",
        "rules": ["Limited client context on file, confirm with CSM before drafting."],
    },
    "Olivia Duncan": {
        "offer": "Interior design vertical. High-performing campaign historically (ratio ~234).",
        "persona": "Interior design owners/founders.",
        "rules": ["Limited client context on file, confirm with CSM before drafting."],
    },
    "PestCo": {
        "offer": "Pest control vertical.",
        "persona": "Limited context, confirm with CSM.",
        "rules": ["Limited client context on file, confirm with CSM before drafting."],
    },
    "Valsoft": {
        "offer": "Corporate development / vertical market software acquisition outreach.",
        "persona": "CEO/founder/MD/COO/finance heads at B2B vertical-market-software companies.",
        "rules": ["Limited client context on file, confirm with CSM before drafting."],
    },
    "Unknown": {
        "offer": "Unknown client, confirm with CSM.",
        "persona": "Unknown, confirm with CSM.",
        "rules": ["Client could not be inferred from the campaign name, confirm with CSM before drafting."],
    },
}

SCOPE_BLOCK = (
    "SCOPE - DATA AND DRAFTING ONLY, DO NOT BUILD:\n"
    "This task is for pulling data, mapping the TAM, and drafting copy or angles only. "
    "Do NOT build or change anything live: no creating or editing campaigns, no pushing "
    "or enriching leads, no uploading or moving lists, no touching sequences, variants, "
    "or automations. The actual build is assigned to someone else (the GTME). Produce "
    "the draft, data, or TAM map ready to hand off, then stop."
)

# Tool-level clients, Step 2 (2026-07-08): `clients` has 3 brands registered
# under BOTH a legacy slug id and a newer `client-N` id (verified read-only
# against the live table - see app/migrations/2026-07-08-tool-level-clients.sql
# for the full writeup). This map collapses the legacy id onto the canonical
# one that campaign_drafts.doc->>'client_id' and signal_sources.client_id
# actually reference.
CLIENT_ID_ALIAS = {
    "navreo": "client-1",
    "amplifyy": "client-2",
    "arnic": "client-3",
}


# -- secrets -----------------------------------------------------------------

def load_keys() -> dict:
    """Env-first with a local-file fallback - same shape as server.py's
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


# -- HTTP helpers ------------------------------------------------------------

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
            # EMPTY body by design (204/201 with no content) - that is not a
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
    """Supabase PostgREST call - same shape as server.py's sb(), scoped to
    whatever table `path` names. This script writes only to
    `optimiser_notifications`; it also does a read-only GET against `clients`
    (see fetch_clients_by_name()) to resolve client_id - never writes there."""
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
    with POST/PUT/DELETE - Smartlead access in this script is read-only by
    construction (there is no write helper)."""
    params = dict(params or {})
    params["api_key"] = KEYS["SMARTLEAD_API_KEY"]
    url = f"{SMARTLEAD_BASE}{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in (1, 2):
        try:
            time.sleep(RATE_SLEEP)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
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


TAG_RE = re.compile(r"<[^>]+>")
DASH_RE = re.compile(r"[—–‒―]")  # em/en/figure/horizontal-bar dashes
SPINTAX_RE = re.compile(r"\{([^{}|]*)(?:\|[^{}]*)*\}")


def _spintax_first_alt(m: "re.Match") -> str:
    """Pick the first non-empty alternative from a {a|b|c} group (handles
    {|x|y} where the first alternative is blank)."""
    for alt in m.group(0)[1:-1].split("|"):
        if alt.strip():
            return alt
    return ""


def resolve_spintax(s: str) -> str:
    """Resolve {a|b|c} spintax groups to their first (non-empty) alternative,
    applied iteratively so nested groups resolve inside-out. Never leaves raw
    alternation syntax in plain-English output."""
    for _ in range(10):
        if "{" not in s or "}" not in s:
            break
        new_s = SPINTAX_RE.sub(_spintax_first_alt, s)
        if new_s == s:
            break
        s = new_s
    return s


def clean_text(s) -> str:
    """Sanitise any generated/quoted text: no em-dashes (optimiser guardrail),
    no HTML, collapsed whitespace."""
    if not s:
        return ""
    s = html_mod.unescape(TAG_RE.sub(" ", str(s)))
    s = DASH_RE.sub("-", s)
    s = resolve_spintax(s)
    return re.sub(r"\s+", " ", s).strip()


# -- table bootstrap + v2 migration ------------------------------------------

def run_mgmt_sql(sql: str, label: str) -> bool:
    """Execute SQL through Supabase's Management API
    (POST /v1/projects/{ref}/database/query), auth'd with SUPABASE_ACCESS_TOKEN.
    Requires a browser-like User-Agent - api.supabase.com sits behind
    Cloudflare and 403s urllib's default UA."""
    token = KEYS.get("SUPABASE_ACCESS_TOKEN")
    if not token or not sql:
        return False
    ref = urllib.parse.urlparse(KEYS["SUPABASE_URL"]).hostname.split(".")[0]
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"query": sql}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": MGMT_UA, "Accept": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            resp.read()
            return True
    except urllib.error.HTTPError as e:
        print(f"  ! Management API {label} failed: {e.code} {e.read().decode()[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ! Management API {label} failed: {e}")
        return False


MIGRATION_SQL = """
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS client_id text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS section smallint;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS block_number int;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS action_type text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS api_safe boolean default false;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS smartlead_url text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS claude_prompt text;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS completion_pct numeric;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS reply_rate numeric;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS replied int;
ALTER TABLE optimiser_notifications ADD COLUMN IF NOT EXISTS variants jsonb;
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_finding_type_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_finding_type_check
  CHECK (finding_type in ('needs_optimisation','performing','lifecycle','variant_call','low_reply_flag','distribution_flag','recommended_action','all_clear'));
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_action_type_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_action_type_check
  CHECK (action_type is null or action_type in ('pause_campaign','replace_variants','scale_winner','disable_loser','fix_distribution','run_list_audit','upload_leads','nearing_completion','kill_threshold_pivot','none'));
ALTER TABLE optimiser_notifications DROP CONSTRAINT IF EXISTS optimiser_notifications_section_check;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_section_check
  CHECK (section is null or section between 0 and 7);
"""

# v3 (2026-07-08): retirement pass. `status` gains 'resolved' - a finding the
# latest run no longer emits (and that a CSM never touched, i.e. still 'new')
# is auto-retired rather than lingering forever. ALTER TABLE can't modify a
# CHECK constraint in place, so this drops whichever check constraint is on
# `status` (found via pg_constraint, not assumed by name - the DDL below names
# it explicitly but a hand-run SQL editor session could have named it
# differently) and re-adds it with the widened value list. Wrapped in a DO
# block so dropping is a no-op when no such constraint exists, making the
# whole thing safe to run on every start.
STATUS_MIGRATION_SQL = """
DO $$
DECLARE
  con_name text;
BEGIN
  SELECT con.conname INTO con_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  WHERE rel.relname = 'optimiser_notifications'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) LIKE '%status%';
  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE optimiser_notifications DROP CONSTRAINT %I', con_name);
  END IF;
END $$;
ALTER TABLE optimiser_notifications ADD CONSTRAINT optimiser_notifications_status_check
  CHECK (status in ('new','acknowledged','actioned','dismissed','resolved'));
"""


def table_exists() -> bool:
    rows = sb("GET", f"{TABLE}?limit=1")
    return isinstance(rows, list)


def ensure_table() -> bool:
    if not table_exists():
        print(f"Table `{TABLE}` not found - creating it via the Supabase Management API...")
        ddl = SQL_FILE.read_text() if SQL_FILE.exists() else None
        if not (ddl and run_mgmt_sql(ddl, "DDL") and table_exists()):
            print(f"\nCould NOT create `{TABLE}` automatically.\n"
                  f"Run the SQL in {SQL_FILE} by hand in the Supabase SQL editor, "
                  "then re-run this script.")
            return False
        print(f"Table `{TABLE}` created successfully.")
        # SQL_FILE's CREATE TABLE already has the widened status check, but run
        # the v3 migration too as a belt-and-braces safety net (idempotent).
        run_mgmt_sql(STATUS_MIGRATION_SQL, "status v3 migration (post-create safety net)")
        return True  # fresh v2 table, no migration needed
    print(f"Table `{TABLE}` exists - applying idempotent v2 column migration...")
    v2_ok = run_mgmt_sql(MIGRATION_SQL, "v2 migration")
    if v2_ok:
        print("  v2 migration applied (ADD COLUMN IF NOT EXISTS + finding_type check).")
    status_ok = run_mgmt_sql(STATUS_MIGRATION_SQL, "status v3 migration (widen to include 'resolved')")
    if status_ok:
        print("  status check constraint widened to allow 'resolved'.")
    else:
        print(f"  ! status constraint migration failed - the retirement pass's PATCH to "
              f"status=resolved will fail against the DB (23514 check violation) until the "
              f"DO block in {SQL_FILE} is run by hand.")
    if v2_ok:
        return True
    # Verify the columns are already there (migration may have run before)
    probe = sb("GET", f"{TABLE}?select=section,block_number,action_type,api_safe,"
                      f"smartlead_url,claude_prompt,completion_pct,reply_rate,variants&limit=1")
    if isinstance(probe, list):
        print("  Management API unavailable but v2 columns already present - continuing.")
        return True
    print("  ! v2 columns missing and migration failed - run the ALTER TABLE block "
          f"in {SQL_FILE} by hand, then re-run.")
    return False


def wipe_all_rows() -> None:
    """ONE-TIME v1->v2 reset (all rows are status=new, no CSM state exists).
    Guarded behind the explicit --reset-once flag; never part of normal runs."""
    print("--reset-once: deleting ALL existing rows (one-time v1->v2 migration wipe)...")
    result = sb("DELETE", f"{TABLE}?id=not.is.null")
    if isinstance(result, dict) and result.get("_error"):
        sys.exit("  ! wipe failed - aborting so we don't upsert on top of v1 rows")
    remaining = sb("GET", f"{TABLE}?select=id&limit=1")
    print(f"  wipe done ({'empty' if not remaining else 'ROWS REMAIN - check!'}).")


# -- Smartlead pulls ---------------------------------------------------------

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
        "replies": to_int(data.get("reply_count") or data.get("replied")),
        "positives": to_int(data.get("positive_reply_count") or data.get("positiveReplyCount")
                             or data.get("interested_count") or cls.get("interested")),
    }


def fetch_total_leads(campaign_id) -> int:
    """total_leads via the leads endpoint with limit=1 (the skill's method -
    NOT unique_lead_count from analytics)."""
    data = sl_get(f"/campaigns/{campaign_id}/leads", {"limit": 1, "offset": 0})
    if isinstance(data, dict):
        return to_int(data.get("total_leads"))
    return 0


def fetch_sequences(campaign_id) -> dict:
    """{variant_id: {seq_number, label, distribution_pct, is_deleted, angle}}.
    `angle` = plain-English-ish summary from subject + first text line of the
    body (HTML stripped), used in Section 7 claude_prompt assembly."""
    sequences = as_list(sl_get(f"/campaigns/{campaign_id}/sequences"), "data", "sequences")
    variants = {}
    for s in sequences:
        seq_num = to_int(s.get("seq_number") or 1)
        for v in (s.get("sequence_variants") or []):
            vid = v.get("id")
            if vid is None:
                continue
            subject = clean_text(v.get("subject"))
            body_line = clean_text(v.get("email_body"))[:140]
            angle = subject if subject else body_line[:80]
            if subject and body_line:
                angle = f"{subject} / {body_line[:100]}"
            variants[vid] = {
                "seq_number": seq_num,
                "label": str(v.get("variant_label") or "A"),
                "distribution_pct": v.get("variant_distribution_percentage"),
                "is_deleted": bool(v.get("is_deleted")),
                "angle": angle or "(no subject or body text on file)",
            }
    return variants


def fetch_variant_stats(campaign_id) -> dict:
    """Paginate /campaigns/{id}/statistics fully (limit=1000 pages, bounded by
    total_stats) and aggregate per seq_variant_id. Null variant-id rows (Email
    2 or any inline step) bucket into the synthetic key "__email2__".

    Positives are deduped by lead email keeping the greatest reply_time (the
    skill's rule), then counted per bucket, guaranteeing variant totals track
    unique positive leads. Exact-equality category match only."""
    sent_by_key: dict = {}
    replies_by_key: dict = {}
    best_positive: dict = {}  # email -> (reply_time, key)  for deduped positives
    anon_positives: dict = {}  # key -> count for positive rows with no email
    best_meeting: dict = {}  # email -> (reply_time, key)  for deduped meetings
    anon_meetings: dict = {}  # key -> count for meeting rows with no email
    offset, total = 0, None
    while offset < STATS_MAX_ROWS:
        page = sl_get(f"/campaigns/{campaign_id}/statistics",
                      {"limit": STATS_PAGE, "offset": offset})
        rows = as_list(page, "data")
        if total is None and isinstance(page, dict):
            total = to_int(page.get("total_stats"))
        for r in rows:
            vid = r.get("seq_variant_id")
            key = vid if vid is not None else "__email2__"
            sent_by_key[key] = sent_by_key.get(key, 0) + 1
            if r.get("reply_time"):
                replies_by_key[key] = replies_by_key.get(key, 0) + 1
            cat = r.get("lead_category") or r.get("category")
            email = r.get("lead_email") or (
                (r.get("lead") or {}).get("email") if isinstance(r.get("lead"), dict)
                else r.get("email"))
            rt = str(r.get("reply_time") or "")
            if cat in POSITIVE_CATEGORIES:  # exact equality via set membership
                if email:
                    prev = best_positive.get(email)
                    if prev is None or rt > prev[0]:
                        best_positive[email] = (rt, key)
                else:
                    anon_positives[key] = anon_positives.get(key, 0) + 1
            if cat in MEETING_CATEGORIES:  # same dedup mechanics, narrower category set
                if email:
                    prev = best_meeting.get(email)
                    if prev is None or rt > prev[0]:
                        best_meeting[email] = (rt, key)
                else:
                    anon_meetings[key] = anon_meetings.get(key, 0) + 1
        if not rows:
            break
        offset += len(rows)
        if total is not None and offset >= total:
            break
        if len(rows) < STATS_PAGE and (total is None or offset >= total):
            break
    agg: dict = {}
    for key, sent in sent_by_key.items():
        agg[key] = {"sent": sent, "positives": 0, "replies": replies_by_key.get(key, 0), "meetings": 0}
    for _rt, key in best_positive.values():
        agg.setdefault(key, {"sent": 0, "positives": 0, "replies": 0, "meetings": 0})
        agg[key]["positives"] += 1
    for key, n in anon_positives.items():
        agg.setdefault(key, {"sent": 0, "positives": 0, "replies": 0, "meetings": 0})
        agg[key]["positives"] += n
    for _rt, key in best_meeting.values():
        agg.setdefault(key, {"sent": 0, "positives": 0, "replies": 0, "meetings": 0})
        agg[key]["meetings"] += 1
    for key, n in anon_meetings.items():
        agg.setdefault(key, {"sent": 0, "positives": 0, "replies": 0, "meetings": 0})
        agg[key]["meetings"] += n
    return agg


def reconcile_positives(agg: dict, campaign_positives: int) -> None:
    """Variant-level positives must never exceed the campaign-level count
    (skill data-accuracy rule). Trim from the largest buckets if needed.
    Meetings are a subset of positives (MEETING_CATEGORIES ⊂
    POSITIVE_CATEGORIES) so once positives are trimmed, cap each bucket's
    meetings at its own (possibly-just-trimmed) positives count too - a
    meeting can never outnumber the positives it's counted within."""
    total = sum(a["positives"] for a in agg.values())
    while total > campaign_positives and total > 0:
        worst = max(agg.values(), key=lambda a: a["positives"])
        if worst["positives"] == 0:
            break
        worst["positives"] -= 1
        total -= 1
    for a in agg.values():
        if a.get("meetings", 0) > a["positives"]:
            a["meetings"] = a["positives"]


# -- client mapping ----------------------------------------------------------

def infer_client(name: str) -> str:
    for needle, client in CLIENT_KEYWORDS:
        if needle.lower() in (name or "").lower():
            return client
    return "Unknown"


_CLIENTS_BY_NAME_CACHE: dict[str, str] | None = None
_UNMATCHED_CLIENTS: dict[str, int] = {}


def fetch_clients_by_name() -> dict:
    global _CLIENTS_BY_NAME_CACHE
    if _CLIENTS_BY_NAME_CACHE is not None:
        return _CLIENTS_BY_NAME_CACHE
    rows = sb("GET", "clients?select=id,name") or []
    by_name: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            cid, name = row.get("id"), row.get("name")
            if cid and name:
                by_name[name.strip().lower()] = CLIENT_ID_ALIAS.get(cid, cid)
    else:
        print("  ! could not fetch `clients` table for client_id resolution "
              "- all notifications this run will have client_id = NULL")
    _CLIENTS_BY_NAME_CACHE = by_name
    return by_name


def infer_client_id(client_name: str, campaign_name: str) -> str | None:
    by_name = fetch_clients_by_name()
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", client_name or "").strip()
    for candidate in (client_name, stripped, campaign_name):
        if not candidate:
            continue
        hit = by_name.get(candidate.strip().lower())
        if hit:
            return hit
    _UNMATCHED_CLIENTS[client_name or "Unknown"] = _UNMATCHED_CLIENTS.get(client_name or "Unknown", 0) + 1
    return None


# -- report maths ------------------------------------------------------------

def ratio(sent: int, positives: int):
    return round(sent / positives, 1) if positives > 0 else None


def ratio_txt(sent: int, positives: int) -> str:
    r = ratio(sent, positives)
    return f"{r:,.0f}" if r is not None else "inf"


def is_failing(sent: int, positives: int) -> bool:
    """REPLACE rule: 800+ sent with 0 positives, or < 1 positive per 800."""
    return sent >= JUDGE_MIN_SENT and (positives == 0 or positives * 800 < sent)


def is_performing_variant(sent: int, positives: int) -> bool:
    return positives > 0 and sent / positives <= PERFORMING_RATIO


def build_variants_list(ctx: dict) -> list[dict]:
    """Structured per-variant breakdown for Section 7's Why-expander table -
    one entry per key in variant_stats, INCLUDING the synthetic "__email2__"
    bucket and 0%-distribution variants (unlike build_campaign_findings'
    `judged` list, nothing here is filtered by the 800-send monitor
    threshold - a CSM should see every variant that has ANY sends). Unknown
    variant ids (no sequences meta - can't attribute an angle/label) are
    skipped, same rule as build_campaign_findings' judged-variant loop.
    Sorted by email step then variant label so the UI table reads top to
    bottom in sequence order."""
    variant_stats, variant_index = ctx["variant_stats"], ctx["variant_index"]
    out: list[dict] = []
    for key, stats in variant_stats.items():
        sent, positives = stats.get("sent", 0), stats.get("positives", 0)
        meetings, replies = stats.get("meetings", 0), stats.get("replies", 0)
        if key == "__email2__":
            # No variant_index meta for the synthetic Email 2 bucket, so
            # zero_distribution/disabled (both meta-derived) never apply -
            # but failing/winner only need sent/positives, so they still can.
            e2_flags = []
            if is_failing(sent, positives):
                e2_flags.append("failing")
            elif is_performing_variant(sent, positives):
                e2_flags.append("winner")
            out.append({"email": 2, "variant": None, "distribution_pct": None,
                        "sent": sent, "replies": replies, "positives": positives,
                        "meetings": meetings, "angle": None, "flags": e2_flags})
            continue
        meta = variant_index.get(key)
        if not meta:
            continue
        flags = []
        dist = meta["distribution_pct"]
        # null distribution means Smartlead didn't report a split, NOT 0% -
        # only an explicit 0 counts. 0 with no sends = split never configured
        # (Bug A); 0 with past sends = variant was turned off later.
        if dist == 0 and sent == 0:
            flags.append("zero_distribution")
        if meta["is_deleted"] or (dist == 0 and sent > 0):
            flags.append("disabled")
        # failing wins over winner - the two ratio rules overlap between
        # 800 and 1,500 sent/pos, and showing both would contradict itself
        if is_failing(sent, positives):
            flags.append("failing")
        elif is_performing_variant(sent, positives):
            flags.append("winner")
        out.append({"email": meta["seq_number"], "variant": meta["label"],
                    "distribution_pct": dist, "sent": sent, "replies": replies,
                    "positives": positives, "meetings": meetings, "angle": meta["angle"],
                    "flags": flags})
    # variants with ZERO sends never appear in /statistics at all, so the
    # stats loop above misses them - but a 0%-split 0-send variant is exactly
    # the Bug A case the table exists to surface. Add them from sequences meta.
    for key, meta in variant_index.items():
        if key in variant_stats:
            continue
        flags = []
        if meta["distribution_pct"] == 0:
            flags.append("zero_distribution")
        if meta["is_deleted"]:
            flags.append("disabled")
        out.append({"email": meta["seq_number"], "variant": meta["label"],
                    "distribution_pct": meta["distribution_pct"], "sent": 0,
                    "replies": 0, "positives": 0, "meetings": 0,
                    "angle": meta["angle"], "flags": flags})
    out.sort(key=lambda v: (v["email"] if v["email"] is not None else 0, v["variant"] or ""))
    return out


# -- claude_prompt assembly (STATIC, no LLM calls) ---------------------------

def variant_lines(judged: list[dict]) -> str:
    lines = []
    for v in judged:
        lines.append(f"- Email {v['seq_number']} Var {v['label']} ({v['sent']:,} sent, "
                     f"{v['positives']} pos, {ratio_txt(v['sent'], v['positives'])}/pos): {v['angle']}")
    return "\n".join(lines) if lines else "- (no variant has cleared the 800-send monitor phase yet)"


def build_claude_prompt(action_type: str, ctx: dict) -> str:
    """Assemble the skill's Section 5 pre-made Claude Code prompt as a static
    string from data already fetched. Begins with the mandatory scope block.
    Kept under 4000 chars."""
    client = ctx["client"]
    cinfo = CLIENT_CONTEXT.get(client, CLIENT_CONTEXT["Unknown"])
    name, cid = ctx["name"], ctx["cid"]
    sent, positives = ctx["sent"], ctx["positives"]
    comp = ctx["completion_pct"]
    comp_txt = f"{comp:.0f}% complete" if comp is not None else "completion unknown"
    url = SMARTLEAD_URL_TPL.format(cid=cid)
    status = (f"{sent:,} sent, {positives} positives, {comp_txt}. "
              f"Ratio {ratio_txt(sent, positives)}.")

    if action_type == "run_list_audit":
        body = (
            "/lilly-list-audit\n\n"
            f"{SCOPE_BLOCK}\n\n"
            f"Audit campaign {cid} ({name}).\n"
            f"URL: {url}\n"
            f"CLIENT: {client}\n"
            f"STATUS: {status} Reply rate {ctx['reply_rate']:.2f}% (under the 1% floor).\n"
            f"INTENDED ICP: {cinfo['persona']}\n\n"
            "TASK: Pull the enrolled leads, classify every title by function, and report "
            "on-ICP vs off-ICP with what is leaking in. An off-ICP list explains a sub-1% "
            "reply rate on its own; a clean on-target list points at deliverability instead "
            "(spam placement, sender reputation, warmup), which should be checked in parallel."
        )
        return clean_dashes_only(body)

    briefings = {
        "replace_variants": "replace the failing Email 1 variants (0 positives past 800+ sends)",
        "scale_winner": "scale the winning variant and draft one new challenger",
        "disable_loser": "disable the losing variant(s) and draft one new challenger",
        "kill_threshold_pivot": "kill-threshold pivot: ideate fresh mechanisms, the current one is not converting",
    }
    tasks = {
        "replace_variants": (
            "TASK: Draft new Email 1 variants (one per failed variant above). Each must use a "
            "completely different core pain point from the failed angles. Match the template "
            "format exactly. Only the problem/pain-point or offer angle changes."),
        "scale_winner": (
            f"TASK: {ctx.get('winner_line') or 'The winning variant is flagged above.'} "
            "Draft 1 new challenger variant at 20% distribution. Different problem angle from "
            "anything tried. Same template."),
        "disable_loser": (
            f"TASK: {ctx.get('loser_line') or 'The losing variant(s) are flagged above.'} "
            "Disable, never delete (deleted variants lose historical data). Draft 1 new "
            "challenger at 20% distribution with a different angle from anything tried."),
        "kill_threshold_pivot": (
            f"TASK: This campaign has hit the kill threshold ({sent:,}+ sends, ratio "
            f"{ratio_txt(sent, positives)}). The current mechanism is not converting. Ideate 3-5 "
            f"fresh mechanisms for this ICP ({cinfo['persona']}): different hook, offer framing, "
            "signal, or CTA style. Not just new variants of the same angle. CSM decision "
            "required before anything changes; do not act autonomously."),
    }
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(cinfo["rules"], 1))
    body = (
        "/lilly-copywriter\n\n"
        f"{SCOPE_BLOCK}\n\n"
        f"BRIEFING: {briefings[action_type]}\n\n"
        f"CLIENT: {client}\n"
        f"OFFER: {cinfo['offer']}\n"
        f"PERSONA: {cinfo['persona']}\n\n"
        f"ACTIVE CAMPAIGN: {name}\n"
        f"URL: {url}\n"
        f"STATUS: {status}\n\n"
        f"VARIANTS (cleared 800+ sends; angle = subject / first line):\n{ctx['variant_block']}\n\n"
        f"CLIENT COPY RULES - non-negotiable:\n{rules}\n\n"
        "TEMPLATE FORMAT - must match exactly:\n"
        "- Match the existing template: same length, structure, personalisation tokens, CTA style\n"
        "- Sign-off: %signature%\n"
        "- No em-dashes anywhere\n"
        "- Never use {{sender_name}} or {{sender_title}}\n\n"
        f"{tasks[action_type]}\n\n"
        "Reminder: NEVER use any sequence API tool to modify existing campaigns. All copy "
        "changes go via the Smartlead UI - draft copy here, the CSM pastes it in manually."
    )
    return clean_dashes_only(body)[:4000]


def clean_dashes_only(s: str) -> str:
    """Strip em/en dashes without collapsing the prompt's newlines."""
    return DASH_RE.sub("-", s)


# -- per-campaign report builder ----------------------------------------------

def row_base(ctx: dict) -> dict:
    return {
        "campaign_id": ctx["cid"], "campaign_name": ctx["name"],
        "client": ctx["client"], "client_id": ctx["client_id"],
        "smartlead_url": SMARTLEAD_URL_TPL.format(cid=ctx["cid"]),
        "sent": ctx["sent"], "positive": ctx["positives"], "replied": ctx.get("replies"),
        "sent_pos_ratio": ratio(ctx["sent"], ctx["positives"]),
        "completion_pct": ctx["completion_pct"], "reply_rate": ctx["reply_rate"],
        "api_safe": False, "block_number": None, "claude_prompt": None,
        "action_type": None,
        # every row must carry the same key set - PostgREST bulk upserts
        # reject mixed-key chunks (PGRST102), so non-section-7 rows send
        # variants explicitly as null rather than omitting the key
        "variants": None,
    }


def build_campaign_findings(ctx: dict) -> tuple[list[dict], list[dict]]:
    """Returns (section 1-6 rows, section-7 action candidates). Action
    candidates are dicts {tier, action_type, bullet, ...} rolled up into one
    Section 7 row per campaign by the caller (after global block numbering)."""
    rows: list[dict] = []
    actions: list[dict] = []
    cid, name = ctx["cid"], ctx["name"]
    sent, positives = ctx["sent"], ctx["positives"]
    comp = ctx["completion_pct"]
    r = ratio(sent, positives)
    variant_stats, variant_index = ctx["variant_stats"], ctx["variant_index"]

    # judged variants: Email 1+ variants with an id, not disabled, 800+ sent
    judged: list[dict] = []
    for key, stats in variant_stats.items():
        if key == "__email2__":
            continue
        meta = variant_index.get(key)
        if not meta:
            continue  # unknown variant id, cannot attribute - skip
        disabled = meta["is_deleted"] or (
            (meta["distribution_pct"] or 0) == 0 and stats["sent"] > 0)
        if disabled or stats["sent"] < JUDGE_MIN_SENT:
            continue
        judged.append({"key": key, **meta, **stats})
    email2 = variant_stats.get("__email2__")
    e1_judged = [v for v in judged if v["seq_number"] == 1]

    any_variant_failing = any(is_failing(v["sent"], v["positives"]) for v in judged) or (
        email2 is not None and is_failing(email2["sent"], email2["positives"]))
    kill = sent >= KILL_MIN_SENT and (positives == 0 or (r is not None and r >= KILL_RATIO))
    campaign_failing = positives == 0  # with the 1,500+ gate = whole offer failing

    # ---- Section 1/2: needs optimisation vs performing (mutually exclusive) --
    # Tier assignment is exclusive: a campaign that qualifies for Section 1
    # (failing variant OR ratio > 1,500) gets ONLY the section-1 row. Section 2
    # is ratio <= 1,500 AND NOT section-1-qualified. The failing-variant
    # context for a campaign that also has ratio <= 1,500 still lives in
    # Section 4 (variant_call rows), so nothing is lost by dropping the
    # Section 2 row for it.
    section1_qualifies = any_variant_failing or positives == 0 or (r is not None and r > PERFORMING_RATIO)
    if section1_qualifies:
        rows.append({**row_base(ctx), "finding_type": "needs_optimisation", "section": 1,
                     "priority": "High" if (kill or campaign_failing) else "Medium",
                     "title": "Needs optimisation",
                     "detail": clean_text(
                         f"Sent {sent:,}, Positive {positives}, Sent/Pos {ratio_txt(sent, positives)}."
                         + (" Kill threshold reached (15,000+ sent, ratio 2,500+)." if kill else "")
                         + (" At least one variant has 800+ sends with under 1 positive per 800."
                            if any_variant_failing else "")),
                     "suggested_action": "Review Section 7 recommended actions for this campaign"})
    elif r is not None and r <= PERFORMING_RATIO:
        rows.append({**row_base(ctx), "finding_type": "performing", "section": 2,
                     "priority": "Low", "title": "Performing",
                     "detail": clean_text(
                         f"Sent {sent:,}, Positive {positives}, Sent/Pos {ratio_txt(sent, positives)}. "
                         f"At or under the 1,500 sent-per-positive bar."),
                     "suggested_action": None})

    # ---- Section 3: lifecycle -----------------------------------------------
    if comp is not None and comp >= 40:
        lifecycle_action = "nearing_completion" if comp >= 95 else "upload_leads"
        title = "Nearing completion" if comp >= 95 else "Upload more leads"
        rows.append({**row_base(ctx), "finding_type": "lifecycle", "section": 3,
                     "priority": "Low", "title": title, "action_type": lifecycle_action,
                     "detail": clean_text(
                         f"Sent {sent:,}, Leads {ctx['total_leads']:,}, Completion {comp:.0f}% "
                         f"(sent / (leads x 2)). Status: {title}."),
                     "suggested_action": title})
        actions.append({"tier": "Low", "action_type": lifecycle_action,
                        "bullet": f"{title}: campaign is {comp:.0f}% complete "
                                  f"({sent:,} sent against {ctx['total_leads']:,} leads x 2)."})

    # ---- Section 4: variant analysis (only campaigns under 60% completion) --
    include_s4 = comp is None or comp < 60
    winner_line = loser_line = None
    if include_s4:
        # campaign-level failure rule: 1,500+ sent, zero positives
        if campaign_failing:
            sub800 = all(v["sent"] < JUDGE_MIN_SENT for v in judged) if judged else True
            detail = (f"{sent:,} sent with zero positives at campaign level - the whole offer "
                      f"is failing" + (", and every variant is still under 800 sends, so this is "
                                       "flagged at campaign level rather than per variant."
                                       if sub800 and not judged else
                                       ". All active variants are implicated, including early ones."))
            rows.append({**row_base(ctx), "finding_type": "variant_call", "section": 4,
                         "priority": "High", "title": "Whole offer failing",
                         "action_type": "replace_variants",
                         "detail": clean_text(detail),
                         "suggested_action": "Replace the offer angle across all variants"})
            actions.append({"tier": "High", "action_type": "replace_variants",
                            "bullet": f"Whole offer failing: {sent:,} sent, 0 positives at campaign "
                                      "level. Draft replacement angles for every active variant."})
        else:
            # per-variant calls on judged Email 1+ variants
            failing = [v for v in judged if is_failing(v["sent"], v["positives"])]
            # clear winner: positives, ratio at most half of every other judged
            # sibling with positives, at least one other judged sibling
            winner = None
            with_pos = [v for v in judged if v["positives"] > 0]
            if len(judged) > 1 and with_pos:
                best = min(with_pos, key=lambda v: v["sent"] / v["positives"])
                br = best["sent"] / best["positives"]
                others = [v for v in with_pos if v["key"] != best["key"]]
                if br <= PERFORMING_RATIO and (
                        not others or all(br * 2 <= o["sent"] / o["positives"] for o in others)) and (
                        others or any(v["positives"] == 0 for v in judged if v["key"] != best["key"])):
                    winner = best
            for v in failing:
                # Disabling only makes sense if there's another currently-active
                # (distribution > 0, not deleted) variant on the SAME sequence
                # step to absorb the traffic. Scope both the "does a sibling
                # perform" check and the "is there any active sibling at all"
                # check to v's own step - a performing variant on a different
                # email step must never make this variant look like it has a
                # sibling to fall back on.
                step_sibs_active = any(
                    vid != v["key"] and meta["seq_number"] == v["seq_number"]
                    and not meta["is_deleted"] and (meta["distribution_pct"] or 0) > 0
                    for vid, meta in variant_index.items())
                sib_performing = any(
                    s["key"] != v["key"] and s["seq_number"] == v["seq_number"]
                    and is_performing_variant(s["sent"], s["positives"])
                    for s in judged)
                if v["positives"] == 0 and sib_performing and step_sibs_active:
                    call, a_type, prio = "Clear loser - disable", "disable_loser", "Medium"
                    bullet = (f"Disable Email {v['seq_number']} Var {v['label']} "
                              f"({v['sent']:,} sent, 0 positives while siblings perform). "
                              "Disable only, never delete.")
                    loser_line = (f"Email {v['seq_number']} Var {v['label']} needs disabling "
                                  f"({v['sent']:,} sent, 0 positives while siblings perform).")
                    rewrite_note = ""
                elif not step_sibs_active:
                    # sole active variant on its step - there is no sibling to
                    # absorb traffic, so this is a rewrite, not a disable.
                    call, a_type, prio = "REPLACE", "replace_variants", "High"
                    rewrite_note = (
                        " The follow-up copy has failed and needs rewriting."
                        if v["seq_number"] >= 2 else
                        " The copy has failed and needs rewriting.")
                    bullet = (f"Rewrite Email {v['seq_number']} Var {v['label']} "
                              f"({v['sent']:,} sent, {v['positives']} pos, "
                              f"{ratio_txt(v['sent'], v['positives'])}/pos) - it is the only active "
                              "variant on this step, so there is no sibling to absorb traffic. "
                              "The copy has failed and needs rewriting.")
                else:
                    call, a_type, prio = "REPLACE", "replace_variants", "High"
                    rewrite_note = ""
                    bullet = (f"Replace Email {v['seq_number']} Var {v['label']} "
                              f"({v['sent']:,} sent, {v['positives']} pos, "
                              f"{ratio_txt(v['sent'], v['positives'])}/pos - under 1 positive per 800).")
                rows.append({**row_base(ctx), "finding_type": "variant_call", "section": 4,
                             "priority": prio, "action_type": a_type,
                             "title": f"Variant call: Email {v['seq_number']} Var {v['label']}",
                             "detail": clean_text(
                                 f"{v['sent']:,} sent, {v['positives']} positive "
                                 f"({ratio_txt(v['sent'], v['positives'])}/pos). {call}."
                                 f"{rewrite_note} "
                                 f"Angle: {v['angle']}"),
                             "suggested_action": call,
                             "sent": v["sent"], "positive": v["positives"],
                             "sent_pos_ratio": ratio(v["sent"], v["positives"])})
                actions.append({"tier": prio if prio == "High" else "Medium",
                                "action_type": a_type, "bullet": bullet})
            if winner is not None and winner not in failing:
                wr = ratio_txt(winner["sent"], winner["positives"])
                rows.append({**row_base(ctx), "finding_type": "variant_call", "section": 4,
                             "priority": "Medium", "action_type": "scale_winner",
                             "title": f"Variant call: Email {winner['seq_number']} Var {winner['label']} (winner)",
                             "detail": clean_text(
                                 f"{winner['sent']:,} sent, {winner['positives']} positive ({wr}/pos) - "
                                 f"materially outperforming siblings. Scale it, build new variants on "
                                 f"this angle, disable the losers. Angle: {winner['angle']}"),
                             "suggested_action": "Scale winner",
                             "sent": winner["sent"], "positive": winner["positives"],
                             "sent_pos_ratio": ratio(winner["sent"], winner["positives"])})
                actions.append({"tier": "Medium", "action_type": "scale_winner",
                                "bullet": f"Scale Email {winner['seq_number']} Var {winner['label']} "
                                          f"(winner at {wr} sends/positive); build new variants on its "
                                          "angle and add one challenger at 20%."})
                winner_line = (f"Email {winner['seq_number']} Var {winner['label']} is the winner at "
                               f"{wr} sends/positive.")
            # Email 2 analysis (own row, same 800 threshold)
            if email2 and email2["sent"] >= JUDGE_MIN_SENT:
                e2r = ratio(email2["sent"], email2["positives"])
                if is_failing(email2["sent"], email2["positives"]):
                    rows.append({**row_base(ctx), "finding_type": "variant_call", "section": 4,
                                 "priority": "High", "action_type": "replace_variants",
                                 "title": "Variant call: Email 2",
                                 "detail": clean_text(
                                     f"Email 2: {email2['sent']:,} sent, {email2['positives']} positive "
                                     f"({ratio_txt(email2['sent'], email2['positives'])}/pos). The follow-up "
                                     "copy has failed on its own merits and needs rewriting."),
                                 "suggested_action": "Rewrite Email 2",
                                 "sent": email2["sent"], "positive": email2["positives"],
                                 "sent_pos_ratio": e2r})
                    actions.append({"tier": "High", "action_type": "replace_variants",
                                    "bullet": f"Rewrite Email 2 ({email2['sent']:,} sent, "
                                              f"{email2['positives']} positives past the 800-send bar)."})
                else:
                    # flip rule: Email 2 clearly outperforming Email 1
                    e1_best = None
                    e1_with_pos = [v for v in e1_judged if v["positives"] > 0]
                    if e1_with_pos:
                        e1_best = min(v["sent"] / v["positives"] for v in e1_with_pos)
                    if email2["positives"] > 0 and e2r is not None and (
                            (e1_best is None and e1_judged) or
                            (e1_best is not None and e2r * 1.5 <= e1_best)):
                        rows.append({**row_base(ctx), "finding_type": "variant_call", "section": 4,
                                     "priority": "Medium", "action_type": "replace_variants",
                                     "title": "Variant call: Email 2 (flip)",
                                     "detail": clean_text(
                                         f"Email 2 ({email2['sent']:,} sent, {email2['positives']} pos, "
                                         f"{ratio_txt(email2['sent'], email2['positives'])}/pos) is clearly "
                                         "outperforming Email 1. Unusual. Recommend flipping: Email 2 offer "
                                         "becomes the new Email 1, write a fresh Email 2 with the opposite "
                                         "CTA style. Await CSM approval."),
                                     "suggested_action": "Flip Email 2 to Email 1 (CSM approval)",
                                     "sent": email2["sent"], "positive": email2["positives"],
                                     "sent_pos_ratio": e2r})
                        actions.append({"tier": "Medium", "action_type": "replace_variants",
                                        "bullet": "Email 2 is outperforming Email 1: flag the flip to the "
                                                  "CSM (Email 2 offer becomes new Email 1, fresh Email 2 "
                                                  "with opposite CTA style)."})

    # ---- Section 5: low reply rate flag -------------------------------------
    if ctx["reply_rate"] is not None and ctx["reply_rate"] < 1.0:
        rows.append({**row_base(ctx), "finding_type": "low_reply_flag", "section": 5,
                     "priority": "Medium", "action_type": "run_list_audit",
                     "title": "Low reply rate flag",
                     "detail": clean_text(
                         f"Reply rate {ctx['reply_rate']:.2f}% ({ctx['replies']} replies on {sent:,} "
                         "sent) - under the 1% floor. Two usual causes: wrong recipients (off-ICP "
                         "list) or deliverability (spam placement, sender reputation, warmup). "
                         "Run lilly-list-audit to confirm the enrolled leads match the intended "
                         "persona, and check deliverability in parallel."),
                     "suggested_action": "Run lilly-list-audit + check deliverability"})
        actions.append({"tier": "Medium", "action_type": "run_list_audit",
                        "bullet": f"Reply rate {ctx['reply_rate']:.2f}% (under 1%): run a lead list "
                                  "audit (lilly-list-audit) to confirm the right people are enrolled, "
                                  "and check deliverability (spam placement, reputation, warmup) in "
                                  "parallel."})

    # ---- Section 6: variant distribution flags ------------------------------
    email2_has_null_sends = bool(email2 and email2["sent"] > 0)
    for vid, meta in variant_index.items():
        if meta["is_deleted"]:
            continue
        v_sent = variant_stats.get(vid, {}).get("sent", 0)
        dist = meta["distribution_pct"]
        bug = None
        if (dist or 0) == 0 and v_sent == 0:
            bug = ("Bug A", "0% distribution, 0 sends - the traffic split was never configured "
                            "for this variant in the UI.")
        elif dist and dist > 0 and v_sent == 0:
            if meta["seq_number"] >= 2 and email2_has_null_sends:
                continue  # sends recorded without variant ids - cannot prove Bug B
            bug = ("Bug B", f"{dist}% distribution but 0 sends despite the campaign actively "
                            "sending - the variant is broken in the UI.")
        if not bug:
            continue
        rows.append({**row_base(ctx), "finding_type": "distribution_flag", "section": 6,
                     "priority": "Medium", "action_type": "fix_distribution",
                     "title": f"Distribution flag: Email {meta['seq_number']} Var {meta['label']}",
                     "detail": clean_text(f"{bug[0]}: {bug[1]} Angle: {meta['angle']}"),
                     "suggested_action": "Fix the traffic split in the Smartlead UI",
                     "sent": v_sent, "positive": None, "sent_pos_ratio": None})
        actions.append({"tier": "Medium", "action_type": "fix_distribution",
                        "bullet": f"{bug[0]} on Email {meta['seq_number']} Var {meta['label']}: {bug[1]} "
                                  "Fix: set the correct traffic split in the Smartlead UI so every "
                                  "intended variant has a non-zero share."})

    # ---- kill threshold (feeds Section 7 at High) ----------------------------
    if kill:
        slug = CLIENT_SLUG.get(ctx["client"], "unknown")
        actions.append({"tier": "High", "action_type": "kill_threshold_pivot",
                        "bullet": (f"Kill threshold reached ({sent:,} sent, ratio "
                                   f"{ratio_txt(sent, positives)}, threshold 15,000+ sent at 2,500+/pos). "
                                   "This ICP likely is not working. Recommend a pivot (new ICP, adjusted "
                                   "targeting, or different channel). Pausing the campaign is the only "
                                   "API-safe act; the pivot itself is CSM ideation - await CSM decision, "
                                   "do not act autonomously. "
                                   f"Consider /lilly-strategy {slug} to ideate replacement angles.")})

    ctx["winner_line"], ctx["loser_line"] = winner_line, loser_line
    ctx["variant_block"] = variant_lines(judged) + (
        f"\n- Email 2 ({email2['sent']:,} sent, {email2['positives']} pos, "
        f"{ratio_txt(email2['sent'], email2['positives'])}/pos): follow-up step"
        if email2 and email2["sent"] >= JUDGE_MIN_SENT else "")
    return rows, actions


# Section 7 primary-action precedence (first match wins)
ACTION_PRECEDENCE = ["kill_threshold_pivot", "replace_variants", "scale_winner",
                     "disable_loser", "fix_distribution", "run_list_audit",
                     "upload_leads", "nearing_completion"]
TIER_ORDER = {"High": 0, "Medium": 1, "Low": 2}
PROMPTED_ACTIONS = {"replace_variants", "scale_winner", "disable_loser",
                    "kill_threshold_pivot", "run_list_audit"}


def build_section7(campaign_actions: list[tuple[dict, list[dict]]]) -> list[dict]:
    """One recommended_action row per campaign with any action; block_number
    assigned sequentially across the section after ordering High > Medium >
    Low, within tier by sent desc."""
    blocks = []
    for ctx, actions in campaign_actions:
        if not actions:
            continue
        tier = min((a["tier"] for a in actions), key=lambda t: TIER_ORDER[t])
        primary = next(a for at in ACTION_PRECEDENCE
                       for a in actions if a["action_type"] == at)
        bullets = "\n".join(f"- {a['bullet']}" for a in actions)
        header = (f"{ctx['name']} - {ctx['client']} | {ctx['sent']:,} sent, "
                  f"{ctx['positives']} pos, "
                  + (f"{ctx['completion_pct']:.0f}% complete" if ctx['completion_pct'] is not None
                     else "completion unknown")
                  + f"\nPriority: {tier}\n\n")
        prompt = (build_claude_prompt(primary["action_type"], ctx)
                  if primary["action_type"] in PROMPTED_ACTIONS else None)
        blocks.append((tier, ctx, primary["action_type"], header + bullets, prompt))
    blocks.sort(key=lambda b: (TIER_ORDER[b[0]], -b[1]["sent"]))
    rows = []
    for n, (tier, ctx, a_type, detail, prompt) in enumerate(blocks, 1):
        rows.append({**row_base(ctx), "finding_type": "recommended_action", "section": 7,
                     "priority": tier, "title": "Recommended actions",
                     "detail": clean_dashes_only(detail),
                     "suggested_action": a_type.replace("_", " "),
                     "action_type": a_type,
                     "api_safe": a_type in ("pause_campaign", "kill_threshold_pivot"),
                     "block_number": n, "claude_prompt": prompt,
                     "variants": ctx.get("variants_list")})
    return rows


# -- upsert -------------------------------------------------------------------

def upsert_findings(rows: list[dict]) -> int:
    """Upsert in chunks. status/created_at/actioned_at are deliberately left
    out of every row so a rerun never resets CSM state or the original
    created_at - see the module docstring."""
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
            print(f"  ! upsert chunk {i // chunk_size + 1} failed - see error above")
        else:
            total += len(chunk)
    return total


# -- retirement pass ----------------------------------------------------------
# The report regenerates fresh every run, but the upsert only ever adds/updates
# rows for keys this run still emits - a finding that stops firing (campaign
# paused, variant fixed, completion moved on, etc.) has no representation in
# `all_rows` at all, so without this pass its row would just sit at whatever
# status it last had forever. This pass diffs the emitted-key set against the
# table's actual state and does exactly two things, neither of which ever
# touches a CSM-owned status (acknowledged/actioned/dismissed):
#   1. a 'new' row whose key is NOT emitted this run -> 'resolved'
#   2. a 'resolved' row whose key IS emitted this run (it came back) -> 'new'
# `status` is deliberately never part of the general upsert body (see
# upsert_findings' docstring) - both transitions here are separate, explicit
# PATCHes so they can never clobber acknowledged/actioned/dismissed state.

PATCH_CHUNK = 100  # ids per `id=in.(...)` PATCH - stays well under any URL length limit


def fetch_all_notification_keys() -> list[dict]:
    """GET id,campaign_id,finding_type,title,status for every row currently in
    the table, paginated. Returns [] (with a warning) if the table can't be
    read, so the retirement pass safely no-ops rather than mass-resolving
    everything on a transient fetch failure."""
    rows_all: list[dict] = []
    offset, page_size = 0, 1000
    while True:
        page = sb("GET", f"{TABLE}?select=id,campaign_id,finding_type,title,status"
                          f"&order=id&limit={page_size}&offset={offset}")
        if not isinstance(page, list):
            print("  ! could not fetch existing notification rows for the retirement pass "
                  "- skipping retirement this run (no rows will be resolved or revived).")
            return []
        rows_all.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows_all


def bulk_patch_status(ids: list[str], new_status: str) -> int:
    """PATCH status for a list of row ids via chunked PostgREST id=in.(...)
    filters. Body carries ONLY {"status": new_status} - never touches any
    other column, so created_at/actioned_at/etc are left exactly as they are."""
    if not ids:
        return 0
    total = 0
    for i in range(0, len(ids), PATCH_CHUNK):
        chunk = ids[i:i + PATCH_CHUNK]
        id_list = ",".join(str(x) for x in chunk)
        result = sb("PATCH", f"{TABLE}?id=in.({id_list})", {"status": new_status},
                    prefer="return=minimal")
        failed = result is None or (isinstance(result, dict) and result.get("_error"))
        if failed:
            print(f"  ! retirement PATCH to status={new_status} failed for chunk "
                  f"{i // PATCH_CHUNK + 1} ({len(chunk)} ids) - see error above")
        else:
            total += len(chunk)
    return total


def run_retirement_pass(emitted_keys: set) -> tuple[int, int, list[dict]]:
    """Diff the table's actual state against this run's emitted keys. Returns
    (resolved_count, revived_count, resolved_rows) - resolved_rows is the list
    of {id, campaign_id, finding_type, title} that got flipped to 'resolved',
    for the caller to report by id/title."""
    existing = fetch_all_notification_keys()
    if not existing:
        return 0, 0, []

    def key_of(row: dict) -> tuple:
        return (row.get("campaign_id"), row.get("finding_type"), row.get("title"))

    stale_rows = [r for r in existing if r.get("status") == "new" and key_of(r) not in emitted_keys]
    reappeared_rows = [r for r in existing if r.get("status") == "resolved" and key_of(r) in emitted_keys]

    resolved_n = bulk_patch_status([r["id"] for r in stale_rows], "resolved")
    revived_n = bulk_patch_status([r["id"] for r in reappeared_rows], "new")
    return resolved_n, revived_n, stale_rows


# -- main ---------------------------------------------------------------------

def main() -> int:
    """Runs the full optimiser-notifications generation. Returns the number of
    rows upserted on success. Raises RuntimeError on failure (e.g. table could
    not be created/verified) so a programmatic caller (app/run_daily.py) can
    catch it, log, and record a failed run without killing its own process.
    The CLI entry point below still exits non-zero on that same failure."""
    if not ensure_table():
        raise RuntimeError(f"could not ensure `{TABLE}` table exists - see log above")
    if "--reset-once" in sys.argv:
        wipe_all_rows()

    active = fetch_active_campaigns()
    all_rows: list[dict] = []
    campaign_actions: list[tuple[dict, list[dict]]] = []
    in_report = all_clear = 0

    for i, c in enumerate(active, 1):
        cid = str(c["id"])
        name = clean_text(c.get("name") or f"Campaign {c['id']}")
        print(f"[{i}/{len(active)}] {name} ({cid})", flush=True)
        analytics = fetch_analytics(c["id"])
        sent, positives = analytics["sent"], analytics["positives"]
        client = infer_client(name)
        ctx = {
            "cid": cid, "name": name, "client": client,
            "client_id": infer_client_id(client, name),
            "sent": sent, "positives": positives, "replies": analytics["replies"],
            "reply_rate": round(analytics["replies"] / sent * 100, 2) if sent else None,
            "completion_pct": None, "total_leads": 0,
            "variant_stats": {}, "variant_index": {},
        }
        if sent < REPORT_MIN_SENT:
            all_clear += 1
            all_rows.append({**row_base(ctx), "finding_type": "all_clear", "section": 0,
                             "priority": "Low", "title": "All clear",
                             "detail": clean_text(
                                 f"{sent:,} sent, {positives} positive. Below the 1,500-send "
                                 "reporting threshold - not yet in the Priority Report."),
                             "suggested_action": None, "action_type": "none"})
            continue
        in_report += 1
        total_leads = fetch_total_leads(c["id"])
        ctx["total_leads"] = total_leads
        if total_leads > 0:
            ctx["completion_pct"] = round(sent / (total_leads * 2) * 100, 1)
        ctx["variant_index"] = fetch_sequences(c["id"])
        ctx["variant_stats"] = fetch_variant_stats(c["id"])
        reconcile_positives(ctx["variant_stats"], positives)
        ctx["variants_list"] = build_variants_list(ctx)
        rows, actions = build_campaign_findings(ctx)
        all_rows.extend(rows)
        campaign_actions.append((ctx, actions))

    all_rows.extend(build_section7(campaign_actions))

    by_section: dict[int, int] = {}
    for row in all_rows:
        by_section[row["section"]] = by_section.get(row["section"], 0) + 1
    print(f"\n{len(active)} active campaigns: {in_report} in report, {all_clear} all_clear")
    for s in sorted(by_section):
        print(f"  section {s}: {by_section[s]} rows")
    s7 = [r for r in all_rows if r["section"] == 7]
    prio = {}
    for r in s7:
        prio[r["priority"]] = prio.get(r["priority"], 0) + 1
    print(f"  section 7 blocks: {len(s7)} ({', '.join(f'{k}={v}' for k, v in sorted(prio.items()))})")
    print(f"  claude_prompt rows: {sum(1 for r in all_rows if r.get('claude_prompt'))}, "
          f"api_safe rows: {sum(1 for r in all_rows if r.get('api_safe'))}")

    upserted = upsert_findings(all_rows)
    print(f"\nUpserted {upserted} rows into `{TABLE}` (run date {date.today().isoformat()}).")

    emitted_keys = {(r["campaign_id"], r["finding_type"], r["title"]) for r in all_rows}
    resolved_n, revived_n, resolved_rows = run_retirement_pass(emitted_keys)
    print(f"\nRetirement pass: {resolved_n} row(s) resolved (no longer emitted this run), "
          f"{revived_n} row(s) revived new -> resolved rows that reappeared.")
    for r in resolved_rows[:50]:
        print(f"  resolved: id={r['id']} campaign_id={r['campaign_id']} "
              f"finding_type={r['finding_type']} title={r['title']!r}")
    if len(resolved_rows) > 50:
        print(f"  ... and {len(resolved_rows) - 50} more")

    if _UNMATCHED_CLIENTS:
        print("\nclient_id unmatched (free-text `client` value -> finding rows this run, "
              "written with client_id = NULL, `client` text unaffected):")
        for name, n in sorted(_UNMATCHED_CLIENTS.items(), key=lambda kv: -kv[1]):
            print(f"  {name!r}: {n}")

    return upserted


if __name__ == "__main__":
    faulthandler.enable()  # surface silent hard crashes in stderr
    try:
        main()
    except Exception as e:  # noqa: BLE001 — CLI still exits non-zero on failure
        sys.exit(f"error: {e}")
