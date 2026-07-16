#!/usr/bin/env python3
"""Static file server + tiny provider-search API for the Navreo prototype.

Serves the project directory (same as `python3 -m http.server`) plus a
/api/* surface the source wizards call:

  POST /api/preview/hiring     TheirStack jobs search, blurred = FREE
  POST /api/preview/companies  Prospeo /search-company page 1 (1 credit)
  POST /api/preview/lookalike  Prospeo ICP-text lookalike page 1 (1 credit)
  GET  /api/sources            read saved draft sources
  POST /api/sources            save a draft source (local JSON only)

Provider calls are SEARCHES ONLY — nothing is written to any external
system. The only write is app/data/draft_sources.json on this machine.

Run:  python3 app/server.py [port]     (default 7901)
"""

import contextlib
import threading
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certifi

import mock_deliv  # DELIV_MOCK — in-memory fake fleet, only ever called when DELIV_MOCK=1
import setter  # Setter tab (appointment-setter agents) — configured below, once sb/http_json/log_activity exist

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DRAFTS = APP_DIR / "data" / "draft_sources.json"       # legacy path, kept only as read fallback
CAMPAIGN_DRAFTS = APP_DIR / "data" / "campaign_drafts.json"  # legacy path, kept only as read fallback
CLIENTS = APP_DIR / "data" / "clients.json"                 # legacy path, kept only as read fallback

_DRAFTS_LOCK = threading.Lock()


@contextlib.contextmanager
def drafts_lock():
    """Process-local mutex for drafts read-modify-write. Operational state now
    lives in Postgres (per-row upserts via sb), so this serialises concurrent
    HTTP handlers in one process; the daily runner is a separate process and
    relies on the DB's atomic per-row upserts. Acquire ONLY at entry points
    (do_POST, runners) - it does not nest."""
    with _DRAFTS_LOCK:
        yield


# ── operational state <-> Postgres (id + jsonb doc tables) ───────────────
# campaign_drafts / sources / clients / role_feedback are authoritative in
# Supabase. These helpers are the ONLY code that touches that state; the
# legacy JSON files remain as a read-only fallback if Supabase is unreachable.

class SupabaseUnavailable(RuntimeError):
    """An authoritative read failed on a WRITE path. Raising (instead of quietly
    returning a stale/empty snapshot) aborts the mutation, so a momentary
    Supabase outage can never be turned into a whole-table replace that deletes
    every row. Surfaced to the UI by do_POST as a plain 'try again' message."""


def _pg_docs(table: str, only_doc: bool = False, strict: bool = False) -> list | None:
    """All doc payloads from a jsonb-doc table. A non-list means Supabase was
    unreachable: read-only callers get None (and fall back to the frozen JSON
    file); write callers pass strict=True and get a SupabaseUnavailable raise so
    they abort rather than persist an empty snapshot."""
    q = f"{table}?select=doc" + ("&doc=not.is.null" if only_doc else "")
    rows = sb("GET", q)
    if not isinstance(rows, list):
        if strict:
            raise SupabaseUnavailable(
                "Couldn't reach the database - nothing was changed. Please try again.")
        return None
    return [r["doc"] for r in rows if isinstance(r, dict) and r.get("doc") is not None]


def _pg_replace(table: str, docs: list, only_doc: bool = False):
    """Persist a doc list to a jsonb-doc table. Upserts every doc, then deletes
    ONLY the rows the live table still has that the caller's list no longer
    contains — reconciled against a FRESH read of the current ids, never against
    the caller's list in isolation.

    Fail-safe by construction: if the caller's list is empty, or the fresh read
    can't confirm the live state, NOTHING is deleted (upserts still stand). That
    closes the data-loss bug where a transient Supabase read failure made the
    caller's list empty and the old blanket `DELETE id=not.is.null` wiped the
    whole table (a whole campaign vanished on returning to the homepage).
    Genuine 'delete the last row' cases use explicit sb_delete_doc()."""
    rows, ids = [], []
    for d in docs:
        if not d.get("id"):
            continue
        row = {"id": d["id"], "doc": d}
        if table == "clients":
            row["name"] = d.get("name")
        rows.append(row)
        ids.append(str(d["id"]))
    if rows:
        sb("POST", f"{table}?on_conflict=id", rows,
           prefer="resolution=merge-duplicates,return=minimal")
    if not ids:
        return  # an empty list is never how these tables are legitimately cleared
    scope = "&doc=not.is.null" if only_doc else ""
    current = sb("GET", f"{table}?select=id{scope}")
    if not isinstance(current, list):
        return  # can't confirm the live state -> upserts stand, delete nothing
    keep = set(ids)
    stale = [str(r["id"]) for r in current
             if isinstance(r, dict) and r.get("id") is not None and str(r["id"]) not in keep]
    if stale:
        sb("DELETE", f"{table}?id=in.({','.join(stale)})")


def thread_abandoned() -> bool:
    """True when the daily-run watchdog has already given up on THIS thread.

    `_timed()` abandons a source at SOURCE_S but cannot kill the daemon thread —
    it keeps running, and minutes later reaches its persist step holding a
    `drafts` snapshot read before every source that has since completed. Writing
    that snapshot rolls those sources back (2026-07-08: an abandoned engagement
    thread reverted a sibling source's `prospects` from 145 to 112, and its
    `last_pull` from 18:13 back to 15:05). A write that loses a race it does not
    know it is in must not happen at all, so abandoned threads persist nothing.

    signal_leads writes are deliberately NOT gated: they are per-row upserts on a
    natural key, they cannot clobber a sibling, and persisting them is the whole
    point of writing leads inside the qualify loop."""
    ev = getattr(threading.current_thread(), "_navreo_abandoned", None)
    return bool(ev is not None and ev.is_set())


def write_source(src: dict):
    """Persist ONE source doc. The single-row counterpart to write_drafts().

    Every pull mutates exactly one source but used to persist the whole list via
    `_pg_replace("sources", …)`, which upserts EVERY doc the caller is holding —
    so two overlapping pulls silently overwrote each other's `prospects`. Writing
    only the row we changed makes concurrent pulls of different sources
    commutative, which is the property the daily run actually needs."""
    if not src or not src.get("id"):
        return
    if thread_abandoned():
        print(f"[persist] abandoned thread - not writing source {src['id']}", file=sys.stderr)
        return
    sb("POST", "sources?on_conflict=id", [{"id": src["id"], "doc": src}],
       prefer="resolution=merge-duplicates,return=minimal")


def write_sources(srcs: list):
    """Persist SEVERAL source docs by id — a campaign-level edit touching each of
    its sources. Still row-scoped: sources this call never looked at are untouched,
    which a whole-list `_pg_replace` could not promise."""
    rows = [{"id": s["id"], "doc": s} for s in srcs if s and s.get("id")]
    if not rows:
        return
    if thread_abandoned():
        print(f"[persist] abandoned thread - not writing {len(rows)} source(s)", file=sys.stderr)
        return
    sb("POST", "sources?on_conflict=id", rows,
       prefer="resolution=merge-duplicates,return=minimal")


def write_drafts(data, path: Path | None = None):
    """Persist a full source/campaign list to Postgres (routed by which legacy
    path constant the caller passed). Unknown paths fall back to a file.

    Whole-list write: only for add/remove/reorder, where the list itself is the
    thing that changed. To persist edits to ONE source use write_source()."""
    p = path or DRAFTS
    if p == DRAFTS:
        if thread_abandoned():  # see thread_abandoned(): a stale snapshot must never land
            print("[persist] abandoned thread - not writing the sources list", file=sys.stderr)
            return
        _pg_replace("sources", data)
    elif p == CAMPAIGN_DRAFTS:
        _pg_replace("campaign_drafts", data)
    else:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, p)
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
UA = "navreo-prototype/1.0 (curl-compatible)"


def load_keys() -> dict:
    """Secrets, env-first with a local-file fallback. On Render every key is an
    environment variable; locally `~/.navreo-keys.env` still works, and any env
    var of the same name overrides the file."""
    keys = {}
    env_file = Path.home() / ".navreo-keys.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            m = re.match(r"^(?:export\s+)?([A-Z0-9_]+)=(\S+)", line.strip())
            if m:
                keys[m.group(1)] = m.group(2).strip("\"'")
    # environment wins (Render injects secrets as env vars; no file needed)
    for k, v in os.environ.items():
        if v and (k in keys or re.search(r"(_KEY|_TOKEN|_URL)$", k)):
            keys[k] = v
    return keys


KEYS = load_keys()


def http_json(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            raw = resp.read().decode()
            # A 2xx with an empty body (PostgREST `return=minimal`, HTTP 204) is
            # SUCCESS, not a failure — returning {} here stops sb() from mis-reading
            # it as a JSONDecodeError and firing a pointless retry. Under load
            # (rapid per-chunk job persists) those phantom retries pile up and can
            # saturate the server, so this guard is a real fix, not cosmetic.
            if not raw.strip():
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        # providers return JSON bodies (NO_RESULTS, INVALID_FILTERS...) on 4xx
        try:
            return json.loads(e.read().decode())
        except ValueError:
            raise e


# ── shared normalisers (country codes, domains, headcount) ───────────────

COUNTRY_CODE = {
    # NB: an unmapped country name used to be passed straight through to
    # TheirStack as a bogus "code" (COUNTRY_CODE.get(c, c)), which rejects the
    # WHOLE multi-country search and silently returns zero jobs. Keep this list
    # broad, and route every lookup through country_codes() which DROPS anything
    # it can't map rather than poisoning the query. Aliases welcome.
    "United States": "US", "USA": "US", "US": "US", "United States of America": "US",
    "United Kingdom": "GB", "UK": "GB", "Great Britain": "GB", "England": "GB",
    "Canada": "CA", "Australia": "AU", "New Zealand": "NZ", "Ireland": "IE",
    "Germany": "DE", "Netherlands": "NL", "The Netherlands": "NL", "Holland": "NL",
    "Switzerland": "CH", "Austria": "AT", "Belgium": "BE", "Luxembourg": "LU",
    "France": "FR", "Spain": "ES", "Italy": "IT", "Portugal": "PT",
    "Sweden": "SE", "Norway": "NO", "Denmark": "DK", "Finland": "FI", "Iceland": "IS",
    "Poland": "PL", "Czechia": "CZ", "Czech Republic": "CZ", "Slovakia": "SK",
    "Hungary": "HU", "Romania": "RO", "Bulgaria": "BG", "Greece": "GR",
    "Estonia": "EE", "Latvia": "LV", "Lithuania": "LT", "Croatia": "HR", "Slovenia": "SI",
    "Singapore": "SG", "Hong Kong": "HK", "Japan": "JP", "India": "IN",
    "United Arab Emirates": "AE", "UAE": "AE", "Saudi Arabia": "SA", "Israel": "IL",
    "South Africa": "ZA", "Mexico": "MX", "Brazil": "BR", "Argentina": "AR",
    "Jamaica": "JM", "Nigeria": "NG",
}
# case-insensitive lookup (source data arrives in mixed case)
_COUNTRY_CODE_LC = {k.lower(): v for k, v in COUNTRY_CODE.items()}


def country_codes(names) -> tuple[list[str], list[str]]:
    """Free-text country names -> ISO-3166 alpha-2 codes for TheirStack.
    Case-insensitive + alias-aware. Returns (codes, dropped): names we cannot
    map are DROPPED, never passed through as a bogus code (one bad name zeroes
    out the entire multi-country job search). Callers surface `dropped`."""
    codes: list[str] = []
    dropped: list[str] = []
    for n in (names or []):
        key = str(n).strip()
        if not key:
            continue
        code = COUNTRY_CODE.get(key) or _COUNTRY_CODE_LC.get(key.lower())
        if code and code not in codes:
            codes.append(code)
        elif not code and key not in dropped:
            dropped.append(key)
    return codes, dropped


TITLE_VARIANTS = {
    "founder": ["Founder", "Co-Founder", "Owner", "Co-Owner", "Founding Partner"],
    "ceo": ["CEO", "Chief Executive Officer", "President", "Managing Director"],
    "vp of sales": ["VP of Sales", "VP Sales", "SVP Sales", "Vice President of Sales", "Head of Sales", "Sales Director"],
    "head of sales": ["Head of Sales", "Sales Director", "Director of Sales", "VP of Sales", "Chief Revenue Officer"],
    "head of e-commerce": ["Head of E-commerce", "Head of Ecommerce", "E-commerce Director", "Director of E-commerce", "Ecommerce Manager", "VP of E-commerce", "Head of Digital"],
    "head of growth": ["Head of Growth", "VP of Growth", "Director of Growth"],
    "managing director": ["Managing Director", "MD", "General Manager", "CEO"],
    "chief revenue officer": ["Chief Revenue Officer", "CRO", "VP of Revenue", "Head of Revenue"],
}


def expand_titles(titles):
    """Grow DM titles with variants for volume (50-100 per signal goal)."""
    out, seen = [], set()
    for x in (titles or []):
        for v in TITLE_VARIANTS.get(str(x).strip().lower(), [x]):
            if v.lower() not in seen:
                seen.add(v.lower())
                out.append(v)
    return out or list(titles or [])


def canon_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    d = d.removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return d.split("/")[0]


def emp_range(buckets) -> tuple[int, int]:
    """UI headcount buckets ('11-20','101-200'...) -> (min_emp, max_emp)."""
    lo, hi = [], []
    for b in (buckets or []):
        nums = re.findall(r"\d+", str(b))
        if nums:
            lo.append(int(nums[0]))
            hi.append(int(nums[-1]))
    return (min(lo) if lo else 11, max(hi) if hi else 500)


# ── TheirStack industry taxonomy ─────────────────────────────────────────
# TheirStack's industry_or/industry_not take EXACT LinkedIn standardized
# industry names and SILENTLY IGNORE anything unrecognized (an unknown name
# returns the full unfiltered universe, so the user thinks they filtered but
# got everything — a silent-no-op footgun). This list was built empirically by
# testing each candidate against the live API and keeping only names that
# actually narrow the result set (verified 2026-07-07). Every industry the
# wizard offers, the suggester emits, or a stored config carries is validated
# against this set before it reaches the API — unrecognized names are dropped
# and surfaced, never silently passed through.
THEIRSTACK_INDUSTRIES = ["Accounting", "Advertising Services", "Airlines and Aviation", "Apparel Manufacturing", "Appliances, Electrical, and Electronics Manufacturing", "Architecture and Planning", "Armed Forces", "Automation Machinery Manufacturing", "Aviation and Aerospace Component Manufacturing", "Banking", "Beverage Manufacturing", "Biotechnology Research", "Book and Periodical Publishing", "Broadcast Media Production and Distribution", "Building Construction", "Business Consulting and Services", "Chemical Manufacturing", "Civic and Social Organizations", "Civil Engineering", "Computer Games", "Computer Hardware Manufacturing", "Computer and Network Security", "Construction", "Consumer Goods", "Consumer Services", "Cosmetics", "Dairy Product Manufacturing", "Data Infrastructure and Analytics", "Defense and Space Manufacturing", "Design Services", "E-Learning Providers", "Education Administration Programs", "Electric Power Generation", "Entertainment Providers", "Environmental Services", "Events Services", "Facilities Services", "Farming", "Financial Data Services", "Financial Services", "Fisheries", "Food and Beverage Manufacturing", "Food and Beverage Services", "Freight and Package Transportation", "Furniture and Home Furnishings Manufacturing", "Government Administration", "Graphic Design", "Higher Education", "Hospitality", "Hospitals and Health Care", "Hotels and Motels", "Human Resources Services", "IT Services and IT Consulting", "Industrial Machinery Manufacturing", "Information Services", "Insurance", "International Affairs", "Internet Publishing", "Investment Management", "Law Practice", "Legal Services", "Machinery Manufacturing", "Management Consulting", "Manufacturing", "Maritime Transportation", "Marketing Services", "Medical Equipment Manufacturing", "Medical Practices", "Mental Health Care", "Mining", "Mobile Gaming Apps", "Motor Vehicle Manufacturing", "Motor Vehicle Parts Manufacturing", "Movies, Videos, and Sound", "Musicians", "Newspaper Publishing", "Non-profit Organizations", "Oil and Gas", "Packaging and Containers Manufacturing", "Paper and Forest Product Manufacturing", "Personal Care Product Manufacturing", "Pharmaceutical Manufacturing", "Photography", "Plastics Manufacturing", "Political Organizations", "Primary and Secondary Education", "Printing Services", "Public Policy Offices", "Public Relations and Communications Services", "Ranching", "Real Estate", "Religious Institutions", "Renewable Energy Semiconductor Manufacturing", "Research Services", "Restaurants", "Retail", "Retail Apparel and Fashion", "Retail Groceries", "Retail Luxury Goods and Jewelry", "Retail Motor Vehicles", "Security and Investigations", "Semiconductor Manufacturing", "Software Development", "Solar Electric Power Generation", "Spectator Sports", "Sports and Recreation Instruction", "Staffing and Recruiting", "Technology, Information and Internet", "Telecommunications", "Textile Manufacturing", "Think Tanks", "Tobacco Manufacturing", "Translation and Localization", "Transportation, Logistics, Supply Chain and Storage", "Travel Arrangements", "Truck Transportation", "Utilities", "Venture Capital and Private Equity", "Veterinary Services", "Warehousing and Storage", "Wellness and Fitness Services", "Wholesale", "Wineries", "Wireless Services", "Writing and Editing"]
_INDUSTRY_CANON = {i.lower(): i for i in THEIRSTACK_INDUSTRIES}


def validate_industries(names) -> tuple:
    """Split industry names into (recognized_canonical, unrecognized).
    Case-insensitive match to the canonical TheirStack spelling; only recognized
    names are safe to send (unknown ones silently no-op at the API)."""
    ok, bad = [], []
    for n in (names or []):
        s = str(n).strip()
        if not s:
            continue
        canon = _INDUSTRY_CANON.get(s.lower())
        if canon:
            if canon not in ok:
                ok.append(canon)
        elif s not in bad:
            bad.append(s)
    return ok, bad


# ── provider previews (search-only) ──────────────────────────────────────

def preview_hiring(p: dict) -> dict:
    """TheirStack blurred search — free, returns real counts + blurred sample."""
    # countries arrive either as free-text names (client wizard) or already-mapped
    # ISO codes (internal probe callers). Normalise BOTH here so no caller can pass
    # a bogus code that silently zeroes the search (the launch bug, client side).
    codes = []
    for c in (p.get("countries") or []):
        s = str(c).strip()
        if not s:
            continue
        mapped, _ = country_codes([s])
        if mapped:
            codes += mapped
        elif len(s) == 2 and s.isalpha():
            codes.append(s.upper())  # already an ISO alpha-2 code
    codes = list(dict.fromkeys(codes)) or ["US"]
    body = {
        "posted_at_max_age_days": int(p.get("days") or 14),
        "job_title_or": p.get("job_titles") or [],
        "job_country_code_or": codes,
        "min_employee_count": int(p.get("min_emp") or 11),
        "max_employee_count": int(p.get("max_emp") or 500),
        "company_type": "direct_employer",
        "blur_company_data": True,
        "limit": 10,
        "include_total_results": True,
    }
    # industry filter (user-facing, hiring wizard) — validate against the exact
    # TheirStack taxonomy so an unrecognized name can never silently no-op. Only
    # recognized names hit the API; the rest come back as ignored_industries so
    # the UI can warn instead of quietly returning the whole unfiltered universe.
    inc, bad_inc = validate_industries(p.get("industries"))
    exc, bad_exc = validate_industries(p.get("industries_not"))
    if inc:
        body["industry_or"] = inc
    if exc:
        body["industry_not"] = exc
    ignored_industries = bad_inc + bad_exc
    # precision layer (description patterns / industry excludes) — passing it
    # here keeps the preview count honest about what a real pull will return
    body.update(p.get("extra") or {})
    body["company_type"] = "direct_employer"  # invariant: never a job board or agency
    data = http_json("POST", "https://api.theirstack.com/v1/jobs/search",
                     {"Authorization": f"Bearer {KEYS['THEIRSTACK_API_KEY']}"}, body)
    meta = data.get("metadata") or {}
    jobs = [
        {
            "job_title": j.get("job_title") or "",
            "company_size": (j.get("company_object") or {}).get("employee_count") or "",
            "industry": (j.get("company_object") or {}).get("industry") or "",
            "country": j.get("country_code") or j.get("country") or "",
            "posted": (j.get("date_posted") or "")[:10],
        }
        for j in (data.get("data") or [])[:10]
    ]
    total_companies = meta.get("total_companies") or None
    dm_count = int(p.get("dm_count") or 0)
    # the number people actually care about: reachable decision makers.
    # Multiplier = the AI-ARK-derived DMs-per-company rate for this profile
    # (cached; ≈1 person's credits on first sight), falling back to the
    # dm_count cap only when no profile is supplied.
    total_prospects = round(total_companies * dms_per_company(p.get("source_id"))) if (total_companies and (p.get("dm_titles") or dm_count)) else None
    return {
        "ok": True, "cost": "free preview",
        "total_jobs": meta.get("total_results") or len(jobs),
        "total_companies": total_companies,
        "total_prospects": total_prospects,   # estimate: companies x DMS_PER_COMPANY
        "sample": jobs,
        "applied_industries": inc,             # what actually filtered
        "ignored_industries": ignored_industries,  # names TheirStack doesn't recognise
    }


def prospeo_row(r: dict) -> dict:
    c = r.get("company") or r
    loc = c.get("location") or {}
    return {
        "name": c.get("name") or "",
        "domain": c.get("domain") or "",
        "country": c.get("country") or (loc.get("country") if isinstance(loc, dict) else "") or "",
        "size": c.get("employee_count") or "",
        "industry": c.get("industry") or "",
        "description": (c.get("description_ai") or c.get("description") or "")[:180],
    }


def friendly_provider_error(data) -> str:
    """Raw provider error bodies must never reach the UI."""
    code = str((data or {}).get("error_code") or (data or {}).get("message") or data)
    if "NO_RESULTS" in code:
        return ("No one matches these filters right now. Try fewer filters - "
                "more locations, more company sizes, or a broader company type.")
    if "INVALID_FILTERS" in code:
        return "One of the filters isn't something the data provider understands - simplify the company type wording."
    if "INSUFFICIENT_CREDITS" in code:
        return "The data provider is out of credits - tell whoever runs the account."
    if "RATE_LIMIT" in code.upper():
        return "The data provider is briefly rate-limited - wait a minute and try again."
    return str((data or {}).get("message") or "The data provider didn't answer - try again in a minute.")


def prospeo_search(filters: dict) -> dict:
    data = http_json("POST", "https://api.prospeo.io/search-company",
                     {"X-KEY": KEYS["PROSPEO_API_KEY"]},
                     {"page": 1, "size": 25, "filters": filters})
    if data.get("error"):
        return {"ok": False, "message": friendly_provider_error(data)}
    rows = data.get("results") or []
    total = (data.get("pagination") or {}).get("total_count") or len(rows)
    return {"ok": True, "cost": "free" if data.get("free") else "1 credit",
            "total_companies": total,
            "sample": [prospeo_row(r) for r in rows[:10]]}


def _with_dm_estimate(res: dict, keywords, countries, headcount) -> dict:
    """Company previews headline PEOPLE: companies x the AI-ARK-derived
    DMs-per-company rate (cached), clearly marked as an estimate in the UI."""
    if res.get("ok") and res.get("total_companies"):
        res["total_dms_estimate"] = round(res["total_companies"] * DMS_PER_COMPANY)
    return res


def preview_companies(p: dict) -> dict:
    filters: dict = {}
    if p.get("keywords"):
        filters["company_keywords"] = {"include": p["keywords"], "include_company_description": True}
    if p.get("industries"):
        filters["company_industry"] = {"include": p["industries"]}
    if p.get("headcount"):
        filters["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        filters["company_location_search"] = {"include": p["countries"]}
    if not filters:
        return {"ok": False, "message": "Add at least one filter"}
    return _with_dm_estimate(prospeo_search(filters), (p.get("keywords") or [None])[0],
                             p.get("countries"), p.get("headcount"))


def _person_rows(data: dict, limit: int, named: bool = False) -> list[dict]:
    people = []
    for r in (data.get("results") or [])[:limit]:
        person = r.get("person") or r.get("contact") or r
        company = r.get("company") or {}
        loc = person.get("location") or {}
        people.append({
            "name": (person.get("full_name") or f"{person.get('first_name', '')} {person.get('last_name', '')}").strip(),
            "title": person.get("current_job_title") or person.get("headline") or "",
            "company": company.get("name") or "",
            "domain": company.get("domain") or "",
            "size": company.get("employee_count") or "",
            "industry": company.get("industry") or "",
            "country": (loc.get("country") if isinstance(loc, dict) else str(loc or "")) or company.get("country") or "",
            "linkedin": person.get("linkedin_url") or "",
            "named_account": named,
        })
    return people


def _search_person(filters: dict) -> dict:
    return http_json("POST", "https://api.prospeo.io/search-person",
                     {"X-KEY": KEYS["PROSPEO_API_KEY"]},
                     {"page": 1, "size": 25, "filters": filters})


def preview_people(p: dict) -> dict:
    """Prospeo /search-person page 1 — real people preview.

    Query A (1 credit): WHO (titles, partial-match) x WHERE (company
    filters) — the filtered audience. Query B (1 credit, only when
    `domains` given): the same WHO at specific named companies, merged
    in regardless of the filters. This is how the flow supports
    person-first, company-first AND named-account briefs at once.
    """
    if not p.get("titles"):
        return {"ok": False, "message": "Add at least one job title"}
    title_filter = {"include": p["titles"], "include_partial_match": True}

    filters: dict = {"person_job_title": title_filter}
    if p.get("keywords"):
        filters["company_keywords"] = {"include": p["keywords"], "include_company_description": True}
    if p.get("industries"):
        filters["company_industry"] = {"include": p["industries"]}
    if p.get("headcount"):
        filters["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        filters["company_location_search"] = {"include": p["countries"]}
    if p.get("exclude_keywords"):
        filters["company_keywords"] = {**filters.get("company_keywords", {"include": []}),
                                       "exclude": p["exclude_keywords"]}

    domains = [d.strip().lower().removeprefix("https://").removeprefix("http://")
               .removeprefix("www.").split("/")[0]
               for d in (p.get("domains") or []) if d.strip()]
    has_audience = len(filters) > 1  # more than just the title filter

    people, total, credits = [], 0, 0

    # Query B first so named accounts lead the preview.
    # Domain-scoped queries match poorly on exact titles, so use the
    # leadership-seniority net instead (same pattern the DM waterfall uses).
    if domains:
        named_data = _search_person({
            "person_seniority": {"include": ["Founder/Owner", "C-Suite", "Partner",
                                             "Vice President", "Head", "Director"]},
            "company": {"websites": {"include": domains[:50]}},
        })
        if not named_data.get("error"):
            people += _person_rows(named_data, 6, named=True)
            total += (named_data.get("pagination") or {}).get("total_count") or 0
            credits += 0 if named_data.get("free") else 1

    if has_audience:
        data = _search_person(filters)
        if data.get("error"):
            if not people:
                return {"ok": False, "message": friendly_provider_error(data)}
        else:
            seen = {(x["name"], x["domain"]) for x in people}
            people += [x for x in _person_rows(data, 12)
                       if (x["name"], x["domain"]) not in seen]
            total += (data.get("pagination") or {}).get("total_count") or 0
            credits += 0 if data.get("free") else 1

    if not people and not total:
        return {"ok": False, "message": "Nothing matched - widen the audience or check the domains"}
    return {"ok": True, "cost": "free" if credits == 0 else f"{credits} credit{'s' if credits > 1 else ''}",
            "total_people": total, "sample": people[:12]}


def tam_map(p: dict) -> dict:
    """The structured lilly-strategy moment: probe the same ICP through
    every sourcing lens IN PARALLEL and return real counts per angle.
    Deterministic: same probes, same order, bounded wait (~8s).

    Probes (page-1 only): company filter (1cr) · true people count (1cr)
    · lookalike universe (1cr) · hiring now (free). Repeat runs are free.
    """
    from concurrent.futures import ThreadPoolExecutor

    company_filters: dict = {}
    if p.get("keywords"):
        company_filters["company_keywords"] = {"include": p["keywords"], "include_company_description": True}
    if p.get("industries"):
        company_filters["company_industry"] = {"include": p["industries"]}
    if p.get("headcount"):
        company_filters["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        company_filters["company_location_search"] = {"include": p["countries"]}

    def probe_companies():
        if not company_filters:
            return None
        r = prospeo_search(company_filters)
        return r.get("total_companies") if r.get("ok") else None

    def probe_people():
        r = preview_people({**p, "domains": []})
        return r.get("total_people") if r.get("ok") else None

    def probe_lookalike():
        icp_text = (p.get("keywords") or [""])[0] or " ".join(p.get("industries") or [])
        if not icp_text:
            return None
        r = preview_lookalike({"icp_text": icp_text, "tier": "T2",
                               "headcount": p.get("headcount"), "countries": p.get("countries")})
        return r.get("total_companies") if r.get("ok") else None

    def probe_hiring():
        codes = country_codes(p.get("countries") or [])[0] or ["US"]
        try:
            r = preview_hiring({"job_titles": p.get("titles") or [], "countries": codes,
                                "min_emp": 11, "max_emp": 500, "days": 14})
            return r.get("total_companies") if r.get("ok") else None
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {k: ex.submit(fn) for k, fn in {
            "companies": probe_companies, "people": probe_people,
            "lookalike": probe_lookalike, "hiring": probe_hiring,
        }.items()}
        out = {k: f.result() for k, f in futs.items()}

    return {"ok": True, "angles": {
        "companies": {"companies": out["companies"], "people": out["people"]},
        "hiring": {"companies": out["hiring"]},
        "lookalike": {"companies": out["lookalike"]},
    }}




# business-name + person-name fields per table: normalised at ingest via the
# name_hygiene cleaners so every name stored (and later merged into an icebreaker)
# is already email-ready — no emoji, no role tails, no mis-cased/auto-link names.
_NAME_FIELD_BY_TABLE = {"signal_leads": "company", "engagement_events": "engager_company_name"}
_PERSON_FIELDS_BY_TABLE = {"signal_leads": ("full_name",),
                           "engagement_events": ("engager_full_name", "post_author_name")}


def _normalise_company_fields(path: str, body):
    """Clean the company + person name fields on rows written to signal_leads /
    engagement_events. Name kept for its single caller in sb()."""
    table = path.split("?")[0].split("/")[0]
    cfield = _NAME_FIELD_BY_TABLE.get(table)
    pfields = _PERSON_FIELDS_BY_TABLE.get(table, ())
    if (not cfield and not pfields) or body is None:
        return body
    try:
        from name_hygiene import clean_company_name, clean_person_name
    except Exception:  # noqa: BLE001 — never let hygiene break a write
        return body
    rows = body if isinstance(body, list) else [body]
    for row in rows:
        if not isinstance(row, dict):
            continue
        if cfield and row.get(cfield):
            row[cfield] = clean_company_name(row[cfield])
        for pf in pfields:
            if row.get(pf):
                row[pf] = clean_person_name(row[pf])
    return body


_SB_TIMEOUT_S = 15  # explicit, saner than http_json's 60s default - a cold-start
                     # Supabase stall used to burn ~60s per attempt (~120s across
                     # the two sequential calls a first page-load makes); capping
                     # this bounds the worst case even with the one retry below.
_SB_RETRY_BACKOFF_S = 1.5


def _sb_transient(exc: Exception) -> bool:
    """True for errors worth one retry (network/timeout/5xx); false for 4xx,
    which won't succeed on a second try."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout)):
        return True
    return False


def sb(method: str, path: str, body=None, prefer: str = "", headers: dict | None = None):
    """Best-effort Supabase PostgREST call - an outage must never break the app.
    `headers` lets callers add per-request headers (e.g. Range for pagination)
    without disturbing any existing call site - it's None everywhere else.
    Retries once on a transient failure (timeout/network/5xx) after a short
    backoff; 4xx failures are not retried. Every failure is logged (path only,
    up to '?' - never the query string, which can carry the api key) with the
    attempt number so a Supabase outage is visible in the server log instead
    of silently degrading."""
    url = KEYS.get("SUPABASE_URL")
    key = KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    if method in ("POST", "PATCH"):
        body = _normalise_company_fields(path, body)
    log_path = path.split("?", 1)[0]
    last_exc = None
    for attempt in (1, 2):
        try:
            return http_json(method, f"{url}/rest/v1/{path}",
                             {"apikey": key, "Authorization": f"Bearer {key}",
                              "Prefer": prefer or "return=minimal", **(headers or {})}, body,
                             timeout=_SB_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            print(f"[sb] WARNING {method} {log_path} attempt={attempt} "
                  f"failed: {type(e).__name__}: {e}", file=sys.stderr)
            if attempt == 1 and _sb_transient(e):
                time.sleep(_SB_RETRY_BACKOFF_S)
                continue
            break
    return None


def sb_count(path: str, mode: str = "exact"):
    """Row count for `path` via PostgREST's count header — transfers ~100B
    instead of the rows. Returns int or None on any failure. mode="estimated"
    answers from the planner beyond max-rows (~4s -> ~0.3s on contact_history
    at 1.1M rows) — use it for display columns, never for safety maths."""
    url = KEYS.get("SUPABASE_URL")
    key = KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method="GET")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Prefer", f"count={mode if mode in ('exact', 'planned', 'estimated') else 'exact'}")
    req.add_header("Range", "0-0")
    try:
        with urllib.request.urlopen(req, timeout=_SB_TIMEOUT_S, context=SSL_CTX) as resp:
            cr = resp.headers.get("Content-Range") or ""  # e.g. "0-0/1234" or "*/0"
        total = cr.rpartition("/")[2]
        return int(total) if total.isdigit() else None
    except Exception as e:  # noqa: BLE001 — best-effort, callers treat None as unknown
        print(f"[sb] WARNING count {path.split('?', 1)[0]} failed: {e}", file=sys.stderr)
        return None


def sb_get_all(path: str, page_size: int = 1000):
    """GET every row for `path`, paginating past PostgREST's default ~1000-row
    cap via the Range header. Stops once a page comes back shorter than
    page_size (works without needing to read the Content-Range response
    header, which http_json/sb don't currently surface). Returns None if any
    page fails outright - a Supabase outage must be visible to callers as a
    failure, not silently truncated into a partial-looking success."""
    out: list = []
    offset = 0
    while True:
        page = sb("GET", path, headers={"Range-Unit": "items", "Range": f"{offset}-{offset + page_size - 1}"})
        if not isinstance(page, list):
            return None
        out.extend(page)
        if len(page) < page_size:
            return out
        offset += page_size


def sb_delete_doc(table: str, doc_id):
    """Delete ONE row from a jsonb-doc table by id — the explicit counterpart to
    the omit-from-list delete that _pg_replace no longer performs when the list
    is empty. Best-effort; a Supabase outage must not block the local delete."""
    if not doc_id:
        return
    sb("DELETE", f"{table}?id=eq.{doc_id}")


def sb_delete_source(sid: str):
    """Erase every Supabase trace of a signal source so a removed draft leaves
    no backend leftovers: the source row, its pulled leads, its engagement
    events. Best-effort - a Supabase outage must not block the local delete."""
    if not sid:
        return
    sb("DELETE", f"signal_leads?source_id=eq.{sid}")
    sb("DELETE", f"engagement_events?source_id=eq.{sid}")
    sb("DELETE", f"signal_sources?id=eq.{sid}")


def sb_sync_source(src: dict):
    if not src.get("client_id"):  # resolve via the campaign draft for client-level exclusions
        camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                     if str(c.get("id")) == str(src.get("campaign_id"))), {})
        if camp.get("client_id"):
            src["client_id"] = camp["client_id"]
    sb("POST", "signal_sources?on_conflict=id", {
        "id": src.get("id"), "campaign_draft_id": str(src.get("campaign_id") or ""),
        "client_id": src.get("client_id"),
        "name": src.get("name"), "mechanism": src.get("mechanism") or src.get("type"),
        "icebreaker": src.get("icebreaker"), "titles": src.get("titles") or [],
        "targeting": {**(src.get("config") or {}), **(src.get("params") or {})},
        "destination": src.get("destination") or {}, "active": src.get("active", True),
    }, prefer="resolution=merge-duplicates,return=minimal")


# ── activity ledger ─────────────────────────────────────────────────────────
# Append-only record in Supabase of every write-shaped call the app receives,
# so the database documents WHO changed WHAT and WHEN — not just the end state.
# Fire-and-forget: the ledger must never add latency to, or fail, the endpoint
# it documents. Table: app_activity_log (service-role only, RLS on).

_ACTIVITY_META = {  # endpoint → (action, entity); anything absent logs as-is
    "/api/clients": ("update", "client"),
    "/api/role-feedback": ("feedback", "role"),
    "/api/sources": ("create", "source"),
    "/api/sources/update": ("update", "source"),
    "/api/sources/duplicate": ("duplicate", "source"),
    "/api/sources/pull": ("pull", "source"),
    "/api/sources/provision-engagement": ("provision", "source"),
    "/api/trigify-webhook": ("ingest", "engagement_event"),
    "/api/qa-history": ("create", "qa_run"),
    "/api/campaign-drafts": ("create", "campaign_draft"),
    "/api/campaign-drafts/update": ("update", "campaign_draft"),
    "/api/campaign-drafts/duplicate": ("duplicate", "campaign_draft"),
    "/api/campaign-drafts/restore": ("restore", "campaign_draft"),
    "/api/campaign-drafts/purge": ("delete", "campaign_draft"),
    "/api/tam-map": ("preview", "tam"),
    "/api/strategy-map": ("preview", "strategy"),
    "/api/verify-campaign": ("verify", "campaign"),
    "/api/verify-remove": ("remove_leads", "campaign"),
    "/api/verify-dismiss": ("dismiss", "verification"),
    "/api/process-new-selected": ("process_new", "mailboxes"),
}


def log_activity(endpoint: str, payload=None, actor: str = "app",
                 action: str | None = None, entity: str | None = None,
                 entity_id=None):
    action_d, entity_d = _ACTIVITY_META.get(endpoint, ("preview", None))
    if entity_id is None and isinstance(payload, dict):
        entity_id = payload.get("id") or payload.get("source_id") or payload.get("campaign_id")
    body = payload
    if isinstance(body, dict):
        try:
            if len(json.dumps(body, default=str)) > 6000:  # ledger rows stay light
                body = {"_truncated": True, "keys": sorted(body.keys())}
        except Exception:  # noqa: BLE001
            body = {"_unserialisable": True}
    row = {"actor": actor, "endpoint": endpoint,
           "action": action or action_d, "entity": entity or entity_d,
           "entity_id": str(entity_id) if entity_id is not None else None,
           "payload": body}
    # return=representation: PostgREST answers with the row as JSON — a minimal
    # 201 has an empty body, which http_json can't parse and logs as a warning.
    threading.Thread(target=lambda: sb("POST", "app_activity_log", row,
                                       prefer="return=representation"),
                     daemon=True).start()


setter.configure(sb=sb, http_json=http_json, keys=KEYS, log_activity=log_activity, sb_count=sb_count)


def client_prefill(p: dict) -> dict:
    """Fetch the client's homepage and prefill name/description from meta
    tags — the Gojiberry 'we analysed your website' moment, LLM-free."""
    url = (p.get("website") or "").strip()
    if not url:
        return {"ok": False, "message": "Give me a website"}
    if not url.startswith("http"):
        url = "https://" + url
    domain = url.split("//")[1].split("/")[0].removeprefix("www.")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NavreoBot)"})
        with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as resp:
            html = resp.read(400_000).decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "domain": domain,
                "name": domain.split(".")[0].title(), "description": "",
                "note": f"Could not read the site ({str(e)[:60]}) - fill in manually"}
    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:name|property)=["\']{prop}["\'][^>]+content=["\']([^"\']+)', html, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{prop}["\']', html, re.I)
        return m.group(1).strip() if m else ""
    title = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    return {"ok": True, "domain": domain,
            "name": (meta("og:site_name") or (title.group(1).split("|")[0].split("–")[0].strip() if title else domain.split(".")[0].title()))[:60],
            "description": (meta("og:description") or meta("description"))[:300]}


def save_client(p: dict) -> dict:
    from datetime import datetime
    clients = read_json_list(CLIENTS)
    if p.get("remove"):
        clients = [c for c in clients if c.get("id") != p.get("id")]
    elif p.get("id"):
        clients = [{**c, **p} if c.get("id") == p.get("id") else c for c in clients]
    else:
        p["id"] = f"client-{len(clients) + 1}"
        p["created_at"] = datetime.now().isoformat(timespec="seconds")
        clients.append(p)
    _pg_replace("clients", clients, only_doc=True)
    return {"ok": True, "id": p.get("id")}


ROLE_SUGGEST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "trigger_roles": {"type": "array", "items": {"type": "string"}},
        "dm_titles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["trigger_roles", "dm_titles"],
}

SUGGEST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"suggestions": {"type": "array", "items": {"type": "string"}}},
    "required": ["suggestions"],
}

# Shared call for the "Generate more" buttons - one minimal-effort JSON-schema
# completion. gpt-5-mini stays the model: a 5-judge bake-off showed nano drifts
# off-theme on tighter fields (region-clustered locations scored 2.8/5 vs mini's
# 4.6/5) for no real latency gain (~0.7s, within noise), so the effectiveness
# bar wins. The speed lever is the seed-from-selection prompt below, not the id.
SUGGEST_MODEL = "gpt-5-mini"


def _suggest_llm(key: str, system: str, user: str, schema_name: str, schema: dict) -> dict:
    r = http_json(
        "POST", "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}"},
        {"model": SUGGEST_MODEL, "reasoning_effort": "minimal",
         "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}],
         "response_format": {"type": "json_schema", "json_schema": {
             "name": schema_name, "strict": True, "schema": schema}}})
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {r['error'].get('message', r['error'])[:200]}")
    return json.loads(r["choices"][0]["message"]["content"])

ROLE_FEEDBACK = APP_DIR / "data" / "role_feedback.json"
# one feedback "family" per ideate-able field across all wizards; each has a
# declined_ / kept_ pair that the suggester reads back per client
FEEDBACK_FAMILIES = ("trigger", "dm", "keywords", "topics", "icp")
ROLE_FEEDBACK_KEYS = tuple(f"{p}_{fam}" for fam in FEEDBACK_FAMILIES for p in ("declined", "kept"))

# what each non-role wizard field asks the LLM for; keyed by the `kind` the
# wizard sends. family = which declined/kept history to read + write.
GENERIC_KINDS = {
    "keywords": {"family": "keywords", "schema": "buyer_types", "single": False,
                 "task": ("Suggest buyer-type phrases naming what KIND of company the client sells to "
                          "- each phrase must say what a company IS (e.g. 'mobile app marketing agency'), "
                          "never who it serves (never 'agencies for brands'). 2-4 words each.")},
    "topics": {"family": "topics", "schema": "post_topics", "single": False,
               "task": ("Suggest LinkedIn post topics that would mark an engager as a warm buyer for the "
                        "client's offer - short topic labels a post could plausibly be about, e.g. "
                        "'GTM strategy', 'cold email deliverability'. 2-4 words each.")},
    "icp_text": {"family": "icp", "schema": "icp_description", "single": True,
                 "task": ("Write ONE ideal-company description, 1-2 sentences of plain English, that a "
                          "lookalike search can match on - what the company does, who it sells to, its "
                          "rough size. Return it as a single-element suggestions array.")},
    "industries": {"family": "industries", "schema": "industries", "single": False,
                   "task": ("Suggest broad industry or sector labels the client's target companies belong "
                            "to - short nouns or 2-3 word phrases like 'Logistics', 'Fintech', "
                            "'Healthcare'. Name what the company IS, never who it serves.")},
    # hiring-signal industry filter feeds TheirStack's `industry_or`, which only
    # matches EXACT LinkedIn standardized industry names - loose labels silently
    # match nothing, so this kind demands the canonical taxonomy spelling.
    "linkedin_industries": {"family": "industries", "schema": "industries", "single": False,
                   "task": ("Suggest industries the client's target companies belong to, using ONLY exact "
                            "LinkedIn standardized industry names (the taxonomy LinkedIn shows on company "
                            "pages). Use the canonical spelling verbatim, e.g. 'Software Development', "
                            "'IT Services and IT Consulting', 'Hospitals and Health Care', "
                            "'Transportation, Logistics, Supply Chain and Storage', 'Financial Services', "
                            "'Construction', 'Motor Vehicle Manufacturing'. Never invent a label or use a "
                            "colloquial one like 'Fintech', 'Logistics' or 'Healthcare' - always the full "
                            "LinkedIn name. Name what the company IS, never who it serves.")},
    "locations": {"family": "locations", "schema": "locations", "single": False,
                  "task": ("Suggest countries or major regions where the client's ideal customers cluster "
                           "- proper country or region names like 'United States', 'Germany', 'Canada'. "
                           "One place per entry.")},
    "exclusions": {"family": "exclusions", "schema": "exclusions", "single": False,
                   "task": ("Suggest words that, if present in a job post, mean it is NOT a buying signal "
                            "for the client - e.g. 'intern', 'contract', 'agency', 'part-time'. Single "
                            "words or 2-word phrases.")},
    "avoid_companies": {"family": "avoid_companies", "schema": "avoid_companies", "single": False,
                        "task": ("Suggest kinds of companies the client should NOT count as warm leads "
                                 "even if they engage - competitors, agencies pitching the same buyers, "
                                 "irrelevant sectors. Short company-type labels, 2-4 words each.")},
}


def _all_role_feedback() -> dict:
    """Whole role_feedback map {client_id: rec} from Postgres (file fallback)."""
    rows = sb("GET", "role_feedback?select=client_id,doc")
    if isinstance(rows, list):
        return {r["client_id"]: r["doc"] for r in rows if r.get("client_id")}
    try:
        return json.loads(ROLE_FEEDBACK.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _role_feedback_for(client_id: str) -> dict:
    return _all_role_feedback().get(client_id or "", {})


def role_feedback(p: dict) -> dict:
    """Remember what the user declined (removed a suggested chip) and kept
    (the list when they advanced) per client, so every later suggestion call
    learns from it. A kept role clears the same role from declined and
    vice versa - the most recent action wins."""
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(p.get("campaign_id"))), {})
    cid = camp.get("client_id") or p.get("client_id") or ""
    if not cid:
        return {"ok": False, "message": "no client to remember this for"}
    fb = _all_role_feedback()
    rec = fb.setdefault(cid, {})
    opposite = {}
    for fam in FEEDBACK_FAMILIES:
        opposite[f"declined_{fam}"] = f"kept_{fam}"
        opposite[f"kept_{fam}"] = f"declined_{fam}"
    for k in ROLE_FEEDBACK_KEYS:
        for t in (p.get(k) or []):
            t = (t or "").strip()
            if not t:
                continue
            cur = rec.setdefault(k, [])
            if t.lower() not in {x.lower() for x in cur}:
                cur.append(t)
            rec[k] = cur[-100:]
            opp = rec.get(opposite[k]) or []
            rec[opposite[k]] = [x for x in opp if x.lower() != t.lower()]
    sb("POST", "role_feedback?on_conflict=client_id",
       {"client_id": cid, "doc": rec},
       prefer="resolution=merge-duplicates,return=minimal")
    return {"ok": True}


def _dedup_fresh(items, exclude, want):
    seen = {(e or "").strip().lower() for e in exclude if (e or "").strip()}
    keep = []
    for t in items:
        t = (t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            keep.append(t)
    return keep[:want]


def _suggest_generic(p, camp, cl, icp, basis, fb, spec, key):
    """One suggestion call for a non-role wizard field (buyer-type keywords,
    engagement post-topics, or a lookalike ICP description). Same decline/keep
    learning as roles, but a single flat `suggestions` list."""
    fam = spec["family"]
    want = 1 if spec["single"] else min(int(p.get("count") or 6), 12)
    declined = (fb.get(f"declined_{fam}") or []) + (p.get("declined") or [])
    have = [t for t in (p.get("exclude") or []) if (t or "").strip()]
    # `already_have` IS the user's current selection. When it's non-empty, the
    # button should widen that selection with close neighbours; when empty, fall
    # back to suggesting fresh from the client/ICP.
    similar = bool(have) and not spec["single"]
    system = (
        f"You help a B2B outbound operator set up a prospecting campaign. {spec['task']}\n"
        + ("The items in `already_have` are what the user has ALREADY SELECTED. Generate MORE "
           "suggestions that stay STRICTLY within the same theme, sub-type and pattern as those - "
           "their closest neighbours and variants, matching their specificity and (for places) "
           "their geographic region or cluster. Do NOT broaden into generic or adjacent-but-"
           "different items, and do NOT fall back to your usual defaults. Prefer returning FEWER, "
           "tighter matches over padding to `count` with loose ones. Never repeat anything in "
           "`already_have`.\n" if similar else
           "Never repeat anything in `already_have`.\n")
        + "The user has rejected everything in `declined` before: never suggest those or close "
          "variants, and steer away from their flavour. `kept` is what this user chose to keep "
          "before: lean that direction. Return exactly `count` unless the space is genuinely "
          "exhausted."
    )
    user = json.dumps({
        "client": {"name": cl.get("name"), "description": cl.get("description"), "offer": cl.get("offer")},
        "icp": {"keywords": icp.get("keywords") or "", "titles": icp.get("titles") or [],
                "sizes": icp.get("sizes") or [], "geos": icp.get("geos") or []},
        "campaign_" + basis: (camp.get("goal") or camp.get("name") or "")[:200],
        "already_have": have,
        "declined": declined[-40:], "kept": (fb.get(f"kept_{fam}") or [])[-40:],
        "count": want,
    })
    out = _suggest_llm(key, system, user, spec["schema"], SUGGEST_SCHEMA)
    return {"ok": True, "based_on": basis,
            "suggestions": _dedup_fresh(out.get("suggestions", []), have + declined, want)}


def role_suggest(p: dict) -> dict:
    """Suggest hiring-trigger roles + decision-maker roles from the client's ICP.
    trigger_roles = what the target company is HIRING (the buying signal);
    dm_titles = who we EMAIL there. Anything in the exclude lists (what the
    user already has in the field) is never re-suggested, so "generate more"
    stays fresh."""
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from ~/.navreo-keys.env")
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(p.get("campaign_id"))), {})
    # the pre-creation new-campaign wizard has no saved campaign yet: it passes the
    # client id (and the in-progress ICP) inline so suggestions still have context
    cid = camp.get("client_id") or p.get("client_id")
    cl = next((c for c in read_json_list(CLIENTS) if c.get("id") == cid), {})
    if not camp and not cl:  # no context at all -> suggesting would be noise
        return {"ok": False, "message": "no client context - keeping the defaults"}
    icp = {**(cl.get("icp") or {}), **{k: v for k, v in (camp.get("icp") or {}).items() if v},
           **{k: v for k, v in (p.get("icp") or {}).items() if v}}
    basis = "goal" if (camp.get("goal") or "").strip() else "name"
    count = min(int(p.get("count") or 6), 12)
    fb = _role_feedback_for(cid or "")

    kind = p.get("kind")
    if kind == "linkedin_industries":
        # the model can drift to deprecated LinkedIn names ("Computer Software")
        # that silently no-op at TheirStack — keep only canonical taxonomy names,
        # then top up from the reference list so the button always returns some.
        res = _suggest_generic(p, camp, cl, icp, basis, fb, GENERIC_KINDS[kind], key)
        good, _ = validate_industries(res.get("suggestions") or [])
        have = {s.lower() for s in (p.get("exclude") or [])} | {g.lower() for g in good}
        for ind in THEIRSTACK_INDUSTRIES:
            if len(good) >= (p.get("count") or 6):
                break
            if ind.lower() not in have:
                good.append(ind)
                have.add(ind.lower())
        res["suggestions"] = good
        return res
    if kind in GENERIC_KINDS:
        return _suggest_generic(p, camp, cl, icp, basis, fb, GENERIC_KINDS[kind], key)
    # declined = never show again; merged from the persisted per-client history
    # plus whatever this wizard session sends (a just-removed chip may not
    # have hit the file yet)
    decl_trig = (fb.get("declined_trigger") or []) + (p.get("declined_trigger") or [])
    decl_dm = (fb.get("declined_dm") or []) + (p.get("declined_dm") or [])
    have_trig = [t for t in (p.get("exclude_trigger") or []) + decl_trig if (t or "").strip()]
    have_dm = [t for t in (p.get("exclude_dm") or []) + decl_dm if (t or "").strip()]
    # the raw selections (what's in the field right now, minus declined) - seed
    # "generate similar" off these; when both are empty the button falls back to
    # suggesting fresh from the client/ICP.
    sel_trig = [t for t in (p.get("exclude_trigger") or []) if (t or "").strip()]
    sel_dm = [t for t in (p.get("exclude_dm") or []) if (t or "").strip()]
    similar = bool(sel_trig or sel_dm)
    system = (
        "You suggest job titles for a B2B hiring-signal campaign. The signal: when a company "
        "posts certain job openings, it is a good moment for the client to reach out.\n"
        "Return two DISTINCT lists:\n"
        "1. trigger_roles - roles the TARGET company would be actively hiring that signal it "
        "needs the client's offer right now. Job-board titles, fully spelled out, no slashes, "
        "no abbreviations - one concrete title per entry.\n"
        "2. dm_titles - the people at that company the client should EMAIL about the offer: "
        "senior, budget-holding titles, matched to the company sizes given.\n"
        + ("The already_have lists are what the user has ALREADY SELECTED. For each list, "
           "generate MORE titles that stay STRICTLY within the same theme, seniority band and "
           "function as the ones already there - their closest neighbours and variants, matching "
           "their specificity. Do NOT drift to generic senior titles (e.g. a bare 'Chief Marketing "
           "Officer' or 'Director of Marketing') unless they clearly fit the seed's niche. Prefer "
           "returning FEWER, tighter matches over padding to `count`. Never repeat anything in the "
           "already_have lists.\n" if similar else
           "Never repeat anything in the already_have lists.\n")
        + "The user has rejected everything in the declined lists before: never suggest those "
          "or close variants, and steer away from their flavour. The kept lists are what this "
          "user chooses to keep: suggest more in that direction. Return exactly `count` per list "
          "unless the space is genuinely exhausted."
    )
    user = json.dumps({
        "client": {"name": cl.get("name"), "description": cl.get("description"), "offer": cl.get("offer")},
        "target_companies": {"keywords": icp.get("keywords") or "", "sizes": icp.get("sizes") or [],
                             "geos": icp.get("geos") or []},
        "campaign_" + basis: (camp.get("goal") or camp.get("name") or "")[:200],
        "already_have_trigger": [t for t in (p.get("exclude_trigger") or []) if (t or "").strip()],
        "already_have_dm": [t for t in (p.get("exclude_dm") or []) if (t or "").strip()],
        "declined_trigger": decl_trig[-40:], "declined_dm": decl_dm[-40:],
        "kept_trigger": (fb.get("kept_trigger") or [])[-40:],
        "kept_dm": (fb.get("kept_dm") or [])[-40:],
        "seed_dm_titles": icp.get("titles") or [], "count": count,
    })
    out = _suggest_llm(key, system, user, "role_suggestions", ROLE_SUGGEST_SCHEMA)

    def fresh(items, have):
        seen = {h.strip().lower() for h in have}
        keep = []
        for t in items:
            t = (t or "").strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                keep.append(t)
        return keep[:count]
    # first fill seeds DMs with the ICP's known-good titles, then the LLM widens
    # (seed only when the field is empty; fresh() still drops declined seeds)
    dm_seed = [] if (p.get("exclude_dm") or []) else (icp.get("titles") or [])
    return {"ok": True, "based_on": basis,
            "trigger_roles": fresh(out.get("trigger_roles", []), have_trig),
            "dm_titles": fresh(dm_seed + out.get("dm_titles", []), have_dm)}


STRATEGY_CACHE = APP_DIR / "data" / "strategy_cache.json"

MECHANISM_DOC = """
Available mechanisms and their params (use EXACTLY these shapes):
- hiring: {"job_titles": [<10-15 VARIANTS of the trigger roles: synonyms, abbreviations, seniority variants, adjacent titles - e.g. "Amazon PPC Specialist","Amazon PPC Manager","Marketplace Manager","Ecommerce Marketplace Manager","Amazon Account Manager","Amazon Brand Manager","Ecommerce Specialist","Head of Marketplaces"...>], "days": 30} - e.g. an Amazon agency client -> ["Amazon PPC Specialist","Marketplace Manager"]; a devshop-selling client -> ["Software Engineer"]. NOT the decision-maker titles.
- engagement: {"keywords": ["<topics prospects post/engage about>"]} - LinkedIn engagement tracking, cannot be sized upfront


VOLUME: every idea should be able to feed 50-100 companies. Use MANY job-title variants (hiring) and add "dm_titles": [<6-10 decision-maker title variants expanding the user's titles with synonyms and adjacent seniorities>] to every idea.

{PRECISION}""".strip()

# Precision-layer prompt styles — the bake-off harness (app/prompt_test.py)
# scores each for on-brief accuracy x volume; the default is the winner.
PRECISION_STYLES = {
    # exclusion-first: NOT-filters as workhorses, REQUIRE gate only on high-volume roles
    "balanced": """PRECISION LAYER (mandatory - we want 100 on-brief companies, never 5000 broad ones):
- hiring params MUST also include:
  "company_description_pattern_not": [<regex for what it must NOT be, e.g. "agency","staffing","SaaS","distributor","managed (it )?services">],
  "industry_not": [<LinkedIn industry names to exclude, e.g. "Staffing and Recruiting","IT Services and IT Consulting">]
  and, when the company type maps cleanly to a LinkedIn industry, "industry_or": [<1-3 LinkedIn industry names, e.g. "Software Development">].
  Exclusions (pattern_not/industry_not/industry_or) are the workhorses. Add "company_description_pattern_or" (a REQUIRE gate:
  [<2-6 lowercase regex fragments describing what the company IS>]) ONLY when the trigger roles are generic and high-volume
  (thousands of jobs, e.g. SDR, E-commerce Manager); on niche roles it starves the search to zero because most company
  descriptions never contain the literal phrase.
  Beware: "IT consulting" patterns attract managed-service providers - for dev-agency briefs use dev-specific patterns only.""",

    # industry-first: LinkedIn industry filters carry the load, no description REQUIRE gates ever
    "industry_first": """PRECISION LAYER (mandatory - we want 100 on-brief companies, never 5000 broad ones):
- hiring params MUST also include:
  "industry_or": [<2-4 LinkedIn industry names the target companies belong to, e.g. "Software Development","Retail Apparel and Fashion">],
  "industry_not": [<LinkedIn industry names to exclude, e.g. "Staffing and Recruiting","IT Services and IT Consulting">],
  "company_description_pattern_not": [<regex for what it must NOT be, e.g. "agency","staffing","distributor">]
  NEVER use "company_description_pattern_or" - industry filters plus exclusions do the work.""",

    # keyword-rich: describe what the company IS in words, avoid industry taxonomies
    "keyword_rich": """PRECISION LAYER (mandatory - we want 100 on-brief companies, never 5000 broad ones):
- hiring params MUST also include:
  "company_description_pattern_or": [<4-8 lowercase regex fragments describing what the company IS, written the way companies describe THEMSELVES, e.g. "we (make|craft|build|design)", "(skincare|apparel|beverage|snack) (brand|company)", "custom software">],
  "company_description_pattern_not": [<regex for what it must NOT be>],
  "industry_not": [<LinkedIn industries to exclude>]""",

    # loose: kill-lists only - the volume ceiling baseline
    "loose": """PRECISION LAYER (light touch - trust the trigger roles to select the right companies):
- hiring params MUST also include:
  "industry_not": [<LinkedIn industries to exclude, e.g. "Staffing and Recruiting">],
  "company_description_pattern_not": [<2-4 regex for the worst offenders only, e.g. "staffing","recruit">]
  Nothing else - no industry_or, no company_description_pattern_or.""",

    # hybrid: pick the discriminator by the NATURE of the company type (bake-off winner design)
    "hybrid": """PRECISION LAYER (mandatory - we want 100 on-brief companies, never 5000 broad ones).
First classify the target company type, then filter accordingly:

CASE A - the company type IS a LinkedIn industry (logistics firm, construction company, consumer-goods brand, medical device maker, B2B software company):
- hiring params MUST include "industry_or": [<2-4 LinkedIn industry names>] plus the kill lists below.

CASE B - the company type is a SUBTYPE that shares its industry with non-targets (a dev AGENCY lives in "Software Development" next to product SaaS; a marketing agency next to ad-tech):
- hiring params MUST include "industry_or" (the parent industries) AND "company_description_pattern_or": [<4-8 lowercase regex fragments of how such companies describe THEMSELVES, e.g. "software development (agency|studio|shop|company)", "custom software (development|solutions)", "(nearshore|offshore) development (team|partner)">].
  RULE: every pattern_or fragment must contain the company-TYPE noun (agency, studio, shop, consultancy, house, development company). Generic relationship phrases ("for our clients", "we help", "our customers") are FORBIDDEN as fragments: pattern_or is an OR gate and EVERY B2B company matches those, so one generic fragment poisons the whole filter.

ALWAYS, both cases:
- "industry_not": [<LinkedIn industries to exclude - staffing, IT services (for non-IT briefs), banking...>]
- "company_description_pattern_not": [<regex kill list: "staffing","recruit","agency" (when targets are not agencies),"distributor","managed (it )?services","MSP"...>]
- NEVER company_description_pattern_or on niche low-volume trigger roles (it starves the search: most descriptions never contain the phrase).
- Trigger roles that exist in EVERY industry (SDR, Sustainability Manager, Office Manager) NEVER select the company type - the industry/description layer must do it.""",
}
DEFAULT_PRECISION_STYLE = "hybrid"  # bake-off winner 2026-07-05: only style with every scenario >=70% on-brief, at the highest volume (app/prompt_test.py)

# Every hiring opener MUST carry two merge variables: {{company}} and {{job_title}}
# (the role the company is actually hiring for, filled per prospect at pull time).
# The AI used to bake the role in as literal text ("...hiring a Demand Gen manager..."),
# so every prospect got the SAME role regardless of what their company was hiring for.
# This default and the guard below make the variables non-negotiable platform-wide.
HIRING_ICE_DEFAULT = "Saw {{company}} is hiring for {{job_title}}, and so I thought I'd reach out."
# tokens (any brace/casing) we treat as the "hiring role" merge variable
_ROLE_TOKEN_RE = re.compile(r"\{\{?\s*(job_title|jobtitle|role|title)\s*\}?\}", re.I)
_COMPANY_TOKEN_RE = re.compile(r"\{\{?\s*company\s*\}?\}", re.I)


def ensure_hiring_vars(icebreaker: str) -> str:
    """Guarantee a hiring opener keeps {{company}} + a job-title variable.
    If either is missing (e.g. the AI baked a literal role, or a user edited them
    out), fall back to the canonical default so no prospect gets a hardcoded role.
    Text around the variables is preserved whenever both are present."""
    ice = (icebreaker or "").strip()
    if not ice:
        return HIRING_ICE_DEFAULT
    if _COMPANY_TOKEN_RE.search(ice) and _ROLE_TOKEN_RE.search(ice):
        return ice
    return HIRING_ICE_DEFAULT


def _run_claude_ideation(p: dict) -> list | None:
    """Stage 1: lilly-strategy's ideation, headless. Returns idea dicts or
    None on any failure (caller falls back to the default catalogue)."""
    client_bits = []
    if p.get("client_name"):
        client_bits.append(f"Client: {p['client_name']}")
    if p.get("client_description"):
        client_bits.append(f"What they do: {p['client_description']}")
    if p.get("client_offer"):
        client_bits.append(f"WHAT IS BEING SOLD (critical - only propose signals that indicate need for THIS): {p['client_offer']}")
    if p.get("goal"):
        client_bits.append(f"THE CAMPAIGN GOAL, in the user's words: {p['goal']}")
    if p.get("existing"):
        client_bits.append("ALREADY RUNNING in this campaign (do NOT propose these again or close variants of them): "
                           + "; ".join(p["existing"]))
    icp_bits = []
    if p.get("titles"):
        icp_bits.append("decision-maker titles: " + ", ".join(p["titles"]))
    if p.get("keywords"):
        icp_bits.append("buyer-type: " + ", ".join(p["keywords"]))
    if p.get("industries"):
        icp_bits.append("industries: " + ", ".join(p["industries"]))
    if p.get("countries"):
        icp_bits.append("geos: " + ", ".join(p["countries"]))
    if p.get("headcount"):
        icp_bits.append("company size: " + ", ".join(p["headcount"]))

    style = p.get("precision_style") or DEFAULT_PRECISION_STYLE
    doc = MECHANISM_DOC.replace("{PRECISION}", PRECISION_STYLES.get(style, PRECISION_STYLES[DEFAULT_PRECISION_STYLE]))
    prompt = f"""You are the campaign-ideation engine of a cold-email agency (the lilly-strategy pass).

{chr(10).join(client_bits) or "Client: unknown - reason from the ICP alone."}
Target audience ({'; '.join(icp_bits)}).

{doc}

{("USER STEER (must be respected): " + p["steer"] + " -- For steer purposes: hiring and engagement are WARM signals (triggered by the prospect's own actions); company_filter and lookalike are COLD/reactive lists. If the steer says warm only, generate ONLY warm mechanisms.") if p.get("steer") else ""}
{('The user chose the mechanism: ' + p.get('mechanism', '') + '. Generate exactly ONE idea using ONLY that mechanism, matching the goal.') if p.get('mechanism') else 'The user stated EXACTLY what they want. Generate ONLY the idea(s) the goal describes - usually just 1, at most 2. Do not add alternatives.' if p.get('mode') == 'direct' else 'Generate 4-6 campaign ideas that SERVE THE GOAL. If the goal names a specific signal type (e.g. hiring for a role), generate ONLY ideas of that type plus at most one close variant - do not pad with unrelated signals.'} Skip any mechanism that makes no sense for what is being sold.
Generate ideas for THIS client specifically. Every idea = a reason-to-reach-out that fits their offer, expressed through one mechanism. Think about which signals actually indicate need for what THIS client sells. Every idea MUST be a recurring SIGNAL (an event or behaviour that keeps happening) - static lists and one-off searches are out of scope. At most one engagement idea. Vary the mechanisms; skip mechanisms that make no sense for this offer.

Score each honestly for THIS client: fit (does the signal indicate need for the offer, 1-5), novelty (vs what every agency sends, 1-5), intent (how timely/warm the moment is, 1-5).

Reply with ONLY a JSON array, no fences, no commentary:
[{{"idea": "<short PLAIN name a non-marketer instantly understands, e.g. 'Brands hiring Amazon roles' not 'Marketplace Talent Expansion'>", "why": "<under 15 words: why this signal means they need the offer. Plain punctuation, never an em-dash>", "icebreaker": "<the opening line: 10-15 words TOTAL, one short signal mention using {{company}}-style merge tags, MUST end with: and so I thought I'd reach out. For a hiring idea, ALWAYS refer to the role with the merge tag {{{{job_title}}}} (it is filled per company at send time) - NEVER write a literal role name like 'a Demand Gen manager', since the role differs per company. e.g. 'Saw {{{{company}}}} is hiring for {{{{job_title}}}}, and so I thought I'd reach out.'>", "mechanism": "<one of hiring|engagement>", "params": {{...}}, "fit": n, "novelty": n, "intent": n}}]"""

    # ideation via OpenAI (OPENAI_API_KEY from env, same key the app already
    # uses) - no local `claude` CLI, so it runs on Render as-is. No key -> None
    # -> the caller falls back to the default catalogue (never breaks).
    ideas = None
    fail_reason = ""
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        print("IDEATION SKIPPED (no OPENAI_API_KEY) - using catalogue fallback")
        return None
    try:
        r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                      {"Authorization": f"Bearer {key}"},
                      {"model": "gpt-5-mini",
                       "messages": [{"role": "user", "content": prompt}]})
        if r.get("error"):
            raise RuntimeError(str(r["error"].get("message", r["error"]))[:200])
        text = (r["choices"][0]["message"]["content"] or "").strip()
        m = re.search(r"\[.*\]", text, re.S)
        ideas = json.loads(m.group(0) if m else text)
    except Exception as e:  # noqa: BLE001
        fail_reason = f"{type(e).__name__}: {str(e)[:100]}"
    if ideas is None:
        print(f"IDEATION FAILED ({fail_reason or 'empty output'}) - returning error, NOT the catalogue")
        return None
    try:
        good = []
        for i in ideas:
            if isinstance(i.get("icebreaker"), str):
                i["icebreaker"] = re.sub(r"\{(\w+)\}(?!\})", r"{{\1}}", i["icebreaker"].replace("{{", "\x00").replace("}}", "\x01")).replace("\x00", "{{").replace("\x01", "}}")
            if not (i.get("mechanism") in ("hiring", "engagement") and i.get("idea")):
                continue
            if i["mechanism"] == "hiring" and not (i.get("params") or {}).get("job_titles"):
                continue  # a hiring idea without trigger roles matches EVERY job
            if i["mechanism"] == "hiring":
                # the AI sometimes bakes a literal role ("...hiring a Demand Gen manager...");
                # force the two merge variables so the role is filled per company at send time
                i["icebreaker"] = ensure_hiring_vars(i.get("icebreaker"))
            good.append(i)
        return good or None
    except Exception:  # noqa: BLE001 — any failure -> fallback catalogue
        return None


def _default_ideas(p: dict) -> list:
    """Fallback catalogue when headless ideation is unavailable — SIGNALS ONLY
    (static audiences are out of scope and fail the monthly-volume rule anyway).
    Purely derived from the request payload — no live/paid lookups of any kind."""
    ideas = [
        {"idea": "Hiring the roles you sell to", "why": "Live job posts signal the need", "mechanism": "hiring",
         "icebreaker": HIRING_ICE_DEFAULT,
         "params": {"job_titles": p.get("titles") or [], "days": 30}, "fit": 5, "novelty": 4, "intent": 5},
    ]
    if p.get("titles") or p.get("keywords") or p.get("industries"):
        ideas.append({"idea": "People engaging with your topics", "why": "Warm - they're already interacting",
                       "mechanism": "engagement", "icebreaker": "",
                       "params": {"keywords": p.get("keywords") or []}, "fit": 3, "novelty": 3, "intent": 4})
    return ideas


NO_IDEATION_LABEL = "sized after launch - live sizing unavailable right now"


def _fallback_strategy_rows(p: dict) -> list:
    """Deterministic, ZERO-COST rows for when Stage-1 ideation can't run (no
    OPENAI_API_KEY, or the model call failed/timed out). Built purely from
    the request payload + the static idea catalogue above.

    CRITICAL GUARANTEE: this function never calls _search_person, preview_hiring,
    or any other paid-provider probe — it only assembles dicts from `p` and the
    static catalogue, so this code path can never spend a Prospeo/TheirStack/
    AI-Ark/Ocean credit. Callers must return straight from this function's
    output without falling through to the Stage-2 probe code below."""
    if p.get("mode") == "direct" and p.get("mechanism") in ("hiring", "engagement"):
        mech = p["mechanism"]
        ideas = [{
            "idea": f"{'Hiring' if mech == 'hiring' else 'Engagement'} signal" + (f" - {p['goal']}" if p.get("goal") else ""),
            "why": NO_IDEATION_LABEL, "mechanism": mech,
            "icebreaker": HIRING_ICE_DEFAULT if mech == "hiring" else "",
            "params": {"job_titles": p.get("titles") or [], "days": 30} if mech == "hiring" else {"keywords": p.get("keywords") or []},
            "fit": 3, "novelty": 3, "intent": 3,
        }]
    else:
        ideas = _default_ideas(p)
    rows = []
    for i, idea in enumerate(ideas):
        rows.append({
            "id": f"idea-{i}", "key": idea["mechanism"], "idea": idea["idea"],
            "signal": idea.get("why") or NO_IDEATION_LABEL, "mechanism": idea["mechanism"],
            "params": idea.get("params") or {},
            "companies": None, "dms": None, "dms_total": None,
            "icebreaker": idea.get("icebreaker") or "",
            "fit": idea.get("fit"), "novelty": idea.get("novelty"), "intent": idea.get("intent"),
            "score": 0, "friction": MECH_FRICTION.get(idea["mechanism"], "Med"),
            "estimated": True, "approx": False,
            "window_days": None, "companies_total": None,
            "fallback": True, "label": NO_IDEATION_LABEL,
        })
    return rows


MECH_FRICTION = {"company_filter": "Easy", "lookalike": "Easy",
                 "hiring": "Med", "engagement": "Med (setup)"}
MECH_EASE = {"Easy": 5, "Med": 3, "Med (setup)": 1}


def strategy_map(p: dict) -> dict:
    """The structured lilly-strategy pass:
    Stage 1 - Claude generates client-specific campaign ideas (which
    signals fit THIS offer, with THIS client's parameters).
    Stage 2 - every idea is probed live for whatever TAM exists.
    The user picks from what the data supports. Cached per brief."""
    from concurrent.futures import ThreadPoolExecutor
    import hashlib

    cache_key = hashlib.md5(json.dumps({k: v for k, v in p.items() if k != "force"}, sort_keys=True).encode()).hexdigest()[:16]
    cache = {}
    if STRATEGY_CACHE.exists():
        try:
            cache = json.loads(STRATEGY_CACHE.read_text())
        except ValueError:
            cache = {}
    if not p.get("force") and cache_key in cache:
        return {"ok": True, "cached": True, "rows": cache[cache_key]}

    base: dict = {}
    if p.get("headcount"):
        base["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        base["company_location_search"] = {"include": p["countries"]}
    base_kw = {}
    if p.get("keywords"):
        base_kw["company_keywords"] = {"include": p["keywords"], "include_company_description": True}
    if p.get("industries"):
        base_kw["company_industry"] = {"include": p["industries"]}

    ideas = _run_claude_ideation(p)
    if ideas is None:
        # Ideation is unavailable (no OPENAI_API_KEY locally, or the model call
        # failed). Rather than dead-ending the wizard, hand back a deterministic,
        # clearly-labelled fallback built only from this payload + the static
        # catalogue. RETURN IMMEDIATELY: the Stage-2 probe closures/calls below
        # (pro_dms/probe/probe_once -> Prospeo/preview_hiring) are defined further
        # down in this function body and are never reached on this branch, so this
        # path is guaranteed to spend zero paid-provider credits. Nothing is cached
        # (a real ideation run should always get the chance to replace this).
        return {"ok": True, "cached": False, "rows": _fallback_strategy_rows(p),
                "fallback": True,
                "message": "Live idea generation is unavailable right now - showing signals sized after launch."}
    ideation_fallback = False

    def pro_dms(filters):
        """Count PEOPLE, not companies — the same /search-person query the pull
        runs, so the number shown is the number of decision makers available.
        Rate-limit aware: Prospeo's cooldown is a few seconds, so wait it out."""
        for attempt in range(4):
            if attempt:
                time.sleep(2.5 * attempt)
            d = _search_person(filters)
            if not d.get("error"):
                return (d.get("pagination") or {}).get("total_count") or len(d.get("results") or [])
            msg = str(d.get("message") or d.get("error_code") or "")
            if "NO_RESULTS" in msg:
                return 0
            if "rate limit" in msg.lower():
                time.sleep(3)  # explicit cooldown on top of the backoff
        return None

    def person_filters(prm, extra):
        """Mirror pull_source's filters exactly: expanded DM titles + the idea's
        own keywords/industries params override the wizard-level ones (the pull
        merges config+params the same way — probe and pull must agree)."""
        dm = expand_titles(prm.get("dm_titles") or p.get("titles") or [])
        f = {**base, **base_kw, **extra}
        if prm.get("keywords"):
            kw = prm["keywords"] if isinstance(prm["keywords"], list) else [prm["keywords"]]
            f["company_keywords"] = {"include": kw, "include_company_description": True}
        if prm.get("industries"):
            f["company_industry"] = {"include": prm["industries"]}
        if dm:
            f["person_job_title"] = {"include": dm, "include_partial_match": True}
        else:
            f["person_seniority"] = {"include": ["Founder/Owner", "C-Suite", "Head",
                                                 "Director", "Vice President"]}
        return f

    # hiring pulls enrich up to this many decision makers per hiring company
    MAX_DMS_PER_CO = 2
    # volume floor IN DECISION MAKERS: below this we widen the time/threshold
    # lever one notch and re-probe. Precision filters are never touched, so
    # accuracy is unaffected.
    VOLUME_FLOOR = 50

    def widen_params(mech, prm):
        """One-notch widening per mechanism. Returns new params or None if maxed."""
        if mech == "hiring" and int(prm.get("days") or 30) < 60:
            return {**prm, "days": 60}
        return None

    def probe_once(mech, prm):
        if mech == "hiring":
            codes = country_codes(p.get("countries") or [])[0] or ["US"]
            lo, hi = emp_range(p.get("headcount"))
            # probe with the SAME precision layer + headcount the pull will use,
            # so the number shown in the ideas table is the number that arrives
            extra = {k: prm[k] for k in ("company_description_pattern_or", "company_description_pattern_not",
                                         "industry_or", "industry_not") if prm.get(k)}

            def ts(x):
                for attempt in range(2):
                    if attempt:
                        time.sleep(2.5)
                    try:
                        r = preview_hiring({"job_titles": prm.get("job_titles") or [], "countries": codes,
                                            "min_emp": lo, "max_emp": hi, "days": prm.get("days") or 30,
                                            "extra": x})
                        if r.get("ok"):
                            tc = r.get("total_companies")
                            if tc is None and not r.get("total_jobs"):
                                tc = 0  # a real empty result, not a failed probe
                            return tc
                    except Exception:  # noqa: BLE001
                        pass
                return None

            val = ts(extra)
            if not val and extra.get("company_description_pattern_or"):
                # the REQUIRE gate starves niche roles — drop it (mirrors the
                # pull's fallback) and heal the idea so the source never carries it
                slim = {k: v for k, v in extra.items() if k != "company_description_pattern_or"}
                v2 = ts(slim)
                if v2:
                    prm.pop("company_description_pattern_or", None)
                    val = v2
            # preview estimate: companies x the self-calibrating kept-DMs rate (fleet
            # blend at ideation time — no source exists yet), always labelled an
            # estimate in the UI; the pull counts real people
            return {"dms": round(val * dms_per_company()), "companies": val, "approx": True} if isinstance(val, int) else None
        return None

    def probe(idea):
        mech, prm = idea["mechanism"], idea.get("params") or {}
        if mech == "engagement":
            return "live"
        if mech == "lookalike":
            kw = {"company_keywords": {"include": [prm["icp_text"]], "include_company_description": True}} if prm.get("icp_text") else {}
            d = pro_dms(person_filters(prm, kw))
            return {"dms": d, "companies": None} if isinstance(d, int) else None
        if mech == "company_filter":
            kw = {"company_keywords": {"include": prm["keywords"], "include_company_description": True}} if prm.get("keywords") else {}
            d = pro_dms(person_filters(prm, kw))
            return {"dms": d, "companies": None} if isinstance(d, int) else None
        val = probe_once(mech, prm)
        while val and (val["dms"] or 0) < VOLUME_FLOOR:
            wider = widen_params(mech, prm)
            if not wider:
                break
            wval = probe_once(mech, wider)
            if wval and (wval["dms"] or 0) > (val["dms"] or 0):
                val, prm = wval, wider
                idea["params"] = wider  # the pull inherits the widened window
                idea["widened"] = True
            else:
                break
        return val

    if p.get("skip_probe"):
        # direct mode: the user typed exactly what they want - params still come
        # from ideation but live sizing is deferred to the first real pull, so
        # creating a campaign costs zero provider credits
        results = {id(i): "live" for i in ideas}
    else:
        # hiring/engagement probes can run beside ONE Prospeo lane; Prospeo stays 2-wide
        prospeo_ideas = [i for i in ideas if i["mechanism"] not in ("hiring", "engagement")]
        other_ideas = [i for i in ideas if i["mechanism"] in ("hiring", "engagement")]
        results = {}
        # BOTH lanes are SERIAL (max_workers=1): two concurrent probes trip the
        # providers' rate limits and the collisions cascade through every retry
        with ThreadPoolExecutor(max_workers=1) as pex, ThreadPoolExecutor(max_workers=1) as oex:
            futs = {id(i): pex.submit(probe, i) for i in prospeo_ideas}
            futs.update({id(i): oex.submit(probe, i) for i in other_ideas})
            for i in ideas:
                results[id(i)] = futs[id(i)].result()

        # second chance, one at a time: transient Prospeo rate limits under the
        # parallel pass leave None counts, which hides otherwise-good ideas
        for i in ideas:
            if results[id(i)] is None and i["mechanism"] != "engagement":
                time.sleep(1.0)
                results[id(i)] = probe(i)

    # the number shown is the MONTHLY capture estimate: what the daily pull
    # would identify over 30 days = total-in-window x (30 / window-days).
    # Static audiences (company_filter/lookalike) have no rate - they count
    # as-is and almost always die on the too-broad rule below.
    WINDOW_DAYS = {
        "hiring": lambda prm: max(1, int(prm.get("days") or 30)),
    }
    MONTHLY_CAP = 10_000  # rule of thumb: >10k DMs/month = too broad, exclude

    MIN_SHOWABLE = 10  # under 10 people the signal risks returning nothing (user rule 2026-07-05)
    rows, too_broad, too_small = [], 0, 0
    for i, idea in enumerate(ideas):
        val = results[id(idea)]
        friction = MECH_FRICTION.get(idea["mechanism"], "Med")
        estimated = val == "live"
        dms_total = None if (estimated or not val) else val["dms"]
        companies = None if (estimated or not val) else val["companies"]
        approx = bool(val.get("approx")) if isinstance(val, dict) else False
        win = WINDOW_DAYS.get(idea["mechanism"])
        monthly = (round(dms_total * 30 / win(idea.get("params") or {}))
                   if isinstance(dms_total, int) and win else dms_total)
        if isinstance(monthly, int) and monthly > MONTHLY_CAP:
            too_broad += 1
            continue
        if isinstance(monthly, int) and monthly < MIN_SHOWABLE and not estimated:
            too_small += 1  # too thin to reliably return results - never shown
            continue
        score = min(5, int(idea.get("fit") or 3)) + min(5, int(idea.get("novelty") or 3)) \
            + min(5, int(idea.get("intent") or 3)) + MECH_EASE[friction]
        rows.append({
            "id": f"idea-{i}", "key": idea["mechanism"], "idea": idea["idea"],
            "signal": idea.get("why") or "", "mechanism": idea["mechanism"],
            "params": idea.get("params") or {},
            "companies": companies,
            "dms": monthly, "dms_total": dms_total,
            "icebreaker": idea.get("icebreaker") or "",
            "fit": idea.get("fit"), "novelty": idea.get("novelty"), "intent": idea.get("intent"),
            "score": score, "friction": friction, "estimated": estimated, "approx": approx,
            "window_days": (val or {}).get("window_days") if isinstance(val, dict) else None,
            "companies_total": (val or {}).get("companies_total") if isinstance(val, dict) else None,
            "fallback": ideation_fallback,
        })
    # data has the last word: dead angles sink regardless of the model's score,
    # and ideas that can fill a campaign (>= VOLUME_FLOOR DMs/month) lead
    rows.sort(key=lambda r: (0 if (r["estimated"] or (r["dms"] or 0) > 0) else 1,
                             0 if (r["estimated"] or (r["dms"] or 0) >= VOLUME_FLOOR) else 1,
                             -r["score"]))

    # only cache runs the UI can show - never freeze an all-unsized run in place
    if any(r["estimated"] or (r["dms"] or 0) > 0 for r in rows):
        cache[cache_key] = rows
        STRATEGY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        STRATEGY_CACHE.write_text(json.dumps(cache, indent=1))
    return {"ok": True, "cached": False, "rows": rows, "too_broad": too_broad, "too_small": too_small}


# ── async strategy jobs: ideation + probes take 2-4 min, which no HTTP
#    request should have to survive. POST starts a job, the client polls. ──
STRAT_JOBS: dict = {}


def strategy_map_start(p: dict) -> dict:
    import hashlib
    import threading
    import uuid
    if p.get("sync"):  # harnesses (scenario_test etc.) that want the old shape
        return strategy_map(p)
    # cache fast-path: identical brief already computed -> answer immediately
    cache_key = hashlib.md5(json.dumps({k: v for k, v in p.items() if k != "force"}, sort_keys=True).encode()).hexdigest()[:16]
    if not p.get("force") and STRATEGY_CACHE.exists():
        try:
            cache = json.loads(STRATEGY_CACHE.read_text())
            cached = cache.get(cache_key)
            # only serve a cache hit the UI can actually show - an entry whose
            # rows are all unsized/zero would render an instant empty table
            if cached and any(r.get("estimated") or (r.get("dms") or 0) > 0 for r in cached):
                return {"ok": True, "cached": True, "rows": cached}
        except ValueError:
            pass
    job = uuid.uuid4().hex[:12]
    STRAT_JOBS[job] = {"status": "running", "ts": time.time()}

    def work():
        try:
            STRAT_JOBS[job] = {"status": "done", "ts": time.time(), "result": strategy_map(p)}
        except Exception as e:  # noqa: BLE001
            STRAT_JOBS[job] = {"status": "done", "ts": time.time(),
                               "result": {"ok": False, "rows": [], "message": f"Strategy run crashed: {str(e)[:160]}"}}
        # drop finished jobs after an hour so the dict can't grow forever
        cutoff = time.time() - 3600
        for k in [k for k, v in STRAT_JOBS.items() if v.get("ts", 0) < cutoff]:
            STRAT_JOBS.pop(k, None)

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "job": job}


def strategy_map_result(job: str) -> dict:
    j = STRAT_JOBS.get(job)
    if not j:
        return {"ok": False, "rows": [], "message": "That run is gone (the engine restarted mid-run). Hit Try again."}
    if j["status"] == "running":
        return {"status": "running"}
    return j["result"]


def suggest_location(p: dict) -> dict:
    """Free Prospeo location autocomplete — normalizes free-typed geos."""
    q = (p.get("q") or "").strip()
    if not q:
        return {"ok": False, "message": "Empty query"}
    data = http_json("POST", "https://api.prospeo.io/search-suggestions",
                     {"X-KEY": KEYS["PROSPEO_API_KEY"]}, {"location_search": q})
    suggestions = [
        {"name": s.get("name"), "type": s.get("type")}
        for s in (data.get("location_suggestions") or [])
    ]
    return {"ok": True, "suggestions": suggestions[:6]}


def preview_lookalike(p: dict) -> dict:
    if not p.get("icp_text"):
        return {"ok": False, "message": "Describe the companies you want"}
    filters: dict = {"company_lookalike": {"icp_text": p["icp_text"],
                                           "minimum_tier": p.get("tier") or "T2"}}
    if p.get("headcount"):
        filters["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        filters["company_location_search"] = {"include": p["countries"]}
    return _with_dm_estimate(prospeo_search(filters), p.get("icp_text"),
                             p.get("countries"), p.get("headcount"))


# ── draft sources + QA history (local files only) ────────────────────────

QA_HISTORY = APP_DIR / "data" / "qa_history.json"  # cache/log — stays a file (ephemeral on Render)


def _file_list(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            return []
    return []


def read_json_list(path: Path, strict: bool = False) -> list:
    """Operational lists come from Postgres; the JSON file is only a fallback
    when Supabase is unreachable. WRITE paths pass strict=True so a failed read
    raises (aborting the mutation) instead of silently returning an empty/stale
    list that a whole-table replace would turn into a mass delete."""
    if path == CAMPAIGN_DRAFTS:
        r = _pg_docs("campaign_drafts", strict=strict)
        return r if r is not None else _file_list(path)
    if path == CLIENTS:
        r = _pg_docs("clients", only_doc=True, strict=strict)
        return r if r is not None else _file_list(path)
    return _file_list(path)


# ── endpoint-level read caches (G1) ───────────────────────────────────────
# /api/sources, /api/campaign-drafts and /api/clients are refetched on every
# list-view paint with no cache anywhere in the stack — /api/sources is the
# slowest (a full Supabase doc fetch even for ?slim=1, since the trim only
# drops the `prospects` key AFTER the fetch) and gates every campaign-list
# render. Same 30s-TTL dict+Lock pattern as _compute_lead_counts/_LEAD_COUNTS_CACHE
# below: a failed/degraded read is NEVER cached, so a real Supabase outage keeps
# retrying on every call instead of getting "stuck" serving nothing for 30s.

# ── S1: stale-while-revalidate (SWR) ──────────────────────────────────────
# Every cache above/below used to do a hard synchronous re-fetch the instant a
# request landed past its TTL, so the unlucky caller that crossed the TTL
# boundary ate the full 2-5s Supabase round-trip. _SWRCache flips that: once a
# cache has ANY successfully-fetched payload, a request past TTL gets that
# stale payload back immediately and a single background thread is kicked off
# to recompute it fresh (a per-entry `refreshing` flag stops duplicate
# refreshes from concurrent requests during the same stale window). Only a
# cache with NO payload at all (first request ever, or right after
# _clear_ui_caches() empties it) pays the synchronous cost — which is exactly
# the "never serve stale after a mutation" requirement, since clearing sets
# payload back to None.
class _SWRCache:
    """SWR wrapper around a zero-arg `compute()` returning a payload.
    `is_degraded(payload)` marks a payload as unfit to cache/serve-as-stale
    (e.g. a `_degraded`/fetch-failed result) - such payloads are returned to
    the caller once but never stored, so the next call retries for real."""

    def __init__(self, compute, ttl, is_degraded=lambda p: False, name=""):
        self.compute = compute
        self.ttl = ttl
        self.is_degraded = is_degraded
        self.name = name
        self.lock = threading.Lock()
        self.ts = 0.0
        self.payload = None
        self.refreshing = False

    def _refresh_bg(self):
        try:
            payload = self.compute()
        except Exception as e:  # noqa: BLE001 - background refresh must never crash
            print(f"[swr:{self.name}] background refresh failed: {e}")
            with self.lock:
                self.refreshing = False
            return
        with self.lock:
            self.refreshing = False
            if not self.is_degraded(payload):
                self.ts = time.time()
                self.payload = payload

    def get(self):
        now = time.time()
        with self.lock:
            payload, ts = self.payload, self.ts
        if payload is not None:
            if (now - ts) < self.ttl:
                return payload  # fresh
            # stale: serve immediately, kick exactly one bg refresh
            start_thread = False
            with self.lock:
                if not self.refreshing:
                    self.refreshing = True
                    start_thread = True
            if start_thread:
                threading.Thread(target=self._refresh_bg, daemon=True).start()
            return payload
        # no payload cached at all -> synchronous read-through (first call, or
        # right after _clear_ui_caches() cleared this entry)
        payload = self.compute()
        if not self.is_degraded(payload):
            with self.lock:
                self.ts = time.time()
                self.payload = payload
        return payload

    def clear(self):
        with self.lock:
            self.ts = 0.0
            self.payload = None


class _SWRKeyedCache:
    """Same SWR semantics as _SWRCache, keyed (e.g. per campaign_id/id-set)."""

    def __init__(self, compute, ttl, is_degraded=lambda p: False, name=""):
        self.compute = compute  # fn(key) -> payload
        self.ttl = ttl
        self.is_degraded = is_degraded
        self.name = name
        self.lock = threading.Lock()
        self.entries: dict = {}  # key -> {"ts", "payload", "refreshing"}

    def _refresh_bg(self, key):
        try:
            payload = self.compute(key)
        except Exception as e:  # noqa: BLE001
            print(f"[swr:{self.name}] background refresh failed for {key!r}: {e}")
            with self.lock:
                e2 = self.entries.get(key)
                if e2 is not None:
                    e2["refreshing"] = False
            return
        with self.lock:
            e2 = self.entries.get(key)
            if e2 is not None:
                e2["refreshing"] = False
            if not self.is_degraded(payload):
                self.entries[key] = {"ts": time.time(), "payload": payload, "refreshing": False}

    def get(self, key):
        now = time.time()
        with self.lock:
            entry = self.entries.get(key)
        if entry is not None:
            if (now - entry["ts"]) < self.ttl:
                return entry["payload"]
            start_thread = False
            with self.lock:
                e2 = self.entries.get(key)
                if e2 is not None and not e2["refreshing"]:
                    e2["refreshing"] = True
                    start_thread = True
            if start_thread:
                threading.Thread(target=self._refresh_bg, args=(key,), daemon=True).start()
            return entry["payload"]
        payload = self.compute(key)
        if not self.is_degraded(payload):
            with self.lock:
                self.entries[key] = {"ts": now, "payload": payload, "refreshing": False}
        return payload

    def clear(self):
        with self.lock:
            self.entries.clear()


_SOURCES_TTL_S = 30


def _compute_sources_full() -> tuple:
    docs = _pg_docs("sources")
    fetch_failed = docs is None
    drafts = docs if docs is not None else _file_list(DRAFTS)
    result = sources_for_ui(drafts)
    return result, fetch_failed


_SOURCES_SWR = _SWRCache(_compute_sources_full, _SOURCES_TTL_S,
                          is_degraded=lambda p: p[1], name="sources")


def _cached_sources_full() -> tuple:
    """(sources, fetch_failed). Computes the FULL sources_for_ui(read_drafts())
    result once per TTL window (SWR: stale results are served instantly with a
    background refresh, see _SWRCache); /api/sources derives its ?slim=1
    variant from this same cached result instead of re-fetching."""
    return _SOURCES_SWR.get()


_CAMPAIGN_DRAFTS_TTL_S = 30


def _compute_campaign_drafts() -> tuple:
    docs = _pg_docs("campaign_drafts")
    fetch_failed = docs is None
    result = docs if docs is not None else _file_list(CAMPAIGN_DRAFTS)
    return result, fetch_failed


_CAMPAIGN_DRAFTS_SWR = _SWRCache(_compute_campaign_drafts, _CAMPAIGN_DRAFTS_TTL_S,
                                  is_degraded=lambda p: p[1], name="campaign-drafts")


def _cached_campaign_drafts() -> tuple:
    """(drafts, fetch_failed) - same SWR pattern as _cached_sources_full()."""
    return _CAMPAIGN_DRAFTS_SWR.get()


def _campaign_client_map() -> dict:
    """{str(campaign_draft_id): client_id}, built from the cached campaign_drafts
    list. Shared by /api/sources and /api/lead-counts client_id filtering: neither
    signal_sources rows nor the sources doc-table can be trusted to carry an
    up-to-date client_id (it's resolved lazily at sync time - see sb_sync_source,
    and only AFTER the doc is first written), so joining through the campaign
    draft (which always carries the real client_id set at creation) is the
    reliable path — same resolution sb_sync_source itself falls back to."""
    drafts, _failed = _cached_campaign_drafts()
    return {str(d.get("id")): d.get("client_id") for d in drafts if d.get("id") and d.get("client_id")}


_CLIENTS_TTL_S = 30


def _compute_clients() -> tuple:
    docs = _pg_docs("clients", only_doc=True)
    fetch_failed = docs is None
    result = docs if docs is not None else _file_list(CLIENTS)
    return result, fetch_failed


_CLIENTS_SWR = _SWRCache(_compute_clients, _CLIENTS_TTL_S,
                          is_degraded=lambda p: p[1], name="clients")


def _cached_clients() -> tuple:
    """(clients, fetch_failed) - same SWR pattern as _cached_sources_full()."""
    return _CLIENTS_SWR.get()


def read_drafts(strict: bool = False) -> list:
    r = _pg_docs("sources", strict=strict)
    return r if r is not None else _file_list(DRAFTS)


_DRAFTS_READ_TTL_S = 30  # /api/leads[-batch] call read_drafts() just to map campaign_id -> source
                          # ids/prospects - a single Supabase GET fetching every source's full doc
                          # (prospects arrays included). That read is the actual cost behind "an
                          # invalid campaign_id still burns 3-5s" (the expensive part runs before
                          # the id is even checked). Cache it here so repeat/invalid lookups don't
                          # re-hit Supabase; never cache a failed/empty read.

_DRAFTS_READ_SWR = _SWRCache(read_drafts, _DRAFTS_READ_TTL_S,
                              is_degraded=lambda p: not p, name="drafts-read")


def _cached_read_drafts() -> list:
    return _DRAFTS_READ_SWR.get()


# Column-trimmed select: only the fields the UI (leads tab + list-view activity
# chart) actually reads - source_id/pulled_at/campaign_id come via the local
# `srcs` join below, so this list is what's pulled straight off each row.
_LEADS_COLS = "source_id,full_name,title,company,domain,linkedin_url,country,icebreaker,email,status,pushed_to,pulled_at"


def _map_lead_rows(rows: list, srcs: list) -> list:
    """signal_leads rows -> UI lead dicts, with the local prospect index attached
    so ✓/✕ work. Shared by the full-list and paged fetch paths."""
    by_src = {d["id"]: d for d in srcs}
    out = []
    for r in rows:
        s = by_src.get(r.get("source_id")) or {}
        local = next(((i, x) for i, x in enumerate(s.get("prospects") or [])
                      if x.get("linkedin") == r.get("linkedin_url")), None)
        out.append({
            "name": r.get("full_name"), "title": r.get("title"), "company": r.get("company"),
            "domain": r.get("domain"),
            "linkedin": (r.get("linkedin_url") or "").startswith("http") and r["linkedin_url"] or "",
            "country": r.get("country"), "icebreaker": r.get("icebreaker"),
            "email": r.get("email"), "status": r.get("status"), "pushed_to": r.get("pushed_to"),
            "pulled_at": r.get("pulled_at"), "source_name": s.get("name") or r.get("source_id"),
            "campaign_id": s.get("campaign_id"),
            "job_url": (local or (None, {}))[1].get("job_url"),
            "verdict": (local or (None, {}))[1].get("verdict")
                or {"rejected": "reject", "pushed": "keep"}.get(r.get("status")),
            "_sid": r.get("source_id"), "_idx": local[0] if local else None,
        })
    return out


def _leads_for_sources(srcs: list) -> list:
    """Every signal_leads row for a set of draft sources -> UI lead dicts. One
    Supabase query for the whole set (all pages), newest first."""
    if not srcs:
        return []
    ids = ",".join(str(d["id"]) for d in srcs)
    rows = sb_get_all(f"signal_leads?select={_LEADS_COLS}&source_id=in.({ids})&order=pulled_at.desc")
    if not isinstance(rows, list):
        return []
    return _map_lead_rows(rows, srcs)


def _leads_page_for_campaign(campaign_id: str, offset: int, limit: int) -> list:
    """ONE page of a campaign's signal_leads, straight from Supabase via a Range
    request — the Leads tab loads incrementally (offset/limit) so a large
    campaign never pulls every row at once. Newest first; same row shape as
    api_leads. Bypasses the all-rows SWR cache on purpose."""
    campaign_id = str(campaign_id or "")
    if not campaign_id:
        return []
    srcs = [d for d in _cached_read_drafts() if str(d.get("campaign_id")) == campaign_id]
    if not srcs:
        return []
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))  # hard cap: never let one page pull an unbounded slice
    ids = ",".join(str(d["id"]) for d in srcs)
    rows = sb("GET", f"signal_leads?select={_LEADS_COLS}&source_id=in.({ids})&order=pulled_at.desc",
              headers={"Range-Unit": "items", "Range": f"{offset}-{offset + limit - 1}"})
    if not isinstance(rows, list):
        return []
    return _map_lead_rows(rows, srcs)


_LEADS_TTL_S = 30  # mirrors _LEAD_COUNTS_TTL_S - the leads tab/dashboard poll these on every
                    # navigation; a short cache keeps tab switches instant without going stale for long


def _compute_leads_for_campaign(campaign_id: str) -> list:
    srcs = [d for d in _cached_read_drafts() if str(d.get("campaign_id")) == campaign_id]
    return _leads_for_sources(srcs) if srcs else []  # unmatched id -> [] with no Supabase call


_LEADS_SWR = _SWRKeyedCache(_compute_leads_for_campaign, _LEADS_TTL_S, name="leads")


def api_leads(campaign_id: str) -> list:
    """Every pulled lead for a campaign, straight from Supabase signal_leads —
    accumulates across pulls (the local file only holds the LAST pull). Newest first.
    Unknown/invalid campaign_id short-circuits to [] before any signal_leads query;
    30s TTL SWR cache (keyed by campaign_id) so repeat tab switches are near-instant
    and a request that lands just past TTL still gets an instant (stale) reply."""
    campaign_id = str(campaign_id or "")
    if not campaign_id:
        return []
    return _LEADS_SWR.get(campaign_id)


def _compute_leads_batch(key: str) -> list:
    wanted_set = set(key.split(","))
    srcs = [d for d in _cached_read_drafts() if str(d.get("campaign_id")) in wanted_set]
    return _leads_for_sources(srcs) if srcs else []


_LEADS_BATCH_SWR = _SWRKeyedCache(_compute_leads_batch, _LEADS_TTL_S, name="leads-batch")


def api_leads_batch(campaign_ids: str) -> list:
    """Leads for MANY campaigns in one shot — the dashboard needs every campaign's
    leads to draw the activity chart; a single read_drafts + one Supabase query
    replaces the old N-calls-one-per-campaign waterfall. Same 30s TTL SWR cache as
    api_leads, keyed by the sorted id set."""
    wanted = sorted({c.strip() for c in (campaign_ids or "").split(",") if c.strip()})
    if not wanted:
        return []
    return _LEADS_BATCH_SWR.get(",".join(wanted))


def sources_for_ui(drafts: list) -> list:
    """Draft sources with `total` overlaid to the ACCUMULATED signal_leads count
    per source (what the Leads tab reads), not just the last pull's local prospect
    list. Without this the Sources tab header shows only the newest batch (e.g. 9)
    while the Leads tab shows every lead ever pulled (e.g. 84) — so the per-source
    counts never sum to the Leads total. Only pulled sources are overlaid; an
    un-pulled source keeps its pre-pull estimate. One query for the whole set."""
    ids = [str(d["id"]) for d in drafts if d.get("id") and d.get("last_pull")]
    if not ids:
        return drafts
    rows = sb_get_all(f"signal_leads?select=source_id&source_id=in.({','.join(ids)})")
    if not isinstance(rows, list):
        # Supabase fetch failed - the local `total` on pulled sources is only the
        # LAST pull's count, so flag it stale rather than presenting it as live.
        for d in drafts:
            if d.get("last_pull"):
                d["_count_stale"] = True
        return drafts
    counts: dict = {}
    for r in rows:
        sid = str(r.get("source_id"))
        counts[sid] = counts.get(sid, 0) + 1
    for d in drafts:
        sid = str(d.get("id"))
        if d.get("last_pull"):  # pulled -> show accumulated total (0 if none saved yet)
            d["total"] = counts.get(sid, 0)
    return drafts


def _compute_lead_counts() -> dict:
    """Per-campaign lead counts from the same signal_leads rows the Leads tab
    reads, so the campaign card and the tab always agree. One query for all
    campaigns; {campaign_id: {leads, sent}}."""
    # Mirror read_drafts() but keep the Supabase failure visible: an outage must
    # come back as _degraded, not as "zero leads on every campaign".
    docs = _pg_docs("sources")
    drafts = docs if docs is not None else _file_list(DRAFTS)
    by_src = {str(d["id"]): str(d.get("campaign_id"))
              for d in drafts if d.get("id") and d.get("campaign_id")}
    if not by_src:
        return {"_degraded": True} if docs is None else {}
    rows = sb_get_all(f"signal_leads?select=source_id,status,pushed_to&source_id=in.({','.join(by_src)})")
    if not isinstance(rows, list):
        return {"_degraded": True}
    out: dict = {}
    for r in rows:
        cid = by_src.get(str(r.get("source_id")))
        if not cid:
            continue
        c = out.setdefault(cid, {"leads": 0, "sent": 0})
        c["leads"] += 1
        if r.get("pushed_to") or r.get("status") == "pushed":
            c["sent"] += 1
    # Every campaign that has a source mapping gets an explicit {leads:0,sent:0}
    # entry even with zero signal_leads rows, so a MISSING entry in the payload
    # strictly means "unavailable" (degraded/never fetched), never "no leads yet".
    for cid in set(by_src.values()):
        out.setdefault(cid, {"leads": 0, "sent": 0})
    if docs is None:  # counts built from the stale local fallback source list
        out["_degraded"] = True
    return out


_LEAD_COUNTS_TTL_S = 30  # /api/lead-counts is polled on every list/detail load;
                          # a short in-process cache avoids re-querying Supabase
                          # on every page view without going stale for long.

_LEAD_COUNTS_SWR = _SWRCache(_compute_lead_counts, _LEAD_COUNTS_TTL_S,
                              is_degraded=lambda p: p.get("_degraded"), name="lead-counts")


def api_lead_counts() -> dict:
    """Cached wrapper around _compute_lead_counts() - never caches a `_degraded`
    result (a transient Supabase outage must not get "stuck" showing degraded
    for the next 30s once Supabase recovers), so a real outage is retried on
    every call same as before, but the common healthy case is served from
    memory for up to _LEAD_COUNTS_TTL_S seconds (SWR: stale-but-good results
    beyond that are served instantly with a background refresh)."""
    return _LEAD_COUNTS_SWR.get()


def _clear_ui_caches():
    """Invalidate every UI-facing read cache (G2). Mutations (approve/skip a
    lead, push, edit a campaign, ...) must be visible on the very next GET, not
    masked by up-to-30s-stale cached payloads. Called ONCE at the top of each
    write-dispatch entry point (do_POST, do_PATCH), before any handler runs.
    Clearing an _SWRCache/_SWRKeyedCache drops its payload entirely (not just
    the timestamp), so the very next GET after a mutation is guaranteed to do
    a synchronous read-through — SWR only ever serves a stale payload when one
    already exists, and clear() removes it."""
    _SOURCES_SWR.clear()
    _CAMPAIGN_DRAFTS_SWR.clear()
    _CLIENTS_SWR.clear()
    _LEAD_COUNTS_SWR.clear()
    _LEADS_SWR.clear()
    _LEADS_BATCH_SWR.clear()
    _DRAFTS_READ_SWR.clear()
    _NOTIFICATIONS_SWR.clear()


NOTIFICATION_STATUSES = ("new", "acknowledged", "actioned", "dismissed", "approved")
# "approved" (tier1-live-ship Step 5 gap closure, 2026-07-14): the DB's status
# CHECK constraint was widened to add it (see app/optimiser_notifications.sql's
# v3 note above the constraint for the widen pattern) so the notifications.html
# Approve button on a replace_variants row's drafted-fix card can PATCH a real,
# durable status instead of the old "reuse acknowledged" workaround.
_NOTIFICATION_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}  # unranked/None sorts last

# canonical client id -> free-text name variants this table's legacy `client`
# column has actually held (see app/migrations/2026-07-08-tool-level-clients.sql,
# NOT yet run against the DB). Mirrors shell.js's CLIENT_ALIAS.
NOTIFICATIONS_CLIENT_ALIASES = {
    "client-1": ["Navreo", "navreo"],
    "client-2": ["Amplifyy", "amplifyy"],
    "client-3": ["Arnic", "arnic"],
}

# Every optimiser_notifications column EXCEPT claude_prompt (per
# app/optimiser_notifications.sql) — the ?slim=1 payload-weight fix. Keep in
# sync with that schema file if columns are ever added/removed.
#
# draft_fix IS included here (unlike claude_prompt): it's a small jsonb blob
# (null on almost every row — only populated once a CSM clicks "Draft the
# fix" on a replace_variants row) rather than a several-KB text column, so
# there's no payload-weight reason to slim it out. Including it lets the
# initial list render a drafted replacement immediately on page load without
# a second per-row fetch — see notifications.html's replacementFixHTML.
NOTIFICATIONS_SLIM_SELECT = (
    "id,campaign_id,campaign_name,client,client_id,finding_type,section,"
    "block_number,priority,title,detail,suggested_action,action_type,"
    "api_safe,smartlead_url,sent,positive,replied,sent_pos_ratio,"
    "completion_pct,reply_rate,status,created_at,actioned_at,variants,"
    "impact_score,impact_reason,meetings,draft_fix"
)


_NOTIFICATIONS_TTL_S = 60  # G1/S1: unfiltered /api/notifications was a single
# uncached Supabase round-trip (every column incl. the heavy claude_prompt
# text) on EVERY list-view paint - 278 rows and rising, no pagination, no
# cache anywhere in the stack (unlike sources/campaign-drafts/clients above).
# Same SWR pattern as those: keyed by the tuple of filter params that affect
# the query (slim/status/priority/client/client_id), so the common no-filter
# call and each per-client ?slim=1&client_id= call get independent 60s-TTL
# entries. `id=` single-row lookups (the "Copy Claude prompt" fetch) always
# bypass this cache - see api_notifications() below - since that's already a
# cheap single-row fetch and must never serve a stale claude_prompt.


def _compute_notifications_list(key: tuple) -> list:
    """key = (slim, status, priority, client, client_id) - see api_notifications()."""
    from urllib.parse import quote
    slim, status, priority, client, client_id = key
    select_param = [f"select={quote(NOTIFICATIONS_SLIM_SELECT, safe=',')}"] if slim else []
    filters = [f"{k}=eq.{quote(v, safe='')}"
               for k, v in (("status", status), ("priority", priority), ("client", client)) if v]

    def _fetch(extra_filters: list):
        parts = select_param + filters + extra_filters + ["order=created_at.desc"]
        return sb("GET", f"optimiser_notifications?{'&'.join(parts)}")

    if client_id:
        names = NOTIFICATIONS_CLIENT_ALIASES.get(client_id, [client_id])
        name_list = ",".join(quote(n, safe="") for n in names)
        cid_q = quote(client_id, safe="")
        rows = _fetch([f"or=(client_id.eq.{cid_q},client.in.({name_list}))"])
        if not isinstance(rows, list):
            # Most likely cause: client_id column doesn't exist on this table
            # yet (pre-migration) - PostgREST errors the whole `or=` filter on
            # an unknown column. Fall back to the free-text-only match so the
            # param still filters correctly today.
            rows = _fetch([f"client=in.({name_list})"])
    else:
        rows = _fetch([])
    rows = rows if isinstance(rows, list) else []
    rows.sort(key=lambda r: _NOTIFICATION_PRIORITY_RANK.get(r.get("priority"), 3))
    return rows


_NOTIFICATIONS_SWR = _SWRKeyedCache(_compute_notifications_list, _NOTIFICATIONS_TTL_S,
                                     is_degraded=lambda p: not isinstance(p, list),
                                     name="notifications")


def api_notifications(qs: dict) -> list:
    """List optimiser_notifications rows (Optimiser tab feed), optionally
    filtered by status/priority/client — all AND'd, all pushed to PostgREST as
    eq. filters rather than fetched-then-filtered in Python. Sort is High >
    Medium > Low > None priority, newest created_at first within each tier;
    PostgREST can't express that custom enum order in one order= clause, so we
    ask it for created_at.desc and re-rank by priority here (a stable sort
    keeps the created_at ordering intact within each priority group).

    Optional `client_id` (canonical id, e.g. "client-1") pushes an equality
    filter down to PostgREST instead of the caller fetching everything and
    filtering client-side. The table only has a free-text `client` column
    today (no client_id column yet — see the migration file above), so this
    matches `client` against the known name variants for that id. The query
    is built as `or=(client_id.eq.<id>,client.in.(<names>))` so that once the
    migration adds a real client_id column, PostgREST starts honouring the
    client_id.eq half automatically with zero code changes here. Until then,
    referencing the not-yet-existing column makes PostgREST error the whole
    request — caught below by falling back to a plain `client=in.(<names>)`
    filter, so the client_id param degrades gracefully to today's free-text
    match instead of silently returning nothing.

    Optional `id=<uuid>` short-circuits everything above and returns just that
    one row, full (never slimmed) — used by the frontend's on-demand "Copy
    Claude prompt" fetch so the initial list load doesn't have to carry every
    row's claude_prompt text.

    Optional `slim=1` selects every column EXCEPT claude_prompt (by far the
    heaviest column — a pre-built Claude Code prompt, often several KB of
    text, present on most Section 7 rows). The initial page load uses this to
    cut payload weight; call again with `id=` when the full text is actually
    needed for one row."""
    from urllib.parse import quote
    row_id = (qs.get("id") or [""])[0].strip()
    if row_id:
        rows = sb("GET", f"optimiser_notifications?id=eq.{quote(row_id, safe='')}")
        return rows if isinstance(rows, list) else []
    slim = (qs.get("slim") or [""])[0].strip() in ("1", "true", "yes")
    status = (qs.get("status") or [""])[0]
    priority = (qs.get("priority") or [""])[0]
    client = (qs.get("client") or [""])[0]
    client_id = (qs.get("client_id") or [""])[0].strip()
    key = (slim, status, priority, client, client_id)
    return _NOTIFICATIONS_SWR.get(key)


def update_notification_status(nid: str, status: str) -> dict:
    """Move one optimiser_notifications row through the new -> acknowledged /
    actioned / dismissed lifecycle (and back to new). actioned_at is stamped
    the moment status becomes 'actioned' and is otherwise left untouched —
    reverting to any other status must never clear a timestamp that already
    recorded when the finding was actioned."""
    from datetime import datetime, timezone
    patch = {"status": status}
    if status == "actioned":
        patch["actioned_at"] = datetime.now(timezone.utc).isoformat()
    result = sb("PATCH", f"optimiser_notifications?id=eq.{nid}", patch,
                prefer="return=representation")
    if result is None:
        raise RuntimeError("Supabase unavailable")
    if not result:
        raise LookupError("notification not found")
    return result[0]


# ── draft-fix (tier1-live-ship Step 5 gap closure, 2026-07-14) ──────────────
# On-demand LLM draft of the FULL replacement email for a replace_variants
# row's flagged variant. The click on notifications.html's "Draft the fix"
# button IS the credit-control gate — this machinery must never be called
# from api_notifications()/_compute_notifications_list() or any other list/
# compute path, only from the POST route below.

DRAFT_FIX_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        # The exact substring of the CURRENT email body that is the problem
        # statement being replaced — copied verbatim so the server (not the
        # model) can do the substitution. This is what actually guarantees
        # the subject/icebreaker/offer/CTA come out byte-identical: the
        # server only ever touches the span the model names here, never
        # regenerates the rest of the body (or the subject) itself. See
        # api_notification_draft_fix's subject-handling comment for why
        # subject isn't a separate model-authored field.
        "old_sentence": {"type": "string"},
        # The new problem statement (45-70 words, no em dashes) that replaces
        # old_sentence.
        "changed_sentence": {"type": "string"},
        "kept": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "icebreaker": {"type": "string"},
                "offer": {"type": "string"},
                "cta": {"type": "string"},
            },
            "required": ["icebreaker", "offer", "cta"],
        },
    },
    "required": ["old_sentence", "changed_sentence", "kept"],
}


def _parsed_variants_list(row: dict) -> list | None:
    variants = row.get("variants")
    if isinstance(variants, str):
        try:
            variants = json.loads(variants)
        except ValueError:
            return None
    return variants if isinstance(variants, list) else None


def _flagged_variant_for_row(row: dict, variants: list) -> dict | None:
    """Mirrors notifications.html's flaggedVariantFor(n) exactly (same
    failing/off flag logic, same title-match-else-worst-first fallback) so
    the server never drafts a fix for a different variant than the one the
    Why-expander names on screen."""
    failing = [v for v in variants if isinstance(v, dict)
               and "failing" in (v.get("flags") or [])
               and "disabled" not in (v.get("flags") or [])
               and "zero_distribution" not in (v.get("flags") or [])]
    if not failing:
        return None
    m = _VARIANT_CALL_TITLE_RE.match(row.get("title") or "")
    if m:
        email_num = m.group(1)
        variant_label = (m.group(2) or "").strip()
        for v in failing:
            if str(v.get("email") or "") == str(email_num) and (
                (variant_label and str(v.get("variant") or "") == variant_label)
                or (not variant_label and not v.get("variant"))
            ):
                return v
    failing = sorted(failing, key=lambda v: ((v.get("positives") or 0), -(v.get("sent") or 0)))
    return failing[0]


def _winning_variant_for_row(variants: list) -> dict | None:
    winners = [v for v in variants if isinstance(v, dict) and "winner" in (v.get("flags") or [])]
    if not winners:
        return None
    winners.sort(key=lambda v: ((v.get("positives") or 0), (v.get("meetings") or 0),
                                 (v.get("replies") or 0)), reverse=True)
    return winners[0]


def _extract_smartlead_variant_copy(sequences: list, email_num, variant_label) -> tuple | None:
    """(subject, body) for one step/variant out of a fresh
    GET /campaigns/{id}/sequences response. `email_num` matches a step's
    seq_number (1-indexed, same field build_notifications.py stores as
    `email` on the row's variants jsonb); `variant_label` matches a
    sequence_variants[].variant_label (case-insensitive), or None for the
    step-level (no-A/B, e.g. Email 2) copy. Falls back to the step's own
    subject/body when the variant row doesn't override one of them (Smartlead
    variants can inherit either field from the step)."""
    for s in sequences:
        if str(s.get("seq_number")) != str(email_num):
            continue
        if variant_label:
            for v in (s.get("sequence_variants") or []):
                if v.get("is_deleted"):
                    continue
                if str(v.get("variant_label") or "").strip().lower() == str(variant_label).strip().lower():
                    subject = v.get("subject") if v.get("subject") is not None else s.get("subject")
                    body = v.get("email_body") if v.get("email_body") is not None else s.get("email_body")
                    return (subject or "", body or "")
            return None
        return (s.get("subject") or "", s.get("email_body") or "")
    return None


def _replace_verbatim_or_normalized(haystack: str, needle: str, replacement: str) -> str | None:
    """Swap `needle` for `replacement` inside `haystack`. Tries an exact
    substring match first (the common case for a careful verbatim copy);
    falls back to a whitespace-insensitive match (collapsing any run of
    whitespace in `needle` to \\s+) since a minimal-effort completion
    occasionally normalises internal line breaks/spacing when it copies a
    span out of HTML-ish email_body text. Returns None (caller must report a
    clear error, never fabricate) if neither matches — this is the one place
    that guarantees the icebreaker/offer/CTA never get silently rewritten."""
    if not needle:
        return None
    if needle in haystack:
        return haystack.replace(needle, replacement, 1)
    pattern = re.sub(r"\s+", r"\\s+", re.escape(needle))
    m = re.search(pattern, haystack, flags=re.DOTALL)
    if not m:
        return None
    return haystack[:m.start()] + replacement + haystack[m.end():]


def api_notification_draft_fix(nid: str) -> tuple:
    """POST /api/notifications/<id>/draft-fix.

    Cache-first: a non-null draft_fix already on the row is returned as-is —
    no LLM spend, no Smartlead call, this IS the cache-hit path the ship
    brief asks for.

    READ-ONLY against Smartlead: the ONLY Smartlead call in this function is
    GET /campaigns/{id}/sequences (via _smartlead_json). NEVER a sequences
    POST/save — that resets variant stats, exactly what the card's fixwarn
    note tells the CSM to avoid by pasting manually.

    The model never reassembles the icebreaker/offer/CTA itself: it names the
    exact substring to replace (old_sentence) and the server does the
    substitution against the untouched current_body, so those three parts
    come out of this endpoint byte-identical to what is live in Smartlead
    right now, not merely "close" to it.
    """
    rows = sb("GET", f"optimiser_notifications?id=eq.{nid}")
    if not isinstance(rows, list) or not rows:
        return 404, {"ok": False, "message": "notification not found"}
    row = rows[0]

    if row.get("action_type") != "replace_variants":
        return 400, {"ok": False, "message": "draft-fix only applies to replace_variants rows"}

    cached = row.get("draft_fix")
    if isinstance(cached, dict) and cached:
        return 200, {"ok": True, "cache_hit": True, "draft_fix": cached}

    variants = _parsed_variants_list(row)
    if not variants:
        return 400, {"ok": False, "message": "this row has no variant breakdown to draft from"}

    flagged = _flagged_variant_for_row(row, variants)
    if not flagged:
        return 400, {"ok": False, "message": "could not identify the flagged (failing) variant on this row"}

    try:
        campaign_id = int(row.get("campaign_id"))
    except (TypeError, ValueError):
        return 400, {"ok": False, "message": "campaign_id is not numeric"}

    if not KEYS.get("SMARTLEAD_API_KEY"):
        return 503, {"ok": False, "message": "SMARTLEAD_API_KEY is not configured on this server"}

    sequences_raw = _smartlead_json("GET", f"/campaigns/{campaign_id}/sequences")
    sequences = sequences_raw if isinstance(sequences_raw, list) else (
        (sequences_raw.get("data") or sequences_raw.get("sequences") or [])
        if isinstance(sequences_raw, dict) else [])
    if not sequences:
        return 502, {"ok": False, "message": "Smartlead returned no sequences for this campaign",
                      "smartlead_url": row.get("smartlead_url")}

    current = _extract_smartlead_variant_copy(sequences, flagged.get("email"), flagged.get("variant"))
    if not current:
        return 404, {"ok": False,
                      "message": "the flagged variant was not found in Smartlead's current sequence — it "
                                 "may have been edited or removed since this finding was generated",
                      "smartlead_url": row.get("smartlead_url")}
    current_subject, current_body = current
    if not current_body.strip():
        return 400, {"ok": False, "message": "the flagged variant has no email body in Smartlead to draft from"}

    winner = _winning_variant_for_row(variants)
    winner_copy = None
    if winner:
        winner_copy = _extract_smartlead_variant_copy(sequences, winner.get("email"), winner.get("variant"))

    tried = sorted({(v.get("angle") or "").strip() for v in variants
                    if isinstance(v, dict) and (v.get("angle") or "").strip()})

    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        return 503, {"ok": False, "message": "OPENAI_API_KEY missing from ~/.navreo-keys.env"}

    system = (
        "You rewrite ONE underperforming cold-email variant for a B2B outbound agency. The email "
        "has, in order: an icebreaker/opening personalisation line, a problem-statement paragraph, "
        "an offer, and a call to action (CTA). old_sentence must be copied CHARACTER FOR CHARACTER "
        "from the current email body given to you — it is the existing problem-statement span that "
        "will be swapped out; a paraphrase or a small edit to it makes the swap fail. changed_sentence "
        "is the NEW problem statement that replaces it: a different argument than every angle already "
        "tried on this campaign (do not reuse or lightly reword a tried angle), 45-70 words, plain "
        "English, no em dashes, and any merge tags or spintax present in the surrounding email "
        "preserved exactly if the new sentence needs them. kept.icebreaker, kept.offer and kept.cta "
        "are the exact verbatim icebreaker/offer/CTA text from the current email (character for "
        "character, including merge tags like {{first_name}} and spintax like {a|b}) — copied for "
        "display only, they are never edited."
    )
    user_bits = [
        f"Current subject: {current_subject}",
        f"Current full email body:\n{current_body}",
    ]
    if tried:
        user_bits.append("Problem-statement angles already tried on this campaign (do not repeat any of "
                          "these, even reworded): " + "; ".join(tried))
    if winner_copy and winner_copy[1].strip():
        user_bits.append("For tone/register reference only — a DIFFERENT variant that is winning on this "
                          "campaign, do not copy its problem statement or angle:\n" + winner_copy[1])
    user = "\n\n".join(user_bits)

    try:
        out = _suggest_llm(key, system, user, "draft_fix", DRAFT_FIX_SCHEMA)
    except Exception as e:  # noqa: BLE001 — surface as a clear JSON error, never a bare 500
        return 502, {"ok": False, "message": f"draft generation failed: {str(e)[:300]}"}

    old_sentence = (out.get("old_sentence") or "").strip()
    changed_sentence = (out.get("changed_sentence") or "").strip()
    if not changed_sentence:
        return 502, {"ok": False, "message": "draft generation returned no replacement text"}
    body_html = _replace_verbatim_or_normalized(current_body, old_sentence, changed_sentence)
    if body_html is None:
        return 502, {"ok": False,
                      "message": "draft generation could not isolate the problem statement in the live "
                                 "copy — try again, or edit the sequence directly in Smartlead"}

    # Subject is server-authoritative, not model-trusted: it stays byte-
    # identical to the live subject (which is legitimately "" on a lot of
    # follow-up steps, e.g. Email 2 replying in-thread — a minimal-effort
    # completion asked to "return the subject unchanged" on an EMPTY current
    # subject has been observed inventing text instead of echoing blank). The
    # one exception the prompt allows — the subject literally quoting the old
    # problem statement — is applied here with the same verbatim/normalized
    # swap as the body, never by trusting out.get("subject") directly.
    subject = current_subject
    if old_sentence and old_sentence in current_subject:
        subject = current_subject.replace(old_sentence, changed_sentence, 1)

    draft_fix = {
        "subject": subject.strip(),
        "body_html": body_html,
        "changed_sentence": changed_sentence,
        "kept": {
            "icebreaker": ((out.get("kept") or {}).get("icebreaker") or "").strip(),
            "offer": ((out.get("kept") or {}).get("offer") or "").strip(),
            "cta": ((out.get("kept") or {}).get("cta") or "").strip(),
        },
        "tried": tried,
        "drafted_at": _now_iso(),
        "model": SUGGEST_MODEL,
    }
    result = sb("PATCH", f"optimiser_notifications?id=eq.{nid}", {"draft_fix": draft_fix},
                prefer="return=representation")
    if not isinstance(result, list) or not result:
        return 502, {"ok": False, "message": "draft generated but failed to save — Supabase unavailable, retry"}

    log_activity("/api/notifications/draft-fix", {"campaign_id": campaign_id}, action="draft",
                 entity="notification", entity_id=nid)
    return 200, {"ok": True, "cache_hit": False, "draft_fix": draft_fix}


# ── executable notification actions (Optimiser CSM-approval gate) ───────

# Only these two action_types have an API-safe executable *pause* act attached.
# kill_threshold_pivot's *executable* half is "pause the campaign" - the
# strategic re-pivot decision itself always stays human, in the Smartlead UI.
# This set gates ONLY the "pause" action below (action_type membership).
# The "disable_variant" action (below) is gated on a completely separate
# check - finding_type=="variant_call" AND suggested_action matching
# /disable/i - since a variant-disable candidate is never one of these two
# campaign-level action_types; do not add "disable_loser" to this set.
NOTIFICATION_EXECUTABLE_ACTIONS = {"pause_campaign", "kill_threshold_pivot"}

# request body {"action": ...} allowlist for POST /api/notifications/{id}/execute.
# "pause" (the default, for backward compatibility with callers that omit
# `action` entirely - the original pause-only body was just {"confirm":"PAUSE"})
# and "disable_variant" (BETA - see execute_disable_variant_action below).
NOTIFICATION_EXECUTE_ACTIONS = {"pause", "disable_variant"}

_VARIANT_CALL_TITLE_RE = re.compile(r"^Variant call: Email\s*(\d+)(?:\s+Var\s+(.+?))?\s*$", re.I)


def execute_notification_action(nid: str, payload: dict) -> tuple:
    """POST /api/notifications/{id}/execute - fires the one API-safe Smartlead
    action attached to a notification finding. Dispatches on body {"action":
    "pause"|"disable_variant"} (default "pause" when omitted, matching the
    original pause-only callers that only ever sent {"confirm":"PAUSE"}).

    Returns (http_status, json_body) for the caller to hand to self._json.
    """
    action = str(payload.get("action") or "pause").strip().lower()
    if action not in NOTIFICATION_EXECUTE_ACTIONS:
        return 400, {"ok": False, "message": f"unknown action '{action}'"}

    rows = sb("GET", f"optimiser_notifications?id=eq.{nid}")
    if not isinstance(rows, list) or not rows:
        return 404, {"ok": False, "message": "notification not found"}
    row = rows[0]

    if action == "disable_variant":
        return execute_disable_variant_action(nid, row, payload)
    return execute_pause_action(nid, row, payload)


def execute_pause_action(nid: str, row: dict, payload: dict) -> tuple:
    """The original pause-campaign action (unchanged behaviour, only moved
    into its own function to make room for execute_disable_variant_action).

    Gated behind an explicit CSM {"confirm": "PAUSE"} in the request body:
    the optimiser guardrails say "NEVER pause or stop a campaign without CSM
    approval" - the CSM typing/clicking confirm in the UI IS that approval,
    so this endpoint must never be callable without it.

    HARD CONSTRAINT: this handler may ONLY EVER call Smartlead's
    POST /campaigns/{id}/status endpoint. Never a sequence-save/variant
    endpoint - those used to destroy variant history when ids were omitted.
    (2026-07-09 draft experiments proved an id-carrying sequences POST is a
    true in-place update that preserves history - see
    execute_disable_variant_action below, which is now the ONE sanctioned
    exception that reaches a sequences endpoint, and only via that exact
    id-carrying + post-verify path. This pause handler still never touches
    sequences/variants.)
    """
    action_type = row.get("action_type")
    api_safe = bool(row.get("api_safe"))
    smartlead_url = row.get("smartlead_url")
    if not api_safe or action_type not in NOTIFICATION_EXECUTABLE_ACTIONS:
        return 400, {"ok": False,
                      "message": "this action must be done in the Smartlead UI",
                      "smartlead_url": smartlead_url}

    if payload.get("confirm") != "PAUSE":
        return 400, {"ok": False,
                      "message": 'confirmation required: send {"confirm":"PAUSE"}'}

    try:
        campaign_id = int(row.get("campaign_id"))
    except (TypeError, ValueError):
        return 400, {"ok": False, "message": "campaign_id is not numeric"}

    # The ONLY Smartlead endpoint this handler is allowed to call - see the
    # HARD CONSTRAINT above. Do not add a sequences/variants call here.
    url = (f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/status"
           f"?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}")
    req = urllib.request.Request(
        url, data=json.dumps({"status": "PAUSED"}).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            sl_status, sl_raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        sl_status, sl_raw = e.code, e.read().decode()
    try:
        sl_body = json.loads(sl_raw) if sl_raw else {}
    except ValueError:
        sl_body = sl_raw

    if not (200 <= sl_status < 300):
        # Smartlead rejected the pause - do NOT touch the notification row.
        return 502, {"ok": False, "message": "Smartlead pause failed",
                      "smartlead_status": sl_status, "smartlead_response": sl_body}

    try:
        updated = update_notification_status(nid, "actioned")
    except Exception as e:  # noqa: BLE001 - Smartlead already paused; the
        # notification-row update is best-effort bookkeeping on top of that,
        # so a failure here must not be reported as the pause having failed.
        return 200, {"ok": True, "executed": action_type, "campaign_id": campaign_id,
                      "smartlead_response": sl_body,
                      "notification_update_error": str(e)[:300]}

    return 200, {"ok": True, "executed": action_type, "campaign_id": campaign_id,
                  "smartlead_response": sl_body, "notification": updated}


def _redistribute_variant_shares(others: list, target_pct: int) -> dict:
    """others = [{"id":..., "pct": int>0}, ...] currently-active siblings
    (never includes the target being disabled, never includes already-0%/
    deleted variants). Returns {id: new_pct} for `others` only, summing to
    exactly (target_pct + sum(o['pct'] for o in others)) - i.e. the target's
    share folded back in, proportionally, to the remaining active variants -
    using the largest-remainder method so integer percentages always sum
    exactly right (plain `round()` on each share independently can drift the
    total off by 1-2 points either way).

    Example: 3 variants at 34/33/33, disabling the 33 -> pool = 33+34=67
    folded into a new pool of 100 across the 2 survivors: raw shares
    34/67*100=50.75 and 33/67*100=49.25 -> floors 50/49, remainder 1 goes to
    the larger fractional remainder -> 51/49 (sums to 100)."""
    pool = target_pct + sum(o["pct"] for o in others)
    total_others = sum(o["pct"] for o in others)
    if total_others <= 0:
        # Defensive fallback (shouldn't happen - `others` is filtered to
        # pct>0 by the caller): split the pool evenly.
        base, rem = divmod(pool, len(others))
        return {o["id"]: base + (1 if i < rem else 0) for i, o in enumerate(others)}
    raw = {o["id"]: (o["pct"] / total_others) * pool for o in others}
    floors = {oid: int(v) for oid, v in raw.items()}
    remainder = pool - sum(floors.values())
    order = sorted(others, key=lambda o: raw[o["id"]] - floors[o["id"]], reverse=True)
    for i in range(remainder):
        floors[order[i]["id"]] += 1
    return floors


def _build_disable_variant_payload(sequences: list, target_seq_id, target_variant_id, new_pcts: dict) -> list:
    """Remap a fresh GET /campaigns/{id}/sequences response (list of steps,
    each with `sequence_variants`) into the POST /campaigns/{id}/sequences
    body shape - carrying every id through untouched and changing ONLY the
    distribution percentages named in new_pcts (target -> 0, everyone else
    per _redistribute_variant_shares). Every step is included (not just the
    target one) so no other step is dropped/recreated by the save. Field-name
    remap per 2026-07-09 draft experiments (GET names != POST names):
    sequence_variants -> seq_variants, delayInDays -> delay_in_days (inside
    seq_delay_details). Never touches subject/email_body anywhere."""
    out = []
    for s in sequences:
        step = {"id": s.get("id"), "seq_number": s.get("seq_number")}
        delay = (s.get("seq_delay_details") or {}).get("delayInDays")
        if delay is not None:
            step["seq_delay_details"] = {"delay_in_days": delay}
        if s.get("subject") is not None:
            step["subject"] = s.get("subject")
        if s.get("email_body") is not None:
            step["email_body"] = s.get("email_body")
        variants = s.get("sequence_variants") or []
        if variants:
            seq_variants = []
            for v in variants:
                vid = v.get("id")
                variant = {"id": vid, "variant_label": v.get("variant_label")}
                if v.get("subject") is not None:
                    variant["subject"] = v.get("subject")
                if v.get("email_body") is not None:
                    variant["email_body"] = v.get("email_body")
                if s.get("id") == target_seq_id and vid in new_pcts:
                    variant["variant_distribution_percentage"] = new_pcts[vid]
                elif v.get("variant_distribution_percentage") is not None:
                    variant["variant_distribution_percentage"] = v.get("variant_distribution_percentage")
                seq_variants.append(variant)
            step["seq_variants"] = seq_variants
        out.append(step)
    return out


def execute_disable_variant_action(nid: str, row: dict, payload: dict) -> tuple:
    """BETA: disables one losing A/B variant (sets its Smartlead traffic
    distribution to 0%, redistributing its share across the remaining active
    variants) without ever touching copy or deleting anything. This is the
    ONE sanctioned code path in this file that reaches Smartlead's sequences
    endpoint (see execute_pause_action's HARD CONSTRAINT comment above) - and
    only via the id-carrying-payload + post-verify pattern proven safe in the
    2026-07-09 draft experiments (memory: reference_smartlead_write_endpoints).

    Eligibility (server-enforced, nothing client-supplied is trusted):
      - row.finding_type == "variant_call"
      - row.suggested_action matches /disable/i (e.g. "Clear loser - disable")
    Anything else -> 400, same "do it in the Smartlead UI" message as pause.

    Confirm token: body must carry {"confirm": "DISABLE"} (the CSM's
    click/type IS the approval, same contract as the pause action's "PAUSE").

    Title parsing: row.title is "Variant call: Email {n} Var {label}" -
    if the title has no "Var {label}" half (e.g. bare "Variant call: Email 2")
    or the regex otherwise fails to match, the variant cannot be uniquely
    identified from this row alone -> 409, with a smartlead_url escape hatch.

    Guards (each a 4xx, NOTHING mutated if any fires):
      - step (by email/seq_number) or variant (by label) not found in a
        fresh GET -> 404 (title parsed fine, but Smartlead's current state
        doesn't match it - stale row, edited since, etc).
      - target variant already at 0% distribution -> 400 (nothing to do).
      - fewer than 2 currently-active (distribution>0, not is_deleted)
        variants on that step -> 400 (never disable the last active one).

    Post-verify: after the POST, a second fresh GET must show every seq id
    and every seq_variant_id on this campaign unchanged from the pre-POST
    snapshot, AND the target variant now at 0%. Any id drift -> 500, loud
    message, full before/after logged server-side, notification row left
    untouched (NOT marked actioned) - "check Smartlead" is the escape hatch,
    not silent retry.
    """
    finding_type = row.get("finding_type")
    suggested_action = row.get("suggested_action") or ""
    smartlead_url = row.get("smartlead_url")
    if finding_type != "variant_call":
        return 400, {"ok": False,
                      "message": "this action must be done in the Smartlead UI",
                      "smartlead_url": smartlead_url}

    if payload.get("confirm") != "DISABLE":
        return 400, {"ok": False,
                      "message": 'confirmation required: send {"confirm":"DISABLE"}'}

    # Title parse (409) before the /disable/i eligibility half (400): a
    # "Whole offer failing" variant_call row has BOTH an unparseable title
    # and a non-disable suggested_action, and its actionable truth is "this
    # cannot be resolved to one variant" - report that (409 + Smartlead
    # escape hatch), not a generic ineligibility.
    title = row.get("title") or ""
    m = _VARIANT_CALL_TITLE_RE.match(title)
    email_num = int(m.group(1)) if m else None
    variant_label = (m.group(2) or "").strip() if m else ""
    if not m or not variant_label:
        return 409, {"ok": False,
                      "message": "variant could not be uniquely identified, use Smartlead",
                      "smartlead_url": smartlead_url}

    # Second half of eligibility: only rows whose optimiser recommendation
    # actually says disable (e.g. "Clear loser - disable") may reach the
    # sequence save. REPLACE / scale-winner / flip rows are never eligible.
    if not re.search(r"disable", suggested_action, re.I):
        return 400, {"ok": False,
                      "message": "this action must be done in the Smartlead UI",
                      "smartlead_url": smartlead_url}

    try:
        campaign_id = int(row.get("campaign_id"))
    except (TypeError, ValueError):
        return 400, {"ok": False, "message": "campaign_id is not numeric"}

    api_key = KEYS.get("SMARTLEAD_API_KEY", "")
    seq_url = f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/sequences?api_key={api_key}"

    before = http_json("GET", seq_url, {})
    before_steps = before if isinstance(before, list) else (
        before.get("data") or before.get("sequences") or [] if isinstance(before, dict) else [])
    if not before_steps:
        return 404, {"ok": False, "message": "could not load campaign sequences from Smartlead",
                      "smartlead_url": smartlead_url}

    target_step = next((s for s in before_steps if int(s.get("seq_number") or 0) == email_num), None)
    if target_step is None:
        return 404, {"ok": False, "message": f"email {email_num} not found in this campaign's sequences",
                      "smartlead_url": smartlead_url}

    step_variants = target_step.get("sequence_variants") or []
    target_variant = next(
        (v for v in step_variants
         if str(v.get("variant_label") or "").strip().lower() == variant_label.lower()),
        None)
    if target_variant is None:
        return 404, {"ok": False,
                      "message": f"variant {variant_label} not found on Email {email_num}",
                      "smartlead_url": smartlead_url}

    target_pct = target_variant.get("variant_distribution_percentage")
    try:
        target_pct = int(target_pct)
    except (TypeError, ValueError):
        target_pct = 0
    if target_variant.get("is_deleted") or target_pct <= 0:
        return 400, {"ok": False, "message": "this variant already has 0% distribution - nothing to disable",
                      "smartlead_url": smartlead_url}

    active = []
    for v in step_variants:
        if v.get("is_deleted"):
            continue
        try:
            pct = int(v.get("variant_distribution_percentage") or 0)
        except (TypeError, ValueError):
            pct = 0
        if pct > 0:
            active.append({"id": v.get("id"), "pct": pct})
    if len(active) < 2:
        return 400, {"ok": False,
                      "message": "fewer than 2 active variants on this step - refusing to disable the last one",
                      "smartlead_url": smartlead_url}

    others = [a for a in active if a["id"] != target_variant.get("id")]
    new_pcts = _redistribute_variant_shares(others, target_pct)
    new_pcts[target_variant.get("id")] = 0

    before_ids = {"seqs": sorted(str(s.get("id")) for s in before_steps),
                  "variants": sorted(str(v.get("id")) for s in before_steps for v in (s.get("sequence_variants") or []))}

    post_body = _build_disable_variant_payload(before_steps, target_step.get("id"), target_variant.get("id"), new_pcts)
    save_url = f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/sequences?api_key={api_key}"
    sl_resp = http_json("POST", save_url, {}, {"sequences": post_body})

    after = http_json("GET", seq_url, {})
    after_steps = after if isinstance(after, list) else (
        after.get("data") or after.get("sequences") or [] if isinstance(after, dict) else [])
    after_ids = {"seqs": sorted(str(s.get("id")) for s in after_steps),
                 "variants": sorted(str(v.get("id")) for s in after_steps for v in (s.get("sequence_variants") or []))}
    after_target_step = next((s for s in after_steps if int(s.get("seq_number") or 0) == email_num), None)
    after_target_variant = next(
        (v for v in (after_target_step.get("sequence_variants") or []) if v.get("id") == target_variant.get("id")),
        None) if after_target_step else None
    after_target_pct = after_target_variant.get("variant_distribution_percentage") if after_target_variant else None

    print(f"[disable_variant] campaign={campaign_id} email={email_num} variant={variant_label} "
          f"before_ids={before_ids} after_ids={after_ids} before_pct={target_pct} after_pct={after_target_pct} "
          f"new_pcts={new_pcts} smartlead_response={sl_resp}")

    if before_ids != after_ids:
        return 500, {"ok": False,
                      "message": "id drift detected - variant history may be affected, check Smartlead",
                      "smartlead_url": smartlead_url}
    if after_target_pct is None or int(after_target_pct or 0) != 0:
        return 500, {"ok": False,
                      "message": "save did not take - variant is not at 0% after saving, check Smartlead",
                      "smartlead_url": smartlead_url}

    try:
        updated = update_notification_status(nid, "actioned")
    except Exception as e:  # noqa: BLE001 - Smartlead already saved; the
        # notification-row update is best-effort bookkeeping on top of that.
        return 200, {"ok": True, "executed": "disable_variant", "campaign_id": campaign_id,
                      "before": {"variant": variant_label, "pct": target_pct},
                      "after": new_pcts,
                      "notification_update_error": str(e)[:300]}

    return 200, {"ok": True, "executed": "disable_variant", "campaign_id": campaign_id,
                 "before": {"variant": variant_label, "pct": target_pct},
                 "after": new_pcts, "notification": updated}


# ── Lists API (read-only viewer over the Supabase list_* tables) ─────────
# Lists are WRITTEN by skills (straight into Supabase) and only READ here.
# HARD RULE: nothing in this server ever writes list_rows cell data, and no
# create-list endpoint exists. The endpoints below serve the viewer UI —
# browse folders/lists, page rows through the api_list_rows_page RPC (search/
# filter/sort/pagination all run in the database; Python only proxies) — plus
# organisational metadata writes on `lists`/`list_folders` (folder create,
# move, last-opened stamp). Every handler returns (status, body)
# for self._json, like execute_notification_action above.

def _lists_sb_error(res) -> str | None:
    """PostgREST errors surface through http_json as a dict with a `message`
    key (a normal result here is a list, or the RPC's json object, which has
    no `message`). Return the message, or None when `res` looks healthy."""
    if isinstance(res, dict) and res.get("message"):
        return str(res["message"])
    return None


_LISTS_DB_DOWN = {"error": "supabase_unavailable",
                  "message": "Couldn't reach the database - try again."}


def _lists_is_duplicate_error(res) -> bool:
    """True when `res` is a PostgREST unique-violation error (code 23505) —
    a panel tester saw this raw ('duplicate key value violates unique
    constraint "..."') verbatim in the new-folder modal. Callers swap it for
    a friendly message naming the folder instead of surfacing it as-is."""
    if not isinstance(res, dict):
        return False
    if str(res.get("code") or "") == "23505":
        return True
    return "duplicate key value violates unique constraint" in str(res.get("message") or "")


def api_lists_index() -> tuple:
    """GET /api/lists — every folder + every list's metadata (never rows)."""
    folders = sb("GET", "list_folders?select=id,client,name,parent_id"
                        "&order=client.asc,name.asc")
    lists_ = sb("GET", "lists?select=id,name,client,folder_id,source_skill,"
                       "owner,access,row_count,created_at,"
                       "last_opened_at,last_opened_by&order=created_at.desc")
    if not isinstance(folders, list) or not isinstance(lists_, list):
        return 503, _LISTS_DB_DOWN
    return 200, {"folders": folders, "lists": lists_}


def api_lists_rows(q: dict) -> tuple:
    """GET /api/lists/rows — the list's metadata row + one page of rows via
    the api_list_rows_page RPC. `q` is a parse_qs dict (values are lists)."""
    lid = (q.get("id") or [""])[0].strip()
    if not lid:
        return 400, {"ok": False, "message": "id is required"}
    try:
        filters = json.loads((q.get("filters") or ["{}"])[0] or "{}")
        if not isinstance(filters, dict):
            raise ValueError("filters must be a JSON object")
    except ValueError as e:
        return 400, {"ok": False,
                     "message": f"filters is not valid JSON: {str(e)[:120]}"}
    try:
        offset = int((q.get("offset") or ["0"])[0] or 0)
        limit = int((q.get("limit") or ["500"])[0] or 500)
    except ValueError:
        return 400, {"ok": False, "message": "offset/limit must be integers"}
    meta = sb("GET", f"lists?id=eq.{lid}&select=id,name,client,columns")
    if meta is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(meta, list) or not meta:
        # a malformed uuid comes back as a PostgREST error dict — same outcome
        # for the caller as an unknown id: there is no such list.
        return 404, {"ok": False, "message": "list not found"}
    page = sb("POST", "rpc/api_list_rows_page", {
        "p_list_id": lid, "p_offset": offset, "p_limit": limit,
        "p_search": (q.get("search") or [""])[0],
        "p_sort": (q.get("sort") or [""])[0],
        "p_dir": (q.get("dir") or [""])[0],
        "p_filters": filters,
    })
    if isinstance(page, list):  # rpc returning a set — unwrap the single row
        page = page[0] if page else None
    err = _lists_sb_error(page)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(page, dict):
        return 503, _LISTS_DB_DOWN
    row = meta[0]
    return 200, {"id": row.get("id"), "name": row.get("name"),
                 "client": row.get("client"), "columns": row.get("columns"),
                 "total": page.get("total"), "filtered": page.get("filtered"),
                 "offset": page.get("offset"), "limit": page.get("limit"),
                 "rows": page.get("rows") or []}


def api_lists_distinct(q: dict) -> tuple:
    """GET /api/lists/distinct — distinct values (+counts) for one column via
    the api_list_distinct_values RPC. Powers the Sheets/Clay-style value-picker
    in the column filter popover (checked values -> exact array filter)."""
    lid = (q.get("id") or [""])[0].strip()
    col = (q.get("col") or [""])[0].strip()
    if not lid:
        return 400, {"ok": False, "message": "id is required"}
    if not col:
        return 400, {"ok": False, "message": "col is required"}
    meta = sb("GET", f"lists?id=eq.{lid}&select=id")
    if meta is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(meta, list) or not meta:
        return 404, {"ok": False, "message": "list not found"}
    try:
        limit = int((q.get("limit") or ["100"])[0] or 100)
    except ValueError:
        return 400, {"ok": False, "message": "limit must be an integer"}
    res = sb("POST", "rpc/api_list_distinct_values", {
        "p_list_id": lid, "p_col": col,
        "p_search": (q.get("search") or [""])[0] or None,
        "p_limit": limit,
    })
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list):
        return 503, _LISTS_DB_DOWN
    return 200, {"id": lid, "col": col, "values": res}


def lists_create_folder(p: dict) -> tuple:
    """POST /api/lists/folder — a client root (name null) or, with parent_id,
    a themed sub-folder (name required). A DB trigger enforces max depth —
    its rejection surfaces as a 400, never a silent success."""
    client = str(p.get("client") or "").strip()
    if not client:
        return 400, {"ok": False, "message": "client is required"}
    name = str(p.get("name") or "").strip() or None
    parent_id = p.get("parent_id") or None
    if parent_id and not name:
        return 400, {"ok": False, "message": "a sub-folder needs a name"}
    res = sb("POST", "list_folders",
             {"client": client, "name": name, "parent_id": parent_id},
             prefer="return=representation")
    if _lists_is_duplicate_error(res):
        return 400, {"ok": False,
                     "message": f"A folder named '{name or client}' already exists here."}
    err = _lists_sb_error(res)
    if err:  # e.g. the max-depth trigger
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list) or not res:
        return 502, _LISTS_DB_DOWN
    return 200, {"id": res[0].get("id")}


def _lists_patch(list_id, patch: dict) -> tuple:
    """Shared PATCH-one-list plumbing for move/touch. Only ever
    touches organisational metadata on `lists` — never list_rows."""
    if not list_id:
        return 400, {"ok": False, "message": "list_id is required"}
    res = sb("PATCH", f"lists?id=eq.{list_id}", patch,
             prefer="return=representation")
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if res is None:
        return 502, _LISTS_DB_DOWN
    if not res:
        return 404, {"ok": False, "message": "list not found"}
    return 200, {"ok": True}


def lists_move(p: dict) -> tuple:
    # folder_id null/absent = unfiled (back under the client root). An optional
    # `client` lets drag-and-drop move a list ACROSS clients (dropping it onto
    # another client's folder or root row): the file browser groups by
    # lists.client, so the list must adopt the destination's client to stay
    # visible under — and travel with — that folder.
    patch = {"folder_id": p.get("folder_id") or None}
    if str(p.get("client") or "").strip():
        patch["client"] = str(p.get("client")).strip()
    return _lists_patch(p.get("list_id"), patch)


def lists_folder_move(p: dict) -> tuple:
    """POST /api/lists/folder/move — reparent a themed sub-folder under a
    different client's root. That's the only meaningful folder move: folders
    live at exactly one level (client root -> theme), so a folder can't nest
    inside another folder, only change which client it belongs to. Sets the
    folder's client + parent_id and CASCADES the new client onto every list
    filed in it, so the browser (which groups by lists.client) keeps the folder
    and its contents together. Client ROOT folders (name IS NULL) can't move."""
    folder_id = p.get("folder_id")
    target = str(p.get("client") or "").strip()
    if not folder_id:
        return 400, {"ok": False, "message": "folder_id is required"}
    if not target:
        return 400, {"ok": False, "message": "a destination client is required"}
    existing = sb("GET", f"list_folders?id=eq.{folder_id}&select=id,client,name")
    if existing is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(existing, list) or not existing:
        return 404, {"ok": False, "message": "folder not found"}
    folder = existing[0]
    if folder.get("name") is None:
        return 400, {"ok": False, "message": "Client root folders can't be moved."}
    if folder.get("client") == target:
        return 200, {"ok": True}  # already under this client — nothing to do
    # find (or create) the destination client's root folder to parent under.
    # Fetch all roots and match in Python so an arbitrary client name never has
    # to be URL-encoded into a PostgREST filter.
    roots = sb("GET", "list_folders?name=is.null&select=id,client")
    if not isinstance(roots, list):
        return 503, _LISTS_DB_DOWN
    root = next((r for r in roots if r.get("client") == target), None)
    root_id = root.get("id") if root else None
    if not root_id:
        made = sb("POST", "list_folders",
                  {"client": target, "name": None, "parent_id": None},
                  prefer="return=representation")
        err = _lists_sb_error(made)
        if err:
            return 400, {"ok": False, "message": err[:300]}
        if not isinstance(made, list) or not made:
            return 502, _LISTS_DB_DOWN
        root_id = made[0].get("id")
    res = sb("PATCH", f"list_folders?id=eq.{folder_id}",
             {"client": target, "parent_id": root_id},
             prefer="return=representation")
    if _lists_is_duplicate_error(res):
        return 400, {"ok": False,
                     "message": f"A folder named '{folder.get('name')}' already exists under {target}."}
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list) or not res:
        return 404, {"ok": False, "message": "folder not found"}
    # cascade the new client onto the folder's lists so they move with it.
    sb("PATCH", f"lists?folder_id=eq.{folder_id}", {"client": target})
    return 200, {"ok": True}


def lists_touch(p: dict) -> tuple:
    from datetime import datetime, timezone
    patch = {"last_opened_at": datetime.now(timezone.utc).isoformat()}
    if p.get("by"):
        patch["last_opened_by"] = str(p.get("by"))
    return _lists_patch(p.get("list_id"), patch)


def lists_folder_rename(p: dict) -> tuple:
    """POST /api/lists/folder/rename — rename a themed sub-folder. Client
    ROOT folders (name IS NULL) aren't renameable — a panel tester needed
    that spelled out rather than a generic failure."""
    folder_id = p.get("folder_id")
    if not folder_id:
        return 400, {"ok": False, "message": "folder_id is required"}
    name = str(p.get("name") or "").strip()
    if not name:
        return 400, {"ok": False, "message": "name is required"}
    existing = sb("GET", f"list_folders?id=eq.{folder_id}&select=id,name")
    if existing is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(existing, list) or not existing:
        return 404, {"ok": False, "message": "folder not found"}
    if existing[0].get("name") is None:
        return 400, {"ok": False, "message": "Client root folders can't be renamed."}
    res = sb("PATCH", f"list_folders?id=eq.{folder_id}", {"name": name},
             prefer="return=representation")
    if _lists_is_duplicate_error(res):
        return 400, {"ok": False,
                     "message": f"A folder named '{name}' already exists here."}
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list) or not res:
        return 404, {"ok": False, "message": "folder not found"}
    return 200, {"ok": True}


def lists_rows_delete(p: dict) -> tuple:
    """POST /api/lists/rows/delete — bulk-delete specific rows from ONE list by
    row_num. SAFETY: refuses (400) when list_id is missing, row_nums is empty,
    or row_nums has more than 2000 entries; the DELETE path is asserted to
    carry `list_id=eq.` before it's ever sent — a past incident wiped a whole
    table on an unscoped delete and this must never repeat. After deleting,
    recounts the list's remaining rows and patches `lists.row_count` so the
    file browser / grid chip stay in sync without a second client round-trip."""
    list_id = p.get("list_id")
    if not list_id or not isinstance(list_id, str):
        return 400, {"ok": False, "message": "list_id is required"}
    row_nums = p.get("row_nums")
    if not isinstance(row_nums, list) or not row_nums:
        return 400, {"ok": False, "message": "row_nums is required and must be a non-empty array"}
    if len(row_nums) > 2000:
        return 400, {"ok": False, "message": "can't delete more than 2000 rows in one request"}
    try:
        nums = sorted({int(n) for n in row_nums})
    except (TypeError, ValueError):
        return 400, {"ok": False, "message": "row_nums must be integers"}
    if not nums:
        return 400, {"ok": False, "message": "row_nums is required and must be a non-empty array"}
    meta = sb("GET", f"lists?id=eq.{list_id}&select=id")
    if meta is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(meta, list) or not meta:
        return 404, {"ok": False, "message": "list not found"}
    in_clause = ",".join(str(n) for n in nums)
    delete_path = f"list_rows?list_id=eq.{list_id}&row_num=in.({in_clause})"
    assert "list_id=eq." in delete_path, "refusing an unscoped list_rows delete"  # hard safety gate
    res = sb("DELETE", delete_path, prefer="return=representation")
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list):
        return 503, _LISTS_DB_DOWN
    deleted = len(res)
    new_count = _sb_count(f"list_rows?list_id=eq.{list_id}")
    if new_count is not None:
        sb("PATCH", f"lists?id=eq.{list_id}", {"row_count": new_count})  # best-effort
    return 200, {"ok": True, "deleted": deleted, "row_count": new_count}


def lists_delete(p: dict) -> tuple:
    """POST /api/lists/delete — hard-delete one list (list_rows cascade via the
    DB's FK). 404s when the list doesn't exist so the UI can tell "already
    gone" apart from a real failure."""
    list_id = p.get("list_id")
    if not list_id:
        return 400, {"ok": False, "message": "list_id is required"}
    existing = sb("GET", f"lists?id=eq.{list_id}&select=id")
    if existing is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(existing, list) or not existing:
        return 404, {"ok": False, "message": "list not found"}
    res = sb("DELETE", f"lists?id=eq.{list_id}", prefer="return=representation")
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list) or not res:
        return 404, {"ok": False, "message": "list not found"}
    return 200, {"ok": True}


def _slugify_filename(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (name or "list")).strip("-").lower()
    return s or "list"


def api_lists_export_csv(q: dict):
    """GET /api/lists/export — stream a CSV of the FULL filtered/sorted set
    (not just one page): loops the api_list_rows_page RPC 2000 rows at a time,
    advancing the offset until a short page signals the end, so a "Download"
    click matches exactly what the current search/sort/filters show on
    screen. Returns a 3-tuple: either ("error", status, body) for the caller
    to hand to self._json, or ("csv", filename, body_bytes) to stream as-is."""
    lid = (q.get("id") or [""])[0].strip()
    if not lid:
        return "error", 400, {"ok": False, "message": "id is required"}
    try:
        filters = json.loads((q.get("filters") or ["{}"])[0] or "{}")
        if not isinstance(filters, dict):
            raise ValueError("filters must be a JSON object")
    except ValueError as e:
        return "error", 400, {"ok": False, "message": f"filters is not valid JSON: {str(e)[:120]}"}
    search = (q.get("search") or [""])[0]
    sort = (q.get("sort") or [""])[0]
    dir_ = (q.get("dir") or [""])[0]
    meta = sb("GET", f"lists?id=eq.{lid}&select=id,name,client,columns")
    if meta is None:
        return "error", 503, _LISTS_DB_DOWN
    if not isinstance(meta, list) or not meta:
        return "error", 404, {"ok": False, "message": "list not found"}
    columns = meta[0].get("columns") or []
    name = meta[0].get("name") or "list"

    import csv, io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    offset = 0
    page_size = 2000
    while True:
        page = sb("POST", "rpc/api_list_rows_page", {
            "p_list_id": lid, "p_offset": offset, "p_limit": page_size,
            "p_search": search, "p_sort": sort, "p_dir": dir_, "p_filters": filters,
        })
        if isinstance(page, list):  # rpc returning a set — unwrap the single row
            page = page[0] if page else None
        err = _lists_sb_error(page)
        if err:
            return "error", 400, {"ok": False, "message": err[:300]}
        if not isinstance(page, dict):
            return "error", 503, _LISTS_DB_DOWN
        batch = page.get("rows") or []
        for row in batch:
            data = row.get("data") or {}
            writer.writerow([data.get(c) for c in columns])
        if len(batch) < page_size:
            break
        offset += page_size
    body = buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 cleanly
    return "csv", f"{_slugify_filename(name)}.csv", body


def lists_folder_delete(p: dict) -> tuple:
    """POST /api/lists/folder/delete — refuse (400, friendly message) when the
    folder still has lists filed in it or sub-folders parented to it; those
    were panel-clutter with no way to remove them otherwise. Empty ones are
    hard-deleted."""
    folder_id = p.get("folder_id")
    if not folder_id:
        return 400, {"ok": False, "message": "folder_id is required"}
    child_lists = sb("GET", f"lists?folder_id=eq.{folder_id}&select=id&limit=1")
    if child_lists is None:
        return 503, _LISTS_DB_DOWN
    err = _lists_sb_error(child_lists)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if child_lists:
        return 400, {"ok": False,
                     "message": "This folder still has lists in it - move or delete them first."}
    child_folders = sb("GET", f"list_folders?parent_id=eq.{folder_id}&select=id&limit=1")
    if child_folders is None:
        return 503, _LISTS_DB_DOWN
    err = _lists_sb_error(child_folders)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if child_folders:
        return 400, {"ok": False,
                     "message": "This folder still has sub-folders in it - move or delete them first."}
    res = sb("DELETE", f"list_folders?id=eq.{folder_id}", prefer="return=representation")
    err = _lists_sb_error(res)
    if err:
        return 400, {"ok": False, "message": err[:300]}
    if not isinstance(res, list) or not res:
        return 404, {"ok": False, "message": "folder not found"}
    return 200, {"ok": True}


# ── Saved Pulls (resumable list_pulls) ────────────────────────────────────
# A "Saved Pull" (list_pulls row) freezes a targeting brief plus a cursor so
# a GTME can take a batch now and come back later for more, from the Lists
# page, with no memory of how it was built. SAMPLE MODE ONLY here (provider
# == 'sample'): it draws batches from an existing free list already sitting
# in list_rows instead of a paid provider. That's a deliberate, narrow
# exception to the "Lists are WRITTEN by skills, only READ here" hard rule
# above — the only list_rows writes this endpoint ever issues are appends to
# an output list it itself owns (named "<pull name> — pulled" and recorded
# on list_pulls.list_id), never an arbitrary caller-supplied list_id. Real
# providers (ocean/prospeo/ai_ark) are refused with a 400 — the paid pull
# engine is a separate, not-yet-built piece of work.

def api_list_pulls_index() -> tuple:
    """GET /api/list_pulls — every Saved Pull, newest first. Retained for
    completeness; the UI no longer uses it (a Saved Pull is discovered by
    opening its backing list, via api_list_pull_for_list below)."""
    rows = sb("GET", "list_pulls?select=id,name,client,provider,total_tam,"
                     "pulled_count,tranche_size,status,cursor,credit_ledger,"
                     "brief_md,filter_json,list_id&order=created_at.desc")
    if not isinstance(rows, list):
        return 503, _LISTS_DB_DOWN
    return 200, {"pulls": rows}


def api_list_pull_for_list(q: dict) -> tuple:
    """GET /api/list_pulls/for_list?id=<list_id> — the single Saved Pull whose
    backing list is <list_id>, or {"pull": null} if the list isn't a Saved
    Pull. Powers the resume panel that docks onto an opened list's grid."""
    from urllib.parse import quote
    lid = (q.get("id") or [""])[0].strip()
    if not lid:
        return 400, {"ok": False, "message": "id is required"}
    rows = sb("GET", f"list_pulls?list_id=eq.{quote(lid, safe='')}&select=id,name,"
                     "provider,total_tam,pulled_count,tranche_size,status,cursor,"
                     "credit_ledger,brief_md&limit=1")
    if not isinstance(rows, list):
        return 503, _LISTS_DB_DOWN
    return 200, {"pull": rows[0] if rows else None}


def api_list_pull_campaigns(q: dict) -> tuple:
    """GET /api/list_pulls/campaigns?pull_id=<id> — the campaigns this pull's
    leads were pushed into, aggregated by campaign (total leads + last date),
    newest first. Powers the "Campaigns" subsection of the resume panel."""
    from urllib.parse import quote
    pull_id = (q.get("pull_id") or [""])[0].strip()
    if not pull_id:
        return 400, {"ok": False, "message": "pull_id is required"}
    rows = sb("GET", f"list_pull_campaigns?pull_id=eq.{quote(pull_id, safe='')}"
                     "&select=campaign_id,campaign_name,rows,at&order=at.desc")
    if not isinstance(rows, list):
        return 503, _LISTS_DB_DOWN
    # Aggregate by campaign in Python (PostgREST can't group+order this shape
    # without a view); key on campaign_id when present, else the name.
    agg: dict = {}
    order: list = []
    for r in rows:
        key = r.get("campaign_id") or r.get("campaign_name") or ""
        if key not in agg:
            agg[key] = {"campaign_id": r.get("campaign_id"),
                        "campaign_name": r.get("campaign_name"),
                        "total": 0, "last_at": r.get("at")}
            order.append(key)
        agg[key]["total"] += r.get("rows") or 0
        if (r.get("at") or "") > (agg[key]["last_at"] or ""):
            agg[key]["last_at"] = r.get("at")
    # `rows` already came back newest-first, so first-seen order preserves it.
    return 200, {"campaigns": [agg[k] for k in order]}


def api_list_pulls_by_campaign(q: dict) -> tuple:
    """GET /api/list_pulls/by_campaign?campaign_id=<id>|campaign_name=<name> —
    reverse lookup: the pull/list rows whose leads filled a given campaign.
    No dedicated UI yet, but the linkage is queryable."""
    from urllib.parse import quote
    cid = (q.get("campaign_id") or [""])[0].strip()
    cname = (q.get("campaign_name") or [""])[0].strip()
    if not cid and not cname:
        return 400, {"ok": False, "message": "campaign_id or campaign_name is required"}
    filt = (f"campaign_id=eq.{quote(cid, safe='')}" if cid
            else f"campaign_name=eq.{quote(cname, safe='')}")
    rows = sb("GET", f"list_pull_campaigns?{filt}"
                     "&select=pull_id,list_id,campaign_id,campaign_name,rows,at"
                     "&order=at.desc")
    if not isinstance(rows, list):
        return 503, _LISTS_DB_DOWN
    return 200, {"links": rows}


def api_list_pulls_push_summary(q: dict) -> tuple:
    """GET /api/list_pulls/push_summary[?list_id=<id>] — where each list's
    leads have been pushed, aggregated list_id -> platform -> campaigns. ONE
    aggregated fetch powers both the All-Files "Pushed to" column (no
    list_id param = every list) and the grid header's destination chips +
    popover (list_id param = just that list)."""
    from urllib.parse import quote
    lid = (q.get("list_id") or [""])[0].strip()
    path = ("list_pull_campaigns?select=list_id,platform,campaign_id,"
            "campaign_name,rows,at&order=at.desc")
    if lid:
        path += f"&list_id=eq.{quote(lid, safe='')}"
    rows = sb_get_all(path)
    if rows is None:
        return 503, _LISTS_DB_DOWN
    # list_id -> platform -> campaign -> {total, last_at}; rows arrive
    # newest-first, so first-seen order keeps campaigns newest-first too.
    summary: dict = {}
    for r in rows:
        list_id = r.get("list_id")
        if not list_id:
            continue
        platform = (r.get("platform") or "smartlead").lower()
        plat = summary.setdefault(list_id, {}).setdefault(
            platform, {"total": 0, "campaigns": {}, "order": []})
        key = r.get("campaign_id") or r.get("campaign_name") or ""
        camp = plat["campaigns"].get(key)
        if camp is None:
            camp = plat["campaigns"][key] = {
                "campaign_id": r.get("campaign_id"),
                "campaign_name": r.get("campaign_name"),
                "total": 0, "last_at": r.get("at")}
            plat["order"].append(key)
        camp["total"] += r.get("rows") or 0
        if (r.get("at") or "") > (camp["last_at"] or ""):
            camp["last_at"] = r.get("at")
        plat["total"] += r.get("rows") or 0
    out = {list_id: [{"platform": platform, "total": plat["total"],
                      "campaigns": [plat["campaigns"][k] for k in plat["order"]]}
                     for platform, plat in plats.items()]
           for list_id, plats in summary.items()}
    return 200, {"summary": out}


_PULL_LOCK_TTL_S = 120  # a locked_by held longer than this is treated as abandoned
_PULL_ROW_CHUNK = 500   # matches list_upload.py's BATCH_SIZE


def _pull_lock_is_stale(locked_at_raw) -> bool:
    """True when a held lock is older than _PULL_LOCK_TTL_S (or unparsable —
    fail open rather than bricking a pull on a timestamp format surprise)."""
    from datetime import datetime, timezone
    if not locked_at_raw:
        return True
    try:
        locked_at = datetime.fromisoformat(str(locked_at_raw).replace("Z", "+00:00"))
        if locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - locked_at).total_seconds() > _PULL_LOCK_TTL_S
    except ValueError:
        return True


def _pull_append_rows(list_id: str, start_row_num: int, columns: list, data_rows: list) -> int:
    """Append `data_rows` (list of {col: val} dicts) to list_rows for
    `list_id`, continuing row_num from start_row_num. Chunked like
    list_upload.py._insert_rows; the only place in server.py that writes
    list_rows (see the Saved Pulls note above)."""
    inserted = 0
    for i in range(0, len(data_rows), _PULL_ROW_CHUNK):
        batch = data_rows[i:i + _PULL_ROW_CHUNK]
        payload = [{"list_id": list_id, "row_num": start_row_num + i + offset,
                    "data": {col: row.get(col) for col in columns}}
                   for offset, row in enumerate(batch)]
        sb("POST", "list_rows", payload)
        inserted += len(batch)
    return inserted


def list_pulls_pull(p: dict) -> tuple:
    """POST /api/list_pulls/pull {id, size?} — take the next batch for a
    SAMPLE-mode Saved Pull. See the Saved Pulls note above for scope."""
    from datetime import datetime, timezone
    from urllib.parse import quote

    pull_id = str(p.get("id") or "").strip()
    if not pull_id:
        return 400, {"ok": False, "message": "id is required"}

    rows = sb("GET", f"list_pulls?id=eq.{quote(pull_id, safe='')}")
    if rows is None:
        return 503, _LISTS_DB_DOWN
    if not isinstance(rows, list) or not rows:
        return 404, {"ok": False, "message": "Saved pull not found"}
    pull = rows[0]

    if pull.get("provider") != "sample":
        return 400, {"ok": False, "message": "only sample pulls can be pulled from the tool"}

    if pull.get("locked_by") and not _pull_lock_is_stale(pull.get("locked_at")):
        return 409, {"ok": False, "message": "a pull is already running"}

    now = datetime.now(timezone.utc)
    sb("PATCH", f"list_pulls?id=eq.{pull_id}",
       {"locked_by": "tool", "locked_at": now.isoformat()})
    try:
        total_tam = pull.get("total_tam") or 0
        pulled_count = pull.get("pulled_count") or 0
        remaining = total_tam - pulled_count
        if remaining <= 0:
            return 200, {"ok": True, "done": True, "message": "all pulled"}

        try:
            size = int(p.get("size")) if p.get("size") else None
        except (TypeError, ValueError):
            size = None
        take = min(size or pull.get("tranche_size") or 500, remaining)
        if take <= 0:
            return 400, {"ok": False, "message": "size must be a positive number"}

        source_list_id = (pull.get("filter_json") or {}).get("sample_source_list_id")
        if not source_list_id:
            return 400, {"ok": False, "message": "this sample pull has no source list configured"}

        cursor = pull.get("cursor") or {}
        offset = int(cursor.get("offset") or 0)

        src_rows = sb("GET", f"list_rows?list_id=eq.{quote(source_list_id, safe='')}"
                             "&order=row_num.asc&select=row_num,data",
                      headers={"Range-Unit": "items", "Range": f"{offset}-{offset + take - 1}"})
        if not isinstance(src_rows, list):
            return 503, _LISTS_DB_DOWN
        if not src_rows:  # end of the source pool — advance nothing further
            return 200, {"ok": True, "done": True, "message": "all pulled"}
        # src_rows may be shorter than `take` at the tail of the source pool —
        # inserted (below) is always len(src_rows), so offset/pulled_count only
        # ever advance by what was actually fetched.

        # Batches append to the pull's OWN backing list (list_pulls.list_id) —
        # the list that appears in the file browser. Under the current model
        # both existing pulls are pre-linked; the create-and-link path below
        # only fires for a future pull whose backing list was never made.
        client = pull.get("client")
        out_list_id = pull.get("list_id")
        columns = None  # set below — either the backing list's, or fresh from this batch

        if out_list_id:
            existing = sb("GET", f"lists?id=eq.{out_list_id}&select=id,columns")
            if isinstance(existing, list) and existing:
                columns = existing[0].get("columns") or []
            else:
                out_list_id = None  # stale link — recreate and re-link below

        if not out_list_id:
            # No backing list yet — create one and link it. Columns are fixed
            # here from the first row's own key order and never recomputed on
            # later batches (a later batch with a slightly different key set
            # must not reshuffle/drop the list's established column schema).
            columns = list((src_rows[0].get("data") or {}).keys())
            created = sb("POST", "lists", {
                "name": pull.get("name"), "client": client, "folder_id": None,
                "source_skill": "signals-list-resume",
                "brief_context": pull.get("brief_md"),
                "row_count": 0, "columns": columns,
            }, prefer="return=representation")
            if not isinstance(created, list) or not created:
                return 502, {"ok": False, "message": "couldn't create the output list"}
            out_list_id = created[0]["id"]

        # A pre-created backing list starts with no columns — set them from the
        # first batch so the grid has headers (fixed once, as above).
        if not columns:
            columns = list((src_rows[0].get("data") or {}).keys())
            sb("PATCH", f"lists?id=eq.{out_list_id}", {"columns": columns})

        max_row_num = 0
        cur_max = sb("GET", f"list_rows?list_id=eq.{out_list_id}"
                            "&select=row_num&order=row_num.desc&limit=1")
        if isinstance(cur_max, list) and cur_max:
            max_row_num = cur_max[0].get("row_num") or 0

        data_rows = [r.get("data") or {} for r in src_rows]
        inserted = _pull_append_rows(out_list_id, max_row_num + 1, columns, data_rows)

        sb("PATCH", f"lists?id=eq.{out_list_id}", {"row_count": max_row_num + inserted})

        # Optional campaign provenance: if the caller named a campaign for
        # this batch, stamp it on the ledger entry AND record a row in
        # list_pull_campaigns (the general list -> sending-platform provenance
        # table — any list can carry these, not just Saved Pulls). SAMPLE mode
        # records the linkage only — it never pushes to the platform; the real
        # prospeo flow will do the actual push later.
        campaign_name = str(p.get("campaign_name") or "").strip()
        campaign_id = str(p.get("campaign_id") or "").strip()
        platform = str(p.get("platform") or "smartlead").strip().lower()
        if platform not in ("smartlead", "heyreach"):
            platform = "smartlead"

        new_pulled = pulled_count + inserted
        new_offset = offset + inserted
        ledger = pull.get("credit_ledger")
        ledger = list(ledger) if isinstance(ledger, list) else []
        entry = {"batch": len(ledger) + 1, "rows": inserted, "credits": 0,
                 "at": now.isoformat(), "output_list_id": out_list_id}
        if campaign_name or campaign_id:
            entry["campaign_name"] = campaign_name or None
            entry["campaign_id"] = campaign_id or None
        ledger.append(entry)
        new_status = "exhausted" if new_pulled >= total_tam else "active"

        sb("PATCH", f"list_pulls?id=eq.{pull_id}", {
            "list_id": out_list_id,
            "cursor": {"offset": new_offset},
            "pulled_count": new_pulled,
            "version": (pull.get("version") or 0) + 1,
            "last_pulled_at": now.isoformat(),
            "last_pulled_by": "tool",
            "credit_ledger": ledger,
            "status": new_status,
        })

        if campaign_name or campaign_id:
            sb("POST", "list_pull_campaigns", {
                "pull_id": pull_id, "list_id": out_list_id,
                "campaign_id": campaign_id or None,
                "campaign_name": campaign_name or None,
                "platform": platform,
                "rows": inserted, "at": now.isoformat(),
            })

        return 200, {"ok": True, "taken": inserted, "pulled_count": new_pulled,
                     "total": total_tam, "remaining": max(0, total_tam - new_pulled),
                     "output_list_id": out_list_id, "batches": len(ledger),
                     "campaign_name": campaign_name or None}
    finally:
        sb("PATCH", f"list_pulls?id=eq.{pull_id}", {"locked_by": None, "locked_at": None})


# POST /api/lists/* dispatch — kept OUT of ROUTES because these handlers
# return (status, body) so validation/trigger failures answer with real 4xx
# codes (ROUTES handlers always answer 200). do_POST checks this map first.
LISTS_POST_ROUTES = {
    "/api/lists/folder": lists_create_folder,
    "/api/lists/folder/rename": lists_folder_rename,
    "/api/lists/folder/delete": lists_folder_delete,
    "/api/lists/folder/move": lists_folder_move,
    "/api/lists/move": lists_move,
    "/api/lists/touch": lists_touch,
    "/api/lists/rows/delete": lists_rows_delete,
    "/api/lists/delete": lists_delete,
    "/api/list_pulls/pull": list_pulls_pull,
}


def save_draft(p: dict) -> dict:
    if (p.get("type") or p.get("mechanism")) == "hiring" and not [t for t in (p.get("titles") or []) if str(t).strip()]:
        return {"ok": False, "message": "A hiring source needs decision-maker roles (who we email at these companies)."}
    if (p.get("type") or p.get("mechanism")) == "hiring":
        p["icebreaker"] = ensure_hiring_vars(p.get("icebreaker"))  # {{company}} + {{job_title}} always survive
    drafts = read_drafts(strict=True)
    # ids must NEVER be reused: Supabase rows (signals, signal_leads) are keyed
    # by source_id and outlive removed drafts — len()+1 recycled ids and
    # cross-contaminated old leads into new sources
    import uuid
    p["id"] = f"draft-{uuid.uuid4().hex[:8]}"
    drafts.append(p)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_source(p)  # an append only adds a row — never rewrite the siblings
    sb_sync_source(p)
    return {"ok": True, "id": p["id"]}


def update_source(p: dict) -> dict:
    """Edit a draft source: include/exclude, remove, icebreaker, targeting
    (params/titles), name, or prospect verdicts (local file only)."""
    drafts = read_drafts(strict=True)
    sid = p.get("id")
    push = None
    trigify_note = None
    edited = None  # the one source this call changed — persisted alone, see write_source()
    if p.get("remove"):
        gone = next((d for d in drafts if d.get("id") == sid), None)
        if gone and (gone.get("mechanism") or gone.get("type")) == "engagement":
            ent = ((gone.get("config") or {}).get("engagement") or {}).get("trigify") or []
            if ent:
                left, removed, errs = _trigify_deprovision(ent)
                if errs:  # keep the source so the user can retry the teardown
                    ((gone.get("config") or {}).get("engagement") or {})["trigify"] = left
                    write_source(gone)
                    return {"ok": False, "message":
                            f"Removed {len(removed)} Trigify workflow(s) but {len(errs)} failed "
                            f"({errs[0]['error']}). Source kept - try Remove again."}
                trigify_note = f"{len(removed)} Trigify workflow(s) stopped"
        sb_delete_source(sid)  # remove the source, its leads and events from Supabase too
        sb_delete_doc("sources", sid)  # explicit: the doc-table row goes even if it was the last source
        # sb_delete_doc already dropped the row — re-writing the surviving list here
        # would upsert every sibling from a snapshot that may now be stale.
    else:
        for d in drafts:
            if d.get("id") != sid:
                continue
            edited = d
            if "active" in p:
                d["active"] = bool(p["active"])
            if p.get("refresh_total") is not None:
                d["total"] = p["refresh_total"]
            if "icebreaker" in p and (d.get("mechanism") or d.get("type")) == "hiring":
                # a hiring opener must always keep {{company}} + {{job_title}};
                # if the edit dropped one, restore the canonical default rather than
                # ship a hardcoded role to every prospect
                p["icebreaker"] = ensure_hiring_vars(p["icebreaker"])
            for k in ("icebreaker", "name", "titles"):
                if k in p:
                    d[k] = p[k]
            if "icebreaker" in p:
                d["ice_edited"] = True  # user's words - never auto-replace
                for pr in (d.get("prospects") or []):
                    pr["icebreaker"] = fill_icebreaker(p["icebreaker"], pr)
            if "params" in p:
                d["params"] = {**(d.get("params") or {}), **p["params"]}
                d.pop("prospects", None)  # targeting changed -> stale pull
            if "config" in p:  # engagement wizard edit-mode saves the full block
                d["config"] = {**(d.get("config") or {}), **p["config"]}
                eng = (d["config"] or {}).get("engagement") or {}
                if eng.get("trigify"):  # URL dropped from the list -> stop its workflow too
                    left, removed, errs = _trigify_deprovision(
                        eng["trigify"], keep_urls=eng.get("linkedin_urls") or [])
                    eng["trigify"] = left
                    if removed or errs:
                        trigify_note = (f"{len(removed)} workflow(s) stopped for removed profiles"
                                        + (f", {len(errs)} teardown(s) failed - re-save to retry" if errs else ""))
            if "destination" in p:
                d["destination"] = p["destination"]
            pushed_to = None
            if "verdict" in p:
                prospects = d.get("prospects") if isinstance(d.get("prospects"), list) else []
                i = int(p.get("index") if p.get("index") is not None else -1)
                pr = prospects[i] if 0 <= i < len(prospects) else None
                if pr is None and p.get("linkedin"):  # Supabase-only lead (local last-pull rotated out)
                    pr = next((x for x in prospects if x.get("linkedin") == p["linkedin"]), None)
                if pr is None and p.get("linkedin"):
                    from urllib.parse import quote
                    row = (sb("GET", f"signal_leads?source_id=eq.{sid}&linkedin_url=eq.{quote(p['linkedin'], safe='')}") or [{}])
                    row = row[0] if isinstance(row, list) and row else {}
                    if not row.get("full_name"):
                        return {"ok": False, "message": "lead not found for this source - refresh the page"}
                    pr = {"name": row.get("full_name"), "title": row.get("title"),
                          "company": row.get("company"), "domain": row.get("domain"),
                          "linkedin": row.get("linkedin_url") or p["linkedin"],
                          "icebreaker": row.get("icebreaker"), "email": row.get("email") or None}
                if pr is not None:
                    dest = resolve_destination(d, ctx_campaign_id=p.get("ctx_campaign_id"))
                    if p["verdict"] == "undo":
                        push = unpush_prospect(pr, dest)  # removes from the live tool
                        if pr.get("linkedin"):
                            from urllib.parse import quote
                            sb("PATCH", f"signal_leads?source_id=eq.{sid}&linkedin_url=eq.{quote(pr['linkedin'], safe='')}",
                               {"status": "new", "pushed_to": None})
                            if (d.get("mechanism") or d.get("type")) == "engagement":
                                sb("PATCH", f"engagement_events?source_id=eq.{sid}"
                                            f"&engager_linkedin_url=eq.{quote(pr['linkedin'], safe='')}",
                                   {"status": "QUALIFIED"})
                        write_source(d)
                        return {"ok": True, "push": push, "undo": True,
                                "lead": {**pr, "verdict": None, "pushed_to": None, "pushed": pr.get("pushed") or {}}}
                    pr["verdict"] = p["verdict"]
                    status = "rejected" if p["verdict"] == "reject" else "qualified"
                    if p["verdict"] == "keep" and dest:
                        push = push_prospect(pr, dest, client_id=d.get("client_id"))  # real API push, idempotent + suppression-checked
                        sent = [k for k, v in push["tools"].items() if v.get("ok")]
                        if sent:
                            status = "pushed"
                            pushed_to = "+".join(
                                f"smartlead:{dest.get('smartlead_campaign_id')}" if k == "smartlead"
                                else f"heyreach:{dest.get('heyreach_list_id') or dest.get('heyreach_list_name')}"
                                for k in sent)
                            pr["pushed_to"] = pushed_to
                    if pr.get("linkedin"):
                        from urllib.parse import quote
                        sb("PATCH", f"signal_leads?source_id=eq.{sid}&linkedin_url=eq.{quote(pr['linkedin'], safe='')}",
                           {"status": status, "pushed_to": pushed_to, "email": pr.get("email")})
                        if (d.get("mechanism") or d.get("type")) == "engagement" and status == "pushed":
                            sb("PATCH", f"engagement_events?source_id=eq.{sid}"
                                        f"&engager_linkedin_url=eq.{quote(pr['linkedin'], safe='')}",
                               {"status": "PUSHED"})
                    write_source(d)
                    return {"ok": True, "push": push, "lead": pr}
            if any(k in p for k in ("icebreaker", "params", "titles", "name", "active", "destination", "config")):
                sb_sync_source(d)
    if edited is not None:
        write_source(edited)
    return {"ok": True, "push": push, **({"trigify": trigify_note} if trigify_note else {})}


# ── real outreach push (Smartlead + HeyReach) ────────────────────────────

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
HEYREACH_BASE = "https://api.heyreach.io/api/public"


def heyreach(path: str, body: dict):
    return http_json("POST", HEYREACH_BASE + path,
                     {"X-API-KEY": KEYS.get("HEYREACH_API_KEY", "")}, body)


# ── background jobs: mailbox-list verify + remove-bad ───────────────────
# In-memory only (no Supabase table) - jobs are a per-process progress feed
# for a UI poll loop, not a durable record. A restart drops them; the ledger
# row written at the end of each worker is the durable trace. Capped at 200
# so a long-running server doesn't leak memory across many runs.
from collections import OrderedDict as _OrderedDict
JOBS: "_OrderedDict[str, dict]" = _OrderedDict()
JOBS_LOCK = threading.Lock()
VERIFY_RESULTS: dict = {}  # campaign_id (str) -> lead-level verify detail, this-session only
_LEAD_COUNT_CACHE: dict = {}  # campaign_id (str) -> (total_leads, fetched_at); 1h TTL (see handler)
_TAG_NAMES_SWR: dict = {"names": None, "ts": 0.0}  # Smartlead tag names; 1h TTL, stale-on-error


def _warm_tag_names():
    """Prime _TAG_NAMES_SWR (boot warmup) — same fetch as the handler."""
    if _TAG_NAMES_SWR["names"] is not None and (time.time() - _TAG_NAMES_SWR["ts"]) < 3600:
        return
    tags = _smartlead_json("GET", "/email-accounts/tags") or []
    _TAG_NAMES_SWR.update(names=sorted({(t.get("name") or "").strip() for t in tags
                                        if isinstance(t, dict)} - {""}, key=str.lower),
                          ts=time.time())
_JOBS_CAP = 200


_JOB_DB_FIELDS = ("id", "kind", "label", "campaign_id", "mode", "status",
                  "progress", "counts", "error", "dry_run", "started_at",
                  "finished_at", "auto_remove", "resume_count", "owner",
                  "max_new")  # max_new is durable so an auto-resumed
                              # continuation inherits the spend cap
# NOTE: app_jobs has no `mock` column (confirmed live: PGRST204 "column
# app_jobs.mock does not exist") - the in-memory job dict keeps a `mock` key
# for runtime branching, but it is deliberately excluded from _JOB_DB_FIELDS.
# Including it here would make every _job_persist POST 400 (unknown column),
# silently killing durability for every job, not just mock ones. Mock-ness on
# a resumed/recovered job is instead inferred from the label ("[TEST] "
# prefix) / campaign_id ("MOCK" prefix) convention used by api_verify_campaign
# and the verification steps below - see _is_mock_job_row().


def _job_persist(job: dict):
    """Mirror a job to Supabase so it survives a process restart. Fire-and-forget:
    the ledger must never add latency to, or fail, the job it records. The
    in-memory JOBS dict stays the fast path; app_jobs is the durability net that
    /api/jobs and the poll fall back to when memory is gone (post-restart)."""
    from datetime import datetime, timezone
    row = {k: job.get(k) for k in _JOB_DB_FIELDS}
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    threading.Thread(
        target=lambda: sb("POST", "app_jobs?on_conflict=id", row,
                          prefer="resolution=merge-duplicates,return=minimal"),
        daemon=True).start()


def _new_job(kind: str, label: str, campaign_id, mode: str = "", dry_run: bool = False,
             auto_remove: bool = False, resume_count: int = 0, mock: bool = False,
             max_new: int | None = None) -> dict:
    import uuid
    job = {"id": uuid.uuid4().hex[:10], "kind": kind, "label": label,
           "campaign_id": campaign_id, "mode": mode, "status": "queued",
           "progress": {"done": 0, "total": 0}, "started_at": None,
           "finished_at": None, "counts": {}, "error": None, "dry_run": dry_run,
           "cancel_requested": False, "auto_remove": auto_remove,
           "resume_count": resume_count, "mock": mock, "max_new": max_new,
           "owner": _SERVER_INSTANCE}  # which server instance owns this job (see recovery)
    with JOBS_LOCK:
        JOBS[job["id"]] = job
        if len(JOBS) > _JOBS_CAP:
            # evict oldest FINISHED jobs first; never drop something in flight
            for jid, j in list(JOBS.items()):
                if len(JOBS) <= _JOBS_CAP:
                    break
                if j["status"] in ("done", "failed", "cancelled", "interrupted"):
                    del JOBS[jid]
    _job_persist(job)
    return job


def _job_started(job: dict):
    from datetime import datetime, timezone
    with JOBS_LOCK:
        job["status"] = "running"
        job["started_at"] = datetime.now(timezone.utc).isoformat()
    _job_persist(job)


def _job_finished(job: dict, status: str, error: str | None = None):
    from datetime import datetime, timezone
    with JOBS_LOCK:
        job["status"] = status
        job["error"] = error
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
    _job_persist(job)


def _job_get(jid: str) -> dict | None:
    """A job by id: memory first (live progress), else the durable app_jobs row
    (survives restarts). Absent everywhere -> None."""
    with JOBS_LOCK:
        job = JOBS.get(jid)
    if job:
        return job
    rows = sb("GET", f"app_jobs?id=eq.{jid}&limit=1")
    return rows[0] if rows else None


# (the old _MAX_AUTO_RESUMES_PER_BOOT cap died with auto-resume itself — see
# _jobs_recover_orphans: recovery now only MARKS orphans, never re-enqueues.)
_JOB_CREATE_LOCK = threading.Lock()  # spans has-active-job check + job creation
                                     # so two rapid clicks can't both pass the
                                     # check before either job registers (TOCTOU)


def _is_mock_job_row(r: dict) -> bool:
    """app_jobs has no `mock` column, so a job's mock-ness has to be inferred
    when reconstructing it from a durable row (recovery/resume). Convention:
    api_verify_campaign prefixes a mock job's label "[TEST] " and the caller
    is expected to use an obviously-fake campaign_id (the manual test steps
    use "MOCKTEST..."); either signal is enough."""
    label = (r.get("label") or "")
    cid = str(r.get("campaign_id") or "").upper()
    return label.startswith("[TEST]") or cid.startswith("MOCK")


_ON_RENDER = bool(os.environ.get("RENDER"))
# STABLE per-service id (NOT RENDER_INSTANCE_ID, which changes every deploy —
# a new instance must be able to reclaim the previous incarnation's orphans, so
# all incarnations of the service share one owner). Local dev gets "local".
_SERVER_INSTANCE = os.environ.get("RENDER_SERVICE_ID") or ("render" if _ON_RENDER else "local")


def _jobs_recover_orphans():
    """On boot, mark this instance's orphaned in-flight jobs 'interrupted'.

    A job left 'running'/'queued' when a process dies has no live worker, so the
    UI must be told to stop showing it as active.

    Auto-resume history: removed 2026-07 because it stormed — every server
    incarnation (including overlapping deploy instances and any dev box sharing
    this Supabase) would re-enqueue the SAME jobs, producing duplicate
    concurrent ListMint runs and wasted credits. Restored 2026-07-12 in
    _sweep_orphan_jobs with guards that close each storm vector: production
    instance only (_ON_RENDER + exact owner match, so dev boxes never
    re-enqueue), a compare-and-set on app_jobs.auto_resumed (so overlapping
    incarnations can't both re-enqueue the same row — Postgres arbitrates),
    the _campaign_has_active_job check under _JOB_CREATE_LOCK (same TOCTOU
    guard as the manual Resume button), and it only ever fires for rows the
    sweep itself just transitioned running/queued → interrupted — historical
    'interrupted' rows stay manual-resume-only. Credit safety is the 60-day
    verdict cache: a continuation only pays for not-yet-checked emails.

    Ownership guard: only touch rows this instance owns (`owner` = _SERVER_INSTANCE),
    so a local/dev server can never mark or disturb production's live jobs, and
    vice-versa. Rows with no owner (legacy) are only reclaimed by the render
    instance, never by a local box."""
    _sweep_orphan_jobs(grace_s=180)


_JOB_STALE_S = 600  # a live worker heartbeats app_jobs every chunk (~35s); 10min silent = dead


def _sweep_orphan_jobs(grace_s: int):
    """Mark this service's dead in-flight app_jobs rows 'interrupted'.

    Two protections against marking a job whose worker is actually ALIVE:
    - `grace_s`: only touch rows whose updated_at is older than the grace window.
      During a rolling deploy the OLD instance shares our owner string and its
      workers heartbeat updated_at every chunk — a fresh row is likely theirs,
      still alive. (Reviewer finding: without this, boot recovery could mark a
      live job interrupted and let Resume start a duplicate concurrent worker.)
    - in-memory check: never touch a job id THIS process is actively running.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=grace_s)).isoformat()
    try:
        from urllib.parse import quote
        stuck = sb("GET", "app_jobs?status=in.(running,queued)"
                          f"&updated_at=lt.{quote(cutoff, safe='')}"
                          "&select=id,owner,kind,campaign_id,mode,label,auto_remove,"
                          "resume_count,auto_resumed,max_new")
    except Exception:  # noqa: BLE001 — best-effort; never block boot or the sweeper
        return
    with JOBS_LOCK:
        live_here = {jid for jid, j in JOBS.items() if j.get("status") in ("queued", "running")}
    for r in (stuck or []):
        owner = r.get("owner")
        mine = (owner == _SERVER_INSTANCE) or (owner is None and _ON_RENDER)
        if not mine or r["id"] in live_here:
            continue  # another instance's job, or genuinely running right here
        try:
            sb("PATCH", f"app_jobs?id=eq.{r['id']}",
               {"status": "interrupted",
                "error": "Interrupted by a server restart — click Resume to continue "
                         "(already-checked emails are cached, so it picks up where it left off).",
                "finished_at": _now_iso()})
        except Exception:  # noqa: BLE001 — one bad row must not stop the rest
            continue
        _maybe_auto_resume(r)


def _maybe_auto_resume(r: dict):
    """Auto-resume a verify job the sweep just marked 'interrupted' — guarded
    so the 2026-07 duplicate-run storm cannot recur (see _jobs_recover_orphans
    docstring for the full guard rationale). At most one automatic continuation
    per app_jobs row, enforced by a compare-and-set on auto_resumed so parallel
    incarnations can't both win. Anything skipped here stays 'interrupted' with
    the manual Resume button as the fallback."""
    if not (_ON_RENDER and r.get("owner") == _SERVER_INSTANCE):
        return  # production instance only — dev boxes never re-enqueue
    if r.get("kind") != "verify" or r.get("auto_resumed"):
        return
    try:
        with _JOB_CREATE_LOCK:
            if _campaign_has_active_job(r.get("campaign_id")):
                return  # something is already working this campaign
            claimed = sb("PATCH",
                         f"app_jobs?id=eq.{r['id']}&auto_resumed=eq.false",
                         {"auto_resumed": True}, prefer="return=representation")
            if not claimed:  # another incarnation claimed it first
                return
            new_job = _reenqueue_verify(r, (r.get("resume_count") or 0) + 1)
        print(f"[auto-resume] job {r['id']} (campaign {r.get('campaign_id')}) "
              f"-> continuation {new_job['id']}")
    except Exception as e:  # noqa: BLE001 — a failed resume must not kill the sweep
        print(f"[auto-resume] failed for job {r.get('id')}: {e}")


def _job_zombie_sweeper():
    """Boot recovery only runs once, so a job created on a DYING deploy-overlap
    instance AFTER the new instance booted becomes a permanent fake-'running'
    row (observed live 2026-07-10: job started on the old instance at 06:00,
    old instance killed 06:07, row stuck 'running' forever). Sweep every 5min
    for own-owner rows silent past _JOB_STALE_S that aren't running here."""
    while True:
        time.sleep(300)
        try:
            _sweep_orphan_jobs(grace_s=_JOB_STALE_S)
        except Exception:  # noqa: BLE001 — the sweeper must never die
            pass


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _reenqueue_verify(r: dict, new_resume_count: int):
    """Reconstruct a fresh verify continuation from a durable app_jobs row and
    enqueue it. Shared by boot auto-recovery and the manual Resume button. The
    60-day verdict cache means the continuation skips every already-checked
    email, so it resumes cheaply from where the old run died. Returns new_job."""
    campaign_id = r["campaign_id"]
    mode = r.get("mode") or "mv"
    mock = _is_mock_job_row(r)
    sl_key = KEYS.get("SMARTLEAD_API_KEY") or os.environ.get("SMARTLEAD_API_KEY") or ""
    mv_key = KEYS.get("MILLIONVERIFIER_API_KEY") or os.environ.get("MILLIONVERIFIER_API_KEY")
    lm_key = KEYS.get("LISTMINT_API_KEY") or os.environ.get("LISTMINT_API_KEY")
    label = r.get("label") or f"Verify campaign {campaign_id}"
    new_job = _new_job("verify", label, campaign_id, mode, dry_run=False,
                       auto_remove=bool(r.get("auto_remove")),
                       resume_count=new_resume_count, mock=mock,
                       max_new=r.get("max_new"))
    _enqueue_job(_verify_job_worker, new_job,
                 (new_job, campaign_id, mode, mv_key, lm_key, sl_key))
    return new_job


def _campaign_has_active_job(campaign_id) -> bool:
    """True if a queued/running job already exists for this campaign — memory
    first, then the durable table. Stops a manual Resume (or a duplicate click)
    from spawning a second concurrent run of the same campaign."""
    cid = str(campaign_id)
    with JOBS_LOCK:
        if any(str(j.get("campaign_id")) == cid and j.get("status") in ("queued", "running")
               for j in JOBS.values()):
            return True
    rows = sb("GET", f"app_jobs?campaign_id=eq.{cid}&status=in.(queued,running)&select=id&limit=1")
    return bool(rows)


def resume_job(jid: str):
    """Manual Resume (the sidebar button). Re-runs an interrupted verify job as
    a fresh continuation. Returns (body, status)."""
    job = _job_get(jid)
    if not job:
        return {"error": "not_found"}, 404
    if job.get("kind") not in ("verify", "remove_bad") or job.get("dry_run"):
        return {"error": "not_resumable",
                "message": "Only an interrupted verification or removal can be resumed."}, 409
    if job.get("status") not in ("interrupted", "failed"):
        return {"error": "not_interrupted",
                "message": "This task isn't interrupted — nothing to resume."}, 409
    campaign_id = job.get("campaign_id")
    sl_key = KEYS.get("SMARTLEAD_API_KEY") or os.environ.get("SMARTLEAD_API_KEY") or ""
    # _JOB_CREATE_LOCK spans the has-active check AND job creation: two rapid
    # Resume clicks would otherwise both pass the check before either job
    # registers (TOCTOU) and race duplicate workers on the same campaign.
    with _JOB_CREATE_LOCK:
        if _campaign_has_active_job(campaign_id):
            return {"error": "already_active",
                    "message": "This campaign already has a task running — no need to resume."}, 409
        if job.get("kind") == "remove_bad":
            # A remove resumes by re-reading the still-pending bad leads from the
            # durable table — fast, no re-fetch.
            new_job = _new_job("remove_bad", job.get("label") or f"Remove bad leads: campaign {campaign_id}",
                               campaign_id, dry_run=False)
            _enqueue_job(_remove_job_worker, new_job, (new_job, campaign_id, sl_key, False))
        else:
            # Manual resume gets a fresh budget; the empty-targets path guarantees it
            # still can't loop forever on a campaign with nothing left to check.
            new_job = _reenqueue_verify(job, 0)
    try:
        log_activity("/api/jobs/resume",
                     payload={"campaign_id": campaign_id, "old_job_id": jid,
                              "new_job_id": new_job["id"], "kind": job.get("kind")},
                     actor="deliverability", action="verify_resume_manual",
                     entity="campaign", entity_id=campaign_id)
    except Exception:  # noqa: BLE001
        pass
    return {"job_id": new_job["id"]}, 202


_FINISHED_STATUSES = ("done", "failed", "cancelled", "interrupted")


def dismiss_job(jid: str):
    """Remove ONE finished task from the panel — deletes its app_jobs row and
    drops it from memory. Refuses to dismiss a live (queued/running) job so an
    in-flight verification can't be hidden out from under itself."""
    job = _job_get(jid)
    if not job:
        return {"ok": True, "already_gone": True}, 200  # idempotent — nothing to remove
    if job.get("status") not in _FINISHED_STATUSES:
        return {"error": "job_active",
                "message": "This task is still running — cancel it first if you want it gone."}, 409
    with JOBS_LOCK:
        JOBS.pop(jid, None)
    sb("DELETE", f"app_jobs?id=eq.{jid}")
    return {"ok": True}, 200


def dismiss_finished_jobs():
    """Clear ALL finished tasks at once (the panel's 'Clear finished' action).
    Live jobs are left untouched. Scoped to this instance's own rows + legacy
    no-owner rows on Render, so a dev box can't wipe production's history."""
    with JOBS_LOCK:
        gone = [jid for jid, j in list(JOBS.items()) if j.get("status") in _FINISHED_STATUSES]
        for jid in gone:
            JOBS.pop(jid, None)
    owner_clause = (f"&or=(owner.eq.{_SERVER_INSTANCE},owner.is.null)" if _ON_RENDER
                    else f"&owner=eq.{_SERVER_INSTANCE}")
    sb("DELETE", f"app_jobs?status=in.({','.join(_FINISHED_STATUSES)}){owner_clause}")
    return {"ok": True, "cleared_memory": len(gone)}


# ── Verify/remove job queue ─────────────────────────────────────────────────
# ListMint (and the Smartlead delete endpoint) rate-limit hard. Firing several
# verify jobs at once multiplies the request rate past what any single job's
# 429-backoff can absorb, so the jobs error out. A single-worker FIFO queue
# serialises them: every extra job you add sits in `queued` (the sidebar shows
# it) and starts only when the one ahead finishes. Bump _JOB_WORKERS if a future
# provider tolerates parallelism — 1 is the safe default for ListMint.
import queue as _queue
_JOB_QUEUE: "_queue.Queue" = _queue.Queue()
_JOB_WORKERS = 1
_JOB_SEQ = [0]  # monotonic enqueue counter — lets the UI order/number the queue


def _enqueue_job(fn, job, args):
    """Queue a job's worker instead of spawning it immediately. The job is
    already `queued` in JOBS/app_jobs; the dispatcher flips it to running when
    a worker slot frees."""
    with JOBS_LOCK:
        _JOB_SEQ[0] += 1
        job["queue_seq"] = _JOB_SEQ[0]
    _JOB_QUEUE.put((fn, job, args))


def _job_dispatcher():
    while True:
        fn, job, args = _JOB_QUEUE.get()
        try:
            # Cancelled while it sat in the queue? Honour it without doing any
            # provider work — the cancel route set the flag on the queued job.
            with JOBS_LOCK:
                cancelled = job.get("cancel_requested")
            if cancelled:
                _job_finished(job, "cancelled")
                continue
            fn(*args)
        except Exception as e:  # noqa: BLE001 — a worker crash must not kill the dispatcher
            try:
                _job_finished(job, "failed", str(e)[:300])
            except Exception:  # noqa: BLE001
                pass
        finally:
            _JOB_QUEUE.task_done()


def _mv_verify_one(email: str, mv_key: str) -> str:
    """One MillionVerifier lookup -> ok|catch_all|unknown|disposable|invalid.
    One retry on timeout/error (per spec); a second failure counts as unknown
    rather than aborting the whole batch over one flaky call."""
    import urllib.parse
    url = ("https://api.millionverifier.com/api/v3/?api=" + mv_key +
           "&email=" + urllib.parse.quote(email))
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode())
            result = data.get("result") or "unknown"
            if result == "error":
                # API-level refusal (e.g. "Insufficient credits") — carry the
                # real message so the worker can fail the whole job loudly
                # instead of silently classifying everything as unknown.
                return "error:" + (data.get("error") or "unspecified API error")
            return result
        except Exception:  # noqa: BLE001 — timeout/network/bad-json: retry once, then unknown
            if attempt == 2:
                return "unknown"
    return "unknown"  # unreachable, keeps linters happy


def _mv_credits(mv_key: str) -> int | None:
    """Current MillionVerifier balance, or None if the lookup itself fails
    (a balance-check outage must not block verification)."""
    try:
        req = urllib.request.Request(
            "https://api.millionverifier.com/api/v3/credits?api=" + mv_key,
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            return int(json.loads(resp.read().decode()).get("credits"))
    except Exception:  # noqa: BLE001
        return None


def _listmint_verify_batch(emails: list, lm_key: str) -> dict:
    """ListMint verify-emails on one chunk -> {email: result}. Results are
    valid | catch_all_valid | invalid | catch_all_invalid (spec: the Listmint
    Clay API docs, proven live 2026-07-09). Auth is the api-key QUERY param —
    the header form is rejected. SMTP + catch-all verification is slow
    (~3s/email observed), so callers chunk small and give a long timeout."""
    import urllib.error
    import urllib.parse
    url = ("https://api.listmint.io/api/verify-emails?return=true&api-key="
           + urllib.parse.quote(lm_key))
    last_err = "no attempts made"
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(url, data=json.dumps({"emails": emails}).encode(),
                                         headers={"User-Agent": UA,
                                                  "Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=240, context=SSL_CTX) as resp:
                r = json.loads(resp.read().decode())
            return {x.get("email"): x.get("result") for x in (r or {}).get("results", [])}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Rate-limited: a campaign-sized run WILL hit this. Honour
                # Retry-After when sent, else back off progressively — waiting
                # is correct, failing the whole job is not.
                try:
                    wait = int((e.headers or {}).get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                last_err = "HTTP 429: Too Many Requests"
                time.sleep(min(max(wait, 10 * attempt), 120))
                continue
            last_err = f"HTTP {e.code}: {str(e.reason)[:150]}"
            if attempt >= 2:
                break
        except Exception as e:  # noqa: BLE001 — one retry on network flake, then surface
            last_err = str(e)[:200]
            if attempt >= 2:
                break
    return {"_error": last_err}


def _fetch_all_smartlead_leads(campaign_id, sl_key: str) -> list:
    """Pages /campaigns/{id}/leads to exhaustion. Returns [{lead_id, email,
    replied, status, is_unsubscribed, contacted}] - replied = lead_category_id
    is not None, i.e. Smartlead has already categorised an inbound event
    (reply, OOO, bounce-notice...) for this lead. That's a deliberately
    conservative definition: anything that LOOKS like the lead engaged guards
    them from the remove step.
    contacted = the lead has already been emailed (or otherwise resolved) by
    Smartlead — status other than STARTED (STARTED = queued, not yet sent),
    OR is_unsubscribed, OR lead_category_id is not None. Verify/remove only
    ever operate on the NOT-contacted subset — no point spending a
    verification credit, or risking a delete, on someone Smartlead already
    emailed."""
    leads = []
    offset = 0
    while True:
        url = (f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/leads"
               f"?api_key={sl_key}&offset={offset}&limit=100")
        page = _smartlead_get_retry(url)
        rows = (page or {}).get("data") or []
        if not rows:
            break
        for row in rows:
            lead = row.get("lead") or {}
            email = (lead.get("email") or "").strip()
            if not email:
                continue
            status = (row.get("status") or "").strip().upper()
            is_unsub = bool(row.get("is_unsubscribed"))
            replied = row.get("lead_category_id") is not None
            contacted = (status not in ("STARTED", "")) or is_unsub or replied
            leads.append({"lead_id": lead.get("id"), "email": email,
                          "replied": replied, "status": status,
                          "is_unsubscribed": is_unsub, "contacted": contacted})
        if len(rows) < 100:
            break
        offset += 100
        time.sleep(0.25)  # pace pagination — a 12k-lead campaign is ~125 pages;
                          # firing them back-to-back trips Smartlead's rate limit
    return leads


def _smartlead_get_retry(url: str, attempts: int = 5) -> dict:
    """Smartlead GET with 429/5xx backoff. A big campaign pages ~125 times, and
    Smartlead rate-limits — without this the raw 'HTTP Error 429' propagates and
    kills the whole verify job on the very first fetch. Honours Retry-After."""
    import urllib.error
    last = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts:
                try:
                    wait = int((e.headers or {}).get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                time.sleep(min(max(wait, 3 * attempt), 30))
                continue
            # Non-retriable (or retries exhausted): RAISE, never return the error
            # body as if it were a page. Returning it made a bad API key or a
            # deleted campaign look like "no leads" — the verify job then reported
            # a clean 'done' instead of failing (reviewer finding). Keep the
            # body's message in the exception so the job error is actionable.
            try:
                detail = json.loads(e.read().decode()).get("message")
            except Exception:  # noqa: BLE001
                detail = None
            raise RuntimeError(f"Smartlead HTTP {e.code}"
                               + (f": {str(detail)[:150]}" if detail else f": {e.reason}")) from e
        except Exception as e:  # noqa: BLE001 — transient network: one more try
            last = e
            if attempt < attempts:
                time.sleep(3 * attempt)
                continue
            raise
    if last:
        raise last
    return {}


_LM_MAP = {"valid": "good", "catch_all_valid": "catch_all",
           "invalid": "bad", "catch_all_invalid": "bad"}
_LM_CHUNK = 10  # ListMint does live SMTP + catch-all checks (~3s/email) — small
                # chunks keep per-request time bounded and progress moving.


def _meter_verify_calls(provider: str, campaign_id, n: int):
    """Best-effort provider-call ledger: one provider_usage row per batch of
    real verification lookups, so spend is auditable by SQL (same table the
    TheirStack meter uses). Never allowed to fail a verify run."""
    if not n:
        return
    try:
        sb("POST", "provider_usage",
           {"provider": provider, "source_id": str(campaign_id or ""),
            "credits": n, "endpoint": "verify", "called_at": _now_iso()})
    except Exception:  # noqa: BLE001
        pass


def _listmint_pass(job: dict, rows: list, lm_key: str, api_errors: dict, campaign_id=None):
    """Run ListMint over `rows` (subset of the details list), writing
    lm_result + overriding verdict in place. Chunked + sequential. When
    `campaign_id` is given, each chunk's verdicts are persisted to
    email_verifications immediately — a mid-run crash or restart only loses
    the in-flight chunk, not the whole pass."""
    for i in range(0, len(rows), _LM_CHUNK):
        with JOBS_LOCK:
            if job.get("cancel_requested"):
                return True  # signal caller: stopped early, don't mark done
        if i:
            time.sleep(1.0)  # pace chunks — cheaper than eating 429 backoffs
        chunk = rows[i:i + _LM_CHUNK]
        res = _listmint_verify_batch([r["email"] for r in chunk], lm_key)
        err = res.get("_error")
        for r in chunk:
            lm = res.get(r["email"])
            r["lm_result"] = lm or ("error" if err else None)
            if lm in _LM_MAP:
                r["verdict"] = _LM_MAP[lm]
            elif err:
                api_errors[err] = api_errors.get(err, 0) + 1
            with JOBS_LOCK:
                job["progress"]["done"] += 1
        if campaign_id is not None:
            _persist_verdicts([r for r in chunk if r.get("lm_result")], campaign_id, "listmint")
        _meter_verify_calls("listmint", campaign_id,
                            sum(1 for r in chunk if res.get(r["email"])))
        _job_persist(job)  # durable progress so a restart's app_jobs row isn't frozen at 0
    return False  # ran to completion, not cancelled


_VERIFY_TTL_DAYS = 60  # cache window for both tiers below


def _people_lookup(emails: list) -> dict:
    """Which of these emails already have a row in the central `people` table
    (public.people, email UNIQUE/citext — case-insensitive by the column
    type, but we lower() our own keys too so the two tiers agree on identity).
    Chunked at 80/request. Returns {lower_email: True}."""
    from urllib.parse import quote
    out = {}
    uniq = sorted(set(e.lower() for e in emails if e))
    for i in range(0, len(uniq), 80):
        chunk = uniq[i:i + 80]
        enc = ",".join(quote(e, safe="") for e in chunk)
        rows = sb("GET", f"people?email=in.({enc})&select=email")
        if isinstance(rows, list):
            for r in rows:
                if r.get("email"):
                    out[r["email"].lower()] = True
    return out


def _cached_verdicts(emails: list) -> dict:
    """Look up prior verdicts, two tiers, so a re-verify skips emails already
    checked — MV/ListMint credits are not free.
    Tier 1: `people` (public.people) is the primary identity store — its
    email_verification/email_verified_at columns win when present.
    Tier 2: `email_verifications` is overflow, checked only for emails that
    tier 1 didn't resolve (no people row, or no verdict on it yet).
    Both tiers use a 60-day window. Chunked at 80 emails/request. Returns
    {lower_email: {result, verdict, source}}; best-effort (an outage just
    means nothing is cached, not a broken run)."""
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote
    out = {}
    if not emails:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_VERIFY_TTL_DAYS)).isoformat()
    uniq = sorted(set(e.lower() for e in emails if e))
    remaining = set(uniq)

    # tier 1: people
    for i in range(0, len(uniq), 80):
        chunk = uniq[i:i + 80]
        enc = ",".join(quote(e, safe="") for e in chunk)
        rows = sb("GET", f"people?email=in.({enc})&email_verification=not.is.null"
                          f"&email_verified_at=gt.{quote(cutoff, safe='')}"
                          f"&select=email,email_verification,email_verified_at")
        if isinstance(rows, list):
            for r in rows:
                e = (r.get("email") or "").lower()
                if e and r.get("email_verification"):
                    out[e] = {"result": None, "verdict": r["email_verification"], "source": "people"}
                    remaining.discard(e)

    # tier 2: email_verifications overflow — only for what tier 1 missed
    rem = sorted(remaining)
    for i in range(0, len(rem), 80):
        chunk = rem[i:i + 80]
        enc = ",".join(quote(e, safe="") for e in chunk)
        rows = sb("GET", f"email_verifications?email=in.({enc})"
                          f"&verified_at=gt.{quote(cutoff, safe='')}"
                          f"&select=email,result,verdict,source")
        if isinstance(rows, list):
            for r in rows:
                e = (r.get("email") or "").lower()
                if e:
                    out[e] = r
    return out


def _persist_verdicts(rows: list, campaign_id, source: str):
    """Write fresh verdicts, two tiers.
    Tier 1: emails that already have a `people` row get PATCHed there
    (email_verification, email_verified_at) — batched per verdict per chunk
    to keep request count low. The verify pipeline NEVER inserts new people
    rows; identity rows aren't ours to fabricate.
    Tier 2: emails with no people row are upserted into email_verifications
    as overflow — one row per email, latest wins. Only columns that exist on
    the table are ever sent (house rule: never send a status-like field
    that isn't in the row on a merge-duplicates upsert — it silently
    clobbers unrelated columns)."""
    from datetime import datetime, timezone
    from urllib.parse import quote
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()
    have_people = _people_lookup([r["email"] for r in rows])
    to_people = [r for r in rows if r["email"].lower() in have_people]
    to_overflow = [r for r in rows if r["email"].lower() not in have_people]

    by_verdict: dict = {}
    for r in to_people:
        by_verdict.setdefault(r["verdict"], []).append(r["email"].lower())
    for verdict, es in by_verdict.items():
        for i in range(0, len(es), 80):
            chunk = es[i:i + 80]
            enc = ",".join(quote(e, safe="") for e in chunk)
            sb("PATCH", f"people?email=in.({enc})",
               {"email_verification": verdict, "email_verified_at": now})

    if to_overflow:
        payload = [{"email": r["email"],
                   "result": (r.get("mv_result") if source == "mv" else r.get("lm_result")),
                   "verdict": r["verdict"], "source": source,
                   "campaign_id": str(campaign_id), "lead_id": r.get("lead_id"),
                   "verified_at": now} for r in to_overflow]
        sb("POST", "email_verifications?on_conflict=email", payload,
           prefer="resolution=merge-duplicates,return=minimal")


def _verify_state_upsert(campaign_id, **fields):
    """Upsert verify_campaign_state (pk campaign_id). Only columns present in
    `fields` are written — everything else keeps its prior value (or NULL on
    first insert). Best-effort; a Supabase outage must not break verify/remove."""
    from datetime import datetime, timezone
    row = {"campaign_id": str(campaign_id),
           "updated_at": datetime.now(timezone.utc).isoformat()}
    row.update({k: v for k, v in fields.items() if v is not None})
    # Any state change here (verify finished, bad leads removed, dismissed)
    # changes what "N to verify" should show — drop the hour-long cached count
    # so the next repaint recomputes instead of serving a stale number.
    _LEAD_COUNT_CACHE.pop(str(campaign_id), None)
    sb("POST", "verify_campaign_state?on_conflict=campaign_id", row,
       prefer="resolution=merge-duplicates,return=minimal")


def _store_bad_leads(campaign_id, bad_details: list):
    """Persist a verify's confirmed-bad leads (id + email) so removal is a direct
    delete instead of re-paginating the whole campaign. Replaces this campaign's
    prior set — a fresh verify supersedes the last. Best-effort."""
    cid = str(campaign_id)
    sb("DELETE", f"verify_bad_leads?campaign_id=eq.{cid}")
    rows = [{"campaign_id": cid, "lead_id": str(d["lead_id"]), "email": d.get("email"),
             "replied": bool(d.get("replied")), "removed": False}
            for d in bad_details if d.get("lead_id") is not None]
    for i in range(0, len(rows), 500):  # chunk to keep each POST light
        sb("POST", "verify_bad_leads?on_conflict=campaign_id,lead_id", rows[i:i + 500],
           prefer="resolution=merge-duplicates,return=minimal")


def _pending_bad_leads(campaign_id) -> list:
    """The campaign's still-in-the-queue bad leads (removed=false, not replied)."""
    cid = str(campaign_id)
    rows = sb_get_all(f"verify_bad_leads?campaign_id=eq.{cid}&removed=eq.false"
                      f"&replied=eq.false&select=lead_id,email,replied,found_at")
    return [{"lead_id": r["lead_id"], "email": r.get("email"), "replied": False,
             "found_at": r.get("found_at")}
            for r in (rows or [])]


_REPLY_RECHECK_AFTER_S = 1800  # stored replied-flags older than 30min get re-checked


def _refresh_reply_guard(campaign_id, candidates: list, sl_key: str) -> list:
    """The stored replied-flag is a snapshot from verify time; someone can reply
    AFTER that and must never be deleted (reviewer finding). When the snapshot is
    older than 30min, re-fetch the campaign's live lead statuses and drop (and
    durably re-mark) any candidate who has replied since. Fresh snapshots — e.g.
    an auto-remove running seconds after its own verify — skip the refetch."""
    from datetime import datetime, timezone
    if not candidates:
        return candidates
    def age_s(iso):
        try:
            s = str(iso).replace(" ", "T")
            dt = datetime.fromisoformat(s if "+" in s or s.endswith("Z") else s + "+00:00")
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:  # noqa: BLE001 — unparseable timestamp = treat as stale
            return _REPLY_RECHECK_AFTER_S + 1
    if all(age_s(c.get("found_at")) < _REPLY_RECHECK_AFTER_S for c in candidates):
        return candidates
    leads = _fetch_all_smartlead_leads(campaign_id, sl_key)
    replied_now = {str(l["lead_id"]) for l in leads if l.get("replied")}
    kept = []
    for c in candidates:
        if str(c["lead_id"]) in replied_now:
            sb("PATCH", f"verify_bad_leads?campaign_id=eq.{str(campaign_id)}"
                        f"&lead_id=eq.{c['lead_id']}", {"replied": True})
        else:
            kept.append(c)
    return kept


def _mark_bad_removed(campaign_id, lead_id):
    sb("PATCH", f"verify_bad_leads?campaign_id=eq.{str(campaign_id)}&lead_id=eq.{lead_id}",
       {"removed": True, "removed_at": _now_iso()})


def _pending_bad_count(campaign_id) -> int:
    rows = sb("GET", f"verify_bad_leads?campaign_id=eq.{str(campaign_id)}"
                     f"&removed=eq.false&replied=eq.false&select=lead_id")
    return len(rows or [])


def _delete_bad_leads(job: dict, campaign_id, sl_key: str, dry_run: bool, candidates: list):
    """Shared delete loop used by both the standalone remove job and verify's
    inline auto-remove tail. Reply-guards (skips) anyone Smartlead has
    categorised an inbound event for. Marks each lead removed=true in
    verify_bad_leads as it goes, so an interrupted remove resumes from the
    still-pending rows. Extends job["progress"]["total"] by the delete count so
    an auto-remove tail shows up in the same progress bar as the verify pass it
    followed. Returns (deleted, guarded, failed, removed_emails, cancelled)."""
    guarded = [d for d in candidates if d.get("replied")]
    to_delete = [d for d in candidates if not d.get("replied")]
    with JOBS_LOCK:
        job["progress"]["total"] += len(to_delete)
    deleted, failed, removed_emails = [], 0, []
    cancelled = False
    for d in to_delete:
        with JOBS_LOCK:
            if job.get("cancel_requested"):
                cancelled = True
        if cancelled:
            break
        if not dry_run:
            # Retry the delete on a transient Smartlead error (429/5xx/timeout)
            # before giving up — without this, a brief hiccup permanently strands
            # a confirmed-bad lead in the campaign as a `failed_delete` the user
            # then has to notice and manually retry.
            url = (f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/leads/"
                   f"{d['lead_id']}?api_key={sl_key}")
            ok = False
            for attempt in (1, 2, 3):
                try:
                    req = urllib.request.Request(url, method="DELETE",
                                                 headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=20, context=SSL_CTX):
                        pass
                    ok = True
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                        time.sleep(1.5 * attempt)
                        continue
                    break  # 4xx (already gone / bad id) — don't hammer it
                except Exception:  # noqa: BLE001 — network/timeout: back off and retry
                    if attempt < 3:
                        time.sleep(1.5 * attempt)
                        continue
            if ok:
                deleted.append(d)
                removed_emails.append(d["email"])
                _mark_bad_removed(campaign_id, d["lead_id"])  # durable: survives a restart
            else:
                failed += 1
            time.sleep(0.45)  # ~150 req/min ceiling on the Smartlead delete endpoint
        else:
            deleted.append(d)  # dry-run: report what WOULD be deleted, delete nothing
            removed_emails.append(d["email"])
        with JOBS_LOCK:
            job["progress"]["done"] += 1
    return deleted, guarded, failed, removed_emails, cancelled


_MOCK_LEAD_COUNT = 40  # fabricated "uncontacted" lead set for mock verify jobs


def _mock_verify_worker(job: dict, campaign_id, mode: str):
    """Credit-free test double for the verify job lifecycle. Fabricates a
    deterministic uncontacted lead set (mock+<n>@example.com) and
    deterministic verdicts (~15% bad, ~10% catch_all, rest good), then drives
    the SAME job machinery as `_verify_job_worker` - job_started/finished,
    progress ticks with small sleeps so the UI visibly moves, per-chunk
    `_job_persist`, cancel honouring, counts including `contacted_skipped`,
    and an auto-remove tail against the fabricated bad set - without ever
    calling MillionVerifier, ListMint, or the Smartlead delete endpoint, and
    without writing to the real `people`/`email_verifications` tables. The
    only Supabase write is a `verify_campaign_state` row keyed by the given
    campaign_id, so the UI has something to read; the caller is expected to
    use an obviously-fake campaign_id (e.g. "MOCKTEST1") and delete that row
    (and the app_jobs row) once done testing."""
    from datetime import datetime, timezone
    _job_started(job)
    try:
        # mock_leads (in-memory only, mock jobs only): lets a restart-survival
        # test size the fake run long enough to straddle a deploy — at 0.03s a
        # lead, the default 40 finishes in ~1s, useless for that.
        n_leads = min(max(int(job.get("mock_leads") or _MOCK_LEAD_COUNT), 1), 30000)
        targets = [{"lead_id": f"mock-{i}", "email": f"mock+{i}@example.com",
                    "replied": False, "status": "STARTED", "is_unsubscribed": False,
                    "contacted": False} for i in range(n_leads)]
        contacted_skipped = 0
        with JOBS_LOCK:
            job["progress"]["total"] = len(targets)
            job["progress"]["done"] = 0

        details = []
        for i, ld in enumerate(targets):
            with JOBS_LOCK:
                cancelled = job.get("cancel_requested")
            if cancelled:
                # NOTE: call _job_finished OUTSIDE the lock — it re-acquires
                # JOBS_LOCK, so calling it while held self-deadlocks the worker
                # thread and, because it never releases, hangs every endpoint
                # that needs JOBS_LOCK (/api/jobs, cancel, new jobs).
                _job_finished(job, "cancelled")
                return
            time.sleep(0.03)  # visible progress movement in the UI, no real API call
            m = i % 20
            verdict = "bad" if m < 3 else "catch_all" if m < 5 else "good"  # ~15% / ~10% / rest
            details.append({"lead_id": ld["lead_id"], "email": ld["email"], "mv_result": None,
                            "lm_result": None, "verdict": verdict, "replied": ld["replied"]})
            with JOBS_LOCK:
                job["progress"]["done"] += 1
            if (i + 1) % 10 == 0:
                _job_persist(job)  # durable per-chunk heartbeat, mirrors the real worker

        counts = {"good": 0, "catch_all": 0, "unknown": 0, "bad": 0}
        for d in details:
            counts[d["verdict"]] += 1
        counts["cached"] = 0
        counts["contacted_skipped"] = contacted_skipped
        bad_emails = [d["email"] for d in details if d["verdict"] == "bad"]
        with JOBS_LOCK:
            job["counts"] = {"total": len(targets), **counts, "bad_emails": bad_emails}

        removal = None
        if job.get("auto_remove") and counts.get("bad", 0) > 0 and not job.get("cancel_requested"):
            bad_candidates = [d for d in details if d["verdict"] == "bad"]
            with JOBS_LOCK:
                job["progress"]["total"] += len(bad_candidates)
            deleted, guarded, failed, removed_emails, r_cancelled = [], [], 0, [], False
            for d in bad_candidates:
                with JOBS_LOCK:
                    if job.get("cancel_requested"):
                        r_cancelled = True
                if r_cancelled:
                    break
                time.sleep(0.02)  # mock delete: no Smartlead call, no real removal
                deleted.append(d)
                removed_emails.append(d["email"])
                with JOBS_LOCK:
                    job["progress"]["done"] += 1
            removal = {"removed": len(deleted), "guarded": len(guarded),
                      "failed_deletes": failed, "removed_emails": removed_emails,
                      "cancelled": r_cancelled}
            with JOBS_LOCK:
                job["counts"]["removed"] = len(deleted)
                job["counts"]["guarded"] = len(guarded)
                job["counts"]["failed_deletes"] = failed

        bad_remaining = counts.get("bad", 0) - (removal["removed"] if removal else 0)
        _verify_state_upsert(campaign_id, name=job.get("name") or job.get("label"),
                             last_verify_at=datetime.now(timezone.utc).isoformat(),
                             last_counts=job["counts"], bad_remaining=max(0, bad_remaining))
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001 — surface the real failure, never a vague one
        _job_finished(job, "failed", str(e)[:300])


def _verify_job_worker(job: dict, campaign_id, mode: str, mv_key: str,
                       lm_key: str, sl_key: str):
    from datetime import datetime, timezone
    if job.get("mock"):
        _mock_verify_worker(job, campaign_id, mode)
        return
    _job_started(job)
    try:
        leads = _fetch_all_smartlead_leads(campaign_id, sl_key)
        # Verify (and any auto-remove that follows) only ever touches leads
        # Smartlead hasn't already emailed — burning a verify credit, or
        # risking a delete, on someone already contacted is pointless and
        # in the delete case actively dangerous.
        targets = [ld for ld in leads if not ld["contacted"]]
        contacted_skipped = len(leads) - len(targets)
        if not targets:
            with JOBS_LOCK:
                job["progress"]["total"] = 0
                job["progress"]["done"] = 0
                job["counts"] = {"total": 0, "good": 0, "catch_all": 0, "unknown": 0,
                                 "bad": 0, "cached": 0, "bad_emails": [],
                                 "contacted_skipped": contacted_skipped,
                                 "detail": "no not-yet-contacted leads to verify — "
                                           "the campaign has already sent to everyone"}
            _verify_state_upsert(campaign_id, name=job.get("name") or job.get("label"),
                                 last_verify_at=datetime.now(timezone.utc).isoformat(),
                                 last_counts=job["counts"], bad_remaining=0)
            _job_finished(job, "done")
            return
        cache = _cached_verdicts([ld["email"] for ld in targets])
        details, cached_n = [], 0
        uncached = []
        for ld in targets:
            c = cache.get(ld["email"].lower())
            if c:
                cached_n += 1
                details.append({"lead_id": ld["lead_id"], "email": ld["email"],
                                "mv_result": c.get("result") if c.get("source") == "mv" else None,
                                "lm_result": c.get("result") if c.get("source") == "listmint" else None,
                                "verdict": c.get("verdict") or "unknown", "replied": ld["replied"]})
            else:
                uncached.append(ld)
        # max_new: hard cap on fresh (credit-spending) verifications this run.
        # Durable on the job row, so an auto-resumed continuation inherits it —
        # without that, a resume after a restart would blow straight past the
        # cap the original run was started with.
        cap_skipped = 0
        if job.get("max_new") is not None and len(uncached) > int(job["max_new"]):
            cap_skipped = len(uncached) - int(job["max_new"])
            uncached = uncached[:int(job["max_new"])]
        uncached_details = [{"lead_id": ld["lead_id"], "email": ld["email"], "mv_result": None,
                             "lm_result": None, "verdict": "unknown", "replied": ld["replied"]}
                            for ld in uncached]
        details.extend(uncached_details)
        api_errors = {}  # error message -> count; a mostly-errored run must fail, not "succeed"
        # progress: cached leads are instantly "done" — only uncached ones do
        # real work, so total/done both start honest rather than fake-full.
        with JOBS_LOCK:
            job["progress"]["total"] = len(details)
            job["progress"]["done"] = cached_n

        if mode == "mv":
            # Pre-flight: verifying costs 1 MV credit per lead, and MV answers
            # "Insufficient credits" per-call once the balance is gone — which
            # would silently land every lead in `unknown`. Refuse upfront instead.
            balance = _mv_credits(mv_key)
            if balance is not None and balance < len(uncached):
                raise RuntimeError(
                    f"MillionVerifier balance is {balance} credits but this campaign "
                    f"has {len(uncached)} unverified leads (1 credit each) — top up at "
                    f"millionverifier.com, then re-run.")
            from concurrent.futures import ThreadPoolExecutor, as_completed
            ex = ThreadPoolExecutor(max_workers=8)
            futs = {ex.submit(_mv_verify_one, d["email"], mv_key): d for d in uncached_details}
            cancelled = False
            for fut in as_completed(futs):
                with JOBS_LOCK:
                    if job.get("cancel_requested"):
                        cancelled = True
                if cancelled:
                    ex.shutdown(wait=False)
                    break
                d = futs[fut]
                mv_result = fut.result()
                if mv_result.startswith("error:"):
                    msg = mv_result[6:]
                    api_errors[msg] = api_errors.get(msg, 0) + 1
                    mv_result = "error"
                d["mv_result"] = mv_result
                d["verdict"] = ("good" if mv_result == "ok" else
                                "catch_all" if mv_result == "catch_all" else
                                "bad" if mv_result in ("disposable", "invalid") else
                                "unknown")
                with JOBS_LOCK:
                    job["progress"]["done"] += 1
                    done = job["progress"]["done"]
                if done % 100 == 0:
                    _job_persist(job)  # durable progress heartbeat every 100 leads
            _meter_verify_calls("millionverifier", campaign_id,
                                sum(1 for d in uncached_details
                                    if d.get("mv_result") and d["mv_result"] != "error"))
            if cancelled:
                _job_finished(job, "cancelled")
                return
            ex.shutdown(wait=True)
            _persist_verdicts([d for d in uncached_details if d.get("mv_result")],
                              campaign_id, "mv")
            errored = sum(api_errors.values())
            if uncached and errored > len(uncached) // 2:
                top = max(api_errors, key=api_errors.get)
                raise RuntimeError(
                    f"MillionVerifier rejected {errored} of {len(uncached)} lookups "
                    f"(\"{top}\") — verdicts are unusable, nothing was classified.")
            # Second layer: ListMint re-checks only what MV couldn't settle
            # (catch-alls + unknowns). Without a ListMint key the MV verdicts
            # stand alone — noted in counts, never silently.
            recheck = [d for d in uncached_details if d["verdict"] in ("catch_all", "unknown")]
            if lm_key and recheck:
                with JOBS_LOCK:
                    job["progress"]["total"] += len(recheck)
                if _listmint_pass(job, recheck, lm_key, api_errors, campaign_id):
                    _job_finished(job, "cancelled")
                    return
        else:  # mode == "listmint" — ListMint on every uncached lead, no MV involved
            if _listmint_pass(job, uncached_details, lm_key, api_errors, campaign_id):
                _job_finished(job, "cancelled")
                return
            errored = sum(api_errors.values())
            if uncached and errored > len(uncached) // 2:
                top = max(api_errors, key=api_errors.get)
                raise RuntimeError(
                    f"ListMint rejected {errored} of {len(uncached)} lookups "
                    f"(\"{top}\") — verdicts are unusable, nothing was classified.")

        counts = {"good": 0, "catch_all": 0, "unknown": 0, "bad": 0}
        for d in details:
            counts[d["verdict"]] += 1
        counts["cached"] = cached_n
        counts["contacted_skipped"] = contacted_skipped
        if cap_skipped:
            counts["cap_skipped"] = cap_skipped  # leads left unverified by max_new
        bad_emails = [d["email"] for d in details if d["verdict"] == "bad"]
        if mode == "mv" and not lm_key:
            counts["listmint_recheck"] = "skipped (LISTMINT_API_KEY not set)"
        VERIFY_RESULTS[str(campaign_id)] = details
        # Persist the bad leads (id + email) so a later Remove is a direct delete,
        # never a full-campaign re-fetch (which is slow and restart-prone).
        _store_bad_leads(campaign_id, [d for d in details if d["verdict"] == "bad"])
        with JOBS_LOCK:
            job["counts"] = {"total": len(details), **counts, "bad_emails": bad_emails}

        # Auto-remove tail: only when asked, only when there's something bad
        # to remove, and only if the verify pass itself wasn't cancelled.
        removal = None
        if job.get("auto_remove") and counts.get("bad", 0) > 0 \
                and not job.get("cancel_requested"):
            bad_candidates = [d for d in details if d["verdict"] == "bad"]
            deleted, guarded, failed, removed_emails, r_cancelled = _delete_bad_leads(
                job, campaign_id, sl_key, dry_run=False, candidates=bad_candidates)
            removal = {"removed": len(deleted), "guarded": len(guarded),
                      "failed_deletes": failed, "removed_emails": removed_emails,
                      "cancelled": r_cancelled}
            with JOBS_LOCK:
                job["counts"]["removed"] = len(deleted)
                job["counts"]["guarded"] = len(guarded)
                job["counts"]["failed_deletes"] = failed
            if not r_cancelled and deleted:
                VERIFY_RESULTS.pop(str(campaign_id), None)

        # bad_remaining = the still-removable bad leads on record (unremoved,
        # not reply-guarded) — read straight from the durable table so it stays
        # true even after a restart, and reflects failed deletes correctly.
        bad_remaining = _pending_bad_count(campaign_id)
        _verify_state_upsert(campaign_id, name=job.get("name") or job.get("label"),
                             last_verify_at=datetime.now(timezone.utc).isoformat(),
                             last_counts=job["counts"], bad_remaining=max(0, bad_remaining))

        payload = {"campaign_id": campaign_id, "mode": mode, "total": len(targets),
                  **counts, "bad_emails": bad_emails[:100]}
        if job.get("auto_remove"):
            payload["auto_remove"] = True
            if removal:
                payload["removed"] = removal["removed"]
                payload["guarded"] = removal["guarded"]
                payload["removed_emails"] = removal["removed_emails"][:100]
        log_activity("/api/verify-campaign", payload=payload,
                     actor="deliverability", action="verify_run",
                     entity="campaign", entity_id=campaign_id)
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001 — surface the real failure, never a vague one
        _job_finished(job, "failed", str(e)[:300])


def _remove_job_worker(job: dict, campaign_id, sl_key: str, dry_run: bool):
    _job_started(job)
    try:
        # Candidates come straight from the durable verify_bad_leads table — the
        # bad leads a prior verify already found and stored, with their lead_ids.
        # No full-campaign re-fetch (that was slow enough to get interrupted on a
        # big campaign). An interrupted remove just re-reads the still-pending
        # rows next time, so it resumes naturally.
        candidates = _pending_bad_leads(campaign_id)
        if not dry_run:
            # A reply may have landed since the verify snapshot — never delete a
            # replier. Fresh snapshots (<30min) skip the refetch, so the fast
            # path stays fast; stale ones pay one live status pass.
            candidates = _refresh_reply_guard(campaign_id, candidates, sl_key)
        note = None if candidates else "no confirmed-bad leads on record for this campaign"
        deleted, guarded, failed, removed_emails, cancelled = _delete_bad_leads(
            job, campaign_id, sl_key, dry_run, candidates)
        # dry_run: "deleted" reports what WOULD be removed (nothing actually was) -
        # the job's own `dry_run` flag is what tells a caller which case it is.
        counts = {"requested": len(candidates), "deleted": len(deleted),
                  "guarded": len(guarded), "failed": failed}
        if note:
            counts["detail"] = note
        with JOBS_LOCK:
            job["counts"] = counts
        if cancelled:
            if not dry_run and deleted:
                # only log a ledger row when something real actually happened -
                # a cancel before the first delete leaves no trace to record.
                log_activity("/api/verify-remove",
                             payload={"campaign_id": campaign_id, **counts,
                                      "removed_emails": removed_emails[:100],
                                      "dry_run": dry_run, "cancelled": True},
                             actor="deliverability", action="remove_bad",
                             entity="campaign", entity_id=campaign_id)
            _job_finished(job, "cancelled")
            return
        log_activity("/api/verify-remove",
                     payload={"campaign_id": campaign_id, **counts,
                              "removed_emails": removed_emails[:100], "dry_run": dry_run},
                     actor="deliverability", action="remove_bad",
                     entity="campaign", entity_id=campaign_id)
        if not dry_run:
            if failed == 0:
                VERIFY_RESULTS.pop(str(campaign_id), None)
            if deleted:
                state = sb("GET", f"verify_campaign_state?campaign_id=eq.{campaign_id}"
                                  "&select=last_counts,name")
                prev = (state[0] if isinstance(state, list) and state else {})
                merged_counts = {**(prev.get("last_counts") or {}), "removed": len(deleted),
                                 "guarded": len(guarded), "failed_deletes": failed}
                _verify_state_upsert(campaign_id, name=prev.get("name"),
                                     bad_remaining=_pending_bad_count(campaign_id),
                                     last_counts=merged_counts)
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001
        _job_finished(job, "failed", str(e)[:300])


def api_verify_campaign(p: dict):
    campaign_id = p.get("campaign_id")
    mode = (p.get("mode") or "mv").strip().lower()
    mock = bool(p.get("mock"))
    if not campaign_id:
        return {"error": "missing_campaign_id"}, 400
    if mode not in ("mv", "listmint"):
        return {"error": "unknown_mode",
                "message": "mode must be \"listmint\" (ListMint on every lead) or "
                           "\"mv\" (MillionVerifier first, ListMint re-checks catch-alls)."}, 400
    mv_key = KEYS.get("MILLIONVERIFIER_API_KEY") or os.environ.get("MILLIONVERIFIER_API_KEY")
    lm_key = KEYS.get("LISTMINT_API_KEY") or os.environ.get("LISTMINT_API_KEY")
    # Mock jobs never touch a real verifier/Smartlead, so key config is
    # irrelevant to them — this is the whole point of mock mode (credit-free
    # testing of the job lifecycle).
    if not mock:
        if mode == "mv" and not mv_key:
            return {"error": "millionverifier_not_configured",
                    "message": "MILLIONVERIFIER_API_KEY isn't set on this server - add it to "
                               "~/.navreo-keys.env locally or as a Render env var."}, 503
        if mode == "listmint" and not lm_key:
            return {"error": "listmint_not_configured",
                    "message": "LISTMINT_API_KEY isn't set on this server - add it to "
                               "~/.navreo-keys.env locally or as a Render env var."}, 503
    if mock and not str(campaign_id).upper().startswith("MOCK"):
        # A mock run writes fabricated counts to verify_campaign_state for its
        # campaign_id — pointing it at a REAL campaign would clobber that
        # campaign's genuine verify status with fake data (reviewer finding).
        return {"error": "mock_requires_fake_id",
                "message": "Mock verifications must use a campaign_id starting with "
                           "\"MOCK\" so they can't overwrite a real campaign's records."}, 400
    sl_key = KEYS.get("SMARTLEAD_API_KEY") or os.environ.get("SMARTLEAD_API_KEY") or ""
    dry_run = bool(p.get("dry_run"))
    auto_remove = bool(p.get("auto_remove"))
    name = (p.get("name") or "").strip() or None
    who = name or f"campaign {campaign_id}"
    label = (f"Verify {who} "
             + ("(ListMint)" if mode == "listmint" else "(MillionVerifier → ListMint)"))
    if auto_remove:
        label += " + auto-remove"
    if mock:
        label = "[TEST] " + label
    # Same TOCTOU-safe pattern as resume/remove: check-and-create under one lock
    # so a double-click can't start two verifies of the same campaign. (Today the
    # single-worker queue would serialise them, but the second run would still
    # re-spend on anything the first hadn't cached yet — and the guard becomes
    # load-bearing the day _JOB_WORKERS is bumped.)
    with _JOB_CREATE_LOCK:
        if not dry_run and not mock and _campaign_has_active_job(campaign_id):
            return {"error": "already_active",
                    "message": "This campaign already has a task running — wait for it to finish."}, 409
        max_new = None
        if p.get("max_new") is not None:
            try:
                max_new = max(0, int(p["max_new"]))
            except (TypeError, ValueError):
                max_new = None
        job = _new_job("verify", label, campaign_id, mode, dry_run,
                       auto_remove=auto_remove, mock=mock, max_new=max_new)
        job["name"] = name
        if mock and p.get("mock_leads"):
            job["mock_leads"] = p.get("mock_leads")
        _enqueue_job(_verify_job_worker, job,
                     (job, campaign_id, mode, mv_key, lm_key, sl_key))
    return {"job_id": job["id"]}, 202


def api_verify_remove(p: dict):
    campaign_id = p.get("campaign_id")
    if not campaign_id:
        return {"error": "missing_campaign_id"}, 400
    dry_run = bool(p.get("dry_run"))
    sl_key = KEYS.get("SMARTLEAD_API_KEY") or os.environ.get("SMARTLEAD_API_KEY") or ""
    name = (p.get("name") or "").strip() or None
    label = f"Remove bad leads: {name or ('campaign ' + str(campaign_id))}"
    # Dedup under _JOB_CREATE_LOCK (TOCTOU-safe): a double-click must not spawn
    # a second remove job for the same campaign. Dry-run previews are exempt.
    with _JOB_CREATE_LOCK:
        if not dry_run and _campaign_has_active_job(campaign_id):
            return {"error": "already_active",
                    "message": "This campaign already has a task running — wait for it to finish."}, 409
        job = _new_job("remove_bad", label, campaign_id, dry_run=dry_run)
        _enqueue_job(_remove_job_worker, job, (job, campaign_id, sl_key, dry_run))
    return {"job_id": job["id"]}, 202


def api_verify_status(ids: list) -> dict:
    from urllib.parse import quote
    if not ids:
        return {"status": {}}
    in_clause = ",".join(quote(i, safe="") for i in ids[:50])
    rows = sb("GET", f"verify_campaign_state?campaign_id=in.({in_clause})"
                      "&select=campaign_id,name,last_verify_at,last_counts,bad_remaining,dismissed")
    out = {}
    for r in (rows or []):
        cid = r.get("campaign_id")
        if not cid:
            continue
        out[cid] = {"name": r.get("name"), "last_verify_at": r.get("last_verify_at"),
                    "counts": r.get("last_counts"), "bad_remaining": r.get("bad_remaining"),
                    "dismissed": bool(r.get("dismissed"))}
    return {"status": out}


def api_verify_dismiss(p: dict):
    campaign_id = p.get("campaign_id")
    if not campaign_id:
        return {"error": "missing_campaign_id"}, 400
    dismissed = bool(p.get("dismissed", True))
    from datetime import datetime, timezone
    _verify_state_upsert(campaign_id, name=(p.get("name") or "").strip() or None,
                         dismissed=dismissed,
                         dismissed_at=datetime.now(timezone.utc).isoformat() if dismissed else None)
    log_activity("/api/verify-dismiss", payload={"campaign_id": campaign_id, "dismissed": dismissed},
                 actor="deliverability", action=("dismiss" if dismissed else "undismiss"),
                 entity="campaign", entity_id=campaign_id)
    return {"ok": True}, 200


def _warmup_job_worker(job: dict, op: str, domains: list):
    """Runs a warm-up pause/resume against the audit backend inside the job
    queue — so the click shows up in the Tasks panel, survives a page refresh,
    and a failure carries a real error message instead of vanishing (owner
    report 2026-07-11: the Warm-up button disappeared with no feedback and no
    error)."""
    from urllib.parse import quote
    _job_started(job)
    try:
        rest = f"warmup-{op}?domain=" + quote(",".join(domains), safe="")
        j = _deliv_backend_json("POST", rest, timeout=170)
        if isinstance(j, dict) and j.get("error"):
            _job_finished(job, "failed", str(j["error"])[:300])
            return
        key = "paused" if op == "pause" else "resumed"
        n = int((j or {}).get(key) or 0)
        counts = {"domains": len(domains), key: n}
        if isinstance(j, dict) and j.get("failed"):
            counts["failed"] = j["failed"]
        with JOBS_LOCK:
            job["counts"] = counts
        log_activity("/api/warmup-job", payload={"op": op, "domains": domains[:20], **counts},
                     actor="deliverability", action="warmup_" + op, entity="domain")
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001 — the whole point is surfacing the real failure
        _job_finished(job, "failed", str(e)[:300])


def api_warmup_job(p: dict):
    op = (p.get("op") or "").strip().lower()
    domains = [str(d).strip() for d in (p.get("domains") or []) if str(d).strip()]
    if op not in ("pause", "resume"):
        return {"error": "bad_op", "message": "op must be \"pause\" or \"resume\""}, 400
    if not domains:
        return {"error": "missing_domains"}, 400
    verb = "Warm-up rest" if op == "pause" else "Reactivate"
    label = f"{verb}: " + ", ".join(domains[:3]) \
        + (f" +{len(domains) - 3} more" if len(domains) > 3 else "")
    job = _new_job("warmup_" + op, label, None)
    _enqueue_job(_warmup_job_worker, job, (job, op, domains))
    return {"job_id": job["id"]}, 202


def _smartlead_json(method: str, path: str, body: dict | None = None, timeout: float = 60,
                    attempts: int = 5):
    """Smartlead call with 429 backoff (honours Retry-After). The 200req/min
    cap is SHARED with the background verify jobs, so a process-new apply can
    land mid-throttle and must wait its turn instead of failing the whole
    apply with 'HTTP Error 429' (seen live 2026-07-09). 5xx retries are
    GET-only: every POST here except /tags is idempotent, but a retried
    /tags create after an ambiguous 5xx could double-mint an undeletable tag."""
    import urllib.error
    key = KEYS.get("SMARTLEAD_API_KEY", "")
    sep = "&" if "?" in path else "?"
    url = f"{SMARTLEAD_BASE}{path}{sep}api_key={key}"
    for attempt in range(1, attempts + 1):
        try:
            if _deliv_mock_on():  # DELIV_MOCK — fake fleet in place of a real Smartlead call,
                return mock_deliv.smartlead(method, path, body)  # but INSIDE the retry loop so
            return http_json(method, url, {}, body, timeout=timeout)  # injected 429s exercise it
        except urllib.error.HTTPError as e:
            retriable = e.code == 429 or (method == "GET" and e.code in (500, 502, 503, 504))
            if not retriable or attempt == attempts:
                raise
            try:
                wait = int((e.headers or {}).get("Retry-After") or 0)
            except (TypeError, ValueError):
                wait = 0
            time.sleep(min(max(wait, 3 * attempt), 30))
    return {}


def api_process_new_selected(p: dict):
    """Tag and/or add-to-campaign an EXACT set of mailboxes, by address.

    The audit backend's process-new only scopes by a single substring filter,
    so a hand-picked selection in the Process-new modal comes here instead:
    addresses resolve to Smartlead account ids via POST /email-accounts/tag-list,
    the tag name resolves to a tag id (GET /email-accounts/tags, created via
    POST /tags if missing), assignment goes through /email-accounts/tag-mapping
    (additive + idempotent, hard cap 25 accounts/call), and the campaign add is
    POST /campaigns/{id}/email-accounts. Endpoint facts verified live
    2026-05-22 (memory: smartlead-api-realities) + probe 2026-07-09.
    """
    tag = (p.get("tag") or "").strip()
    campaign_id = str(p.get("campaign_id") or "").strip()
    tag_emails = [e.strip() for e in (p.get("tag_emails") or []) if isinstance(e, str) and e.strip()]
    camp_emails = [e.strip() for e in (p.get("camp_emails") or []) if isinstance(e, str) and e.strip()]
    if not (tag and tag_emails) and not (campaign_id and camp_emails):
        return {"ok": False, "reason": "nothing_to_do"}, 200
    if not KEYS.get("SMARTLEAD_API_KEY"):
        return {"ok": False, "message": "SMARTLEAD_API_KEY missing on this server"}, 503
    try:
        # 1. address → Smartlead email_account_id (tag-list is the one endpoint
        #    that resolves accounts by address; chunked defensively).
        want = sorted({*(tag_emails if tag else []), *(camp_emails if campaign_id else [])})
        ids: dict = {}
        for i in range(0, len(want), 100):
            r = _smartlead_json("POST", "/email-accounts/tag-list", {"email_ids": want[i:i + 100]})
            for row in ((r or {}).get("data") or []):
                if row.get("email_account_id") and row.get("email_id"):
                    ids[row["email_id"]] = row["email_account_id"]
        unresolved = [e for e in want if e not in ids]

        tagged = 0
        if tag and tag_emails:
            # 2. tag name → id: reuse an existing tag object (names are the UI
            #    identity; duplicate tag objects can't be API-deleted).
            tags = _smartlead_json("GET", "/email-accounts/tags") or []
            tag_id = next((t["id"] for t in tags
                           if isinstance(t, dict) and (t.get("name") or "").strip().lower() == tag.lower()), None)
            if tag_id is None:
                made = _smartlead_json("POST", "/tags", {"name": tag, "color": "#B1D4FC"})
                tag_id = ((made or {}).get("data") or {}).get("id")
            if not tag_id:
                return {"ok": False, "message": f"couldn't create Smartlead tag {tag!r}"}, 502
            acct = [ids[e] for e in tag_emails if e in ids]
            for i in range(0, len(acct), 25):
                _smartlead_json("POST", "/email-accounts/tag-mapping",
                                {"email_account_ids": acct[i:i + 25], "tag_ids": [tag_id]})
            tagged = len(acct)

        added = 0
        if campaign_id and camp_emails:
            acct = [ids[e] for e in camp_emails if e in ids]
            for i in range(0, len(acct), 100):
                _smartlead_json("POST", f"/campaigns/{campaign_id}/email-accounts",
                                {"email_account_ids": acct[i:i + 100]})
            added = len(acct)
    except Exception as e:  # noqa: BLE001 — surface provider errors to the UI
        return {"ok": False, "message": str(e)[:300]}, 502
    log_activity("/api/process-new-selected",
                 payload={"tag": tag, "campaign_id": campaign_id,
                          "tag_emails": len(tag_emails), "camp_emails": len(camp_emails)},
                 actor="deliverability", action="process_new_selected",
                 entity="mailboxes", entity_id=tag or campaign_id)
    return {"ok": True, "tagged": tagged, "addedToCampaign": added,
            **({"unresolved": unresolved} if unresolved else {})}, 200


_HR_LISTS: dict = {}


def heyreach_lists(refresh: bool = False) -> list:
    if _HR_LISTS.get("items") and not refresh:
        return _HR_LISTS["items"]
    items, off = [], 0
    while True:
        r = heyreach("/list/GetAll", {"limit": 100, "offset": off})
        page = r.get("items") or []
        items += [{"id": x.get("id"), "name": x.get("name") or ""} for x in page]
        if len(page) < 100:
            break
        off += 100
    _HR_LISTS["items"] = items
    return items


_OUTREACH_DESTS_TTL_S = 600  # the live Smartlead /campaigns GET was the slowest of
                              # the 5 list-view calls (baseline ~4s) - the picker
                              # data doesn't need to be second-fresh, and the
                              # frontend already calls ?refresh=1 (which bypasses
                              # this cache, see below) right after creating a new
                              # destination, so this TTL never hides a just-created
                              # campaign/list from the picker that created it.


def _compute_outreach_destinations(refresh: bool = False) -> dict:
    out: dict = {"smartlead": [], "heyreach": []}
    try:
        camps = http_json("GET", f"{SMARTLEAD_BASE}/campaigns?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}", {})
        if not isinstance(camps, list):
            # an auth failure comes back as {"message": "Invalid API Key"} — that
            # must surface as an error, never as a silently empty campaign list
            msg = camps.get("message") if isinstance(camps, dict) else str(camps)
            raise RuntimeError(f"Smartlead /campaigns: {msg or 'unexpected response'}")
        out["smartlead"] = [{"id": c.get("id"), "name": c.get("name") or "", "status": c.get("status")}
                            for c in camps
                            if c.get("status") in ("ACTIVE", "PAUSED", "DRAFTED")]
        out["smartlead_synced_at"] = int(time.time())
    except Exception as e:  # noqa: BLE001
        out["smartlead_error"] = str(e)[:150]
    try:
        out["heyreach"] = heyreach_lists(refresh=refresh)
        out["heyreach_synced_at"] = int(time.time())
    except Exception as e:  # noqa: BLE001
        out["heyreach_error"] = str(e)[:150]
    return out


_OUTREACH_DESTS_SWR = _SWRCache(_compute_outreach_destinations, _OUTREACH_DESTS_TTL_S,
                                 is_degraded=lambda p: bool(p.get("smartlead_error") or p.get("heyreach_error")),
                                 name="outreach-destinations")  # error payloads are
                                 # served once but never cached, so a transient
                                 # "Invalid API Key" can't poison the mirror


_OUTREACH_SYNC_INTERVAL_S = 540  # the campaigns-tab mirror refreshes on this
                                  # cadence (one Smartlead GET + one HeyReach
                                  # page-walk per cycle — nowhere near the shared
                                  # 200/min Smartlead budget)


def _store_outreach_payload(out: dict) -> dict:
    """Store a freshly computed destinations payload into the SWR cache,
    keeping the last good per-platform list when the new fetch errored — the
    error field stays on the payload so the UI can show it loudly next to
    the (stale) rows instead of an empty tab."""
    with _OUTREACH_DESTS_SWR.lock:
        prev = _OUTREACH_DESTS_SWR.payload or {}
        for plat in ("smartlead", "heyreach"):
            if out.get(f"{plat}_error") and prev.get(plat):
                out[plat] = prev[plat]
                if prev.get(f"{plat}_synced_at"):
                    out[f"{plat}_synced_at"] = prev[f"{plat}_synced_at"]
        _OUTREACH_DESTS_SWR.ts = time.time()
        _OUTREACH_DESTS_SWR.payload = out
    return out


def _outreach_sync_loop():
    """~10-minute background mirror sync for the campaigns tab (in-process,
    no external cron)."""
    while True:
        time.sleep(_OUTREACH_SYNC_INTERVAL_S)
        try:
            out = _compute_outreach_destinations()
            _store_outreach_payload(out)
            print(f"[outreach-sync] refreshed: {len(out.get('smartlead') or [])} smartlead, "
                  f"{len(out.get('heyreach') or [])} heyreach"
                  + (f", smartlead_error={out.get('smartlead_error')}" if out.get("smartlead_error") else "")
                  + (f", heyreach_error={out.get('heyreach_error')}" if out.get("heyreach_error") else ""),
                  flush=True)
        except Exception as e:  # noqa: BLE001 - the sync loop must never die
            print(f"[outreach-sync] cycle failed: {e}", flush=True)


def outreach_destinations(p: dict) -> dict:
    """Live pickers for the two outreach tools (header dropdowns).

    p['refresh'] forces a live re-pull of HeyReach lists AND bypasses the SWR
    cache entirely (synchronous fetch + store), so a list or campaign created
    moments ago shows up the instant the picker is opened - see campaigns.html's
    post-create flow which calls this endpoint with ?refresh=1. Non-refresh
    calls go through _OUTREACH_DESTS_SWR: fresh-within-TTL is served from
    memory, stale-past-TTL is served instantly with a background refresh (S1),
    and the live Smartlead /campaigns fetch (baseline ~4s) never blocks a
    normal picker open once the cache has been populated once."""
    if bool(p.get("refresh")):
        # the campaigns-tab manual "↻ Refresh" — recorded so we can see whether
        # users lean on it (signal for tuning the background sync cadence)
        log_activity("/api/outreach-destinations", actor="user",
                     action="refresh", entity="outreach_destinations")
        return _store_outreach_payload(_compute_outreach_destinations(refresh=True))
    return _OUTREACH_DESTS_SWR.get()


# ── Source → List bridge (campaigns-unified-home) ─────────────────────────
# A source's pulled prospects are materialised into a real `lists` +
# `list_rows` list so the People/All Files page can open them directly
# (deep link lists.html#<list_id>) and visibly reuse them in another
# campaign. THE JOIN LIVES HERE: sources.doc["list_id"] -> lists.id (uuid).
# Idempotent — one list per source, rows fully re-synced from the source's
# prospects after every pull; called from pull_source and backfilled once
# at boot for pre-existing sources.
_SOURCE_LIST_COLS = ["name", "title", "company", "domain", "linkedin_url",
                     "country", "email", "icebreaker"]


def _client_display_name(client_id) -> str:
    try:
        clients, _ = _cached_clients()
        for c in (clients or []):
            if c.get("id") == client_id:
                return c.get("name") or "Navreo"
    except Exception:  # noqa: BLE001
        pass
    return "Navreo"


def _ensure_source_list(src: dict):
    """Create/refresh the `lists` mirror of this source's prospects and
    stamp list_id on the source doc. Best-effort: a lists outage must never
    fail the pull that triggered it."""
    try:
        prospects = src.get("prospects") or []
        if not prospects:
            return src.get("list_id")
        list_id = src.get("list_id")
        if list_id:
            cur = sb("GET", f"lists?id=eq.{list_id}&select=id")
            if not (isinstance(cur, list) and cur):
                list_id = None  # list was deleted out from under us — recreate
        name = f"{src.get('name') or 'Source'} (source)"
        if not list_id:
            created = sb("POST", "lists",
                         {"name": name,
                          "client": _client_display_name(src.get("client_id")),
                          "source_skill": "signal-source",
                          "owner": "signals-tool",
                          "columns": _SOURCE_LIST_COLS,
                          "row_count": 0},
                         prefer="return=representation")
            if not (isinstance(created, list) and created):
                return None
            list_id = created[0]["id"]
            src["list_id"] = list_id
            write_source(src)
        rows = [{"list_id": list_id, "row_num": i + 1,
                 "data": {"name": x.get("name") or "", "title": x.get("title") or "",
                          "company": x.get("company") or "", "domain": x.get("domain") or "",
                          "linkedin_url": x.get("linkedin") or "", "country": x.get("country") or "",
                          "email": x.get("email") or "", "icebreaker": x.get("icebreaker") or ""}}
                for i, x in enumerate(prospects)]
        sb("DELETE", f"list_rows?list_id=eq.{list_id}")
        sb("POST", "list_rows", rows, prefer="return=minimal")
        sb("PATCH", f"lists?id=eq.{list_id}", {"row_count": len(rows)})
        return list_id
    except Exception as e:  # noqa: BLE001
        print(f"[source-list] sync failed for {src.get('id')}: {e}", flush=True)
        return src.get("list_id")


def _backfill_source_lists():
    """One-shot boot backfill: every live source with prospects but no
    (valid) list gets its mirror list created."""
    try:
        n = 0
        for src in read_drafts():
            if src.get("deleted_at"):
                continue
            if (src.get("prospects") and _ensure_source_list(src)):
                n += 1
        print(f"[source-list] backfill done: {n} sources linked", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[source-list] backfill failed: {e}", flush=True)


# ── Unified campaigns mirror (campaigns-unified-home) ──────────────────────
# ONE row per outbound campaign across the whole account: every Smartlead
# campaign (all statuses) + every HeyReach campaign, merged with the
# platform-keyed campaign_drafts docs (camp-sl-<id> / camp-hr-<listId>).
# Rows without a draft doc are EXTERNAL (read-only in the UI — managed in
# the platform, not this tool). Same SWR + last-good-on-error pattern as
# outreach-destinations. Never returns a silently-empty list on auth
# failure: the per-platform *_error field survives into the payload.
_CAMPAIGNS_UNIFIED_TTL_S = 600


def _compute_campaigns_unified(refresh: bool = False) -> dict:
    out: dict = {"rows": []}
    sl_rows, hr_rows = [], []
    try:
        camps = http_json("GET", f"{SMARTLEAD_BASE}/campaigns?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}", {})
        if not isinstance(camps, list):
            msg = camps.get("message") if isinstance(camps, dict) else str(camps)
            raise RuntimeError(f"Smartlead /campaigns: {msg or 'unexpected response'}")
        sl_rows = [{"key": f"camp-sl-{c.get('id')}", "platform": "smartlead",
                    "platform_id": c.get("id"), "name": c.get("name") or "",
                    "status": (c.get("status") or "").upper(),
                    "created_at": c.get("created_at")}
                   for c in camps]
        out["smartlead_synced_at"] = int(time.time())
    except Exception as e:  # noqa: BLE001
        out["smartlead_error"] = str(e)[:150]
    try:
        for it in _hey_pages("/campaign/GetAll"):
            hr_rows.append({"key": f"camp-hr-c{it.get('id')}", "platform": "heyreach",
                            "platform_id": it.get("id"), "name": it.get("name") or "",
                            "status": (it.get("status") or "").upper(),
                            "hr_list_id": it.get("linkedInUserListId"),
                            "created_at": it.get("creationTime") or it.get("startedAt")})
        out["heyreach_synced_at"] = int(time.time())
    except Exception as e:  # noqa: BLE001
        out["heyreach_error"] = str(e)[:150]

    # join the app's own docs: camp-sl-<id> direct; camp-hr-<listId> joins a
    # HeyReach campaign through its linkedInUserListId (a HR draft doc is
    # keyed by the LIST the tool fills, not the campaign that sends it)
    try:
        all_drafts, _fetch_failed = _cached_campaign_drafts()
        drafts = [d for d in (all_drafts or []) if not d.get("superseded_by") and not d.get("deleted_at")]
    except Exception:  # noqa: BLE001
        drafts = []
    by_key = {d.get("id"): d for d in drafts}
    claimed = set()
    for r in sl_rows:
        doc = by_key.get(r["key"])
        if doc:
            r["draft_id"], r["client_id"], r["managed"] = doc.get("id"), doc.get("client_id"), True
            claimed.add(doc.get("id"))
        else:
            r["managed"] = False
    for r in hr_rows:
        doc = by_key.get(f"camp-hr-{r.get('hr_list_id')}") if r.get("hr_list_id") else None
        if doc:
            r["draft_id"], r["client_id"], r["managed"] = doc.get("id"), doc.get("client_id"), True
            claimed.add(doc.get("id"))
        else:
            r["managed"] = False
    # drafts with no live platform row (unlinked or platform fetch failed):
    # still shown, never silently dropped
    for d in drafts:
        if d.get("id") in claimed:
            continue
        plat = "smartlead" if str(d.get("id", "")).startswith("camp-sl-") else \
               ("heyreach" if str(d.get("id", "")).startswith("camp-hr-") else None)
        if plat == "smartlead" and out.get("smartlead_error"):
            continue  # last-good handling below keeps the mirror row instead
        out.setdefault("unlinked", []).append(
            {"key": d.get("id"), "platform": plat, "platform_id": None,
             "name": d.get("name") or "", "status": "UNLINKED",
             "draft_id": d.get("id"), "client_id": d.get("client_id"), "managed": True,
             "created_at": d.get("created_at")})
    out["rows"] = sl_rows + hr_rows + (out.pop("unlinked", []) or [])
    out["smartlead_count"] = len(sl_rows)
    out["heyreach_count"] = len(hr_rows)
    return out


_CAMPAIGNS_UNIFIED_SWR = _SWRCache(_compute_campaigns_unified, _CAMPAIGNS_UNIFIED_TTL_S,
                                    is_degraded=lambda p: bool(p.get("smartlead_error") or p.get("heyreach_error")),
                                    name="campaigns-unified")


def campaign_readonly(p: dict) -> dict:
    """Live, read-only performance for ONE campaign the tool doesn't manage —
    so the homepage can open an external campaign instead of leaving a dead
    row. Smartlead: fresh /analytics. HeyReach: latest stored snapshot (LinkedIn
    campaigns have progress counts, not email metrics). Every number is the
    platform's own; nothing is invented."""
    platform = (p.get("platform") or "").lower()
    cid = str(p.get("id") or "").strip()
    if not cid:
        return {"error": "missing id"}
    if platform == "smartlead":
        try:
            data = _smartlead_json("GET", f"/campaigns/{cid}/analytics") or {}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:150], "platform": "smartlead", "id": cid}
        if isinstance(data, list):
            data = data[0] if data else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            data = {}
        cls = data.get("campaign_lead_stats") if isinstance(data.get("campaign_lead_stats"), dict) else {}
        positives = data.get("positive_reply_count")
        if positives is None:
            positives = data.get("positiveReplyCount")
        if positives is None:
            positives = cls.get("interested")
        return {"platform": "smartlead", "id": cid,
                "name": data.get("name") or data.get("campaign_name"),
                "status": data.get("status"),
                "sent": _sc_int(data.get("sent_count") or data.get("sent")),
                "replied": _sc_int(data.get("reply_count") or data.get("replied")),
                "positives": _sc_int(positives),
                "bounced": _sc_int(data.get("bounce_count")),
                "total": _sc_int(cls.get("total") or data.get("total_count")),
                "completed": _sc_int(cls.get("completed"))}
    if platform == "heyreach":
        rows = sb("GET", f"heyreach_campaigns?heyreach_id=eq.{cid}&order=snapshot_date.desc&limit=1") or []
        payload = (rows[0].get("payload") if rows and isinstance(rows, list) else {}) or {}
        ps = payload.get("progressStats") or {}
        return {"platform": "heyreach", "id": cid,
                "name": payload.get("name"),
                "status": payload.get("status"),
                "list_name": payload.get("linkedInUserListName"),
                "total": _sc_int(ps.get("totalUsers")),
                "in_progress": _sc_int(ps.get("totalUsersInProgress")),
                "completed": _sc_int(ps.get("totalUsersFinished")),
                "failed": _sc_int(ps.get("totalUsersFailed"))}
    return {"error": "unknown platform", "id": cid}


def campaign_platform_leads(p: dict) -> dict:
    """One page of a campaign's ACTUAL leads from the platform, so the detail
    Leads tab shows the real audience of any campaign (not just app-sourced
    signal leads). Smartlead: /campaigns/{id}/leads with offset/limit. HeyReach:
    campaign leads via the public API. Read-only — these people are already in
    the platform campaign."""
    platform = (p.get("platform") or "").lower()
    cid = str(p.get("id") or "").strip()
    try:
        offset = max(0, int(p.get("offset") or 0))
    except Exception:  # noqa: BLE001
        offset = 0
    try:
        limit = max(1, min(100, int(p.get("limit") or 50)))
    except Exception:  # noqa: BLE001
        limit = 50
    if not cid:
        return {"error": "missing id", "leads": [], "total": None}
    if platform == "smartlead":
        key = KEYS.get("SMARTLEAD_API_KEY", "")
        url = f"{SMARTLEAD_BASE}/campaigns/{cid}/leads?api_key={key}&offset={offset}&limit={limit}"
        page = _smartlead_get_retry(url)
        if not isinstance(page, dict):
            return {"error": "Smartlead leads fetch failed", "leads": [], "total": None}
        total = page.get("total_leads")
        try:
            total = int(total) if total is not None else None
        except Exception:  # noqa: BLE001
            total = None
        out = []
        for row in (page.get("data") or []):
            lead = row.get("lead") or {}
            nm = " ".join(x for x in [(lead.get("first_name") or "").strip(), (lead.get("last_name") or "").strip()] if x).strip()
            status = (row.get("status") or "").strip().upper()
            replied = row.get("lead_category_id") is not None
            out.append({"name": nm or (lead.get("email") or ""),
                        "email": lead.get("email") or "",
                        "company": lead.get("company_name") or "",
                        "title": lead.get("linkedin_bio") or lead.get("title") or "",
                        "status": status,
                        "replied": replied,
                        "unsubscribed": bool(row.get("is_unsubscribed"))})
        return {"platform": "smartlead", "id": cid, "leads": out, "total": total, "offset": offset, "limit": limit}
    if platform == "heyreach":
        try:
            r = heyreach("/campaign/GetLeadsFromCampaign", {"campaignId": int(cid), "offset": offset, "limit": limit})
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:150], "leads": [], "total": None}
        items = (r or {}).get("items") or []
        total = (r or {}).get("totalCount")
        out = []
        for it in items:
            prof = it.get("linkedInUserProfile") or it
            nm = " ".join(x for x in [(prof.get("firstName") or "").strip(), (prof.get("lastName") or "").strip()] if x).strip()
            out.append({"name": nm or (prof.get("profileUrl") or ""),
                        "company": prof.get("companyName") or "",
                        "title": prof.get("headline") or prof.get("position") or "",
                        "status": (it.get("status") or "").upper(),
                        "linkedin": prof.get("profileUrl") or ""})
        return {"platform": "heyreach", "id": cid, "leads": out, "total": total, "offset": offset, "limit": limit}
    return {"error": "unknown platform", "leads": [], "total": None}


def campaigns_unified(p: dict) -> dict:
    if bool(p.get("refresh")):
        out = _compute_campaigns_unified(refresh=True)
        with _CAMPAIGNS_UNIFIED_SWR.lock:
            _CAMPAIGNS_UNIFIED_SWR.ts = time.time()
            _CAMPAIGNS_UNIFIED_SWR.payload = out
        return out
    return _CAMPAIGNS_UNIFIED_SWR.get()


# ── Per-day performance series (campaigns-unified-home) ────────────────────
# The homepage's single multi-line graph. Every point is read from the
# Supabase data layer (fed by the existing Smartlead/HeyReach daily syncs);
# NOTHING is fabricated — a day/metric with no data is null, and the UI
# renders a labelled gap. Sources of truth per line:
#   sent       — sent_messages rows per sent_at::date (outbound archive of
#                synced campaigns; a real undercount of fleet volume, so the
#                label says so)
#   reply_rate — fleet 30d-rolling reply % from mailbox_stats_daily
#                (sum replies_30d / sum sent_30d per stat_date). NOT
#                replies÷sent_messages: that archive only holds replied
#                threads historically, which made the naive daily ratio read
#                84–400% — real numbers, misleading metric.
#   bounce_rate— fleet 30d-rolling bounce % from mailbox_stats_daily
#                (sum bounces_30d / sum sent_30d per stat_date; the only
#                bounce series the data layer has — sparse, labelled)
def _campaign_source_ids(smartlead_id) -> list:
    """signal_leads.source_id list for every source feeding the campaign(s) whose
    destination is this Smartlead campaign id. The join is: campaign_drafts.doc
    (destination.smartlead_campaign_id == id) -> draft id -> sources.doc where
    campaign_id == draft id -> source id (== signal_leads.source_id). Returns []
    (not None) when the id resolves to no sources, so leads_added scopes to an
    empty set (all-null absent line) rather than falling back to fleet."""
    if not smartlead_id:
        return None
    sid = str(smartlead_id)
    drafts, _failed = _cached_campaign_drafts()
    draft_ids = {str(d.get("id")) for d in (drafts or [])
                 if str((d.get("destination") or {}).get("smartlead_campaign_id") or "") == sid and d.get("id")}
    if not draft_ids:
        return []
    srcs = read_drafts() or []
    return [str(s.get("id")) for s in srcs
            if str(s.get("campaign_id") or "") in draft_ids and s.get("id")]


# ── Per-day performance series (campaigns homepage graph) ──────────────────
# FIVE per-day series, each from its REAL Supabase store (nothing estimated):
#   sent        — sent_messages archive by sent_at UTC date
#   leads_added — signal_leads by pulled_at UTC date (scoped to the campaign's
#                 source ids when a campaign is selected)
#   positives   — replies in POSITIVE_CATEGORIES by replied_at UTC date
#   meetings    — replies in MEETING_CATEGORIES  by replied_at UTC date
#   reply_rate  — fleet: mailbox_stats_daily 30d rolling; per-campaign: 30d
#                 trailing replies÷sent over the archive (bounded, campaign-scoped)
# Accepts days (7/30/90/…) OR explicit start/end, plus an optional campaign
# (smartlead_campaign_id; absent/"all" = fleet). A series with no data in the
# window is an all-null (labelled ABSENT) line; a real zero-activity day inside
# an active run stays 0 — the two never get confused. Bounce is still returned
# for any other consumer but the homepage graph no longer plots it.
def perf_daily(p: dict) -> dict:
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    today = _dt.now(_tz.utc).date()
    end = today
    start = None
    s_in, e_in = p.get("start"), p.get("end")
    if s_in and e_in:
        try:
            start = _dt.fromisoformat(str(s_in)[:10]).date()
            end = _dt.fromisoformat(str(e_in)[:10]).date()
        except Exception:  # noqa: BLE001
            start = None
    if start is None:
        try:
            days = max(7, min(120, int(p.get("days") or 30)))
        except Exception:  # noqa: BLE001
            days = 30
        start = end - _td(days=days - 1)
    if end < start:
        start, end = end, start
    ndays = (end - start).days + 1
    dates = [(start + _td(days=i)).isoformat() for i in range(ndays)]

    camp_raw = p.get("campaign")
    campaign = str(camp_raw).strip() if camp_raw not in (None, "", "all", "All") else None
    src_ids = _campaign_source_ids(campaign) if campaign else None

    # DB-side aggregation (rpc/…_v2) = one exact row per day, no client-side
    # pagination. p_source_ids scopes leads_added to the campaign's sources.
    rows = sb("POST", "rpc/perf_daily_series_v2",
              {"p_start": start.isoformat(), "p_end": end.isoformat(),
               "p_campaign": campaign, "p_source_ids": src_ids})
    if not isinstance(rows, list):
        return {"error": "Supabase read failed", "days": dates, "campaign": campaign,
                "sent": [None] * ndays, "leads_added": [None] * ndays,
                "positives": [None] * ndays, "meetings": [None] * ndays,
                "reply_rate": [None] * ndays, "bounce_rate": [None] * ndays}

    by = {r.get("d"): r for r in rows if r.get("d")}
    def col(name):
        return {d: _sc_int(by.get(d, {}).get(name)) for d in dates}
    sent_m, pos_m, mtg_m, la_m = col("sent"), col("positives"), col("meetings"), col("leads_added")

    def bounded(m):
        # real count (incl 0) between the first and last active day IN the visible
        # window; null outside (unknown); all-null when the series never fires —
        # that's the labelled ABSENT line, never a fabricated zero.
        active = [d for d in dates if m.get(d, 0) > 0]
        if not active:
            return [None] * ndays
        lo, hi = min(active), max(active)
        return [(m.get(d, 0) if lo <= d <= hi else None) for d in dates]

    # Fleet ("All campaigns") sent / reply-rate / positives come from the
    # PERMANENT day-by-day record in Supabase — fleet_daily_stats, sourced from
    # Smartlead's own day-wise analytics (same source as the deliverability tab),
    # backfilled and refreshed daily by the mailbox-sync cron. Full history (the
    # old mailbox_stats_daily snapshot method only reached back to the first sweep,
    # 2026-07-08, which is why Campaigns showed nothing older than the 9th).
    # A day Smartlead reports 0 sent for is a real 0; a day with no stored row is
    # null (absent). If the table isn't populated yet (pre-backfill), fall back to
    # the live deliverability series so the graph never blanks. A single campaign
    # has no fleet-analytics dimension → sent stays on the sent_messages archive,
    # positives on the replies table, reply-rate absent (no reliable denominator).
    if campaign:
        sent = bounded(sent_m)
        positives = bounded(pos_m)
        reply_rate = [None] * ndays
        bounce_rate = [None] * ndays
    else:
        frows = sb("GET", ("fleet_daily_stats?select=stat_date,sent,replies,positives,bounced,reply_rate"
                           f"&stat_date=gte.{start.isoformat()}&stat_date=lte.{end.isoformat()}"))
        fmap = {r.get("stat_date"): r for r in (frows or []) if isinstance(r, dict)}
        if fmap:
            def _fg(field):
                return [(fmap[d].get(field) if (d in fmap and fmap[d].get(field) is not None) else None) for d in dates]
            sent = [int(v) if v is not None else None for v in _fg("sent")]
            positives = [int(v) if v is not None else None for v in _fg("positives")]
            reply_rate = [float(v) if v is not None else None for v in _fg("reply_rate")]
            bounce_rate = [(round(int(fmap[d]["bounced"]) * 100.0 / int(fmap[d]["sent"]), 2)
                            if (d in fmap and fmap[d].get("sent")) else None) for d in dates]
        else:
            # Table not populated yet → live deliverability series (Smartlead day-wise).
            lookback = min(90, max(7, (today - start).days + 1))
            _tr, _ = deliv_trends_get(lookback)
            _ser = (_tr or {}).get("series") or {}
            _days = _ser.get("days") or []
            _sm = dict(zip(_days, _ser.get("sent") or []))
            _rm = dict(zip(_days, _ser.get("reply_pct") or []))
            _bm = dict(zip(_days, _ser.get("bounce_pct") or []))
            sent = [_sm.get(d) for d in dates]
            reply_rate = [_rm.get(d) for d in dates]
            bounce_rate = [_bm.get(d) for d in dates]
            positives = bounded(pos_m)
    leads_added = bounded(la_m)
    meetings = bounded(mtg_m)

    return {"days": dates, "campaign": campaign,
            "sent": sent, "leads_added": leads_added, "positives": positives,
            "meetings": meetings, "reply_rate": reply_rate, "bounce_rate": bounce_rate,
            "labels": {
                "sent": ("Emails sent/day (this campaign — sent_messages archive)"
                         if campaign else "Emails sent/day (whole fleet — Smartlead day-wise, stored daily in Supabase fleet_daily_stats)"),
                "leads_added": ("Leads added/day (signal_leads — this campaign's sources)"
                                if campaign else "Leads added/day (signal_leads pulled_at, all sources)"),
                "positives": ("Positive replies/day (replies: Interested / Call Booked / Meeting Request / Information Request)"
                              if campaign else "Positive replies/day (whole fleet — Smartlead day-wise positive replies, stored in fleet_daily_stats)"),
                "meetings": "Meetings/day (replies: Call Booked / Meeting Request)",
                "reply_rate": ("Reply rate % — fleet-wide only (no reliable per-campaign daily rate in the data layer)"
                               if campaign else "Reply rate % (whole fleet — Smartlead day-wise replies÷sent, stored in fleet_daily_stats)"),
                "bounce_rate": "Bounce rate % (whole fleet — Smartlead day-wise bounced÷sent, stored in fleet_daily_stats)"},
            "last_synced_day": max([d for d in dates if sent_m.get(d, 0)], default=None)}


# ── Campaign scorecard (Smartlead-style per-campaign performance) ──────────
# Powers the campaigns-list scorecard: for every signal campaign that sends to
# a real Smartlead campaign, its live Smartlead numbers (sent / reply / positive
# / bounce / completion). Meetings is the ONE metric Smartlead's /analytics call
# doesn't return, so it's read from the optimiser_notifications cache (the same
# {Call Booked, Meeting Request} category count build_notifications already
# computes) and left null — the UI gates it, never fakes it — when a campaign
# isn't covered there. Every number is Smartlead's own; nothing is invented.
_CAMPAIGN_SCORECARD_TTL_S = 600  # like _OUTREACH_DESTS: the live per-campaign
# /analytics fetches are the slow part; 10-min SWR keeps repaints instant and
# respects Smartlead's shared 200/min budget (only a handful of campaigns).


def _sc_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _scorecard_smartlead_ids() -> list:
    """Unique Smartlead campaign ids referenced by non-deleted signal campaigns,
    in first-seen order. A draft points at Smartlead via
    destination.smartlead_campaign_id (or, for a legacy type=='smartlead' doc,
    its campaign_id)."""
    drafts, _failed = _cached_campaign_drafts()
    ids, seen = [], set()
    for d in (drafts or []):
        if d.get("deleted_at"):
            continue
        dest = d.get("destination") or {}
        sl = dest.get("smartlead_campaign_id") or (
            d.get("campaign_id") if d.get("type") == "smartlead" else None)
        sl = str(sl) if sl else ""
        if sl and sl not in seen:
            seen.add(sl)
            ids.append(sl)
    return ids


def _scorecard_meetings(sl_ids: list) -> dict:
    """{sl_id: meetings} for the covered ids, from the latest optimiser_notifications
    row per campaign. Absent id -> not in the dict -> UI gates the tile."""
    out = {}
    if not sl_ids:
        return out
    from urllib.parse import quote
    ors = ",".join(sl_ids)
    rows = sb("GET", "optimiser_notifications?select=campaign_id,meetings,created_at"
                     f"&campaign_id=in.({quote(ors, safe=',')})"
                     "&order=created_at.desc") or []
    for r in rows:
        cid = str(r.get("campaign_id") or "")
        if cid and cid not in out and r.get("meetings") is not None:
            out[cid] = _sc_int(r.get("meetings"))
    return out


def _compute_campaign_scorecard() -> dict:
    """{ generated_at, campaigns: {sl_id: {..metrics..}}, degraded: bool }.
    Per campaign, straight from Smartlead /analytics: sent, replied, positives,
    bounced, completed, total (lead stats). meetings from the optimiser cache or
    None. Rates are computed by the UI from these raw counts so the collective
    strip can re-derive them from summed numerators/denominators."""
    from datetime import datetime, timezone
    sl_ids = _scorecard_smartlead_ids()
    meetings = _scorecard_meetings(sl_ids)
    camps, degraded = {}, False
    for sl in sl_ids:
        try:
            data = _smartlead_json("GET", f"/campaigns/{sl}/analytics") or {}
        except Exception as e:  # noqa: BLE001 — one bad id must not blank the whole board
            print(f"[scorecard] analytics fetch failed for {sl}: {e}", file=sys.stderr)
            degraded = True
            continue
        if isinstance(data, list):
            data = data[0] if data else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            data = {}
        cls = data.get("campaign_lead_stats") if isinstance(data.get("campaign_lead_stats"), dict) else {}
        positives = data.get("positive_reply_count")
        if positives is None:
            positives = data.get("positiveReplyCount")
        if positives is None:
            positives = cls.get("interested")
        camps[sl] = {
            "sent": _sc_int(data.get("sent_count") or data.get("sent")),
            "replied": _sc_int(data.get("reply_count") or data.get("replied")),
            "positives": _sc_int(positives),
            "bounced": _sc_int(data.get("bounce_count")),
            "completed": _sc_int(cls.get("completed")),
            "total": _sc_int(cls.get("total") or data.get("total_count")),
            "status": data.get("status"),
            "meetings": meetings.get(sl),  # int, or None -> UI gates it
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaigns": camps,
        "degraded": degraded,
    }


# ── All-campaign scorecard (background-synced, Supabase-cached) ─────────────
# The list wants real performance for EVERY campaign, not just the handful the
# tool manages. 874 live /analytics calls per page load is impossible, so a
# background thread fetches them all on a relaxed cadence and upserts to the
# `campaign_scorecard` table; the endpoint reads that table (one cheap query)
# and the numbers survive a restart. Same Smartlead source as the detail page's
# Live-performance strip, so list and detail always agree.
def _parse_smartlead_analytics(data) -> dict:
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        data = {}
    cls = data.get("campaign_lead_stats") if isinstance(data.get("campaign_lead_stats"), dict) else {}
    positives = data.get("positive_reply_count")
    if positives is None:
        positives = data.get("positiveReplyCount")
    if positives is None:
        positives = cls.get("interested")
    return {"sent": _sc_int(data.get("sent_count") or data.get("sent")),
            "replied": _sc_int(data.get("reply_count") or data.get("replied")),
            "positives": _sc_int(positives),
            "bounced": _sc_int(data.get("bounce_count")),
            "completed": _sc_int(cls.get("completed")),
            "total": _sc_int(cls.get("total") or data.get("total_count")),
            "status": data.get("status")}


_SCORECARD_SYNC_INTERVAL_S = 3600  # hourly; campaign stats don't move fast and
                                    # this is 874 /analytics calls per cycle
_SCORECARD_SYNC_LOCK = threading.Lock()


def _scorecard_sync_all():
    """Fetch /analytics for every Smartlead campaign and upsert to the
    campaign_scorecard cache. Paced under Smartlead's 200/min budget; one bad
    campaign never aborts the run. Batched upserts keep Supabase writes cheap."""
    if not _SCORECARD_SYNC_LOCK.acquire(blocking=False):
        return  # a cycle is already running
    try:
        camps = http_json("GET", f"{SMARTLEAD_BASE}/campaigns?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}", {})
        if not isinstance(camps, list):
            print(f"[scorecard-sync] campaign list unavailable: {camps}", flush=True)
            return
        rows, done, t0 = [], 0, time.time()
        for c in camps:
            cid = c.get("id")
            if not cid:
                continue
            try:
                data = _smartlead_json("GET", f"/campaigns/{cid}/analytics")
                m = _parse_smartlead_analytics(data)
            except Exception:  # noqa: BLE001
                continue
            rows.append({"smartlead_campaign_id": cid, "name": c.get("name") or "",
                         "status": m.get("status") or c.get("status"),
                         "sent": m["sent"], "replied": m["replied"], "positives": m["positives"],
                         "bounced": m["bounced"], "completed": m["completed"], "total": m["total"],
                         "updated_at": _now_iso()})
            done += 1
            if len(rows) >= 100:  # flush in batches so partial progress is visible
                sb("POST", "campaign_scorecard?on_conflict=smartlead_campaign_id", rows,
                   prefer="resolution=merge-duplicates,return=minimal")
                rows = []
            time.sleep(0.28)  # ~215/min ceiling — stay just under Smartlead's cap
        if rows:
            sb("POST", "campaign_scorecard?on_conflict=smartlead_campaign_id", rows,
               prefer="resolution=merge-duplicates,return=minimal")
        print(f"[scorecard-sync] refreshed {done} campaigns in {int(time.time() - t0)}s", flush=True)
    finally:
        _SCORECARD_SYNC_LOCK.release()


def _scorecard_sync_loop():
    """Background: prime once shortly after boot, then refresh hourly."""
    time.sleep(20)  # let boot settle before the first (long) sweep
    while True:
        try:
            _scorecard_sync_all()
        except Exception as e:  # noqa: BLE001 — the loop must never die
            print(f"[scorecard-sync] cycle failed: {e}", flush=True)
        time.sleep(_SCORECARD_SYNC_INTERVAL_S)


def _all_campaign_scorecard() -> dict:
    """The cached scorecard for EVERY campaign — one Supabase read. Keyed by
    str(smartlead_campaign_id), same shape as _compute_campaign_scorecard so the
    UI is unchanged. Meetings merged from the optimiser cache. HeyReach campaigns
    get their LinkedIn progress counts (people/replied) from the snapshot table."""
    rows = sb_get_all("campaign_scorecard?select=smartlead_campaign_id,name,status,sent,replied,positives,bounced,completed,total")
    camps = {}
    for r in (rows or []):
        sid = str(r.get("smartlead_campaign_id"))
        camps[sid] = {k: r.get(k) for k in ("sent", "replied", "positives", "bounced", "completed", "total", "status")}
        camps[sid]["meetings"] = None
    # meetings from the optimiser cache (latest per campaign)
    try:
        for r in (sb("GET", "optimiser_notifications?select=campaign_id,meetings,created_at&order=created_at.desc") or []):
            cid = str(r.get("campaign_id") or "")
            if cid in camps and camps[cid].get("meetings") is None and r.get("meetings") is not None:
                camps[cid]["meetings"] = _sc_int(r.get("meetings"))
    except Exception:  # noqa: BLE001
        pass
    # HeyReach per-campaign LinkedIn progress (people / in-progress / finished),
    # keyed hr-<campaignid> so the UI can show LinkedIn campaigns' real numbers
    hr = {}
    try:
        for r in (sb_get_all("heyreach_campaigns?select=heyreach_id,payload") or []):
            p = (r.get("payload") or {})
            ps = p.get("progressStats") or {}
            hr[f"hr-{r.get('heyreach_id')}"] = {
                "people": _sc_int(ps.get("totalUsers")), "in_progress": _sc_int(ps.get("totalUsersInProgress")),
                "finished": _sc_int(ps.get("totalUsersFinished")), "failed": _sc_int(ps.get("totalUsersFailed")),
                "status": p.get("status")}
    except Exception:  # noqa: BLE001
        pass
    return {"campaigns": camps, "heyreach": hr}


_CAMPAIGN_SCORECARD_ALL_SWR = _SWRCache(_all_campaign_scorecard, 120,
                                         is_degraded=lambda p: not (p and p.get("campaigns")),
                                         name="campaign-scorecard-all")


_CAMPAIGN_SCORECARD_SWR = _SWRCache(
    _compute_campaign_scorecard, _CAMPAIGN_SCORECARD_TTL_S,
    is_degraded=lambda p: not isinstance(p, dict) or not p.get("campaigns"),
    name="campaign-scorecard")


# ── Collective last-30-days top line (homepage strip) ──────────────────────
# The strip above the campaign list is a LAST-30-DAYS window, not all-time.
# Everything is one DB round-trip via rpc/collective_30d:
#  - sent / replies / positives / bounces + reply% / bounce% come from the latest
#    mailbox_stats_daily snapshot's per-mailbox trailing-30d columns (Smartlead's
#    OWN numbers — same source + definitions as the deliverability graph, so the
#    strip's reply/bounce rates match the graph's health verdict exactly);
#  - meetings from the dated meetings table (booked_at, last 30d);
#  - signals_sourced from signal_leads.pulled_at (last 30d).
# Nothing is invented; a failed read degrades to a labelled empty strip.
def _collective_30d() -> dict:
    r = sb("POST", "rpc/collective_30d", {})
    if isinstance(r, list):                 # defensive: some PostgREST shapes wrap
        r = r[0] if r else None
    if isinstance(r, dict) and "collective_30d" in r:   # select-style wrapping
        r = r.get("collective_30d")
    if not isinstance(r, dict) or r.get("sent") is None:
        return {"error": "Supabase read failed"}
    return r


_COLLECTIVE_30D_SWR = _SWRCache(_collective_30d, 300,
                                is_degraded=lambda p: not (isinstance(p, dict) and p.get("sent") is not None),
                                name="collective-30d")


# ── tier1-live-ship Step 2: campaign detail insights, hiring-signal campaign
# ideas, and recontact. Hard rules baked into every function below:
#   - nothing here activates a campaign or sends anything (drafts + QA-gate only)
#   - Smartlead sequence-save NEVER targets an id that already had sequences
#     (see execute_disable_variant_action's docstring at ~2553 for the one
#     existing-campaign exception; _create_smartlead_shell_from_god is the
#     other, and only ever targets a campaign this same call just created)
#   - idea generation is hiring-signal only, and only ever runs from an
#     explicit POST (never on a GET/page load)
WORKSPACE_TAG = "navreo"  # sent_messages/replies/contact_history/campaigns tag
                          # (matches setter.py's WORKSPACE) - every query below
                          # scopes to it explicitly


def _tier1_write_ok(res) -> bool:
    """True when an sb() write actually succeeded. A return=minimal success is
    `{}`; a hard failure (network/timeout, sb()'s own retry-then-give-up path)
    is None; a PostgREST error (e.g. PGRST205 'table not found', so this write
    happened before the migration was applied) comes back as a DICT CARRYING A
    `message` key, not None - same shape _lists_sb_error (~2737) checks for.
    Checking `res is not None` alone (an earlier draft of this code did) reads
    that error dict as success, which is exactly the "table not found" case
    this whole helper exists to catch."""
    if res is None:
        return False
    if isinstance(res, dict) and res.get("message"):
        return False
    return True


# ── 1. Campaign insights (proxy source attribution + deterministic findings) ─
_POS_REPLY_CATS = {"Interested", "Call Booked", "Meeting Request", "Information Request"}
_MEETING_REPLY_CATS = {"Call Booked", "Meeting Request"}
_IN_PROGRESS_STATUSES = {"INPROGRESS", "STARTED", "PAUSED"}


def _campaign_draft_ids_for_sl(sid) -> set:
    """draft ids whose destination points at this Smartlead campaign - same
    join _campaign_source_ids (~5559) does, factored out so campaign-insights
    and campaign-ideas can share it (both need the full source dicts, not
    just ids)."""
    sid = str(sid)
    drafts, _failed = _cached_campaign_drafts()
    return {str(d.get("id")) for d in (drafts or [])
            if str((d.get("destination") or {}).get("smartlead_campaign_id") or "") == sid
            and d.get("id") and not d.get("deleted_at")}


def _campaign_sources_full(sid) -> list:
    """Every non-deleted source doc feeding Smartlead campaign `sid` - same
    draft-resolution join as _campaign_source_ids, but returns the source
    dicts (id/name/mechanism/config/params/titles), not just ids."""
    draft_ids = _campaign_draft_ids_for_sl(sid)
    if not draft_ids:
        return []
    srcs = _cached_read_drafts() or []
    return [s for s in srcs if str(s.get("campaign_id") or "") in draft_ids
            and s.get("id") and not s.get("deleted_at")]


def _campaign_primary_draft(sid) -> dict | None:
    """One representative campaign_drafts doc for `sid` (name/client_id) - a
    campaign normally resolves to exactly one draft."""
    draft_ids = _campaign_draft_ids_for_sl(sid)
    if not draft_ids:
        return None
    drafts, _failed = _cached_campaign_drafts()
    return next((d for d in (drafts or []) if str(d.get("id")) in draft_ids), None)


def _campaign_insights_findings(sid: str, ro: dict, per_source: list,
                                ro_unavailable: bool = False) -> dict:
    """Deterministic (no LLM) plain-English findings: a summary line against
    the 1% fleet reply-rate benchmark, working/not-working sources from the
    reply-rate spread, concrete change suggestions, and this campaign's open
    optimiser rows. Every sentence is plain English, no jargon, no em dashes."""
    sent = ro.get("sent") or 0
    replied = ro.get("replied") or 0
    reply_rate = round(100.0 * replied / sent, 2) if sent else None
    if ro_unavailable:
        summary = ("Live campaign numbers could not be fetched just now, so the "
                   "summary is hidden rather than shown as zeros. Refresh in a minute.")
    elif not sent:
        summary = "This campaign has not sent any emails yet."
    elif reply_rate is None:
        summary = "Smartlead has not reported a reply rate for this campaign yet."
    elif reply_rate >= 1.0:
        summary = (f"This campaign is replying at {reply_rate}%, at or above the 1% benchmark "
                   f"most cold campaigns aim for.")
    else:
        summary = (f"This campaign is replying at {reply_rate}%, below the 1% benchmark "
                   f"most cold campaigns aim for.")

    working, not_working, changes = [], [], []
    rated = [r for r in per_source if r["reply_pct"] is not None and r["sent"] >= 20]
    if len(rated) >= 2:
        avg = sum(r["reply_pct"] for r in rated) / len(rated)
        for r in rated:
            if r["reply_pct"] >= avg * 1.3 and r["reply_pct"] - avg >= 0.3:
                working.append(f"{r['name']} is replying at {r['reply_pct']}%, well above this "
                               f"campaign's own average of {round(avg, 2)}%.")
            elif r["reply_pct"] <= avg * 0.7 and avg - r["reply_pct"] >= 0.3:
                not_working.append(f"{r['name']} is replying at {r['reply_pct']}%, well below this "
                                   f"campaign's own average of {round(avg, 2)}%.")
        if working:
            top = max((r for r in rated if r["reply_pct"] >= avg * 1.3), key=lambda r: r["reply_pct"])
            changes.append(f"Send more leads through {top['name']} - it is the strongest source right now.")
        if not_working:
            bottom = min((r for r in rated if r["reply_pct"] <= avg * 0.7), key=lambda r: r["reply_pct"])
            changes.append(f"Pause or rework {bottom['name']} - it is underperforming the other sources.")
    elif rated:
        working.append(f"Only {rated[0]['name']} has enough sends yet to read a reply rate "
                       f"({rated[0]['reply_pct']}%).")
    else:
        not_working.append("No source has sent enough emails yet to compare reply rates.")

    if reply_rate is not None and reply_rate < 1.0 and sent >= 200:
        changes.append("Reply rate is under the 1% benchmark with real send volume behind it - "
                       "worth reviewing the copy or the audience.")

    opt_rows = sb("GET", f"optimiser_notifications?campaign_id=eq.{sid}&status=eq.new"
                         "&select=title,suggested_action,detail&order=created_at.desc&limit=20")
    opt_rows = opt_rows if isinstance(opt_rows, list) else []
    optimisations = []
    for r in opt_rows:
        text = (r.get("suggested_action") or r.get("title") or r.get("detail") or "").strip()
        if text:
            optimisations.append(text)

    return {"summary": summary, "working": working, "not_working": not_working,
            "changes": changes, "optimisations": optimisations}


def _compute_campaign_insights(sid: str) -> dict:
    """PROXY per-source attribution (labelled - see the perf_daily comment
    block at ~5579 for why: sent_messages has no source_id) + deterministic
    findings for one Smartlead campaign. Cached 10min per campaign id via
    _CAMPAIGN_INSIGHTS_SWR below."""
    sources = _campaign_sources_full(sid)
    src_ids = [s["id"] for s in sources]

    # signal_leads -> lower(email) -> source_id (first source wins a rare
    # cross-source dupe). Batched via sb_get_all's Range pagination.
    email_source: dict = {}
    if src_ids:
        ids_csv = ",".join(str(x) for x in src_ids)
        rows = sb_get_all(f"signal_leads?select=source_id,email&source_id=in.({ids_csv})",
                          page_size=2000)
        for r in (rows or []):
            em = (r.get("email") or "").strip().lower()
            if em:
                email_source.setdefault(em, r.get("source_id"))

    # sent_messages + replies for the WHOLE Smartlead campaign, columns
    # trimmed to what the join needs - this is the proxy join the fact-sheet
    # calls for (_campaign_source_ids -> signal_leads (join) sent_messages/
    # replies on lower(email)). Paginated/batched so a 10k-send campaign
    # stays well under the 5s budget.
    sent_rows = sb_get_all(
        f"sent_messages?select=email&workspace=eq.{WORKSPACE_TAG}&smartlead_campaign_id=eq.{sid}",
        page_size=2000)
    reply_rows = sb_get_all(
        f"replies?select=email,category&workspace=eq.{WORKSPACE_TAG}&smartlead_campaign_id=eq.{sid}",
        page_size=2000)
    degraded = not isinstance(sent_rows, list) or not isinstance(reply_rows, list)
    sent_emails = {(r.get("email") or "").strip().lower() for r in (sent_rows or []) if r.get("email")}
    reply_cats: dict = {}
    for r in (reply_rows or []):
        em = (r.get("email") or "").strip().lower()
        if em:
            reply_cats.setdefault(em, set()).add(r.get("category"))

    per_source = []
    for s in sources:
        s_emails = [em for em, src in email_source.items() if src == s["id"]]
        sent_n = sum(1 for em in s_emails if em in sent_emails)
        replies_n = sum(1 for em in s_emails if em in reply_cats)
        pos_n = sum(1 for em in s_emails if reply_cats.get(em, set()) & _POS_REPLY_CATS)
        mtg_n = sum(1 for em in s_emails if reply_cats.get(em, set()) & _MEETING_REPLY_CATS)
        per_source.append({
            "source_id": s["id"], "name": s.get("name") or s["id"],
            "type": s.get("mechanism") or s.get("type") or "unknown",
            "leads_pushed": len(s_emails), "sent": sent_n, "replies": replies_n,
            "reply_pct": round(100.0 * replies_n / sent_n, 2) if sent_n else None,
            "positives": pos_n, "meetings": mtg_n,
        })
    per_source.sort(key=lambda r: -(r["sent"] or 0))

    # runs_dry: campaign_readonly's real Smartlead totals + a 14-day send pace
    ro = campaign_readonly({"platform": "smartlead", "id": sid})
    # campaign_readonly zero-fills silently when the live Smartlead fetch fails
    # (a real campaign always has a name and a status). Treat that as "numbers
    # unavailable", never as "campaign sent nothing" - rendering a false zero
    # as fact is worse than admitting the fetch failed.
    ro_unavailable = ro.get("name") is None and ro.get("status") is None
    leads_total = None if ro_unavailable else ro.get("total")
    leads_completed = None if ro_unavailable else ro.get("completed")
    from datetime import datetime, timedelta, timezone
    # date-only bound: an isoformat() timestamp carries "+00:00" whose "+"
    # reads as a space in a query string -> PostgREST 400 (caught on staging
    # 2026-07-14). A day of slack is irrelevant to a 14-day pace estimate.
    since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    pace_n = sb_count(f"sent_messages?workspace=eq.{WORKSPACE_TAG}&smartlead_campaign_id=eq.{sid}"
                      f"&sent_at=gte.{since}")
    pace_per_day = (pace_n / 14.0) if pace_n else 0.0
    days_left = None
    if isinstance(leads_total, int) and isinstance(leads_completed, int) and pace_per_day > 0:
        remaining = max(0, leads_total - leads_completed)
        days_left = int(round(remaining / pace_per_day)) if remaining else 0
    best = max(per_source, key=lambda r: (r["positives"], r["reply_pct"] or 0.0), default=None)

    insights = _campaign_insights_findings(sid, ro, per_source, ro_unavailable=ro_unavailable)

    return {
        "attribution": "proxy",
        "runs_dry": {
            "days_left": days_left, "leads_total": leads_total, "leads_completed": leads_completed,
            "best_source_id": (best or {}).get("source_id"), "best_source_name": (best or {}).get("name"),
            "new_estimate_note": ("Estimated from the last 14 days of sends - a slower or faster send "
                                  "pace changes this." if days_left is not None else
                                  "Not enough send history yet to estimate days left."),
        },
        "per_source": per_source,
        "insights": insights,
        "degraded": degraded or ro_unavailable,
    }


_CAMPAIGN_INSIGHTS_SWR = _SWRKeyedCache(_compute_campaign_insights, 600,
                                        is_degraded=lambda p: bool(p.get("degraded")),
                                        name="campaign-insights")


def api_campaign_insights(p: dict) -> dict:
    platform = (p.get("platform") or "").lower()
    sid = str(p.get("id") or "").strip()
    if not sid:
        return {"error": "missing id"}
    if platform != "smartlead":
        return {"error": "campaign-insights currently supports platform=smartlead only"}
    return _CAMPAIGN_INSIGHTS_SWR.get(sid)


# ── 2. Campaign ideas: on-demand, hiring-signal only, never on page load ────
CAMPAIGN_IDEA_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"ideas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "job_titles": {"type": "array", "items": {"type": "string"}},
            "dm_titles": {"type": "array", "items": {"type": "string"}},
            "lead_magnet": {"type": "string"},
            "rationale": {"type": "string"},
            "icebreaker": {"type": "string"},
        },
        "required": ["title", "job_titles", "dm_titles", "lead_magnet", "rationale", "icebreaker"],
    }}},
    "required": ["ideas"],
}


def _campaign_ideas_context(sid: str) -> dict:
    """Client/ICP context for idea generation, all derived server-side from
    the campaign's own client + any hiring source it already runs - no
    frontend wizard state involved (this is a pure backend feature)."""
    draft = _campaign_primary_draft(sid)
    client: dict = {}
    if draft and draft.get("client_id"):
        clients, _failed = _cached_clients()
        client = next((c for c in (clients or []) if c.get("id") == draft["client_id"]), None) or {}
    campaign_name = (draft or {}).get("name")
    if not campaign_name:
        campaign_name = campaign_readonly({"platform": "smartlead", "id": sid}).get("name")
    sources = _campaign_sources_full(sid) if draft else []
    existing = [f"{s.get('mechanism') or s.get('type') or 'signal'}: {s.get('name')}"
               for s in sources if s.get("name")]
    hiring_src = next((s for s in sources if (s.get("mechanism") or s.get("type")) == "hiring"), None)
    cfg = {**((hiring_src or {}).get("config") or {}), **((hiring_src or {}).get("params") or {})}
    return {
        "campaign_id": sid, "campaign_name": campaign_name,
        "client_name": client.get("name") or "", "client_description": client.get("description") or "",
        "client_offer": client.get("offer") or "", "existing": existing,
        "countries": cfg.get("countries") or [], "headcount": cfg.get("headcount") or [],
        "dm_titles": cfg.get("dm_titles") or (hiring_src or {}).get("titles") or [],
    }


def _generate_campaign_ideas(ctx: dict, exclude_titles: list, max_credits: int) -> list:
    """Reuses _suggest_llm (~933) - the same minimal-effort JSON-schema
    completion the wizard's Generate-more buttons use - constrained to
    hiring-signal ideas only. Sizing reuses preview_hiring (~359, FREE
    TheirStack blurred preview - the same probe strategy_map's Stage 2 uses
    at ~1554), so idea generation spends zero paid-provider credits;
    max_credits only bounds how many of those free probes one call makes."""
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        return []
    bits = []
    if ctx.get("client_name"):
        bits.append(f"Client: {ctx['client_name']}")
    if ctx.get("client_description"):
        bits.append(f"What they do: {ctx['client_description']}")
    if ctx.get("client_offer"):
        bits.append(f"What is being sold (only propose signals that indicate need for THIS): {ctx['client_offer']}")
    if ctx.get("campaign_name"):
        bits.append(f"This existing campaign: {ctx['campaign_name']}")
    if ctx.get("existing"):
        bits.append("Already running on this campaign (do not repeat or propose a close variant): "
                    + "; ".join(ctx["existing"]))
    if exclude_titles:
        bits.append("Already suggested before - propose genuinely different ideas, not close variants: "
                    + "; ".join(t for t in exclude_titles if t))
    system = ("You are the campaign-ideation engine of a cold-email agency, generating HIRING-SIGNAL "
             "ideas ONLY. A hiring-signal idea fires when a target company posts a live job opening for "
             "a specific role - that open role is the buying signal. Every idea needs job_titles (the "
             "roles being hired for, which indicate need for the offer) and dm_titles (the decision-makers "
             "to actually email at that company - e.g. Founder, Head of Sales - never the role being "
             "hired). Plain English, no jargon, no em dashes.")
    user = (("\n".join(bits) if bits else
            "No client context is available - reason from a generic B2B hiring-signal angle.")
           + "\n\nGenerate exactly 3 NEW hiring-signal campaign ideas.")
    try:
        out = _suggest_llm(key, system, user, "hiring_ideas", CAMPAIGN_IDEA_SCHEMA)
    except Exception as e:  # noqa: BLE001 — generation is best-effort; caller reports "try again"
        print(f"[campaign-ideas] generation failed: {e}", file=sys.stderr)
        return []

    codes, _unmapped = country_codes(ctx.get("countries") or [])
    codes = codes or ["US"]
    lo, hi = emp_range(ctx.get("headcount"))
    probes_left = max(0, max_credits)
    result = []
    import hashlib
    for it in (out.get("ideas") or [])[:3]:
        title = (it.get("title") or "").strip()
        job_titles = [t.strip() for t in (it.get("job_titles") or []) if str(t).strip()]
        if not title or not job_titles:
            continue
        dm_titles = ([t.strip() for t in (it.get("dm_titles") or []) if str(t).strip()]
                    or ctx.get("dm_titles") or [])
        dm_per_month = None
        if probes_left > 0:
            try:
                r = preview_hiring({"job_titles": job_titles, "countries": codes,
                                    "min_emp": lo, "max_emp": hi, "days": 30})
                probes_left -= 1
                companies = r.get("total_companies")
                # gate fallback: companies-with-signal/mo x 2.5 titles, estimate=true
                if isinstance(companies, int):
                    dm_per_month = round(companies * 2.5)
            except Exception:  # noqa: BLE001 — sizing is best-effort, never blocks the idea
                pass
        idea_id = hashlib.md5(f"{ctx['campaign_id']}|{title.lower()}".encode()).hexdigest()[:12]
        result.append({
            "id": idea_id, "title": title, "mechanism": "hiring-signal",
            "lead_magnet": (it.get("lead_magnet") or "").strip(),
            "rationale": (it.get("rationale") or "").strip(),
            "dm_per_month": dm_per_month, "estimate": True,
            "job_titles": job_titles, "dm_titles": dm_titles,
            "icebreaker": ensure_hiring_vars(it.get("icebreaker") or HIRING_ICE_DEFAULT),
        })
    return result


def _campaign_ideas_job_worker(job: dict, sid: str, more: bool, max_credits: int):
    _job_started(job)
    try:
        ctx = _campaign_ideas_context(sid)
        exclude_titles = []
        if more:
            prev = sb("GET", f"campaign_idea_suggestions?campaign_id=eq.{sid}&select=idea")
            if isinstance(prev, list):
                exclude_titles = [(r.get("idea") or {}).get("title") for r in prev
                                  if isinstance(r.get("idea"), dict) and (r.get("idea") or {}).get("title")]
        ideas = _generate_campaign_ideas(ctx, exclude_titles, max_credits)
        if not ideas:
            job["counts"] = {"ideas": [],
                             "message": "Could not generate ideas right now - check OPENAI_API_KEY, or try again."}
            _job_finished(job, "done")
            return
        now = _now_iso()
        rows = [{"id": i["id"], "campaign_id": sid, "idea": i, "status": "suggested", "created_at": now}
               for i in ideas]
        res = sb("POST", "campaign_idea_suggestions?on_conflict=id", rows,
                prefer="resolution=merge-duplicates,return=minimal")
        persisted = _tier1_write_ok(res)
        job["counts"] = {"ideas": ideas, "persisted": persisted}
        if not persisted:
            job["counts"]["warning"] = ("Ideas generated but could not be saved - the "
                                        "campaign_idea_suggestions table may not exist yet. Apply "
                                        "migrations/tier1_idea_suggestions.sql, then try again.")
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001
        _job_finished(job, "failed", str(e)[:300])


def api_campaign_ideas_start(p: dict):
    sid = str(p.get("campaign_id") or "").strip()
    if not sid:
        return {"error": "missing_campaign_id"}, 400
    more = bool(p.get("more"))
    try:
        max_credits = max(1, min(200, int(p.get("max_credits") or 50)))
    except (TypeError, ValueError):
        max_credits = 50
    with _JOB_CREATE_LOCK:
        if _campaign_has_active_job(sid):
            return {"error": "already_active",
                   "message": "This campaign already has a task running - wait for it to finish."}, 409
        job = _new_job("campaign_ideas", "Suggest campaign ideas", sid, mode=("more" if more else "first"))
        _enqueue_job(_campaign_ideas_job_worker, job, (job, sid, more, max_credits))
    return {"job_id": job["id"]}, 202


def api_campaign_ideas_get(p: dict):
    """Pure read - NEVER triggers generation (generation only ever happens
    inside api_campaign_ideas_start, reached only via POST)."""
    sid = str(p.get("campaign_id") or "").strip()
    if not sid:
        return {"status": "idle", "ideas": []}
    with JOBS_LOCK:
        running = [j for j in JOBS.values() if str(j.get("campaign_id")) == sid
                  and j.get("kind") == "campaign_ideas" and j.get("status") in ("queued", "running")]
    status = running[-1]["status"] if running else "idle"
    rows = sb("GET", f"campaign_idea_suggestions?campaign_id=eq.{sid}&status=neq.dismissed"
                     "&order=created_at.desc")
    if not isinstance(rows, list):
        return {"status": status, "ideas": [],
               "error": "campaign_idea_suggestions table unavailable - apply "
                        "migrations/tier1_idea_suggestions.sql"}
    return {"status": status, "ideas": [r["idea"] for r in rows if isinstance(r.get("idea"), dict)]}


def api_campaign_ideas_dismiss(p: dict):
    sid = str(p.get("campaign_id") or "").strip()
    iid = str(p.get("idea_id") or "").strip()
    if not sid or not iid:
        return {"ok": False, "message": "campaign_id and idea_id are required"}, 400
    res = sb("PATCH", f"campaign_idea_suggestions?id=eq.{iid}&campaign_id=eq.{sid}", {"status": "dismissed"})
    if not _tier1_write_ok(res):
        return {"ok": False, "message": "Could not save - the campaign_idea_suggestions table may not "
                                       "exist yet, or the database is unreachable."}, 503
    log_activity("/api/campaign-ideas/dismiss", p, action="dismiss", entity="campaign_idea", entity_id=iid)
    return {"ok": True}, 200


def _patch_campaign_draft(cid: str, **fields) -> bool:
    """Set arbitrary fields on ONE campaign_drafts doc by id - same whole-list
    read/patch/write pattern update_campaign_draft (~8333) uses for its
    whitelisted fields; this covers fields that function doesn't expose
    (e.g. needs_shell)."""
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    found = False
    for d in drafts:
        if d.get("id") == cid:
            d.update(fields)
            found = True
    if found:
        write_drafts(drafts, CAMPAIGN_DRAFTS)
    return found


def _idea_add_default_dm_titles(idea: dict) -> list:
    return idea.get("dm_titles") or ["Founder", "CEO", "VP of Sales", "Head of Sales"]


def _idea_add_plan(sid: str, idea: dict, mode: str, test_cap: int) -> dict:
    """The dry-run plan - what api_campaign_ideas_add would do, without doing
    any of it. Same shape whether dry_run is true or not."""
    draft = _campaign_primary_draft(sid)
    plan = {"mode": mode, "test_cap": test_cap, "idea_title": idea.get("title"),
           "target_smartlead_campaign_id": sid,
           "draft_id": (draft or {}).get("id") or f"camp-sl-{sid}",
           "draft_exists": bool(draft),
           "source_config": {
               "type": "hiring", "mechanism": "hiring", "name": idea.get("title") or "Hiring signal idea",
               "titles": _idea_add_default_dm_titles(idea),
               "params": {"job_titles": idea.get("job_titles") or [], "days": 30, "leads_per_day": test_cap},
           }}
    if mode == "existing":
        plan["will_create_source_on_existing_campaign"] = True
        plan["note"] = (f"Creates a hiring source on the existing campaign and pulls up to {test_cap} "
                        f"leads. Leads land as drafts and go through the normal QA gate - nothing sends.")
    else:
        god = KEYS.get("GOD_TEMPLATE_SL_ID") or os.environ.get("GOD_TEMPLATE_SL_ID")
        plan["will_duplicate_campaign"] = True
        plan["god_template_sl_id"] = god
        plan["will_create_smartlead_shell"] = bool(god)
        plan["needs_shell"] = not bool(god)
        plan["note"] = ((f"Duplicates the campaign draft, attaches a new hiring source, creates a "
                         f"Smartlead DRAFT campaign, and copies sequences from campaign {god} onto it "
                         f"only - the template itself is never written to.") if god else
                        "Duplicates the campaign draft and attaches a new hiring source. "
                        "GOD_TEMPLATE_SL_ID is not set, so no Smartlead shell is created - "
                        "the new draft is marked needs_shell.")
    return plan


def _create_smartlead_shell_from_god(god_sl_id: str, name: str) -> dict:
    """Creates ONE new Smartlead DRAFT campaign and copies the God-template's
    sequence onto it. This and execute_disable_variant_action (~2553) are the
    only two places in this file that call Smartlead's sequences endpoint -
    that one is the sanctioned exception for an EXISTING campaign (id-carrying
    + post-verify, never destroys history); this one is safe by construction
    because the target campaign was JUST created by this same call and has no
    sequence yet, so there is no history to lose and no ids to preserve. It
    NEVER writes to god_sl_id or any other pre-existing campaign, and never
    sets any campaign active (Smartlead campaigns are created in DRAFT status)."""
    if not KEYS.get("SMARTLEAD_API_KEY"):
        return {"ok": False, "message": "SMARTLEAD_API_KEY is not configured on this server"}
    created = _smartlead_json("POST", "/campaigns/create", {"name": (name or "New campaign")[:190]})
    new_id = created.get("id") if isinstance(created, dict) else None
    if not new_id:
        return {"ok": False, "message": "Smartlead did not return a new campaign id",
               "smartlead_response": created}
    if str(new_id) == str(god_sl_id):
        # Cannot happen in practice - Smartlead always mints a fresh id - but this
        # is exactly the invariant that must never be violated, so refuse outright.
        return {"ok": False, "message": "Smartlead returned the template's own id - refusing to touch it"}
    template = _smartlead_json("GET", f"/campaigns/{god_sl_id}/sequences")
    steps = template if isinstance(template, list) else (
        template.get("data") or template.get("sequences") or [] if isinstance(template, dict) else [])
    if not steps:
        return {"ok": True, "smartlead_campaign_id": new_id, "sequences_copied": 0,
               "message": "Shell created; the God-template has no sequences to copy"}
    body = []
    for s in steps:
        step = {"seq_number": s.get("seq_number")}
        delay = (s.get("seq_delay_details") or {}).get("delayInDays")
        if delay is not None:
            step["seq_delay_details"] = {"delay_in_days": delay}
        if s.get("subject") is not None:
            step["subject"] = s.get("subject")
        if s.get("email_body") is not None:
            step["email_body"] = s.get("email_body")
        variants = [v for v in (s.get("sequence_variants") or []) if not v.get("is_deleted")]
        if variants:
            step["seq_variants"] = [
                {"variant_label": v.get("variant_label"), "subject": v.get("subject"),
                 "email_body": v.get("email_body"),
                 "variant_distribution_percentage": v.get("variant_distribution_percentage")}
                for v in variants]
        body.append(step)
    # ONLY the campaign this call just created - never god_sl_id, never any
    # other existing id (mirrors the HARD CONSTRAINT at ~2419).
    save_res = _smartlead_json("POST", f"/campaigns/{new_id}/sequences", {"sequences": body})
    return {"ok": True, "smartlead_campaign_id": new_id, "sequences_copied": len(body),
           "smartlead_save_response": save_res,
           # Smartlead's public API has no separate sub-sequence resource distinct
           # from these steps as of this build - nothing further is known to copy.
           # Flagged as a known gap rather than silently skipped.
           "sub_sequences_copied": None}


def _apply_idea_add_existing(sid: str, idea: dict, test_cap: int) -> dict:
    draft = _campaign_primary_draft(sid)
    if draft:
        draft_id = draft["id"]
    else:
        ro = campaign_readonly({"platform": "smartlead", "id": sid})
        r = save_campaign_draft({"id": f"camp-sl-{sid}",
                                 "destination": {"platform": "smartlead", "smartlead_campaign_id": sid},
                                 "name": ro.get("name") or f"Smartlead campaign {sid}"})
        draft_id = r.get("id") or f"camp-sl-{sid}"
    src_doc = {
        "type": "hiring", "mechanism": "hiring", "name": idea.get("title") or "Hiring signal idea",
        "campaign_id": draft_id, "active": True, "titles": _idea_add_default_dm_titles(idea),
        "params": {"job_titles": idea.get("job_titles") or [], "days": 30, "leads_per_day": test_cap},
        "icebreaker": ensure_hiring_vars(idea.get("icebreaker") or HIRING_ICE_DEFAULT),
    }
    r = save_draft(src_doc)
    if not r.get("ok"):
        return {"ok": False, "message": r.get("message") or "Could not create the source.", "draft_id": draft_id}
    source_id = r["id"]
    pull = pull_source({"id": source_id})
    log_activity("/api/campaign-ideas/add", {"campaign_id": sid, "idea_id": idea.get("id"),
                "mode": "existing", "source_id": source_id, "test_cap": test_cap},
                action="add_idea", entity="source", entity_id=source_id)
    return {"ok": True, "draft_id": draft_id, "source_id": source_id,
           "pull": {"ok": pull.get("ok"), "message": pull.get("message"),
                     "leads": len(pull.get("prospects") or [])}}


def _apply_idea_add_new(sid: str, idea: dict, test_cap: int) -> dict:
    draft = _campaign_primary_draft(sid)
    if not draft:
        ro = campaign_readonly({"platform": "smartlead", "id": sid})
        r = save_campaign_draft({"id": f"camp-sl-{sid}",
                                 "destination": {"platform": "smartlead", "smartlead_campaign_id": sid},
                                 "name": ro.get("name") or f"Smartlead campaign {sid}"})
        draft = {"id": r.get("id") or f"camp-sl-{sid}"}
    dup = duplicate_campaign_draft({"id": draft["id"]})
    if not dup.get("ok"):
        return {"ok": False, "message": dup.get("message") or "Could not duplicate the campaign."}
    new_draft_id = dup["id"]
    # the duplicate inherited the ORIGINAL's destination (still pointing at sid) -
    # clear it immediately so this new, unlinked draft never gets mistaken for a
    # source of the campaign it was copied from (see _campaign_draft_ids_for_sl).
    _patch_campaign_draft(new_draft_id, destination={})
    src_doc = {
        "type": "hiring", "mechanism": "hiring", "name": idea.get("title") or "Hiring signal idea",
        "campaign_id": new_draft_id, "active": True, "titles": _idea_add_default_dm_titles(idea),
        "params": {"job_titles": idea.get("job_titles") or [], "days": 30, "leads_per_day": test_cap},
        "icebreaker": ensure_hiring_vars(idea.get("icebreaker") or HIRING_ICE_DEFAULT),
    }
    r = save_draft(src_doc)
    source_id = r.get("id") if r.get("ok") else None
    god = KEYS.get("GOD_TEMPLATE_SL_ID") or os.environ.get("GOD_TEMPLATE_SL_ID")
    shell = None
    if god:
        shell = _create_smartlead_shell_from_god(god, dup.get("name") or idea.get("title") or "New campaign")
        if shell.get("ok"):
            update_campaign_draft({"id": new_draft_id,
                                   "destination": {"platform": "smartlead",
                                                    "smartlead_campaign_id": shell["smartlead_campaign_id"]}})
        else:
            _patch_campaign_draft(new_draft_id, needs_shell=True, shell_error=shell.get("message"))
    else:
        _patch_campaign_draft(new_draft_id, needs_shell=True)
    log_activity("/api/campaign-ideas/add", {"campaign_id": sid, "idea_id": idea.get("id"), "mode": "new",
                "new_draft_id": new_draft_id, "source_id": source_id, "test_cap": test_cap},
                action="add_idea", entity="campaign_draft", entity_id=new_draft_id)
    return {"ok": True, "draft_id": new_draft_id, "source_id": source_id, "shell": shell}


def _campaign_idea_add_worker(job: dict, sid: str, idea: dict, mode: str, dry_run: bool, test_cap: int):
    _job_started(job)
    try:
        plan = _idea_add_plan(sid, idea, mode, test_cap)
        if dry_run:
            job["counts"] = {"plan": plan, "dry_run": True}
            _job_finished(job, "done")
            return
        result = (_apply_idea_add_existing(sid, idea, test_cap) if mode == "existing"
                 else _apply_idea_add_new(sid, idea, test_cap))
        job["counts"] = {"plan": plan, "result": result}
        _job_finished(job, "done")
    except Exception as e:  # noqa: BLE001
        _job_finished(job, "failed", str(e)[:300])


def api_campaign_ideas_add(p: dict):
    sid = str(p.get("campaign_id") or "").strip()
    iid = str(p.get("idea_id") or "").strip()
    mode = p.get("mode")
    dry_run = bool(p.get("dry_run"))
    try:
        test_cap = max(1, min(500, int(p.get("test_cap") or 25)))
    except (TypeError, ValueError):
        test_cap = 25
    if not sid or not iid:
        return {"error": "missing_campaign_id_or_idea_id"}, 400
    if mode not in ("existing", "new"):
        return {"error": "unknown_mode", "message": 'mode must be "existing" or "new"'}, 400
    rows = sb("GET", f"campaign_idea_suggestions?id=eq.{iid}&campaign_id=eq.{sid}&limit=1")
    if not isinstance(rows, list) or not rows:
        return {"error": "idea_not_found",
               "message": "That idea was not found - it may have been dismissed, or the suggestion "
                          "table isn't available (apply migrations/tier1_idea_suggestions.sql)."}, 404
    idea = rows[0].get("idea") or {}
    with _JOB_CREATE_LOCK:
        if not dry_run and _campaign_has_active_job(sid):
            return {"error": "already_active",
                   "message": "This campaign already has a task running - wait for it to finish."}, 409
        job = _new_job("campaign_idea_add", f"Add idea to campaign: {idea.get('title') or iid}", sid,
                      mode=mode, dry_run=dry_run, max_new=test_cap)
        _enqueue_job(_campaign_idea_add_worker, job, (job, sid, idea, mode, dry_run, test_cap))
    return {"job_id": job["id"]}, 202


# ── 3. Recontact: sibling scan + eligibility buckets + draft creation ──────
_RECONTACT_NAME_STOP = {"the", "a", "an", "and", "of", "for", "to", "campaign", "email",
                        "cold", "outreach", "v1", "v2", "test", "copy"}


def _recontact_name_tokens(name: str) -> set:
    toks = re.split(r"[^a-z0-9]+", (name or "").lower())
    return {t for t in toks if t and t not in _RECONTACT_NAME_STOP and len(t) > 1}


def _recontact_resolve_sl_id(campaign_id) -> str | None:
    """Accepts a bare Smartlead numeric id, a camp-sl-<id> mirror key, or a
    cdraft-*/draft id whose destination points at Smartlead - always returns
    the bare numeric id (the key contact_history/replies/sent_messages/
    campaigns are all keyed on), or None."""
    cid = str(campaign_id or "").strip()
    if not cid:
        return None
    if cid.isdigit():
        return cid
    if cid.startswith("camp-sl-"):
        rest = cid[len("camp-sl-"):]
        return rest if rest.isdigit() else None
    drafts, _failed = _cached_campaign_drafts()
    d = next((x for x in (drafts or []) if str(x.get("id")) == cid), None)
    sl = (d or {}).get("destination", {}).get("smartlead_campaign_id")
    return str(sl) if sl else None


def _batched_in_matches(table: str, col: str, values, select: str | None = None, chunk: int = 180) -> list:
    """PostgREST `in.()` filter, chunked so a large candidate set never blows
    the URL length limit. Chunks fetch concurrently (pool of 6 - same budget
    as the scan's candidate fan-out); at 20k emails the serial version alone
    took ~40s per table, which is most of why buckets ran minutes."""
    vals = sorted({str(v) for v in values if v})
    sel = select or col
    parts = [",".join(vals[i:i + chunk]) for i in range(0, len(vals), chunk)]
    if not parts:
        return []
    def _fetch(part):
        rows = sb("GET", f"{table}?{col}=in.({part})&select={sel}")
        return rows if isinstance(rows, list) else []
    from concurrent.futures import ThreadPoolExecutor
    out = []
    with ThreadPoolExecutor(max_workers=min(6, len(parts))) as ex:
        for rows in ex.map(_fetch, parts):
            out.extend(rows)
    return out


_RECONTACT_CAP = 20000  # scan-path sample bound only - buckets reads the FULL population


def _sb_paged(query: str, cap: int | None = _RECONTACT_CAP, on_page=None) -> list:
    """Fetch rows in 1000-row pages - up to `cap`, or the WHOLE result set when
    cap is None. A single Range header does NOT work: Supabase's max-rows
    setting silently clips every request to 1000, so the old one-shot fetch
    computed verdicts on a 2% sample of big campaigns (found in the 2026-07-15
    test loop: 50,245 contacts -> 1,000 rows). on_page(rows_so_far) fires after
    every page so minutes-long reads can stream progress into a job."""
    out: list = []
    page = 1000
    while cap is None or len(out) < cap:
        lo = len(out)
        hi = (lo + page - 1) if cap is None else (min(lo + page, cap) - 1)
        rows = sb("GET", query, headers={"Range-Unit": "items", "Range": f"{lo}-{hi}"})
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        if on_page:
            on_page(len(out))
        if len(rows) < (hi - lo + 1):
            break
    return out


def _contact_history_emails(sl_id: str, cap: int = _RECONTACT_CAP) -> set:
    rows = _sb_paged(f"contact_history?smartlead_campaign_id=eq.{sl_id}&select=email", cap)
    return {(r.get("email") or "").strip().lower() for r in rows if r.get("email")}


def _recontact_resolve_target(term: str) -> tuple[str | None, dict | None]:
    """Resolve whatever the user typed - a Smartlead id, camp-sl-<id>, a draft
    id, or (the common case) a campaign NAME fragment - to (sl_id, campaign
    row). Name lookup is ilike-first, then token-overlap so multi-word input
    like "navreo influencer" still lands. ACTIVE beats finished on ties."""
    term = str(term or "").strip()
    sid = _recontact_resolve_sl_id(term)
    if sid:
        rows = sb("GET", f"campaigns?workspace=eq.{WORKSPACE_TAG}&smartlead_campaign_id=eq.{sid}"
                         "&select=smartlead_campaign_id,name,client_id,status&limit=1")
        return sid, (rows[0] if isinstance(rows, list) and rows else None)
    if len(term) < 2:
        return None, None
    from urllib.parse import quote
    sel = "smartlead_campaign_id,name,client_id,status,updated_at"
    like = quote(term.replace("*", " ").replace(",", " "))
    rows = sb("GET", f"campaigns?workspace=eq.{WORKSPACE_TAG}&name=ilike.*{like}*"
                     f"&select={sel}&order=updated_at.desc&limit=50")
    rows = rows if isinstance(rows, list) else []
    if not rows:
        toks = _recontact_name_tokens(term)
        if toks:
            allc = sb("GET", f"campaigns?workspace=eq.{WORKSPACE_TAG}&select={sel}"
                             "&order=updated_at.desc&limit=1000")
            rows = [c for c in (allc if isinstance(allc, list) else [])
                   if toks & _recontact_name_tokens(c.get("name") or "")]
    if not rows:
        return None, None
    # stable double-sort: newest first, then ACTIVE campaigns bubble to the top
    rows.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    rows.sort(key=lambda c: 0 if (c.get("status") or "").upper() == "ACTIVE" else 1)
    best = rows[0]
    return str(best.get("smartlead_campaign_id") or "") or None, best


def api_recontact_scan(campaign_id: str) -> dict:
    """Returns {"target": {...}, "siblings": [...]} - target echoes what the
    input resolved to so the page can show "Matched: <name>" (typing a name
    used to hard-fail with "campaign not found"; owner hit this 2026-07-15)."""
    sid, target = _recontact_resolve_target(campaign_id)
    if not sid:
        return {"error": f"No campaign matched \"{str(campaign_id or '').strip()}\". "
                         "Type part of the campaign's name (e.g. \"influencer\") "
                         "or paste its Smartlead id."}
    if not target:
        return {"error": "That campaign isn't in the synced campaigns table yet - "
                         "it should appear after the next daily sync."}
    tinfo = {"campaign_id": sid, "name": target.get("name"), "status": target.get("status")}
    target_tokens = _recontact_name_tokens(target.get("name") or "")
    if not target_tokens:
        return {"target": tinfo, "siblings": []}
    scope = (f"client_id=eq.{target['client_id']}" if target.get("client_id")
            else f"workspace=eq.{WORKSPACE_TAG}")
    all_camps = sb("GET", f"campaigns?{scope}&select=smartlead_campaign_id,name,status&limit=1000")
    all_camps = all_camps if isinstance(all_camps, list) else []
    # Rarity-weighted similarity. Plain token-overlap let ubiquitous naming
    # tokens ("navreo", "may", "2026") crowd out the token the user actually
    # typed: searching "Clay" surfaced 4 of the account's 16 Clay campaigns
    # (owner, live 2026-07-15). Weight = 1/df, and any campaign containing
    # every SEARCH token is guaranteed a seat regardless of rank.
    df: dict = {}
    for c in all_camps:
        for t in _recontact_name_tokens(c.get("name") or ""):
            df[t] = df.get(t, 0) + 1
    def _w(tokens) -> float:
        return sum(1.0 / df.get(t, 1) for t in tokens)
    search_tokens = {t for t in _recontact_name_tokens(str(campaign_id or ""))} \
        if not str(campaign_id or "").strip().isdigit() else set()
    scored = []
    for c in all_camps:
        csid = str(c.get("smartlead_campaign_id") or "")
        if not csid or csid == sid:
            continue
        ctoks = _recontact_name_tokens(c.get("name") or "")
        shared = target_tokens & ctoks
        term_match = bool(search_tokens) and search_tokens <= ctoks
        if not shared and not term_match:
            continue
        ratio = _w(shared) / max(1e-9, _w(target_tokens | ctoks))
        scored.append((c, csid, shared or (search_tokens & ctoks), ratio, term_match))
    scored.sort(key=lambda x: (0 if x[4] else 1, -x[3]))  # search-term matches first
    keep = scored[:20]
    # never drop a campaign that literally contains what the user typed
    keep += [s for s in scored[20:] if s[4]]
    scored = [(c, csid, shared, ratio) for c, csid, shared, ratio, _tm in keep]
    if not scored:
        return {"target": tinfo, "siblings": []}

    # finished/in_progress are EXACT counts (sb_count -> PostgREST's count
    # header, no row transfer, cheap regardless of table size - a bounded row
    # fetch here would silently undercount a campaign bigger than PostgREST's
    # own per-request row cap). overlap_count is the one genuinely bounded
    # SAMPLE (a real join would mean pulling both full email sets - fine at
    # signal_leads/source scale, too slow across whole Smartlead campaigns).
    # Candidates are independent, so all three calls per candidate run in
    # parallel across candidates too - together this is what keeps a
    # 15-candidate scan under the 10s budget (was ~23s fully serial).
    # Overlap is a RELEVANCE hint, not the safety maths (buckets does the full
    # 20k read) - so sample 3k rows per campaign. The paginated reader at full
    # cap made this 11-campaign fan-out pull 200k+ rows: the owner's "Clay"
    # scan sat 30s on a silent label (live, 2026-07-15).
    _SCAN_OVERLAP_CAP = 3000
    target_emails = _contact_history_emails(sid, cap=_SCAN_OVERLAP_CAP)

    def _count_retry(path: str) -> int:
        # sb_count has no built-in retry (unlike sb()); under this function's
        # concurrent fan-out a transient hiccup must not silently read as a
        # real zero, so retry once before accepting "unknown -> 0".
        # "estimated": these are the picker table's Finished/In-progress
        # DISPLAY columns - exact counts cost ~4s each on contact_history
        # (20 of them made the owner's "Clay" scan sit ~30s on a silent
        # label, live 2026-07-15). Buckets' safety maths stays count=exact.
        n = sb_count(path, mode="estimated")
        if n is None:
            time.sleep(0.4)
            n = sb_count(path, mode="estimated")
        return n or 0

    def _candidate_stats(item):
        c, csid, shared, _ratio = item
        finished = _count_retry(f"contact_history?smartlead_campaign_id=eq.{csid}&status=eq.COMPLETED")
        in_progress = _count_retry(
            f"contact_history?smartlead_campaign_id=eq.{csid}&status=in.(INPROGRESS,STARTED,PAUSED)")
        cand_emails = _contact_history_emails(csid, cap=_SCAN_OVERLAP_CAP) if target_emails else set()
        overlap = len(target_emails & cand_emails)
        return {"campaign_id": csid, "name": c.get("name"), "status": c.get("status"),
               "finished": finished, "in_progress": in_progress, "overlap_count": overlap,
               "match_reason": "shares \"" + "\", \"".join(sorted(shared)[:5]) + "\" in the name"}

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(scored))) as ex:
        out = list(ex.map(_candidate_stats, scored))
    return {"target": tinfo, "siblings": out}


def _recontact_verdicts(campaign_ids: list, include_repliers: bool,
                        progress=None) -> tuple[list, int, int]:
    """Every person contacted in ANY of `campaign_ids`, each with one verdict:
    suppressed > active_elsewhere > in_progress > replied > eligible - checked
    in that order so every person lands in exactly one bucket. Reads the FULL
    population: the old 20k cap left ~61% of a 51,837-contact set silently
    unadjudicated (unanimous 5-tester top issue, 2026-07-15). Adjudication runs
    in bounded passes so the join fan-out and intermediate row sets stay small
    no matter how big the set grows, and progress(done, total, stage) streams
    into the job's counts so the page can show "Reviewing contacts - 34,000 of
    51,837". Returns (verdicts, contact_rows_fetched, true_total_rows)."""
    ids_csv = ",".join(campaign_ids)
    base = f"contact_history?smartlead_campaign_id=in.({ids_csv})"

    def _note(done, total, stage):
        if progress and total:
            progress(done, total, stage)

    # exact row count up front - it anchors both fetch progress and the honest
    # coverage disclosure. sb_count has no built-in retry, so try twice.
    true_total = sb_count(base)
    if true_total is None:
        time.sleep(0.4)
        true_total = sb_count(base)
    rows = _sb_paged(base + "&select=email,company_domain,smartlead_campaign_id,status", cap=None,
                     on_page=lambda n: _note(n, max(true_total or 0, n), "Loading contact records"))
    by_email: dict = {}
    for r in rows:
        em = (r.get("email") or "").strip().lower()
        if em:
            by_email.setdefault(em, []).append(r)
    emails = list(by_email.keys())
    if not emails:
        return [], len(rows), (true_total or len(rows))

    from concurrent.futures import ThreadPoolExecutor
    out = []
    _PASS = 5000
    _note(0, len(emails), "Reviewing contacts")
    for start in range(0, len(emails), _PASS):
        batch = emails[start:start + _PASS]
        suppressed_emails = {(r.get("email") or "").strip().lower()
                             for r in _batched_in_matches("suppressions", "email", batch, "email")}
        domains = {(r.get("company_domain") or "").strip().lower() for em in batch
                  for r in by_email[em] if r.get("company_domain")}
        suppressed_domains = {(r.get("domain") or "").strip().lower()
                              for r in _batched_in_matches("suppressions", "domain", domains, "domain")}

        replied_emails = set()
        if not include_repliers:
            rrows = _batched_in_matches("replies", "email", batch, "email")
            replied_emails = {(r.get("email") or "").strip().lower() for r in rrows}

        chunks = [",".join(batch[i:i + 180]) for i in range(0, len(batch), 180)]
        def _fetch_other(chunk):
            r = sb("GET", f"contact_history?email=in.({chunk})&smartlead_campaign_id=not.in.({ids_csv})"
                          "&status=in.(INPROGRESS,STARTED,PAUSED)&select=email,smartlead_campaign_id")
            return r if isinstance(r, list) else []
        other_rows = []
        if chunks:
            with ThreadPoolExecutor(max_workers=min(6, len(chunks))) as ex:
                for r in ex.map(_fetch_other, chunks):
                    other_rows.extend(r)
        active_elsewhere: dict = {}
        for r in other_rows:
            em = (r.get("email") or "").strip().lower()
            if em and em not in active_elsewhere:
                active_elsewhere[em] = str(r.get("smartlead_campaign_id"))
        other_ids = sorted({v for v in active_elsewhere.values() if v})
        other_names = {}
        if other_ids:
            crows = sb("GET", f"campaigns?smartlead_campaign_id=in.({','.join(other_ids)})"
                              "&select=smartlead_campaign_id,name")
            if isinstance(crows, list):
                other_names = {str(r.get("smartlead_campaign_id")): r.get("name") for r in crows}

        for em in batch:
            recs = by_email[em]
            domain = next((r.get("company_domain") for r in recs if r.get("company_domain")), "") or ""
            domain = domain.strip().lower()
            if em in suppressed_emails or (domain and domain in suppressed_domains):
                verdict, other = "suppressed", None
            elif em in active_elsewhere:
                other_id = active_elsewhere[em]
                verdict, other = "active_elsewhere", other_names.get(other_id) or other_id
            elif any((r.get("status") or "") in _IN_PROGRESS_STATUSES for r in recs):
                verdict, other = "in_progress", None
            elif not include_repliers and em in replied_emails:
                verdict, other = "replied", None
            else:
                verdict, other = "eligible", None
            out.append({"email": em, "verdict": verdict, "other_campaign": other})
        _note(len(out), len(emails), "Reviewing contacts")
    return out, len(rows), (true_total or len(rows))


def _recontact_resolve_ids(p: dict) -> tuple[list, str | None]:
    raw_ids = [str(x).strip() for x in (p.get("campaign_ids") or []) if str(x).strip()]
    ids = [x for x in (_recontact_resolve_sl_id(x) for x in raw_ids) if x]
    if not ids:
        return [], ("None of the given campaign ids could be resolved to a "
                    "Smartlead campaign." if raw_ids else "campaign_ids is required")
    return ids, None


def _recontact_buckets_summary(ids: list, include_repliers: bool,
                               progress=None) -> tuple[dict, list]:
    """The full bucket computation. Runs MINUTES on big sets, so it only ever
    executes inside a background job thread - a synchronous handler here gets
    killed by Render's edge timeout and by every redeploy (both observed live
    2026-07-15: the owner's first-ever click died exactly this way)."""
    verdicts, rows_fetched, true_total = _recontact_verdicts(ids, include_repliers, progress)
    counts = {"eligible": 0, "in_progress": 0, "suppressed": 0, "replied": 0}
    active_elsewhere_counts: dict = {}
    for v in verdicts:
        if v["verdict"] == "active_elsewhere":
            key = v["other_campaign"] or "unknown campaign"
            active_elsewhere_counts[key] = active_elsewhere_counts.get(key, 0) + 1
        else:
            counts[v["verdict"]] += 1
    active_elsewhere = [{"campaign": k, "count": n}
                        for k, n in sorted(active_elsewhere_counts.items(), key=lambda x: -x[1])]
    total = len(verdicts)
    # honest-coverage disclosure: the cap is gone (verdicts read the whole
    # population), so `capped` is now only true when the paged fetch came up
    # short of the exact count (a transient mid-read break) - the note must
    # still say so rather than let a partial read masquerade as "everyone".
    true_total = true_total or rows_fetched
    summary = {"eligible": counts["eligible"], "in_progress": counts["in_progress"],
               "active_elsewhere": active_elsewhere, "suppressed": counts["suppressed"],
               "replied": counts["replied"], "total": total,
               "rows_scanned": rows_fetched, "total_contact_rows": true_total,
               "capped": true_total > rows_fetched,
               "sample": [{"email": v["email"], "verdict": v["verdict"]} for v in verdicts[:20]]}
    return summary, verdicts


# Finished buckets keep their full verdict list here so Create can reuse it
# (seconds of writes instead of re-running the minutes-long compute). Memory
# only - a redeploy between Compute and Create just means Create recomputes.
_RECONTACT_RESULTS: dict = {}
_RECONTACT_RESULTS_CAP = 8


def _recontact_stash(job_id: str, ids: list, include_repliers: bool, verdicts: list):
    _RECONTACT_RESULTS[job_id] = {"ids": sorted(ids), "include_repliers": include_repliers,
                                  "verdicts": verdicts}
    while len(_RECONTACT_RESULTS) > _RECONTACT_RESULTS_CAP:
        _RECONTACT_RESULTS.pop(next(iter(_RECONTACT_RESULTS)))


def api_recontact_buckets_start(p: dict):
    """Returns {job_id} immediately; the page polls /api/recontact/job."""
    ids, err = _recontact_resolve_ids(p)
    if err:
        return {"ok": False, "message": err}, 400
    include_repliers = bool(p.get("include_repliers"))
    run_id = str(p.get("run_id") or "")
    job = _new_job("recontact_buckets", f"Recontact buckets ({len(ids)} campaigns)", ids[0])
    def _progress(done, total, stage):
        # streamed into counts so the polling page shows live coverage
        # ("Reviewing contacts - 34,000 of 51,837") instead of a blind ticker
        with JOBS_LOCK:
            job["counts"] = {"done": done, "total": total, "stage": stage}
    def _run():
        _job_started(job)
        try:
            summary, verdicts = _recontact_buckets_summary(ids, include_repliers, _progress)
            _recontact_stash(job["id"], ids, include_repliers, verdicts)
            with JOBS_LOCK:
                job["counts"] = summary
            _job_finished(job, "done")
            if run_id:
                sb("PATCH", f"recontact_runs?id=eq.{run_id}",
                   {"payload": {"campaign_ids": ids, "include_repliers": include_repliers,
                                "buckets": summary}})
        except Exception as e:  # noqa: BLE001 - job must record ANY failure, never die silently
            _job_finished(job, "failed", f"{type(e).__name__}: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "job_id": job["id"]}, 200


def api_recontact_job(jid: str) -> dict:
    job = _job_get(jid)
    if not job:
        return {"error": "job not found (it may have been lost to an app update - run the step again)"}
    return {"status": job.get("status"), "counts": job.get("counts") or {},
           "error": job.get("error")}


def api_recontact_create_start(p: dict):
    """Returns {job_id} immediately. Reuses the buckets job's verdicts when
    still in memory; recomputes inside the job thread when not."""
    ids, err = _recontact_resolve_ids(p)
    if err:
        return {"ok": False, "message": err}, 400
    include_repliers = bool(p.get("include_repliers"))
    name = (p.get("name") or "").strip() or f"Recontact - {len(ids)} campaign(s)"
    cached = _RECONTACT_RESULTS.get(str(p.get("buckets_job_id") or ""))
    if cached and (cached["ids"] != sorted(ids) or cached["include_repliers"] != include_repliers):
        cached = None  # selection changed since the compute - never reuse stale verdicts
    run_id = str(p.get("run_id") or "")
    job = _new_job("recontact_create", f"Recontact draft: {name}"[:80], ids[0])
    def _progress(done, total, stage):
        # only fires on the recompute path (cache hit skips the whole compute)
        with JOBS_LOCK:
            job["counts"] = {"done": done, "total": total, "stage": stage}
    def _run():
        _job_started(job)
        try:
            verdicts = cached["verdicts"] if cached \
                else _recontact_buckets_summary(ids, include_repliers, _progress)[1]
            result, code = _recontact_create_draft(ids, include_repliers, name, verdicts)
            if code == 200:
                with JOBS_LOCK:
                    job["counts"] = result
                _job_finished(job, "done")
                if run_id:
                    sb("PATCH", f"recontact_runs?id=eq.{run_id}",
                       {"payload": {"campaign_ids": ids, "include_repliers": include_repliers,
                                    "created_draft_id": result.get("draft_id")}})
            else:
                _job_finished(job, "failed", result.get("message") or "create failed")
        except Exception as e:  # noqa: BLE001 - job must record ANY failure, never die silently
            _job_finished(job, "failed", f"{type(e).__name__}: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "job_id": job["id"]}, 200


def _recontact_create_draft(ids: list, include_repliers: bool, name: str, verdicts: list):
    eligible = [v["email"] for v in verdicts if v["verdict"] == "eligible"]
    if not eligible:
        return {"ok": False, "message": "No eligible people to recontact with these settings."}, 400
    # save_campaign_draft mints its own cdraft-<hex> id for non-mirror rows -
    # use the id it RETURNS everywhere below. (Passing our own id in and
    # returning it to the caller shipped a phantom: the API said one id, the
    # draft saved under another, and the source pointed at the phantom.
    # Found in the 2026-07-15 test loop.)
    r = save_campaign_draft({"name": name,
                             "recontact": {"source_campaign_ids": ids, "include_repliers": include_repliers,
                                            "eligible_count": len(eligible)}})
    if not r.get("ok"):
        return {"ok": False, "message": "Could not create the draft campaign."}, 502
    new_id = r["id"]
    src = {"type": "recontact", "mechanism": "recontact", "name": f"Recontact list ({len(eligible)})",
          "campaign_id": new_id, "active": False,
          "prospects": [{"name": None, "email": em, "company": None,
                          "linkedin": f"recontact:{em}", "icebreaker": "", "verdict": None}
                       for em in eligible]}
    src_r = save_draft(src)
    if src_r.get("ok"):
        rows = [{"source_id": src_r["id"], "full_name": None, "title": None, "company": None,
                "domain": None, "linkedin_url": f"recontact:{em}", "country": None,
                "icebreaker": "", "email": em} for em in eligible]
        # chunked: with the adjudication cap lifted, eligible can be 30k+ rows -
        # a single multi-MB POST risks the request-body limit dropping them all
        for i in range(0, len(rows), 2000):
            sb("POST", "signal_leads?on_conflict=source_id,linkedin_url", rows[i:i + 2000],
              prefer="resolution=merge-duplicates,return=minimal")
    log_activity("/api/recontact/create", {"campaign_ids": ids, "eligible": len(eligible), "draft_id": new_id},
                action="create", entity="recontact_draft", entity_id=new_id)
    return {"ok": True, "draft_id": new_id, "id": new_id, "eligible": len(eligible)}, 200


def _split_name(pr: dict) -> tuple[str, str]:
    parts = (pr.get("name") or "").strip().split(" ", 1)
    return parts[0] or ".", (parts[1] if len(parts) > 1 else ".") or "."


def find_email(pr: dict) -> str | None:
    """Verified email for a prospect — Prospeo enrich-person, cached on the
    prospect so repeat pushes are free. Name+domain first, LinkedIn fallback."""
    if pr.get("email"):
        return pr["email"]
    first, last = _split_name(pr)
    attempts = []
    if pr.get("domain"):
        attempts.append({"first_name": first, "last_name": last, "company_website": pr["domain"]})
    if pr.get("linkedin"):
        attempts.append({"linkedin_url": pr["linkedin"]})
    for data in attempts:
        r = http_json("POST", "https://api.prospeo.io/enrich-person",
                      {"X-KEY": KEYS.get("PROSPEO_API_KEY", "")},
                      {"only_verified_email": True, "data": data})
        if r.get("error"):
            if r.get("error_code") in ("INSUFFICIENT_CREDITS", "INVALID_API_KEY"):
                raise RuntimeError(f"Prospeo: {r['error_code']}")
            continue  # NO_MATCH etc -> next identifier
        person = r.get("person") or (r.get("response") or {}).get("person") or {}
        email = person.get("email")
        if isinstance(email, dict):
            email = email.get("email")
        if email:
            pr["email"] = email
            pr.pop("email_checked", None)
            return email
    pr["email_checked"] = True  # attempted, none found -> LinkedIn route is definitive
    return None


def push_to_smartlead(pr: dict, campaign_id) -> dict:
    email = find_email(pr)
    if not email:
        return {"ok": False, "message": "no verified email found for this person"}
    first, last = _split_name(pr)
    body = {"lead_list": [{
        "first_name": first, "last_name": last, "email": email,
        "company_name": pr.get("company") or "",
        "linkedin_profile": pr.get("linkedin") or "",
        "custom_fields": {"Icebreaker": pr.get("icebreaker") or "",
                          **({"WhosePost": pr["whose_post"]} if pr.get("whose_post") else {}),
                          **({"Topic": pr["topic"]} if pr.get("topic") else {})},
    }]}
    r = http_json("POST", f"{SMARTLEAD_BASE}/campaigns/{campaign_id}/leads?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}", {}, body)
    added = int(r.get("upload_count") or 0)
    dup = int(r.get("already_added_to_campaign") or 0) + int(r.get("duplicate_count") or 0)
    if added or dup:
        return {"ok": True, "message": "added" if added else "already in campaign"}
    return {"ok": False, "message": str(r.get("error") or r)[:150]}


def push_to_heyreach(pr: dict, list_id) -> dict:
    if not pr.get("linkedin"):
        return {"ok": False, "message": "no LinkedIn profile on this person"}
    first, last = _split_name(pr)  # empty lastName silent-drops on HeyReach
    lead = {"firstName": first, "lastName": last, "profileUrl": pr["linkedin"],
            "companyName": pr.get("company") or "", "position": pr.get("title") or ""}
    if pr.get("email"):
        lead["emailAddress"] = pr["email"]
    custom = [{"name": n, "value": pr[k]} for n, k in
              (("Icebreaker", "icebreaker"), ("WhosePost", "whose_post"), ("Topic", "topic")) if pr.get(k)]
    if custom:
        lead["customUserFields"] = custom
    r = heyreach("/list/AddLeadsToListV2", {"listId": int(list_id), "leads": [lead]})
    n = int(r.get("addedLeadsCount") or 0) + int(r.get("updatedLeadsCount") or 0)
    if n:
        return {"ok": True, "message": "added" if r.get("addedLeadsCount") else "already in list"}
    return {"ok": False, "message": str(r)[:150]}


def resolve_destination(src: dict, ctx_campaign_id: str | None = None) -> dict:
    """Where ✓'d people go: campaign-level destination first, source-level
    fallback. Accepts legacy {type, campaign_id} and the two-tool shape.

    `ctx_campaign_id` overrides which campaign doc's destination to read —
    needed when a source is shared by two campaigns (doc.campaign_ids) and the
    verdict is being actioned from a specific campaign's Sources tab, not the
    source's own (single) campaign_id."""
    want_cid = str(ctx_campaign_id) if ctx_campaign_id else str(src.get("campaign_id"))
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == want_cid), {})
    dest: dict = {}
    for d in ((camp.get("destination") or {}), (src.get("destination") or {})):
        if d.get("type") == "smartlead" and d.get("campaign_id"):  # legacy
            dest.setdefault("smartlead_campaign_id", d["campaign_id"])
        for k in ("smartlead_campaign_id", "heyreach_list_id", "heyreach_list_name"):
            if d.get(k):
                dest.setdefault(k, d[k])
    return dest


def is_suppressed(client_id, email, domain) -> bool:
    """Client-level suppression + prior contact history via the DB RPC. Shared by
    the hiring pull (email known early) and the push path (engagement's email is
    only known at push). Fails CLOSED — an outage suppresses rather than sends,
    so we never accidentally re-contact someone."""
    if not client_id or not (email or domain):
        return False
    try:
        rows = sb("POST", "rpc/check_exclusions",
                  {"p_client": client_id, "p_emails": [email] if email else [],
                   "p_domains": [domain] if domain else []})
        return bool(rows)
    except Exception:  # noqa: BLE001
        return True


def push_prospect(pr: dict, dest: dict, client_id=None) -> dict:
    """EXCLUSIVE routing by email (user rule 2026-07-05): if we find a verified
    email the person goes ONLY to Smartlead; if we don't, ONLY to HeyReach.
    Never both. Idempotent via pr['pushed'] stamps; both APIs upsert anyway.
    Respects client suppression / prior-contact at push time (both mechanisms)."""
    done = pr.setdefault("pushed", {})
    tools: dict = {}
    sl = dest.get("smartlead_campaign_id")
    hr = dest.get("heyreach_list_id")
    if not hr and dest.get("heyreach_list_name"):
        want = dest["heyreach_list_name"].strip().lower()
        hr = next((x["id"] for x in heyreach_lists() if (x["name"] or "").strip().lower() == want), None)

    # the email lookup decides the route
    email_error = None
    try:
        email = find_email(pr)
    except Exception as e:  # noqa: BLE001 — credits/key failure is NOT "no email"
        email, email_error = None, str(e)[:150]

    # suppression: don't burn a lead already contacted for this client (skip, don't fail)
    if not email_error and is_suppressed(client_id, email, pr.get("domain")):
        return {"ok": False, "suppressed": True,
                "tools": {"suppressed": {"ok": False, "suppressed": True,
                                         "message": "already contacted for this client - skipped"}}}

    if email_error:
        # can't know the route -> fail loudly, never mis-route to HeyReach
        tools["smartlead"] = {"ok": False, "message": f"email lookup failed: {email_error}"}
    elif email:
        if not sl and hr:
            # HeyReach-only destination (e.g. engagement/Trigify campaigns): email is
            # bonus enrichment, not a routing key — send to HeyReach directly.
            if done.get(f"heyreach:{hr}"):
                tools["heyreach"] = {"ok": True, "message": "already sent"}
            else:
                try:
                    tools["heyreach"] = push_to_heyreach(pr, hr)
                except Exception as e:  # noqa: BLE001
                    tools["heyreach"] = {"ok": False, "message": str(e)[:150]}
                if tools["heyreach"]["ok"]:
                    done[f"heyreach:{hr}"] = True
        elif not sl:
            tools["smartlead"] = {"ok": False, "message": "email found but no Smartlead campaign set"}
        elif done.get(f"smartlead:{sl}"):
            tools["smartlead"] = {"ok": True, "message": "already sent"}
        else:
            try:
                tools["smartlead"] = push_to_smartlead(pr, sl)
            except Exception as e:  # noqa: BLE001
                tools["smartlead"] = {"ok": False, "message": str(e)[:150]}
            if tools["smartlead"]["ok"]:
                done[f"smartlead:{sl}"] = True
    else:
        if not hr:
            msg = (f"list '{dest['heyreach_list_name']}' not found" if dest.get("heyreach_list_name")
                   else "no email found and no HeyReach list set")
            tools["heyreach"] = {"ok": False, "message": msg}
        elif done.get(f"heyreach:{hr}"):
            tools["heyreach"] = {"ok": True, "message": "already sent"}
        else:
            try:
                tools["heyreach"] = push_to_heyreach(pr, hr)
            except Exception as e:  # noqa: BLE001
                tools["heyreach"] = {"ok": False, "message": str(e)[:150]}
            if tools["heyreach"]["ok"]:
                done[f"heyreach:{hr}"] = True
    fails = {k: v.get("message") for k, v in tools.items() if not v.get("ok")}
    if fails:
        pr["push_fail"] = fails  # rendered on the lead row so partial sends are explained
    else:
        pr.pop("push_fail", None)
    return {"ok": bool(tools) and all(v.get("ok") for v in tools.values()), "tools": tools}


def auto_push_new_leads(src: dict) -> list:
    """Autopilot: push every un-pushed, un-rejected prospect on the source
    through the email-exclusive router. Mutates prospects (stamps + verdicts);
    the CALLER persists the drafts file. Returns evidence rows."""
    dest = resolve_destination(src)
    if not (dest.get("smartlead_campaign_id") or dest.get("heyreach_list_id") or dest.get("heyreach_list_name")):
        return []
    out = []
    for pr in (src.get("prospects") or []):
        if pr.get("pushed") or pr.get("verdict") == "reject":
            continue
        push = push_prospect(pr, dest, client_id=src.get("client_id"))
        sent = [k for k, v in push["tools"].items() if v.get("ok")]
        if sent:
            pr["verdict"] = "keep"
            pr["pushed_to"] = "+".join(
                f"smartlead:{dest.get('smartlead_campaign_id')}" if k == "smartlead"
                else f"heyreach:{dest.get('heyreach_list_id') or dest.get('heyreach_list_name')}" for k in sent)
            if pr.get("linkedin"):
                sb("PATCH", f"signal_leads?source_id=eq.{src['id']}&linkedin_url=eq.{pr['linkedin']}",
                   {"status": "pushed", "pushed_to": pr["pushed_to"]})
        elif push.get("suppressed"):
            # Excluded domain/prior contact — stamp once so we never retry this lead.
            pr["verdict"] = "reject"
            if pr.get("linkedin"):
                sb("PATCH", f"signal_leads?source_id=eq.{src['id']}&linkedin_url=eq.{pr['linkedin']}",
                   {"status": "rejected"})
        out.append({"name": pr.get("name"), "company": pr.get("company"), "email": pr.get("email"),
                    "ok": bool(sent), "tools": {k: v.get("message") for k, v in push["tools"].items()}})
    # the local `prospects` list only holds the LAST pull, so leads pulled on
    # earlier ticks (or before autopilot was switched on) strand in signal_leads
    # as status='new' and never push. Drain that backlog straight from Supabase.
    seen = set()
    for pr in (src.get("prospects") or []):
        if pr.get("linkedin"):
            seen.add(pr["linkedin"])
        if pr.get("email"):
            seen.add(str(pr["email"]).lower())
    out += _drain_backlog_leads(src, dest, seen)
    return out


def reconcile_prospects(src: dict) -> int:
    """Re-seed a source's `prospects` array from signal_leads, the authoritative
    accumulator. Returns how many leads were missing.

    For engagement sources `prospects` is meant to be cumulative (each pull
    appends), so any lead in signal_leads that isn't in the array is a lead the
    UI has silently lost — the array is a doc-wide read-modify-write, and any
    write that lands on a stale snapshot rolls it back. signal_leads can't be
    rolled back that way: it's one upsert per lead on (source_id, linkedin_url).

    Making the pull start from a reconciled array means a gap heals on the next
    tick instead of persisting forever. Idempotent: matched on linkedin_url."""
    if not src.get("id"):
        return 0
    rows = sb("GET", f"signal_leads?source_id=eq.{src['id']}"
                     "&select=full_name,title,company,domain,linkedin_url,country,"
                     "icebreaker,email,status,pushed_to&order=pulled_at.asc")
    if not isinstance(rows, list):
        return 0  # read blip — never truncate the array on a failed read
    prospects = src.get("prospects") if isinstance(src.get("prospects"), list) else []
    known = {x.get("linkedin") for x in prospects if x.get("linkedin")}
    added = 0
    for r in rows:
        lu = r.get("linkedin_url") or ""
        if not lu or lu.startswith("unknown:") or lu in known:
            continue
        pr = {"name": r.get("full_name") or "", "title": r.get("title") or "",
              "company": r.get("company") or "", "domain": r.get("domain") or "",
              "linkedin": lu, "country": r.get("country"), "email": r.get("email"),
              "icebreaker": r.get("icebreaker") or "",
              "verdict": {"pushed": "keep", "rejected": "reject"}.get(r.get("status")),
              "recovered": True}  # no post_url/topic: the event detail didn't survive
        if r.get("pushed_to"):
            pr["pushed_to"] = r["pushed_to"]
            # rebuild the per-tool stamps push_prospect() keys its idempotency on,
            # so a recovered lead is never re-pushed and renders "sent", not "Send"
            pr["pushed"] = {k: True for k in str(r["pushed_to"]).split("+") if k}
        elif r.get("status") == "pushed":
            # already contacted, but we can't say through which tool. Stamp it anyway:
            # auto_push_new_leads() skips any prospect carrying `pushed`, and a missing
            # chip is far cheaper than re-contacting someone.
            pr["pushed"] = {"unknown": True}
        prospects.append(pr)
        known.add(lu)
        added += 1
    if added:
        src["prospects"] = prospects
    return added


def _drain_backlog_leads(src: dict, dest: dict, seen: set, cap: int = 100) -> list:
    """Autopilot completeness sweep. signal_leads is the authoritative accumulator
    (it keeps every lead ever pulled; the local prospects list is only the newest
    batch). Any status='new' row here that isn't in the current pull is a stranded
    lead — push it through the same exclusive router and stamp it 'pushed' as we
    go, so progress persists even if the run is later abandoned mid-sweep. Bounded
    per call (the rest drains on the next tick); a suppressed lead is marked
    'rejected' so it leaves the pool instead of being re-attempted every tick."""
    if not (dest.get("smartlead_campaign_id") or dest.get("heyreach_list_id") or dest.get("heyreach_list_name")):
        return []
    try:
        rows = sb("GET", f"signal_leads?source_id=eq.{src['id']}&status=eq.new&limit={cap}")
    except Exception:  # noqa: BLE001 — a read blip must not kill the pull
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        lu = r.get("linkedin_url") or ""
        em = str(r.get("email") or "").lower()
        if (lu and lu in seen) or (em and em in seen):
            continue  # already handled from this pull's local prospects
        pr = {"name": r.get("full_name"), "email": r.get("email"), "company": r.get("company"),
              "title": r.get("title"), "domain": r.get("domain"),
              "linkedin": lu if lu.startswith("http") else "", "icebreaker": r.get("icebreaker")}
        push = push_prospect(pr, dest, client_id=src.get("client_id"))
        sent = [k for k, v in push["tools"].items() if v.get("ok")]
        if sent:
            pushed_to = "+".join(
                f"smartlead:{dest.get('smartlead_campaign_id')}" if k == "smartlead"
                else f"heyreach:{dest.get('heyreach_list_id') or dest.get('heyreach_list_name')}" for k in sent)
            sb("PATCH", f"signal_leads?id=eq.{r['id']}", {"status": "pushed", "pushed_to": pushed_to})
        elif push.get("suppressed"):
            sb("PATCH", f"signal_leads?id=eq.{r['id']}", {"status": "rejected"})
        out.append({"name": pr.get("name"), "company": pr.get("company"), "email": pr.get("email"),
                    "ok": bool(sent), "backlog": True,
                    "tools": {k: v.get("message") for k, v in push["tools"].items()}})
    return out


def unpush_prospect(pr: dict, dest: dict) -> dict:
    """Undo a push: remove the lead from both live tools and clear the stamps."""
    tools: dict = {}
    sl = dest.get("smartlead_campaign_id")
    if sl and pr.get("email"):
        try:
            key = KEYS.get("SMARTLEAD_API_KEY", "")
            d = http_json("GET", f"{SMARTLEAD_BASE}/campaigns/{sl}/leads?api_key={key}", {})
            lid = next(((r.get("lead") or {}).get("id") for r in (d.get("data") or [])
                        if ((r.get("lead") or {}).get("email") or "").lower() == pr["email"].lower()), None)
            if lid:
                try:
                    http_json("DELETE", f"{SMARTLEAD_BASE}/campaigns/{sl}/leads/{lid}?api_key={key}", {})
                except ValueError:
                    pass  # smartlead's delete returns literal "success", not JSON
            tools["smartlead"] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            tools["smartlead"] = {"ok": False, "message": str(e)[:150]}
    hr = dest.get("heyreach_list_id")
    if not hr and dest.get("heyreach_list_name"):
        want = dest["heyreach_list_name"].strip().lower()
        hr = next((x["id"] for x in heyreach_lists() if (x["name"] or "").strip().lower() == want), None)
    if hr and pr.get("linkedin"):
        try:
            http_json("DELETE", HEYREACH_BASE + "/list/DeleteLeadsFromListByProfileUrl",
                      {"X-API-KEY": KEYS.get("HEYREACH_API_KEY", "")},
                      {"listId": int(hr), "profileUrls": [pr["linkedin"]]})
            tools["heyreach"] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            tools["heyreach"] = {"ok": False, "message": str(e)[:150]}
    if all(v.get("ok") for v in tools.values()):
        for k in ("pushed", "pushed_to", "push_fail"):
            pr.pop(k, None)
        pr["verdict"] = None
    return {"ok": all(v.get("ok") for v in tools.values()), "tools": tools}


# ── Trigify engagement-signal ingest ─────────────────────────────────────

# camelCase keys as Trigify's http_request step sends them → engagement_events columns
TRIGIFY_FIELD_MAP = {
    "postUrl": "post_url", "postAuthorName": "post_author_name",
    "postAuthorUrl": "post_author_url", "postDatePosted": "post_date_posted",
    "postText": "post_text", "postLikes": "post_likes", "postComments": "post_comments",
    "engagementType": "engagement_type", "engagedAt": "engaged_at",
    "commentText": "comment_text", "commentPermalink": "comment_permalink",
    "commentLikes": "comment_likes",
    "engagerFirstName": "engager_first_name", "engagerLastName": "engager_last_name",
    "engagerFullName": "engager_full_name", "engagerLinkedinUrl": "engager_linkedin_url",
    "engagerUsername": "engager_username", "engagerHeadline": "engager_headline",
    "engagerJobTitle": "engager_job_title", "engagerCompanyName": "engager_company_name",
    "engagerCompanyDomain": "engager_company_domain",
    "engagerCompanyIndustry": "engager_company_industry",
    "engagerCompanyHeadCount": "engager_company_headcount",
    "engagerCompanyDescription": "engager_company_description",
    "engagerCountry": "engager_country", "engagerLocation": "engager_location",
    "engagerOpenToWork": "engager_open_to_work",
    "sourceId": "source_id", "campaignDraftId": "campaign_draft_id", "clientId": "client_id",
}
TRIGIFY_COLUMNS = set(TRIGIFY_FIELD_MAP.values())


def trigify_webhook(p: dict) -> dict:
    """Stage a Trigify engagement payload (camelCase or snake_case) in Supabase.

    Same table the Trigify workflows POST to directly; this local route exists
    for test pushes and as the relay target if the server is ever tunnelled.
    """
    row = {}
    for k, v in (p or {}).items():
        col = TRIGIFY_FIELD_MAP.get(k) or (k if k in TRIGIFY_COLUMNS else None)
        if col is not None and v is not None:
            row[col] = v
    missing = [c for c in ("source_id", "engager_linkedin_url", "post_url") if not row.get(c)]
    if missing:
        return {"ok": False, "message": f"missing required fields: {', '.join(missing)}"}
    row["raw"] = p
    res = sb("POST", "engagement_events?on_conflict=source_id,engager_linkedin_url,post_url",
             [row], prefer="resolution=ignore-duplicates,return=representation")
    if res is None:
        return {"ok": False, "message": "Supabase insert failed"}
    inserted = len(res) if isinstance(res, list) else 0
    return {"ok": True, "inserted": inserted, "duplicate": inserted == 0}


# ── GPT-5-mini engager qualification (post gate + person gate, one call) ──

QUALIFY_CACHE = Path.home() / ".navreo-cache" / "openai" / "qualify-engager"

QUALIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "post_verdict": {"type": "string", "enum": ["QUALIFIED", "DISQUALIFIED", "BORDERLINE"]},
        "person_verdict": {"type": "string", "enum": ["QUALIFIED", "DISQUALIFIED", "BORDERLINE"]},
        "topic": {"type": "string", "description": "2-5 word plain-English label for what the post is about"},
        "reason": {"type": "string", "description": "one short sentence explaining the verdicts"},
    },
    "required": ["post_verdict", "person_verdict", "topic", "reason"],
}


def _openai_qualify(event: dict, eng: dict) -> dict:
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing from ~/.navreo-keys.env")
    system = (
        "You qualify people who engaged with a LinkedIn post, for B2B outreach.\n"
        "Two independent gates:\n"
        "1. POST gate - is the post about one of the include topics (or the wildcard)? "
        "A post matching any avoid topic is DISQUALIFIED even if the engager is perfect. "
        "Personal or emotional posts are not buying signals.\n"
        "2. PERSON gate - does the engager's job title/headline match the target roles "
        "(similar seniority and function count), and do they survive the avoid rules? "
        "Job seekers, students, and obvious vendors of the same service are DISQUALIFIED.\n"
        "Use BORDERLINE only when genuinely ambiguous. Also return `topic`, a 2-5 word "
        "plain-English label for the post (used in outreach copy, so keep it natural)."
    )
    user = json.dumps({
        "post": {"author": event.get("post_author_name"), "text": (event.get("post_text") or "")[:2500]},
        "engagement": {"type": event.get("engagement_type"), "comment": event.get("comment_text")},
        "engager": {"job_title": event.get("engager_job_title"), "headline": event.get("engager_headline"),
                    "company": event.get("engager_company_name"), "industry": event.get("engager_company_industry"),
                    "company_description": event.get("engager_company_description")},
        "include_topics": eng.get("include_topics") or [],
        "wildcard": eng.get("wildcard") or "",
        "avoid_topics": eng.get("avoid_topics") or [],
        "target_roles": eng.get("engager_titles") or [],
        "avoid_rules": eng.get("avoid_rules") or "",
    })
    r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                  {"Authorization": f"Bearer {key}"},
                  {"model": "gpt-5-mini",
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": "engager_verdict", "strict": True, "schema": QUALIFY_SCHEMA}}})
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {r['error'].get('message', r['error'])[:200]}")
    return json.loads(r["choices"][0]["message"]["content"])


def qualify_engager(event: dict, cfg: dict) -> dict:
    """Verdict one engagement_events row against a source's engagement config.

    Cheap string gates (country, headcount) run first and cost zero tokens;
    survivors get ONE gpt-5-mini call covering post gate + person gate + topic.
    Returns {verdict, post_verdict, person_verdict, reason, topic, method}.
    """
    eng = (cfg or {}).get("engagement") or {}
    # string gate 1: country (Trigify sends UI labels, config stores UI labels)
    countries = cfg.get("countries") or []
    country = (event.get("engager_country") or "").strip()
    if countries and country and country not in countries:
        return {"verdict": "OFF_BRIEF", "post_verdict": None, "person_verdict": None,
                "reason": f"loc={country}", "topic": None, "method": "string-gate"}
    # string gate 2: headcount band
    hc = (str(event.get("engager_company_headcount") or "")).strip()
    nums = [int(n) for n in re.findall(r"\d+", hc)]
    if cfg.get("headcount") and nums:
        lo, hi = emp_range(cfg["headcount"])
        e_lo, e_hi = nums[0], nums[-1]
        if e_hi < lo or e_lo > hi:
            return {"verdict": "OFF_BRIEF", "post_verdict": None, "person_verdict": None,
                    "reason": f"co=size {hc}, outside {lo}-{hi}", "topic": None, "method": "string-gate"}
    # cache: same engager on the same post never gets re-judged
    import hashlib
    ck = hashlib.sha256(f"{event.get('engager_linkedin_url')}|{event.get('post_url')}".encode()).hexdigest()[:32]
    cache_file = QUALIFY_CACHE / f"{ck}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        cached["method"] = "cache"
        return cached
    v = _openai_qualify(event, eng)
    verdict = ("QUALIFIED" if v["post_verdict"] == "QUALIFIED" and v["person_verdict"] == "QUALIFIED"
               else "OFF_BRIEF" if "DISQUALIFIED" in (v["post_verdict"], v["person_verdict"])
               else "BORDERLINE")
    out = {"verdict": verdict, "post_verdict": v["post_verdict"], "person_verdict": v["person_verdict"],
           "reason": v["reason"], "topic": v["topic"], "method": "llm"}
    QUALIFY_CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(out))
    return out


# ── Trigify provisioning (duplicate-and-repoint, one search+workflow per URL) ──

BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def trigify_api(method: str, path: str, body: dict | None = None):
    key = KEYS.get("TRIGIFY_API_KEY")
    if not key:
        raise RuntimeError("TRIGIFY_API_KEY missing from ~/.navreo-keys.env")
    # Cloudflare rejects non-browser UAs with error 1010
    return http_json(method, f"https://api.trigify.io/v1{path}",
                     {"x-api-key": key, "User-Agent": BROWSER_UA}, body)


def _eng_workflow_def(src: dict, author_name: str, search_id: str) -> dict:
    """Clone of the proven 'Engagers → Make' workflow shape, with the
    http_request step repointed at Supabase PostgREST. Count/boolean refs are
    deliberately left out of the body: Trigify renders missing refs as empty
    strings, and '' fails the Postgres int/bool cast, losing the row."""
    ref = lambda p: f"{{{{ !ref($.{p}) }}}}"  # noqa: E731
    body = {
        "source_id": src["id"],
        "campaign_draft_id": str(src.get("campaign_id") or ""),
        "client_id": src.get("client_id") or "",
        "post_author_name": author_name,
        "post_url": ref("trigger.outputs.postUrl"),
        "post_date_posted": ref("trigger.outputs.datePosted"),
        "post_text": ref("trigger.outputs.text"),
        "engagement_type": "comment",
        "engaged_at": ref("steps.loop.item.createdAtString"),
        "comment_text": ref("steps.loop.item.text"),
        "comment_permalink": ref("steps.loop.item.permalink"),
        "engager_first_name": ref("steps.enrich.result.firstName"),
        "engager_last_name": ref("steps.enrich.result.lastName"),
        "engager_full_name": ref("steps.enrich.result.fullName"),
        "engager_linkedin_url": ref("steps.loop.item.author.linkedinUrl"),
        "engager_username": ref("steps.loop.item.author.username"),
        "engager_headline": ref("steps.loop.item.author.title"),
        "engager_job_title": ref("steps.enrich.result.jobTitle"),
        "engager_company_name": ref("steps.enrich.result.companyName"),
        "engager_company_domain": ref("steps.enrich.result.companyDomain"),
        "engager_company_industry": ref("steps.enrich.result.companyIndustry"),
        "engager_company_headcount": ref("steps.enrich.result.companyHeadCount"),
        "engager_company_description": ref("steps.enrich.result.companyDescription"),
        "engager_country": ref("steps.enrich.result.country"),
        "engager_location": ref("steps.enrich.result.location"),
    }
    sb_url = (f"{KEYS.get('SUPABASE_URL')}/rest/v1/engagement_events"
              "?on_conflict=source_id,engager_linkedin_url,post_url")
    sb_key = KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    return {
        "trigger": {"kind": "workflows/new-post",
                    "inputs": {"savedSearchId": search_id, "monitoringType": "linkedin-profile"}},
        "edges": [
            {"to": "getComments", "from": "$source"},
            {"to": "loop", "from": "getComments"},
            {"to": "enrich", "from": "loop", "name": "For Each Comment",
             "conditional": {"ref": "!ref($.steps.loop.isCompleted)", "type": "loop"}},
            {"to": "push", "from": "enrich"},
            # builtin:loop validates as exactly 2 outgoing edges; exports hide
            # the exit node but the create API needs it as a real action
            {"to": "_exit_done", "from": "loop", "name": "Completed",
             "conditional": {"ref": "!ref($.steps.loop.isCompleted)", "type": "completed"}},
        ],
        "actions": [
            {"id": "getComments", "kind": "linkedin_get_post_comments",
             "inputs": {"postUrl": "{{ !ref($.trigger.outputs.postUrl) }}", "maxComments": 25}},
            {"id": "loop", "kind": "builtin:loop",
             "inputs": {"collection": "{{ !ref($.steps.getComments.result.data.items) }}"}},
            {"id": "enrich", "kind": "person_enrichment",
             "inputs": {"profile": "{{ !ref($.steps.loop.item.author.linkedinUrl) }}"}},
            {"id": "push", "kind": "http_request",
             "inputs": {"method": "POST", "url": sb_url,
                        "headers": {"Content-Type": "application/json", "apikey": sb_key,
                                    "Authorization": f"Bearer {sb_key}",
                                    "Prefer": "resolution=ignore-duplicates"},
                        "body": json.dumps(body)}},
            {"id": "_exit_done", "kind": "builtin:exit", "inputs": {}},
        ],
    }


def _trigify_data(r: dict):
    if isinstance(r, dict) and r.get("success") is False:
        err = r.get("error") or {}
        det = (err.get("details") or {}) if isinstance(err, dict) else {}
        detail = json.dumps(det.get("issues") or det.get("errors") or "")[:200]
        raise RuntimeError(f"Trigify: {str(r.get('message') or r)[:200]}"
                           + (f" | {detail}" if detail and detail != '""' else ""))
    return r.get("data") if isinstance(r, dict) and "data" in r else r


def _find_profile_search(url: str) -> str | None:
    """Locate an existing linkedin-profile saved search by profile URL
    (normalised: no scheme/www, no trailing slash). Detail fetch per
    candidate because the list view omits the profile URL."""
    want = re.sub(r"^https?://(www\.)?", "", url).rstrip("/").lower()
    offset = 0
    while True:
        r = _trigify_data(trigify_api("GET", f"/searches?limit=100&offset={offset}"))
        page = r if isinstance(r, list) else (r or {}).get("items", [])
        for s in page:
            if s.get("monitoring_type") != "linkedin-profile":
                continue
            # cheap pre-filter: our own naming or a name-ish match, else fetch detail
            det = _trigify_data(trigify_api("GET", f"/searches/{s['id']}"))
            got = ((det.get("query") or {}).get("profile_url") or "").rstrip("/").lower()
            if got and re.sub(r"^https?://(www\.)?", "", got) == want:
                return s["id"]
        if len(page) < 100:
            return None
        offset += 100


def provision_engagement_source(p: dict) -> dict:
    """Create one Trigify saved search + one bound workflow per monitored URL.

    Idempotent: URLs already carrying a workflow_id are skipped. The
    search_id binding only exists at create time (PATCH strips it), so a
    rebind is always delete + recreate, never update.
    """
    drafts = read_drafts()
    src = next((d for d in drafts if d.get("id") == p.get("id")), None)
    if not src:
        return {"ok": False, "message": "Source not found"}
    eng = (src.get("config") or {}).setdefault("engagement", {})
    urls = eng.get("linkedin_urls") or []
    if not urls:
        return {"ok": False, "message": "No LinkedIn URLs on this source"}
    if not src.get("client_id"):  # resolve for the ownership chain in the POST body
        camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                     if str(c.get("id")) == str(src.get("campaign_id"))), {})
        src["client_id"] = camp.get("client_id")
    provisioned = eng.setdefault("trigify", [])
    done = {t["profile_url"] for t in provisioned if t.get("workflow_id")}
    results, errors = [], []
    for url in urls:
        if url in done:
            continue
        slug = url.rstrip("/").split("/")[-1]
        try:
            search_id = None
            try:
                s = _trigify_data(trigify_api("POST", "/searches/linkedin/profile", {
                    "name": f"Navreo Tool — {slug} ({src['id']})", "profile_url": url,
                    "frequency": "daily", "time_frame": "past-24h", "max_results": 50}))
                search_id = s.get("id") or (s.get("search") or {}).get("id")
            except RuntimeError as e:
                if "already being monitored" not in str(e):
                    raise
                # profile already has a saved search (ours or the wider fleet's):
                # adopt it - a search can drive any number of workflows
                search_id = _find_profile_search(url)
                if not search_id:
                    raise RuntimeError(f"profile monitored but its search wasn't found: {url}")
            if not search_id:
                raise RuntimeError("search created but no id in response")
            w = _trigify_data(trigify_api("POST", "/workflows", {
                "name": f"{slug} Engagers → Navreo Tool ({src['id']})",
                "description": f"Auto-provisioned for source {src['id']} (campaign {src.get('campaign_id')})",
                "workflow": _eng_workflow_def(src, slug.replace("-", " ").title(), search_id),
                "search_id": search_id, "enabled": True, "status": "PUBLISHED"}))
            workflow_id = w.get("id") or (w.get("workflow") or {}).get("id")
            entry = {"profile_url": url, "search_id": search_id, "workflow_id": workflow_id}
            provisioned.append(entry)
            results.append(entry)
        except Exception as e:  # noqa: BLE001 — provision the rest, surface the failures
            errors.append({"profile_url": url, "error": str(e)[:200]})
    write_source(src)  # only `src` changed — never rewrite the sibling sources
    sb_sync_source(src)
    return {"ok": not errors, "provisioned": results, "already": sorted(done),
            "errors": errors,
            "message": f"{len(results)} workflow(s) created, {len(done)} already live"
                       + (f", {len(errors)} failed" if errors else "")}


def _search_in_use(search_id: str, exclude_wf: str | None = None) -> bool:
    """True if any OTHER workflow is still bound to this saved search."""
    offset = 0
    while True:
        r = _trigify_data(trigify_api("GET", f"/workflows?limit=100&offset={offset}"))
        items = r.get("items", []) if isinstance(r, dict) else (r or [])
        for w in items:
            if w.get("id") != exclude_wf and w.get("social_saved_search_id") == search_id:
                return True
        if len(items) < 100:
            return False
        offset += 100


def _trigify_deprovision(entries: list, keep_urls: list | None = None) -> tuple[list, list, list]:
    """Tear down Trigify infra for monitored URLs that are going away.

    Deletes each entry's workflow (always ours). Deletes the saved search ONLY
    when we created it (the 'Navreo Tool — ' naming) AND nothing else is bound
    to it - adopted fleet searches (e.g. 'Profile: Bjion Henry') are never
    touched, other workflows may depend on them.
    Returns (kept_entries, removed_urls, errors). Failed teardowns keep their
    entry so a later remove can retry instead of orphaning live workflows.
    """
    keep = set(keep_urls or [])
    kept, removed, errors = [], [], []
    for e in entries or []:
        if e.get("profile_url") in keep:
            kept.append(e)
            continue
        try:
            # idempotent: "not found" means a previous teardown already got it
            if e.get("workflow_id"):
                try:
                    _trigify_data(trigify_api("DELETE", f"/workflows/{e['workflow_id']}"))
                except RuntimeError as ex:
                    if "not found" not in str(ex).lower():
                        raise
            sid = e.get("search_id")
            if sid:
                try:
                    det = _trigify_data(trigify_api("GET", f"/searches/{sid}"))
                    ours = str((det or {}).get("name", "")).startswith("Navreo Tool — ")
                    if ours and not _search_in_use(sid, exclude_wf=e.get("workflow_id")):
                        _trigify_data(trigify_api("DELETE", f"/searches/{sid}"))
                except RuntimeError as ex:
                    if "not found" not in str(ex).lower():
                        raise
            removed.append(e.get("profile_url"))
        except Exception as ex:  # noqa: BLE001 — keep the entry, surface, retry on next remove
            errors.append({"profile_url": e.get("profile_url"), "error": str(ex)[:150]})
            kept.append(e)
    return kept, removed, errors


def _plain_reason(reason: str, status: str) -> str:
    """String-gate shorthand → plain English; LLM reasons are already sentences."""
    if not reason:
        return "Needs a closer look" if status == "BORDERLINE" else "No reason recorded"
    m = re.match(r"^loc=(.+)$", reason)
    if m:
        return f"Outside target countries ({m.group(1)})"
    m = re.match(r"^co=size (\S+), outside (\d+)-(\d+)$", reason)
    if m:
        nums = [int(n) for n in re.findall(r"\d+", m.group(1))]
        lo = int(m.group(2))
        if nums and nums[-1] < lo:
            people = "person" if nums[-1] == 1 else "people"
            return f"Company too small ({m.group(1)} {people})"
        return f"Company too big ({m.group(1)} people)"
    return reason


def engagement_verdicts(source_id: str, verdict: str) -> dict:
    """Qualified / not-qualified engagers for one source, read from staging."""
    if not source_id:
        return {"count": 0, "rows": []}
    from urllib.parse import quote
    statuses = "QUALIFIED,PUSHED" if verdict == "qualified" else "OFF_BRIEF,BORDERLINE"
    # Fetch ALL matching engagers (paginated) and de-dup by person, so the count
    # is the true de-duped total of not-qualified prospects, not a 200-row sample.
    sel = ("&select=engager_full_name,engager_job_title,engager_company_name,"
           "engager_country,engager_linkedin_url,post_author_name,status,qualification,received_at")
    base = (f"engagement_events?source_id=eq.{quote(source_id, safe='')}"
            f"&status=in.({statuses})&order=received_at.desc{sel}")
    rows, offset = [], 0
    while True:
        page = sb("GET", base + f"&limit=1000&offset={offset}")
        if not isinstance(page, list) or not page:
            break
        rows += page
        if len(page) < 1000 or offset >= 20000:  # exhausted, or safety valve above real volume
            break
        offset += 1000
    label = {"OFF_BRIEF": "rejected", "BORDERLINE": "needs review",
             "QUALIFIED": "qualified", "PUSHED": "sent"}
    out, seen = [], set()
    for r in rows:
        # de-dup by the person (same engager across posts / re-pulls); newest row wins
        who = r.get("engager_linkedin_url") or ("nc", r.get("engager_full_name"), r.get("engager_company_name"))
        if who in seen:
            continue
        seen.add(who)
        q = r.get("qualification") or {}
        out.append({"name": r.get("engager_full_name") or "Unknown",
                    "title": r.get("engager_job_title") or "",
                    "company": r.get("engager_company_name") or "",
                    "country": r.get("engager_country") or "",
                    "post_author": r.get("post_author_name") or "",
                    "status": label.get(r.get("status"), r.get("status")),
                    "reason": _plain_reason(q.get("reason") or "", r.get("status")),
                    "method": q.get("method"), "received_at": r.get("received_at")})
    return {"count": len(out), "rows": out}


# ── engagement daily pull: staged events → qualified prospects → leads ────

ENG_ICE_REF = "Saw your comment on {{WhosePost}}'s post about {{Topic}}, and so I thought I'd reach out."
ENG_ICE_PLAIN = "Your work at {{company}} caught my eye, and so I thought I'd reach out."


# ── tool-driven engagement pull (replaces the unreliable Trigify workflow push) ──
# The saved searches reliably collect POSTS; the workflows that were meant to
# turn posts -> engagers -> Supabase almost never fire. So the tool pulls
# engagers itself on the daily run: recent posts -> /post/comments -> enrich ->
# stage into engagement_events (the same table + qualify path as before).

ENG_BACKFILL_DAYS = 15
ENG_COMMENTS_PER_POST = 30
ENG_STAGE_PER_RUN = 200  # engagers enriched+staged per source per run (credit bound)
# Trigify calls are network-bound (~2.5s each) and independent, so they run
# concurrently. Kept modest: these are someone else's rate limits, not ours.
ENG_LIST_WORKERS = 10     # saved-search listings (was 47 x 2.8s = 131s serially)
ENG_FETCH_WORKERS = 8     # /post/comments
ENG_ENRICH_WORKERS = 8    # /profile/enrich (also the credit-bound step)


def _activity_urn(post_url: str):
    # LinkedIn uses both activity:DIGITS (/feed/update/ URLs) and activity-DIGITS (/posts/ URLs)
    mm = re.search(r"activity[:\-](\d+)", post_url or "")
    return mm.group(1) if mm else None


def _clean_company_domain(url):
    if not url:
        return None
    d = str(url).lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
    return None if (not d or "linkedin.com" in d) else d


def _trigify_recent_posts(search_id: str, days: int) -> list:
    """Posts from a saved search within the last `days`, newest first."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        r = _trigify_data(trigify_api("GET", f"/searches/{search_id}/results?limit=100"))
    except Exception:  # noqa: BLE001
        return []
    items = r if isinstance(r, list) else (r.get("items") or r.get("results") or [])
    out = []
    for it in items:
        cu = (it.get("content") or {}).get("url") or ""
        urn = _activity_urn(cu)
        if not urn:
            continue
        pub = it.get("published_at") or ""
        try:
            when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            when = None
        if when and when < cutoff:
            continue
        out.append({"post_url": cu, "post_urn": urn, "published_at": pub,
                    "post_author": (it.get("author") or {}).get("name") or "",
                    "post_text": (it.get("content") or {}).get("text") or ""})
    out.sort(key=lambda p: p["published_at"], reverse=True)
    return out


def _trigify_post_engagers(post_urn: str, limit: int) -> list:
    """Commenters on one post (the engagers)."""
    try:
        r = _trigify_data(trigify_api("POST", "/post/comments", {"postUrn": post_urn, "limit": limit}))
    except Exception:  # noqa: BLE001
        return []
    items = r if isinstance(r, list) else (r.get("comments") or r.get("items") or [])
    out = []
    for c in items:
        a = c.get("author") or {}
        li = a.get("linkedinUrl") or a.get("url") or ""
        if not li or "/company/" in li:  # skip company (non-person) commenters
            continue
        out.append({"name": a.get("name") or "", "linkedin": li.rstrip("/"),
                    "headline": a.get("title") or "", "comment_text": c.get("text") or "",
                    "comment_permalink": c.get("permalink") or "",
                    "engaged_at": c.get("createdAtString") or ""})
    return out


def _trigify_enrich(profile_url: str) -> dict:
    try:
        r = _trigify_data(trigify_api("POST", "/profile/enrich", {"profileUrl": profile_url}))
        return (r.get("prospect") if isinstance(r, dict) else None) or (r if isinstance(r, dict) else {})
    except Exception:  # noqa: BLE001
        return {}


def _swept_posts(eng: dict) -> set:
    """Post URLs this source has already fetched comments for.

    A post that yielded no NEW engagers (all commenters already staged, or only
    company commenters, or no comments at all) writes no engagement_events row —
    so deriving "already processed" from engagement_events alone made us re-fetch
    its comments on every tick, forever. Measured 2026-07-08: 100-130 of ~202
    in-window posts were being re-swept every 3h on the two sources that timed
    out. The swept set is what makes a pull's cost proportional to what's NEW.

    Keyed off the resolved `engagement` dict (which `cfg` aliases by reference,
    whether it came from config or params) so we never read one copy and write
    another — writing a bare `config.engagement` when the real block lives under
    `params.engagement` would leave the source with zero saved searches."""
    return set((eng or {}).get("swept_posts") or [])


def _remember_swept(eng: dict, swept: set, window: set):
    """Record the swept set on the live engagement dict, pruned to the current
    backfill window so it can't grow without bound (posts older than
    ENG_BACKFILL_DAYS are never revisited). Caller persists the source."""
    eng["swept_posts"] = sorted(swept & window) if window else sorted(swept)


def stage_trigify_engagers(src: dict, cfg: dict, days: int = ENG_BACKFILL_DAYS,
                           per_post: int = ENG_COMMENTS_PER_POST,
                           per_run: int = ENG_STAGE_PER_RUN) -> int:
    """Pull recent-post engagers for a source and stage them as NEW
    engagement_events (deduped by post+engager). Returns the count staged.

    Three independent Trigify round-trips per layer (list searches -> fetch each
    post's comments -> enrich each engager), all network-bound and all
    independent, so each layer runs concurrently. Serially this was 131s of
    listing before the first comment fetch, which is what blew the 300s
    per-source watchdog on every tick."""
    from concurrent.futures import ThreadPoolExecutor
    # cfg is {**config, **params}, so cfg["engagement"] IS the source's own dict —
    # mutating it here is what lets the caller persist swept_posts with write_source.
    eng = cfg.get("engagement") or {}
    searches = [t.get("search_id") for t in (eng.get("trigify") or []) if t.get("search_id")]
    if not searches:
        return 0
    seen = sb("GET", f"engagement_events?source_id=eq.{src['id']}"
                     "&select=post_url,engager_linkedin_url&limit=20000") or []
    if not isinstance(seen, list):
        return 0  # a failed read would look like "nothing staged yet" and re-stage everything
    seen_pair = {(r.get("post_url"), r.get("engager_linkedin_url")) for r in seen}
    # legacy sources have no swept list yet: any post that produced an event was
    # certainly swept, so seed from there and let this run record the rest.
    swept = _swept_posts(eng) | {r.get("post_url") for r in seen if r.get("post_url")}

    # ── layer 1: list every saved search's recent posts, concurrently ──────────
    with ThreadPoolExecutor(max_workers=ENG_LIST_WORKERS) as ex:
        listings = list(ex.map(lambda s: _trigify_recent_posts(s, days), searches))
    window: dict = {}  # post_url -> post; a post can surface in more than one search
    for lst in listings:
        for p in lst:
            window.setdefault(p["post_url"], p)
    todo = sorted((p for p in window.values() if p["post_url"] not in swept),
                  key=lambda p: p["published_at"], reverse=True)  # newest first

    # ── layer 2: fetch comments, concurrently, stopping once we have enough ────
    # Only posts we actually fetch get marked swept — a run cut short by the cap
    # must leave the rest to the next tick, not silently skip them forever.
    engagers: list = []  # (post, engager)
    for i in range(0, len(todo), ENG_FETCH_WORKERS):
        if len(engagers) >= per_run:
            break
        chunk = todo[i:i + ENG_FETCH_WORKERS]
        with ThreadPoolExecutor(max_workers=ENG_FETCH_WORKERS) as ex:
            results = list(ex.map(lambda p: _trigify_post_engagers(p["post_urn"], per_post), chunk))
        for post, found in zip(chunk, results):
            if found:  # only mark swept once comments are confirmed — new posts need re-checks as comments accumulate
                swept.add(post["post_url"])
            for e in found:
                key = (post["post_url"], e["linkedin"])
                if key in seen_pair:
                    continue
                seen_pair.add(key)
                engagers.append((post, e))
    engagers = engagers[:per_run]  # the enrich cap is the credit bound

    # ── layer 3: enrich, concurrently, one call per PERSON (not per comment) ───
    urls = list({e["linkedin"] for _p, e in engagers})
    with ThreadPoolExecutor(max_workers=ENG_ENRICH_WORKERS) as ex:
        profiles = dict(zip(urls, ex.map(_trigify_enrich, urls)))

    batch = []
    for post, e in engagers:
        pr = profiles.get(e["linkedin"]) or {}
        batch.append({
            "source_id": src["id"], "campaign_draft_id": str(src.get("campaign_id") or ""),
            "client_id": src.get("client_id") or None,
            "post_url": post["post_url"], "post_author_name": post["post_author"],
            "post_text": post["post_text"], "engagement_type": "comment",
            "engaged_at": e["engaged_at"] or None, "comment_text": e["comment_text"],
            "comment_permalink": e["comment_permalink"],
            "engager_full_name": pr.get("full_name") or e["name"],
            "engager_first_name": pr.get("first_name"), "engager_last_name": pr.get("last_name"),
            "engager_linkedin_url": e["linkedin"], "engager_headline": e["headline"],
            "engager_job_title": pr.get("job_title") or e["headline"],
            "engager_company_name": pr.get("job_company_name"),
            "engager_company_domain": _clean_company_domain(pr.get("job_company_website")),
            "engager_company_industry": pr.get("industry"),
            "engager_country": pr.get("location_country"), "engager_location": pr.get("location_name"),
            "status": "NEW",
        })
    if batch:
        sb("POST", "engagement_events?on_conflict=source_id,engager_linkedin_url,post_url",
           batch, prefer="resolution=ignore-duplicates,return=minimal")
    _remember_swept(eng, swept, set(window))
    return len(batch)


def pull_engagement_source(src: dict, drafts: list) -> dict:
    """Engagement counterpart of pull_hiring_source: pull fresh engagers from
    Trigify (recent posts -> commenters -> enrich), then read NEW
    engagement_events for this source, qualify each with gpt-5-mini, keep
    QUALIFIED as prospects (engager IS the lead), write signals, leave
    BORDERLINE visible for manual review, mark everything back on staging."""
    from datetime import datetime
    cfg = {**(src.get("config") or {}), **(src.get("params") or {})}
    eng = cfg.get("engagement") or {}
    cap = int(eng.get("leads_per_day") or cfg.get("leads_per_day") or 25)
    copy_ref = eng.get("copy_reference", True)

    # Heal first, before any early return: a source with nothing new to stage still
    # needs its prospects array reconciled against signal_leads, or a gap opened by
    # a clobbered write survives every quiet tick. See reconcile_prospects().
    _recovered = reconcile_prospects(src)
    if _recovered:
        print(f"[engagement] {src['id']}: recovered {_recovered} lead(s) missing from prospects",
              file=sys.stderr)
        src["total"] = len(src.get("prospects") or [])
        write_source(src)

    # tool-driven pull: stage fresh engagers before qualifying (no reliance on
    # the Trigify workflow trigger, which barely fires)
    try:
        _staged = stage_trigify_engagers(src, cfg)
        # Persist the swept-post set NOW, not at the end of the run: qualifying can
        # still be abandoned by the watchdog, and losing the set would make the next
        # tick re-fetch every post's comments again — the exact loop being fixed.
        write_source(src)
        print(f"[engagement] {src['id']}: staged {_staged} new engager(s), "
              f"{len(_swept_posts(eng))} post(s) swept", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — a staging hiccup must not block qualifying what's already NEW
        print(f"[engagement] staging error for {src['id']}: {type(e).__name__}: {e}", file=sys.stderr)

    events = sb("GET", f"engagement_events?source_id=eq.{src['id']}&status=eq.NEW"
                       f"&order=received_at.asc&limit=1500") or []
    if not isinstance(events, list) or not events:
        return {"ok": False, "message": "No new engagers staged yet - Trigify pushes land daily once monitoring is live.",
                "total": 0, "signals": 0}

    # qualify_engager is the throughput bottleneck (one gpt-5-mini call each,
    # ~1-2s). The calls are independent, so run them concurrently, then apply the
    # verdicts serially below (keeps the daily-cap ordering + list mutation
    # single-threaded). String-gated rows cost zero tokens. A per-event failure
    # (quota/key) leaves that row NEW to retry next pull; it no longer aborts the run.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    # already reconciled against signal_leads at the top of this function, so
    # `known` covers every lead ever pulled — not just the ones that survived
    prospects = list(src.get("prospects") or [])
    known = {x.get("linkedin") for x in prospects}
    counts = {"qualified": 0, "borderline": 0, "off_brief": 0, "capped": 0, "errored": 0}
    kept_this_run = []
    # Qualify (one gpt-5-mini call each, ~3s) runs 40-wide; each verdict is
    # APPLIED the instant its future resolves, so if the per-source watchdog
    # abandons the run mid-batch, everything done so far is already committed
    # (no all-or-nothing waste). String-gated rows resolve instantly, no tokens.
    _ex = ThreadPoolExecutor(max_workers=40)
    _dbex = ThreadPoolExecutor(max_workers=24)  # status/signal writes run concurrently too — Render->Supabase latency was the real wall
    _db_futs = []
    _futs = {_ex.submit(qualify_engager, ev, cfg): ev for ev in events}
    for _fut in as_completed(_futs):
        ev = _futs[_fut]
        if counts["qualified"] >= cap:
            counts["capped"] += 1
            continue
        try:
            q = _fut.result()
        except Exception:  # noqa: BLE001 — quota/key/timeout: leave NEW, retry next pull
            counts["errored"] += 1
            continue
        status = {"QUALIFIED": "QUALIFIED", "BORDERLINE": "BORDERLINE", "OFF_BRIEF": "OFF_BRIEF"}[q["verdict"]]
        counts[q["verdict"].lower() if q["verdict"] != "OFF_BRIEF" else "off_brief"] += 1
        if q["verdict"] == "QUALIFIED" and ev.get("engager_linkedin_url") not in known:
            pr = {"name": ev.get("engager_full_name") or "", "title": ev.get("engager_job_title") or "",
                  "company": ev.get("engager_company_name") or "", "domain": ev.get("engager_company_domain") or "",
                  "linkedin": ev.get("engager_linkedin_url"), "country": ev.get("engager_country"),
                  "industry": ev.get("engager_company_industry"), "size": ev.get("engager_company_headcount"),
                  "post_url": ev.get("post_url"), "engagement_type": ev.get("engagement_type"),
                  "comment_text": ev.get("comment_text"), "verdict": None,
                  "signal_reason": q["reason"]}
            if copy_ref:
                from name_hygiene import clean_person_name
                pr["whose_post"] = clean_person_name(ev.get("post_author_name") or "")
                pr["topic"] = q.get("topic") or ""
            template = (src.get("icebreaker") or "").strip() or (ENG_ICE_REF if copy_ref else ENG_ICE_PLAIN)
            ice = fill_icebreaker(template, pr)
            ice = ice.replace("{{WhosePost}}", pr.get("whose_post") or "").replace(
                "{{Topic}}", pr.get("topic") or "")
            if not copy_ref and ("{{WhosePost}}" in template or "{{Topic}}" in template):
                ice = fill_icebreaker(ENG_ICE_PLAIN, pr)  # post-referencing template but copy_ref OFF
            from name_hygiene import email_safe
            pr["icebreaker"] = email_safe(ice)  # emoji in WhosePost/Topic can't leak through
            prospects.append(pr)
            known.add(pr["linkedin"])
            kept_this_run.append(pr)
            # Write the LEAD row immediately (per engager), not in one end-of-run
            # batch — an abandoned/killed run must still persist the leads it
            # qualified. on_conflict makes the (dropped) end batch idempotent.
            _db_futs.append(_dbex.submit(
                sb, "POST", "signal_leads?on_conflict=source_id,linkedin_url",
                # no "status": merge-duplicates would reset an already-pushed lead to
                # new and the next autopilot tick would re-contact them. Insert default
                # is 'new'; on update, only the pusher may change status/pushed_to.
                [{"source_id": src["id"], "full_name": pr.get("name"), "title": pr.get("title"),
                  "company": pr.get("company"), "domain": pr.get("domain"),
                  "linkedin_url": pr.get("linkedin"), "country": pr.get("country"),
                  "icebreaker": pr.get("icebreaker"), "email": pr.get("email")}],
                "resolution=merge-duplicates,return=minimal"))
            _db_futs.append(_dbex.submit(sb, "POST", "signals", {
                "signal_type": "engagement", "source": "trigify",
                "company_domain": None,  # engager IS the lead; company row may not exist
                "detected_at": ev.get("engaged_at") or ev.get("received_at"),
                "detail": {"post_url": ev.get("post_url"), "post_author": ev.get("post_author_name"),
                           "topic": q.get("topic"), "engager": ev.get("engager_linkedin_url"),
                           "source_id": src["id"]},
            }, "resolution=ignore-duplicates,return=minimal"))
        _db_futs.append(_dbex.submit(
            sb, "PATCH", f"engagement_events?id=eq.{ev['id']}",
            {"status": status, "qualification": {k: q[k] for k in
             ("verdict", "post_verdict", "person_verdict", "reason", "topic", "method")}}))

    for _f in _db_futs:  # let every status/signal write land before finishing the source
        try:
            _f.result()
        except Exception:  # noqa: BLE001
            pass
    _ex.shutdown(wait=False)
    _dbex.shutdown(wait=False)
    src["prospects"] = prospects
    src["total"] = len(prospects)
    src["signals_found"] = counts["qualified"]
    # analogous to hiring's companies_scanned/left_for_next_run (S5): engagers
    # scanned this pull, and anything queued past today's cap for next time.
    src["companies_scanned"] = len(events)
    src["left_for_next_run"] = counts.get("capped") or 0
    src["mechanism"] = "engagement"
    src["last_pull"] = datetime.now().isoformat(timespec="seconds")
    write_source(src)
    sb_sync_source(src)

    # signal_leads are now written per-engager inside the loop above (survives an
    # abandoned run), so no end-of-run batch is needed here.
    sb("PATCH", f"signal_sources?id=eq.{src['id']}", {"last_pull_at": src["last_pull"]})

    # autopilot campaigns push immediately; manual campaigns leave ✓ to the user
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(src.get("campaign_id"))), {})
    pushed = auto_push_new_leads(src) if camp.get("autopilot") else []
    if pushed:
        write_source(src)
        for ev_pr in (src.get("prospects") or []):
            if ev_pr.get("pushed_to") and ev_pr.get("linkedin"):
                from urllib.parse import quote
                sb("PATCH", f"engagement_events?source_id=eq.{src['id']}"
                            f"&engager_linkedin_url=eq.{quote(ev_pr['linkedin'], safe='')}",
                   {"status": "PUSHED"})

    tail = (f" · {counts['borderline']} borderline await your review" if counts["borderline"] else "") + \
           (f" · {counts['capped']} over the daily cap, queued" if counts["capped"] else "")
    return {"ok": True, "total": len(events), "signals": counts["qualified"],
            "prospects": prospects, "db_synced": True, "pushed": pushed,
            "note": f"{len(events)} engagers scanned, {counts['qualified']} qualified, "
                    f"{counts['off_brief']} off-brief{tail}"}


def fill_icebreaker(template: str, prospect: dict) -> str:
    from name_hygiene import clean_company_name, clean_person_name, email_safe
    out = template or ""
    company = clean_company_name(prospect.get("company") or "") or "their company"
    first_name = clean_person_name(prospect.get("name") or "").split(" ")[0]
    # the hiring role the company is advertising - filled per prospect so every
    # email names that company's real role, not a baked-in one (aliases cover
    # whichever token the AI / a hand-edited opener used)
    role = str(prospect.get("role") or prospect.get("hiring_for") or "").strip()
    reps = {"company": company, "first_name": first_name,
            "job_title": role, "jobtitle": role, "role": role}
    # engagement openers reference the post the lead commented on - fill
    # {{WhosePost}}/{{Topic}} here too (not only in the pull) so a hand-edited
    # opener renders them on Save. Only when present, so a prospect without the
    # data keeps the raw token rather than emitting "post about ." - the pull's
    # copy_reference-off path still swaps in the plain template.
    whose = str(prospect.get("whose_post") or "").strip()
    topic = str(prospect.get("topic") or "").strip()
    if whose:
        reps["WhosePost"] = whose  # proper noun - keep its own case
    if topic:
        from name_hygiene import fit_merge_case  # case Topic to fit its slot
        reps["Topic"] = fit_merge_case(topic, template, "Topic")
    for k, v in reps.items():
        out = out.replace("{{" + k + "}}", v).replace("{" + k + "}", v)
    return email_safe(out)  # last line of defence: no special char can survive


# ── TheirStack credit control ────────────────────────────────────────────
# TheirStack bills 1 credit per JOB RETURNED, and RE-CHARGES for a job you have
# already downloaded (theirstack.com/en/docs/pricing/credits). A pull that
# re-scans the same `posted_at_max_age_days` window every tick therefore pays
# full price for the same rows forever, and the dedupe further down (`already`)
# throws them away for free — which is exactly how ~12k credits/day bought ~350
# companies on 2026-07-07. Two defences, belt and braces:
#   1. cursor: `discovered_at_gte` + `job_id_not`, so a tick only pays for jobs
#      TheirStack discovered since the last successful pull of THIS source.
#   2. meter: every call's cost is written to provider_usage, so spend is visible
#      per source per day instead of silent.
#
# There is deliberately NO daily credit ceiling by default. Spend is governed by
# the LEAD budget (SIGNAL_DAILY_LEADS, split across active sources): a pull stops
# paging the moment its share of today's leads is in, so credits track leads. A
# credit ceiling on top of that would only ever truncate a source mid-window for
# reasons the operator never asked for. Set THEIRSTACK_DAILY_CAP > 0 to arm it as
# an emergency brake — e.g. while debugging a suspected runaway.
THEIRSTACK_DAILY_CAP = int(os.environ.get("THEIRSTACK_DAILY_CAP", "0"))  # 0 = off
# Ceiling on jobs ONE pull may buy. The real governor is the source's leads_per_day
# (we stop paging the moment the day's leads are in); this is the runaway backstop
# for a source whose window is huge and whose companies rarely yield a DM.
THEIRSTACK_JOBS_PER_PULL = int(os.environ.get("THEIRSTACK_JOBS_PER_PULL", "1000"))
# THE governor. Total new leads per DAY across every active hiring source, split
# evenly between them. Self-adjusting: add a 5th source and each gets a fifth.
# A source may override with its own `leads_per_day`; unset means "take an even
# share". Credits follow leads at roughly 2.35 credits per lead.
SIGNAL_DAILY_LEADS = int(os.environ.get("SIGNAL_DAILY_LEADS", "400"))
# Companies enriched per lead, worst case. AI-ARK/Prospeo bill per person; measured
# yield is ~45% of companies producing a verified-email DM, so ~2 companies per lead.
COMPANIES_PER_LEAD_HEADROOM = int(os.environ.get("SIGNAL_COMPANIES_PER_LEAD", "4"))


def theirstack_credits_today() -> int | None:
    """Credits billed by TheirStack since 00:00 UTC. None when Supabase can't be
    read — an unknown spend must never hard-block the pull."""
    from datetime import datetime, timezone
    midnight = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    rows = sb("GET", f"provider_usage?provider=eq.theirstack&called_at=gte.{midnight}"
                     f"&select=credits")
    if not isinstance(rows, list):
        return None
    return sum(int(r.get("credits") or 0) for r in rows if isinstance(r, dict))


def _theirstack_meter(source_id, credits: int) -> None:
    """Record what a call actually cost. Never raises — metering must not be able
    to fail a pull that already happened."""
    try:
        sb("POST", "provider_usage", {"provider": "theirstack", "source_id": source_id,
                                      "credits": int(credits), "endpoint": "/v1/jobs/search"},
           prefer="return=minimal")
    except Exception:  # noqa: BLE001
        pass


def _parse_iso(s) -> "object | None":
    """TheirStack stamps `discovered_at` as '2026-07-08T05:51:32.664000' — sometimes
    with a trailing Z, sometimes without. Parse to an aware UTC datetime, or None."""
    from datetime import datetime, timezone
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _discovered_watermark(raw: list) -> tuple[str | None, list]:
    """Newest `discovered_at` in a RAW (unfiltered) response, plus the ids sitting
    exactly on it. Computed before client-side filtering on purpose: a page whose
    every job is dropped by KILL/negatives must still advance the cursor, or the
    next tick re-buys the same rows forever."""
    stamps = [(j.get("discovered_at") or "") for j in raw]
    top = max((s for s in stamps if s), default=None)
    if not top:
        return None, []
    ids = [j["id"] for j in raw if j.get("discovered_at") == top and j.get("id") is not None]
    return top, ids


def theirstack_jobs(job_titles, codes, min_emp, max_emp, days, limit=25, extra=None,
                    negatives=None, source_id=None, cap=True):
    """Unblurred TheirStack jobs search — real companies + domains (costs
    credits, so callers bound `limit`). Returns (jobs, metadata).
    `negatives`: keywords that must NOT appear in the post title/description —
    also enforced client-side because API-side pattern filters can miss.
    Billing: 1 credit per job returned, re-charged on every re-fetch — pass a
    `discovered_at_gte` cursor via `extra` (see pull_hiring_source) so a repeat
    tick pays only for genuinely new posts. Every call is metered, and the day's
    spend is capped by THEIRSTACK_DAILY_CAP unless `cap=False`."""
    if cap and THEIRSTACK_DAILY_CAP > 0:   # 0 = brake not armed; leads govern spend
        spent = theirstack_credits_today()
        if spent is not None and spent >= THEIRSTACK_DAILY_CAP:
            return [], {"_error": f"TheirStack daily credit cap reached "
                                  f"({spent}/{THEIRSTACK_DAILY_CAP}). No jobs were fetched. "
                                  f"Raise THEIRSTACK_DAILY_CAP if this is expected.",
                        "_capped": True, "_credits": 0}
    body = {
        "posted_at_max_age_days": int(days or 30),
        "job_title_or": job_titles or [],
        "job_country_code_or": codes or ["US"],
        "min_employee_count": int(min_emp or 11),
        "max_employee_count": int(max_emp or 500),
        "company_type": "direct_employer",
        "blur_company_data": False,
        "limit": int(limit),
        "include_total_results": True,
    }
    body.update(extra or {})
    # INVARIANT, set after the merge so a stray `extra` key can never relax it: we only
    # ever want the company that is actually hiring, never a job board, staffing agency
    # or aggregator reposting the ad.
    body["company_type"] = "direct_employer"
    if body.get("discovered_at_gte"):
        # cursor forward, oldest-new-job first, so a full page never strands the
        # jobs behind it: the next tick resumes from this page's newest stamp.
        body["order_by"] = [{"field": "discovered_at", "desc": False}]
    data = http_json("POST", "https://api.theirstack.com/v1/jobs/search",
                     {"Authorization": f"Bearer {KEYS['THEIRSTACK_API_KEY']}"}, body)
    raw = data.get("data") or []
    if raw:  # a job returned is a credit spent, whatever we do with it afterwards
        _theirstack_meter(source_id, len(raw))
    meta = data.get("metadata") or {}
    meta["_credits"] = len(raw)
    meta["_max_discovered_at"], meta["_max_discovered_ids"] = _discovered_watermark(raw)
    # a genuine zero-result carries "data": [] + a metadata block. An error body
    # (validation / auth / rate-limit) carries neither — don't read it as "0 jobs".
    if "data" not in data:
        detail = data.get("detail") or data.get("error") or data.get("message") or data
        if isinstance(detail, list):  # FastAPI-style [{"loc":..,"msg":..}]
            detail = "; ".join(str(d.get("msg") or d) for d in detail)
        meta = {**meta, "_error": str(detail)[:300]}
    jobs = []
    KILL = ("staffing", "talent", "recruit", "consultants")  # empty descriptions dodge pattern_not
    negs = [str(n).strip().lower() for n in (negatives or []) if str(n).strip()]
    for j in raw:
        co = j.get("company_object") or {}
        domain = canon_domain(co.get("domain") or j.get("company_domain") or "")
        if not domain:
            continue
        blob = (str(co.get("name") or "") + " " + str(co.get("industry") or "")).lower()
        if any(k in blob for k in KILL):
            continue
        if negs:
            post = (str(j.get("job_title") or "") + " " + str(j.get("description") or "")).lower()
            if any(n in post for n in negs):
                continue
        jobs.append({
            "domain": domain,
            "company": co.get("name") or j.get("company") or "",
            "job_title": j.get("job_title") or "",
            "job_url": j.get("url") or j.get("source_url") or "",
            "date_posted": (j.get("date_posted") or "")[:10],
            "country": j.get("country_code") or co.get("country_code") or "",
            "industry": co.get("industry") or "",
            "description": (co.get("long_description") or co.get("seo_description") or "")[:220],
            "employee_count": co.get("employee_count") if isinstance(co.get("employee_count"), int) else None,
            "employee_range": co.get("employee_count_range") or "",
        })
    return jobs, meta


# ── AI-ARK: DM counts (previews) + DM finder (pulls) ─────────────────────
# Role split (user rule 2026-07-05): Prospeo/TheirStack identify COMPANIES;
# AI-ARK identifies the DECISION MAKERS at them (better people coverage).
# AI-ARK bills PER PERSON RETURNED: every call caps `size` deliberately, and
# counts use the size:1 -> totalElements pattern (≈1 person per count).

# Preview sizing: decision-makers KEPT per hiring company. No longer a flat guess —
# dms_per_company() derives it from real kept-lead history (verified-email leads ÷
# companies actually signalled), because a flat 1.6 overstated the reachable count
# (the AI-ARK candidates it implies get thinned by Prospeo's verified-email keep-gate
# and suppression; real blended rate ≈1.3, and swings 0.7–3.1 by profile). The constant
# below is only the conservative fallback for a brand-new profile with no history yet.
DMS_PER_COMPANY = 1.2      # no-history default (was a flat 1.6; measured blend ≈1.3)
_DMS_MIN_COMPANIES = 12    # trust a derived rate only past this much history
_DMS_BAND = (0.5, 3.0)     # clamp so one lopsided profile can't distort a preview
_dms_cache: dict = {}      # {source_id | "*": (rate, expires_epoch)} — 10-min memo


def _sb_count(path: str) -> int | None:
    """Exact row count via PostgREST select=count. None on any Supabase hiccup."""
    r = sb("GET", f"{path}&select=count")
    if isinstance(r, list) and r and isinstance(r[0], dict) and r[0].get("count") is not None:
        return int(r[0]["count"])
    return None


def _dms_rate_from_history(source_id: str | None) -> float | None:
    """Empirical kept-DMs-per-company = verified-email leads ÷ companies signalled,
    scoped to one hiring source or (source_id=None) blended across the whole fleet.
    None when there isn't enough history to trust yet."""
    if source_id:
        comps = _sb_count(f"signals?source=eq.theirstack&detail->>source_id=eq.{source_id}")
        leads = _sb_count(f"signal_leads?source_id=eq.{source_id}")
    else:
        ids = [d["id"] for d in read_drafts()
               if (d.get("mechanism") or d.get("type")) == "hiring" and not d.get("deleted_at")]
        if not ids:
            return None
        inlist = ",".join(ids)
        comps = _sb_count(f"signals?source=eq.theirstack&detail->>source_id=in.({inlist})")
        leads = _sb_count(f"signal_leads?source_id=in.({inlist})")
    if not comps or comps < _DMS_MIN_COMPANIES or leads is None:
        return None
    return leads / comps


def dms_per_company(source_id: str | None = None) -> float:
    """Decision-makers kept per hiring company, for preview sizing. Self-calibrating:
    prefers THIS source's real history, falls back to the fleet-wide blend, then to a
    conservative constant for a brand-new profile. Cached 10 min; clamped to a sane band."""
    import time
    key = source_id or "*"
    hit = _dms_cache.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    rate = _dms_rate_from_history(source_id) if source_id else None
    if rate is None:
        rate = _dms_rate_from_history(None)   # fleet-wide blend
    if rate is None:
        rate = DMS_PER_COMPANY                # no history anywhere yet
    rate = max(_DMS_BAND[0], min(_DMS_BAND[1], rate))
    _dms_cache[key] = (rate, time.time() + 600)
    return rate

AIARK_BASE = "https://api.ai-ark.com/api/developer-portal"


def aiark(body: dict):
    # Cloudflare 1010-blocks the default python UA on this host - send a browser one
    return http_json("POST", f"{AIARK_BASE}/v1/people",
                     {"X-TOKEN": KEYS.get("AI_ARK_API_KEY", ""),
                      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}, body)

def _aiark_person_row(x: dict) -> dict:
    """One AI-ARK /v1/people record -> the same shape the Prospeo path emits
    (_person_rows + provider). Email is absent from AI-ARK people results, so it
    stays None and the pull's find_email() keep-gate fills it."""
    prof = x.get("profile") or {}
    link = x.get("link") or {}
    loc = x.get("location") or {}
    comp = x.get("company") or {}
    csum = comp.get("summary") or {}
    clink = comp.get("link") or {}
    staff = csum.get("staff") if isinstance(csum.get("staff"), dict) else {}
    name = (prof.get("full_name")
            or f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip())
    return {
        "name": name,
        "title": prof.get("title") or prof.get("headline") or "",
        "company": csum.get("name") or "",
        "domain": clink.get("domain") or clink.get("domain_ltd") or "",
        "size": (staff or {}).get("total") or (staff or {}).get("count") or "",
        "industry": x.get("industry") or csum.get("industry") or "",
        "country": loc.get("country") or "",
        "linkedin": link.get("linkedin") or "",
        "email": prof.get("email") or x.get("email") or None,
        "named_account": False,
        "provider": "aiark",
    }


def aiark_dms_by_domain(domain, dm_titles, cap) -> list:
    """The pull-path DM finder: people at ONE company domain, title-tightened
    (cost warning: broad seniority alone bills for off-function heads)."""
    body = {"page": 0, "size": max(1, min(int(cap or 2), 5)),
            "account": {"domain": {"any": {"include": [canon_domain(domain)]}}},
            # decision-makers are Director-and-above by DEFAULT: the seniority
            # floor is ANDed with the title net so a junior sharing title words
            # (an SDR under "Head of Sales") never comes back.
            "contact": {"seniority": {"any": {"include": AIARK_LEADER_SENIORITY}},
                        "experience": {"current": {"title": {"any": {"include": {"mode": "SMART", "content": list(dm_titles or [])}}}}}}}
    if not dm_titles:  # tight leadership net, never unbounded
        body["contact"] = {"seniority": {"any": {"include": AIARK_LEADER_SENIORITY}}}
    r = aiark(body)
    rows = (r.get("content") or []) if isinstance(r, dict) else []
    out = []
    for x in rows:
        p = _aiark_person_row(x)
        if p["name"] and (p["linkedin"] or p["email"]) and _title_on_brief(p.get("title"), dm_titles):
            p.setdefault("domain", canon_domain(domain))
            out.append(p)
    return out


# a LEADER rank word — mid-level "manager"/"lead" deliberately excluded so a
# functional brief ("Sales Director") never passes an Account Manager / Team Lead.
_SENIORITY_WORDS = re.compile(
    r"\b(head|vp|svp|evp|avp|vice president|director|chief|c[oetifms]o|president|"
    r"founder|owner|partner|managing)\b", re.I)
_TITLE_STOP = {"of", "the", "and", "&", "for", "senior", "sr", "jr", "a", "to", "at", "on"}
# role/seniority words that are NOT a business function. Two titles that share
# ONLY these are not the same job ("Sales Director" vs "Marketing Director",
# "General Manager" vs "Customer Success Manager"), so they're stripped before
# the function-overlap test and the match must rest on a real function word.
_GENERIC_ROLE = {
    "director", "manager", "head", "vp", "svp", "evp", "avp", "vice", "president",
    "officer", "chief", "lead", "leader", "owner", "co", "cofounder", "founder",
    "partner", "general", "executive", "exec", "md", "gm", "board", "member",
    "managing", "global", "regional", "national", "interim", "deputy", "assistant",
    "group", "team", "staff", "principal",
}
# genuine top-of-company markers (multilingual — the pull spans US/UK/NL/CA/AU/DE/PL)
_TOP_EXEC = re.compile(
    r"\b(ceo|chief executive|founder|co-?founder|(?<!vice[ -])president|"
    r"managing director|gesch[aä]ftsf[uü]hrer|gr[uü]nder|prezes|"
    r"directeur g[eé]n[eé]ral|inhaber|eigenaar|proprietor|amministratore|owner)\b",
    re.I)


# Seniority FLOOR — decision-makers are Director-and-above by default. These
# enums are ANDed into every DM query so the provider only returns leaders, and
# _is_director_plus() is the local backstop. Below the floor: manager, lead,
# specialist, coordinator, associate, IC "executive"/"representative".
AIARK_LEADER_SENIORITY = ["founder", "owner", "c_suite", "partner", "vp", "head", "director"]
PROSPEO_LEADER_SENIORITY = ["Founder/Owner", "C-Suite", "Partner", "Vice President", "Head", "Director"]


def _sig_words(s) -> set:
    return set(re.findall(r"[a-z]+", str(s).lower())) - _TITLE_STOP


# unambiguous Director-and-above rank words. Deliberately NO bare "owner"/
# "partner" (they'd pass "Product Owner"/"Partner Manager"); bare-owner is
# handled correctly by _is_top_exec, which rejects a function-qualified owner.
_DIRECTOR_RANK = re.compile(
    r"\b(head|vp|svp|evp|avp|vice president|director|chief|c[oetifms]o|"
    r"president|managing director)\b", re.I)


def _is_director_plus(title) -> bool:
    """Local seniority floor: Director-and-above. True for a leader rank
    (director/VP/head/chief/president/MD) or a genuine multilingual top-exec
    (Geschäftsführer, Prezes, bare Owner). Mid-level 'Manager'/'Lead'/IC
    'Executive'/'Product Owner'/'Partner Manager' fall through to False."""
    return _is_top_exec(title) or bool(_DIRECTOR_RANK.search(str(title or "")))


def _is_top_exec(title) -> bool:
    """Top-of-company only: a named C-suite/founder/president/MD (any language),
    or a BARE owner ('Owner', 'Co-Owner') — but NOT a functional 'X Owner'
    ('Product Owner', 'Process Owner', 'Account Owner' are individual contributors)."""
    if not _TOP_EXEC.search(str(title)):
        return False
    toks = _sig_words(title)
    if toks & {"owner", "proprietor", "eigenaar", "inhaber"} and not _TOP_EXEC.search(
            re.sub(r"\b(owner|proprietor|eigenaar|inhaber)\b", "", str(title), flags=re.I)):
        # the only exec marker is a bare-owner word — reject if it's qualified by
        # a function ('Product Owner' -> {product} remains after dropping role words)
        return not (toks - _GENERIC_ROLE)
    return True


def _title_on_brief(title, dm_titles) -> bool:
    """Local precision gate. Provider title search is fuzzy (AND-of-words, any
    order) and the seniority-net fallback returns any exec, so this decides on
    the brief: a FUNCTIONAL brief ('Sales Director') needs the person to share
    the function AND hold a leader rank; a TOP-EXEC brief ('CEO','Founder')
    matches only genuine top-of-company people, never any senior colleague who
    happens to share a role word ('Managing Director' != 'Marketing Director')."""
    if not dm_titles or not title:
        return True  # seniority-net mode already scoped server-side
    t_func = _sig_words(title) - _GENERIC_ROLE
    senior = bool(_SENIORITY_WORDS.search(str(title)))
    for dm in dm_titles:
        d_func = _sig_words(dm) - _GENERIC_ROLE
        if d_func:  # functional brief — share the function, hold a leader rank
            if senior and len(d_func & t_func) / len(d_func) >= 0.6:
                return True
        elif _is_top_exec(title):  # pure top-of-company brief
            return True
    return False


def dm_find_by_domain(domain, dm_titles, max_dms):
    """DM finder for one company: AI-ARK first (user rule 2026-07-05 - better
    people coverage; emails verified at source), Prospeo as the error/empty
    fallback so a provider outage never blanks a pull. Never both billed for
    the same company in one call."""
    try:
        people = aiark_dms_by_domain(domain, dm_titles, max_dms)
        people = [p for p in people if _is_director_plus(p.get("title"))]
        if people:
            return people[:max_dms]
    except Exception as e:  # noqa: BLE001 — fall through to Prospeo, but SAY SO
        # a silent pass here hid a missing-parser NameError for weeks: every
        # AI-ARK call "failed" and Prospeo quietly did 100% of the work.
        print(f"[aiark] {domain} fell back to Prospeo: {type(e).__name__}: {e}",
              file=sys.stderr)
    # local Director-and-above backstop (default), even if a provider's own
    # seniority classification lets a mid-level title slip through
    return [p for p in _prospeo_dms_by_domain(domain, dm_titles, max_dms)
            if _is_director_plus(p.get("title"))]


def _prospeo_dms_by_domain(domain, dm_titles, max_dms):
    """Prospeo /search-person scoped to one company domain. Titles first,
    leadership-seniority net as fallback (domain-scoped exact-title matching is
    weak — mirrors the named-account path in preview_people)."""
    people = []
    if dm_titles:
        d = _search_person({
            "person_job_title": {"include": dm_titles, "include_partial_match": True},
            # Director-and-above floor ANDed with the title net (default)
            "person_seniority": {"include": PROSPEO_LEADER_SENIORITY},
            "company": {"websites": {"include": [domain]}},
        })
        if not d.get("error"):
            people = _person_rows(d, max_dms)
    if not people:
        d = _search_person({
            "person_seniority": {"include": PROSPEO_LEADER_SENIORITY},
            "company": {"websites": {"include": [domain]}},
        })
        if not d.get("error"):
            net = _person_rows(d, max_dms * 3)  # scan wider, then gate to the brief
            # the seniority net returns ANY exec at the company. With a stated DM
            # brief that would backfill off-function leaders (a CIO / Head of
            # Product / HR VP for a 'Sales Leaders' signal), so keep only titles
            # that actually match the brief. No brief => any leader is fine.
            people = [p for p in net if _title_on_brief(p.get("title"), dm_titles)] if dm_titles else net
    for x in people:
        x["provider"] = "prospeo"
    return people[:max_dms]


def _daily_lead_share(src: dict, drafts: list) -> int:
    """This source's slice of the fleet-wide daily lead budget.

    SIGNAL_DAILY_LEADS is a TOTAL across every active hiring source, divided evenly,
    so adding a source narrows everyone's share rather than multiplying the bill.

    A source's own `leads_per_day` can only ask for LESS than its share, never more.
    The even split is the ceiling: it is the thing the operator actually set, and it
    is enforced in code rather than in the source docs because the running app
    rewrites those docs from its own copy (an out-of-band edit does not survive)."""
    active = [d for d in drafts
              if (d.get("mechanism") or d.get("type")) == "hiring"
              and d.get("active", True) and not d.get("deleted_at")]
    share = max(1, SIGNAL_DAILY_LEADS // max(1, len(active) or 1))
    cfg = {**(src.get("config") or {}), **(src.get("params") or {})}
    try:
        want = int(cfg.get("leads_per_day") or 0)
    except (TypeError, ValueError):
        want = 0
    return max(1, min(share, want)) if want > 0 else share


THEIRSTACK_EXCLUDE_MAX = int(os.environ.get("THEIRSTACK_EXCLUDE_MAX", "200000"))
# Fold the client's suppression + prior-contact domains into the SEARCH body too.
# Off by user instruction (2026-07-08): it is a pure cost optimisation — those domains
# are still rejected per-lead by lead_excluded(), so this flag cannot change who is
# contacted, only how many jobs we pay TheirStack for before rejecting them.
THEIRSTACK_EXCLUDE_SUPPRESSED = os.environ.get("THEIRSTACK_EXCLUDE_SUPPRESSED", "0") == "1"
_excl_cache: dict = {}   # {client_id: (domains, expires_epoch)} — 30-min memo


def _exclusion_domains(client_id: str | None) -> list:
    """Every domain this client would reject anyway: prior contact (contact_history)
    plus suppression lists, exactly what `lead_excluded` already enforces — but
    row-by-row, AFTER we have paid TheirStack for the job and paid AI-ARK/Prospeo to
    enrich the company. One RPC (~5MB, ~8s for 290k domains) instead of 290 paged
    PostgREST reads. Memoised: the list moves slowly, the pull runs every 3 hours."""
    import time as _t
    key = client_id or "*"
    hit = _excl_cache.get(key)
    if hit and hit[1] > _t.time():
        return hit[0]
    try:
        rows = sb("POST", "rpc/exclusion_domains", {"p_client": client_id})
    except Exception as e:  # noqa: BLE001
        rows = {"message": f"{type(e).__name__}: {e}"}
    if not isinstance(rows, list):
        # SAY SO. A silent [] here degrades to scanned-domains-only and quietly costs
        # credits forever — exactly how a PostgREST statement timeout (57014) hid the
        # whole saving on 2026-07-08. Correctness is unaffected: lead_excluded() still
        # fails closed on every lead. Cache the failure briefly so it self-heals.
        print(f"[exclusions] rpc/exclusion_domains failed for client={client_id!r}: "
              f"{str(rows)[:160]} — search-stage exclusion degraded to scanned domains only",
              file=sys.stderr)
        _excl_cache[key] = ([], _t.time() + 60)
        return []
    out = [d for d in (canon_domain(str(r)) for r in rows if r) if d]
    _excl_cache[key] = (out, _t.time() + 1800)
    return out


def scanned_domains(source_id: str) -> set:
    """EVERY company this source has ever pulled. Not a 90-day window: once a source has
    seen a domain it must never buy a job at that domain again (user rule 2026-07-08).

    Paged, never a bare `limit=N`. A silent truncation here is invisible and expensive:
    the missing domains simply get re-bought, forever."""
    out, offset = set(), 0
    while True:
        page = sb("GET", f"signals?source=eq.theirstack&detail->>source_id=eq.{source_id}"
                         f"&select=company_domain&limit=1000&offset={offset}")
        if not isinstance(page, list) or not page:
            break
        out |= {r["company_domain"] for r in page
                if isinstance(r, dict) and r.get("company_domain")}
        if len(page) < 1000:
            break
        offset += 1000
        if offset >= 200000:      # safety valve far above real volume (~30 domains/day)
            print(f"[exclusions] scanned_domains({source_id}) hit the 200k page guard",
                  file=sys.stderr)
            break
    return out


def _search_exclusions(source_id: str, client_id: str | None, scanned: set | None = None) -> list:
    """Domains to exclude AT THE SEARCH, so we never buy the job in the first place.

    The set is this source's OWN scanned domains: once a source pulls a domain it never
    buys a job there again (user rule 2026-07-08). Measured that day: 21-24% of a
    source's window, bought and then binned by the `already` check a few lines later.

    The client suppression/contact set (~40k domains for client-1) would take that to 46%
    but is OFF by default at the user's instruction — those lists are still enforced
    per-lead by lead_excluded(), so turning this on changes cost, never who gets emailed.
    Set THEIRSTACK_EXCLUDE_SUPPRESSED=1 to fold them back into the search body.

    Scanned domains go first, so a THEIRSTACK_EXCLUDE_MAX cap can never evict the entries
    that carry the source's permanent no-re-pull guarantee. Pass `scanned` to reuse a set
    the caller already paged."""
    if scanned is None:
        scanned = scanned_domains(source_id)
    candidates = list(scanned)
    if THEIRSTACK_EXCLUDE_SUPPRESSED:
        candidates += _exclusion_domains(client_id)
    seen, out = set(), []
    for d in candidates:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
            if len(out) >= THEIRSTACK_EXCLUDE_MAX:
                break
    return out


def _leads_today(source_id: str) -> int:
    """signal_leads this source has already produced since 00:00 UTC. `leads_per_day`
    is a DAILY budget, but the pull runs 8x a day (pg_cron `0 */3 * * *`), so a
    per-invocation cap would silently permit 8x the stated number."""
    from datetime import datetime, timezone
    midnight = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    n = _sb_count(f"signal_leads?source_id=eq.{source_id}&pulled_at=gte.{midnight}")
    return n or 0


def _enrichment_backlog(source_id: str, limit: int) -> list[dict]:
    """Companies this source has BOUGHT but not yet tried to enrich, newest job
    first. Bought jobs are recorded as signals immediately; enrichment (AI-ARK +
    Prospeo, billed per person) drains this backlog at leads_per_day. Without the
    backlog a full-window buy would throw away everything past the daily budget."""
    rows = sb("GET", f"signals?source=eq.theirstack&detail->>source_id=eq.{source_id}"
                     f"&enriched_at=is.null&order=detected_at.desc&limit={int(limit)}"
                     f"&select=id,company_domain,detail,detected_at")
    return rows if isinstance(rows, list) else []


def _mark_enriched(signal_ids: list) -> None:
    """Enrichment ATTEMPTED — pass or fail. ~55% of hiring companies never yield a
    verified-email DM; without this mark they'd be re-bought from AI-ARK/Prospeo on
    every tick, forever."""
    if not signal_ids:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    ids = ",".join(str(i) for i in signal_ids)
    sb("PATCH", f"signals?id=in.({ids})", {"enriched_at": now}, prefer="return=minimal")


def pull_hiring_source(src: dict, drafts: list) -> dict:
    """The TheirStack hiring pipeline, server-side and idempotent. Two budgets,
    deliberately separate, because they bill against different providers:

      BUY (TheirStack, 1 credit per job) — page via an ascending discovered_at cursor,
      floored at the start of yesterday, until this source's share of today's leads is
      in or the day's discoveries are exhausted. A pull acts only on jobs discovered
      the day before: older posts are stale signal and are never bought. Records every
      new company as a signal. Resumes next tick where it stopped, re-buying nothing.

      ENRICH (AI-ARK + Prospeo, billed per person) — drain the unenriched signal
      backlog to empty before buying another page. A company is marked enriched
      whether or not it produced a lead.

    The single governor is SIGNAL_DAILY_LEADS, split evenly across active hiring
    sources: buying stops when the leads are in, so credits track leads.

    Previously these were one loop: it bought exactly one 100-job page and enriched
    from it, so a source matching 3,000 posts saw 100 and the rest were never bought.
    No local state files — dedupe lives in Supabase (signals unique index +
    signal_leads (source_id, linkedin_url) + a per-source domain skip)."""
    from datetime import datetime, timezone
    cfg = {**(src.get("config") or {}), **(src.get("params") or {})}

    # job-post titles: AI-idea path stores them in params.job_titles;
    # the manual wizard stores them as the config.titles string.
    job_titles = cfg.get("job_titles")
    if not job_titles:
        t = cfg.get("titles")
        job_titles = [x.strip() for x in t.split(",")] if isinstance(t, str) else (t or [])
    job_titles = [x for x in (job_titles or []) if str(x).strip()]
    if not job_titles:
        return {"ok": False, "message": "This hiring signal has no job titles to search. Edit the source and add the roles whose live job posts should trigger it."}

    # decision-maker roles to enrich (AI path stores them at top-level `titles`)
    dm_titles = expand_titles((src.get("params") or {}).get("dm_titles")
                              or [x.strip() for x in (src.get("titles") or []) if str(x).strip()])
    codes, unmapped_countries = country_codes(cfg.get("countries") or [])
    codes = codes or ["US"]
    min_emp, max_emp = emp_range(cfg.get("headcount"))
    days = min(int(cfg.get("days") or 30), 30)  # freshness: never act on posts older than 30d
    # ONE user-facing pace knob; internals derive from it
    # This source's share of the fleet-wide daily lead budget (or its own override)
    leads_per_day = _daily_lead_share(src, drafts)
    max_dms = 5                          # fixed: at most 5 decision makers per company

    # ENRICH budget: what's LEFT of today's leads, not a fresh allowance per tick.
    # pg_cron fires `0 */3 * * *` (8x a day), so a per-invocation cap would quietly
    # permit 8x leads_per_day. Once the day's budget is filled every later tick is
    # a no-op, and buys nothing.
    done_today = _leads_today(src["id"])
    enrich_budget = max(0, leads_per_day - done_today)
    if enrich_budget <= 0:
        return {"ok": False, "message":
                f"Today's budget for this signal is full ({done_today}/{leads_per_day} leads). "
                "It resumes at midnight UTC. Raise 'leads per day' on the source to pull more."}

    # BUY budget: a runaway backstop on ONE pull, not a spend ceiling. The lead
    # budget above is what actually governs how many jobs get bought. Only floored
    # by the emergency credit brake when it has been armed (THEIRSTACK_DAILY_CAP>0).
    job_budget = THEIRSTACK_JOBS_PER_PULL
    if THEIRSTACK_DAILY_CAP > 0:
        spent_today = theirstack_credits_today()
        if spent_today is not None:      # None = Supabase unreadable; never hard-block
            job_budget = min(job_budget, max(0, THEIRSTACK_DAILY_CAP - spent_today))

    # Enrichment ceiling. AI-ARK and Prospeo bill per person, and ~55% of hiring
    # companies yield no verified-email DM at all, so a lead costs roughly 2
    # companies. 4x headroom covers a bad-yield source without letting one pull
    # enrich unboundedly when the DM hit-rate collapses.
    company_budget = max(200, enrich_budget * COMPANIES_PER_LEAD_HEADROOM)

    # client for exclusion checks, resolved via the campaign draft
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(src.get("campaign_id"))), {})
    client_id = src.get("client_id") or camp.get("client_id")
    src["client_id"] = client_id

    precision = {k: cfg[k] for k in ("company_description_pattern_or", "company_description_pattern_not",
                                     "industry_or", "industry_not") if cfg.get(k)}
    # normalise/drop industry names TheirStack doesn't recognise — an unknown
    # value silently no-ops (returns everything), so keeping only canonical names
    # guarantees the stored filter (manual OR AI-generated) actually applies.
    for k in ("industry_or", "industry_not"):
        if precision.get(k):
            good, _bad = validate_industries(precision[k])
            if good:
                precision[k] = good
            else:
                precision.pop(k, None)
    negatives = [str(n).strip() for n in (cfg.get("negative_keywords") or []) if str(n).strip()]
    if negatives:
        pats = [re.escape(n.lower()) for n in negatives]
        precision["job_title_pattern_not"] = pats
        precision["job_description_pattern_not"] = pats
    # The KILL words below are also enforced client-side against name + industry. Doing
    # the name half server-side costs nothing and removes those jobs before we buy them.
    precision["company_name_partial_match_not"] = ["staffing", "talent", "recruit", "consultants"]

    # Search-stage exclusion, built lazily: a tick that buys nothing must not pay for the
    # exclusion RPC. Rebuilt per page from the SAME scanned set `_record` grows, so a
    # company banked on page 1 is already excluded on page 2 instead of being re-bought.
    _excl_box: dict = {}

    def _page_extra(extra: dict) -> dict:
        if "scanned" not in _excl_box:
            _excl_box["scanned"] = scanned_domains(src["id"])
        lst = _search_exclusions(src["id"], client_id, scanned=_excl_box["scanned"])
        return {**extra, "company_domain_not": lst} if lst else extra
    # ── BUY + ENRICH ─────────────────────────────────────────────────────
    # Goal: fill today's leads_per_day, however many job pages that takes — not
    # "one 100-job page and hope". Jobs are bought page by page against an
    # ascending discovered_at cursor (TheirStack re-charges for repeats, so a
    # cursor is the only way to page without re-buying). Every company bought is
    # recorded as a signal immediately; enrichment then drains that backlog until
    # the budget is met. A page bought at the boundary is therefore never wasted:
    # whatever we didn't enrich is already paid for and waits as backlog.
    from datetime import timedelta
    template = ensure_hiring_vars(src.get("icebreaker"))  # guarantee {{company}} + {{job_title}}
    now_iso = datetime.now(timezone.utc).isoformat()
    min_posted = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    def lead_excluded(email, domain):
        return is_suppressed(client_id, email, domain)  # shared helper (also used at push time)

    prospects, dropped = [], {"no_email": 0, "excluded": 0}
    signals_n = companies_tried = bought = 0
    exhausted = capped = filter_dropped = False
    walk_error = None
    meta: dict = {}
    first_total = None

    def _persist_cursor(cur, bids):
        """A paid page must advance the cursor before anything else can fail."""
        src["last_discovered_at"], src["last_discovered_ids"] = cur, list(bids)
        sb("POST", "sources?on_conflict=id", {"id": src["id"], "doc": src},
           prefer="resolution=merge-duplicates,return=minimal")
        sb("PATCH", f"signal_sources?id=eq.{src['id']}",
           {"last_discovered_at": cur, "last_discovered_ids": list(bids)})

    def _enrich(domain, jc, job_title, job_url):
        """AI-ARK + Prospeo for one company. Billed per person, so never ask for
        more decision-makers than the day still needs. Returns nothing; appends."""
        nonlocal companies_tried
        companies_tried += 1
        from name_hygiene import clean_company_name, clean_job_title, email_safe
        want = min(max_dms, enrich_budget - len(prospects))
        for person in dm_find_by_domain(domain, dm_titles, want):
            if len(prospects) >= enrich_budget:
                break
            person["company"] = clean_company_name(person.get("company")) or jc
            person["domain"] = person.get("domain") or domain
            try:  # verified email is the keep-gate (Prospeo enrich-person)
                email = find_email(person)
            except Exception:  # noqa: BLE001 — credit/key failure: skip, never guess
                email = None
            if not email:
                dropped["no_email"] += 1
                continue
            if lead_excluded(email, person["domain"]):
                dropped["excluded"] += 1
                continue
            person["email"] = email
            role = clean_job_title(job_title or "") or ""
            person["hiring_for"] = person["role"] = role
            person["job_url"] = job_url
            ice = fill_icebreaker(template, person)
            person["icebreaker"] = email_safe(ice.replace("{{role}}", role).replace("{role}", role))
            person["verdict"] = None
            prospects.append(person)

    def _drain_backlog():
        """Enrich companies we have ALREADY paid TheirStack for, in batches, until the
        lead budget is met or the backlog runs dry or the enrichment ceiling is hit.

        Draining to EMPTY before buying is the invariant that makes paging safe: if we
        stopped draining early and bought another page, we'd be spending TheirStack
        credits while paid-for inventory sat untouched, and that inventory would then
        cost AI-ARK/Prospeo credits tomorrow anyway. Buy last, enrich first."""
        while len(prospects) < enrich_budget and companies_tried < company_budget:
            rows = _enrichment_backlog(src["id"], 200)
            if not rows:
                return
            done = []
            for row in rows:
                if len(prospects) >= enrich_budget or companies_tried >= company_budget:
                    break
                d = row.get("detail") or {}
                _enrich(row.get("company_domain"), d.get("company"), d.get("job_title"), d.get("job_url"))
                done.append(row.get("id"))
            # attempted, pass or fail — ~55% of hiring companies never yield a
            # verified-email DM, and without this mark they'd be re-enriched forever
            _mark_enriched(done)
            if len(done) < len(rows):
                return  # stopped on a budget, not on an empty backlog

    def _record(page):
        """Every company on a paid page becomes a signal, budget or no budget.

        The signal row IS the backlog marker, so an insert that gets silently swallowed
        means a company we paid TheirStack for that nobody will ever enrich. Count real
        inserts (return=representation), never assume — `signals_dedupe` once collided
        across sources and quietly ate 33 of 35 companies on a single page."""
        nonlocal signals_n
        from name_hygiene import clean_company_name
        page = [j for j in page if not j.get("date_posted") or j["date_posted"] >= min_posted]
        page.sort(key=lambda j: j.get("date_posted") or "", reverse=True)
        uniq, seen_d = [], set()
        for j in page:
            if j["domain"] not in seen_d:
                seen_d.add(j["domain"])
                uniq.append(j)
        if not uniq:
            return 0
        # Once this source has pulled a domain it never pulls it again (user rule
        # 2026-07-08). This used to be a 90-day re-touch window; it is now permanent,
        # and it must agree with the search-stage company_domain_not exclusion built
        # from the same set — if the two disagree we pay for jobs we then discard.
        # Memoised for the pull: the set only grows, and only by what _record banks.
        if "scanned" not in _excl_box:
            _excl_box["scanned"] = scanned_domains(src["id"])
        already = _excl_box["scanned"]
        fresh = [j for j in uniq if j["domain"] not in already]
        already |= {j["domain"] for j in fresh}   # this page is now scanned too
        for j in fresh:
            jc = clean_company_name(j["company"]) if j.get("company") else j.get("company")
            detected = (j["date_posted"] + "T00:00:00Z") if j.get("date_posted") else now_iso
            # company row FIRST — signals.company_domain has an FK to companies(domain)
            sb("POST", "companies?on_conflict=domain", {
                "domain": j["domain"], "name": jc or None,
                "industry": j["industry"] or None,
                "employee_count": j["employee_count"],
                "employee_range": j["employee_range"] or None,
                "country": j["country"] or None,
            }, prefer="resolution=merge-duplicates,return=minimal")
            # enriched_at stays NULL: this is the backlog marker
            r = sb("POST", "signals", {
                "signal_type": "hiring", "source": "theirstack", "company_domain": j["domain"],
                "detected_at": detected,
                "detail": {"job_title": j["job_title"], "job_url": j["job_url"],
                           "company": jc, "source_id": src["id"]},
            }, prefer="resolution=ignore-duplicates,return=representation")
            if isinstance(r, list) and r:
                signals_n += 1
            else:
                # bought, but no backlog row exists -> it would never be enriched.
                # Enrich it inline, right now, rather than lose what we paid for.
                dropped["unbanked"] = dropped.get("unbanked", 0) + 1
                if len(prospects) < enrich_budget and companies_tried < company_budget:
                    _enrich(j["domain"], jc, j["job_title"], j["job_url"])
        return len(fresh)

    # Cursor, floored at the start of YESTERDAY (UTC). A daily pull acts only on
    # jobs TheirStack discovered the day before; anything older is stale signal and
    # is never bought, however many credits are left. The floor also bounds a brand
    # new source (no cursor) and a source that has been paused for a week: neither
    # can walk backwards into a 30-day window and spend a fortune on old posts.
    #
    # The stored cursor wins whenever it is NEWER than the floor -- that is the
    # normal case within a day, and it is what stops the 3-hourly ticks re-buying
    # each other's jobs. The boundary ids only make sense against the stored cursor.
    floor_dt = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    stored_dt = _parse_iso(src.get("last_discovered_at"))
    if stored_dt and stored_dt >= floor_dt:
        cursor = src["last_discovered_at"]
        bids = [i for i in (src.get("last_discovered_ids") or []) if isinstance(i, int)]
    else:
        cursor = floor_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        bids = []   # a fresh floor has no boundary to exclude

    while True:
        _drain_backlog()                       # paid inventory first, always
        if len(prospects) >= enrich_budget:
            break                              # today's leads are in
        if companies_tried >= company_budget:
            break                              # enrichment ceiling; backlog waits
        if _sb_count(f"signals?source=eq.theirstack&detail->>source_id=eq.{src['id']}"
                     f"&enriched_at=is.null"):
            break                              # backlog left over -> never buy more
        if bought >= job_budget:
            break                              # this pull's TheirStack ceiling
        room = min(100, job_budget - bought)
        page_extra = _page_extra({**precision, "discovered_at_gte": cursor})
        if bids:
            page_extra["job_id_not"] = bids[:500]  # `gte` is inclusive: skip the boundary
        page, meta = theirstack_jobs(job_titles, codes, min_emp, max_emp, days, room,
                                     extra=page_extra, negatives=negatives, source_id=src["id"])
        credits = meta.get("_credits") or 0
        bought += credits
        if first_total is None and meta.get("total_results") is not None:
            # jobs matching FROM THE CURSOR FORWARD, i.e. everything still unbought.
            # On a first pull the cursor is the window start, so this is the window.
            first_total = meta["total_results"]

        if credits == 0 and precision.get("company_description_pattern_or"):
            # the description REQUIRE gate starves niche roles to zero (most company
            # descriptions never contain the literal phrase). Drop it, keep the safe
            # NOT-excludes, self-heal the source so probes and pulls agree, retry.
            # Free: a zero-credit response bought nothing.
            precision.pop("company_description_pattern_or")
            (src.setdefault("params", {})).pop("company_description_pattern_or", None)
            (src.get("config") or {}).pop("company_description_pattern_or", None)
            filter_dropped = True
            continue

        top = meta.get("_max_discovered_at")
        if top and top != cursor:
            cursor, bids = top, list(meta.get("_max_discovered_ids") or [])
            _persist_cursor(cursor, bids)
        elif top:
            # a whole page sharing one discovered_at second: widen the exclusion
            # instead of re-buying it next iteration.
            bids = list({*bids, *(meta.get("_max_discovered_ids") or [])})
            if len(bids) > 500:
                walk_error = ("Over 500 job posts share one discovered_at timestamp; "
                              "stopped rather than re-buy them.")
                break
            _persist_cursor(cursor, bids)

        if meta.get("_capped"):
            capped = True
            break
        if meta.get("_error"):
            walk_error = meta["_error"]
            break
        if credits == 0:
            exhausted = True   # nothing new left in the window
            break

        _record(page)          # paid for: bank every company before enriching any
        _drain_backlog()       # ...then spend enrichment credits up to the budget

        if credits < room:
            exhausted = True   # short page = end of the window
            break

    total_jobs = first_total   # matching jobs this pull could still buy, from the cursor
    if capped and not prospects:
        return {"ok": False, "message":
                f"Paused: TheirStack's daily credit cap ({THEIRSTACK_DAILY_CAP}) is spent. "
                "No jobs were bought. This signal resumes on the next run, from exactly "
                "where it stopped — nothing is lost or double-charged."}
    if walk_error and not prospects and not signals_n:
        # a real provider error (bad filter/auth/rate-limit) — never report it as
        # the benign "no jobs today", or a broken signal looks like an idle one.
        return {"ok": False, "message":
                f"The hiring search couldn't run: {walk_error}. "
                "Your targeting is saved — fix the flagged issue and try again."}
    if not prospects and not signals_n:
        note = ("No live job posts match this signal today. That's normal for a hiring signal. "
                "It keeps checking daily and adds companies as they start hiring. "
                "Your campaign audience is unchanged.")
        if unmapped_countries:
            note += (" (Skipped unrecognised countries: "
                     f"{', '.join(unmapped_countries)}.)")
        return {"ok": False, "message": note}

    # what's still bought-but-unenriched: tomorrow's budget starts here, free
    left_over = _sb_count(f"signals?source=eq.theirstack"
                          f"&detail->>source_id=eq.{src['id']}&enriched_at=is.null") or 0

    # compounding campaign-level exclusion: never re-pull an individual
    # already seen (any source in this campaign) or previously rejected
    seen = set()
    for other in drafts:
        if str(other.get("campaign_id")) == str(src.get("campaign_id")):
            for x in (other.get("prospects") or []):
                if x.get("linkedin"):
                    seen.add(x["linkedin"])
                if other.get("id") != src.get("id") and x.get("name"):
                    seen.add(("nm", x.get("name"), x.get("company")))
    prospects = [x for x in prospects
                 if not ((x.get("linkedin") and x["linkedin"] in seen and next(
                     (px for px in (src.get("prospects") or []) if px.get("linkedin") == x.get("linkedin")), None) is None)
                     or ("nm", x.get("name"), x.get("company")) in seen)] or prospects
    src["prospects"] = prospects
    # "N matched" in the UI means PEOPLE — company/job tallies live in the meta fields
    src["total"] = len(prospects)
    src["total_jobs"] = total_jobs
    src["signals_found"] = signals_n
    src["companies_scanned"] = companies_tried
    src["jobs_bought"] = bought
    src["window_exhausted"] = exhausted
    src["left_for_next_run"] = left_over
    src["mechanism"] = "hiring"
    src["last_pull"] = datetime.now().isoformat(timespec="seconds")
    write_source(src)
    sb_sync_source(src)

    # NB: no "status" key. This is an UPSERT on (source_id, linkedin_url), and
    # merge-duplicates writes every column provided — so sending status:"new" reset
    # already-PUSHED leads back to new, and the next autopilot tick re-contacted them.
    # (2026-07-08: 52 leads flipped this way in one afternoon.) Omitting the column
    # lets the 'new' default apply on INSERT while leaving pushed/rejected untouched
    # on UPDATE. Same reasoning for pushed_to: only the pusher may write it.
    rows = [{"source_id": src["id"], "full_name": x.get("name"), "title": x.get("title"),
             "company": x.get("company"), "domain": x.get("domain"),
             "linkedin_url": x.get("linkedin") or f"unknown:{x.get('name')}",
             "country": x.get("country"), "icebreaker": x.get("icebreaker"),
             "email": x.get("email")}
            for x in prospects]
    if rows:
        sb("POST", "signal_leads?on_conflict=source_id,linkedin_url", rows,
           prefer="resolution=merge-duplicates,return=minimal")
    sb("PATCH", f"signal_sources?id=eq.{src['id']}", {"last_pull_at": src["last_pull"]})

    drop_note = " · ".join(f"{v} dropped ({k.replace('_', ' ')})" for k, v in dropped.items() if v)
    if not prospects:
        return {"ok": False, "message":
                f"Scanned {signals_n} hiring companies but kept no leads"
                + (f" - {drop_note}" if drop_note else " - no decision-maker contacts surfaced yet")
                + ". The signals are saved; it retries daily.",
                "total": total_jobs, "signals": signals_n, "jobs_bought": bought,
                "companies_scanned": companies_tried, "dropped": dropped}
    tail = f" ({left_over} companies already bought and queued for the next run)" if left_over else ""
    dm_word = "decision-maker" if len(prospects) == 1 else "decision-makers"
    notices = []
    if filter_dropped:
        notices.append("Removed your 'description must contain' filter to get results "
                       "- it matched no live jobs. Targeting saved.")
    if unmapped_countries:
        notices.append("Skipped unrecognised countries: " + ", ".join(unmapped_countries) + ".")
    if capped:
        notices.append(f"Stopped early: TheirStack's daily credit cap ({THEIRSTACK_DAILY_CAP}) "
                       "was reached. This signal resumes from the same place on the next run.")
    elif len(prospects) < enrich_budget and exhausted:
        notices.append(f"Bought every matching job post in the window and kept "
                       f"{len(prospects)} of today's {leads_per_day}-lead budget. "
                       "There simply aren't more live posts to buy right now.")
    return {"ok": True, "total": total_jobs, "signals": signals_n,
            "companies_scanned": companies_tried, "jobs_bought": bought,
            "prospects": prospects, "db_synced": True,
            "dropped": dropped,
            "notice": " ".join(notices) or None,
            "note": f"{signals_n} hiring companies, {len(prospects)} {dm_word}"
                    f" from {bought} job posts{tail}"
                    + (f" · {drop_note}" if drop_note else "")}


def pull_source(p: dict) -> dict:
    """Simulate the daily pull: fetch real prospects for a source using its
    own targeting, fill its icebreaker per person, store on the source."""
    drafts = read_drafts()
    src = next((d for d in drafts if d.get("id") == p.get("id")), None)
    if not src:
        return {"ok": False, "message": "Source not found"}
    if (src.get("mechanism") or src.get("type")) == "hiring":
        r = pull_hiring_source(src, drafts)
        _ensure_source_list(src)  # keep the People-page mirror list in step
        return r
    if (src.get("mechanism") or src.get("type")) == "engagement":
        r = pull_engagement_source(src, drafts)
        _ensure_source_list(src)
        return r
    cfg = {**(src.get("config") or {}), **(src.get("params") or {})}
    titles = src.get("titles") or (cfg.get("titles").split(",") if isinstance(cfg.get("titles"), str) else cfg.get("titles")) or []
    titles = [x.strip() for x in titles if str(x).strip()]

    filters: dict = {}
    titles = expand_titles((src.get("params") or {}).get("dm_titles") or titles)
    if titles:
        filters["person_job_title"] = {"include": titles, "include_partial_match": True}
    else:
        filters["person_seniority"] = {"include": ["Founder/Owner", "C-Suite", "Head", "Director", "Vice President"]}
    kw = cfg.get("keywords")
    kw = [kw] if isinstance(kw, str) and kw.strip() else (kw if isinstance(kw, list) else [])
    if kw:
        filters["company_keywords"] = {"include": kw, "include_company_description": True}
    if cfg.get("industries"):
        filters["company_industry"] = {"include": cfg["industries"]}
    if cfg.get("headcount"):
        filters["company_headcount_range"] = cfg["headcount"]
    if cfg.get("countries"):
        filters["company_location_search"] = {"include": cfg["countries"]}
    if cfg.get("icp_text") and not kw:
        filters["company_keywords"] = {"include": [cfg["icp_text"]], "include_company_description": True}

    def paged(f):
        rows, total = [], 0
        for page in (1, 2, 3):
            d = http_json("POST", "https://api.prospeo.io/search-person",
                          {"X-KEY": KEYS["PROSPEO_API_KEY"]},
                          {"page": page, "size": 25, "filters": f})
            if d.get("error"):
                return ({"error": True, **d} if page == 1 else {"results": rows, "pagination": {"total_count": total}})
            total = (d.get("pagination") or {}).get("total_count") or total
            rows += d.get("results") or []
            if len(rows) >= min(total, 75):
                break
        return {"results": rows, "pagination": {"total_count": total}}

    data = paged(filters)
    if data.get("error") or not (data.get("results") or []):
        msg = ("No matches for the new targeting yet. Your change is saved and all future pulls use it. Widen it a little if you want people today."
               if p.get("after_retarget") else
               "Nothing new from this signal today - that's normal. It keeps checking daily and adds people as companies trigger it. Your campaign audience is unchanged.")
        return {"ok": False, "message": msg}

    template = src.get("icebreaker") or ""

    prospects = []
    for row in _person_rows(data, 10):
        row["icebreaker"] = fill_icebreaker(template, row)
        row["verdict"] = None
        prospects.append(row)
    total = (data.get("pagination") or {}).get("total_count") or len(prospects)
    src["prospects"] = prospects
    src["total"] = total
    src["last_pull"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    src["broadened"] = False
    write_source(src)
    sb_sync_source(src)
    # no "status": merge-duplicates would reset an already-pushed lead to new, and the
    # next autopilot tick would re-contact them. See pull_hiring_source for the full note.
    rows = [{"source_id": src["id"], "full_name": x.get("name"), "title": x.get("title"),
             "company": x.get("company"), "domain": x.get("domain"),
             "linkedin_url": x.get("linkedin") or f"unknown:{x.get('name')}",
             "country": x.get("country"), "icebreaker": x.get("icebreaker")}
            for x in prospects]
    sb("POST", "signal_leads?on_conflict=source_id,linkedin_url", rows,
       prefer="resolution=merge-duplicates,return=minimal")
    sb("PATCH", f"signal_sources?id=eq.{src['id']}", {"last_pull_at": src["last_pull"]})
    _ensure_source_list(src)  # keep the People-page mirror list in step
    return {"ok": True, "total": total, "broadened": False, "prospects": prospects, "db_synced": True}


def _link_unlinked_draft(old_doc: dict, new_dest: dict, drafts: list) -> dict:
    """LINK flow (S3): an Unlinked draft (cdraft-*, no platform id yet) gets a
    destination that names a live Smartlead campaign and/or HeyReach list for
    the first time. Materialise the platform-keyed camp-sl-*/camp-hr-* doc(s)
    (merging into one that already exists, e.g. a second unlinked draft picking
    the same platform target), tombstone the old doc with `superseded_by` (kept,
    never deleted, so history/undo stays possible), and re-point every `sources`
    row + `signal_sources.campaign_draft_id` row that pointed at the old id so
    pulls/pushes keep working uninterrupted. Mutates `drafts` in place; caller
    still persists via write_drafts(drafts, CAMPAIGN_DRAFTS)."""
    from datetime import datetime
    old_id = old_doc["id"]
    now = datetime.now().isoformat(timespec="seconds")
    sl = new_dest.get("smartlead_campaign_id")
    hr = new_dest.get("heyreach_list_id")
    hr_name = new_dest.get("heyreach_list_name")
    plan = []  # [(new_id, identity_fields)] — smartlead first so it's the primary when both present
    if sl:
        plan.append((f"camp-sl-{sl}", {"platform": "smartlead", "smartlead_campaign_id": sl}))
    if hr or hr_name:
        ident = {"platform": "heyreach", "heyreach_list_id": hr}
        if hr_name:
            ident["heyreach_list_name"] = hr_name
        plan.append((f"camp-hr-{hr or hr_name}", ident))
    if not plan:
        return {"ok": False, "message": "destination has no platform id to link to"}
    body_base = {k: v for k, v in old_doc.items()
                 if k not in ("id", "destination", "deleted_at", "platform",
                              "smartlead_campaign_id", "heyreach_list_id",
                              "heyreach_list_name", "migrated_from", "migrated_at",
                              "superseded_by")}
    old_sources = old_doc.get("sources") or []
    new_ids = []
    for new_id, ident in plan:
        existing = next((d for d in drafts if d.get("id") == new_id), None)
        if existing:
            if old_sources:
                existing["sources"] = (existing.get("sources") or []) + old_sources
            mig = existing.get("migrated_from") or []
            if old_id not in mig:
                mig.append(old_id)
            existing["migrated_from"] = mig
        else:
            drafts.append({**body_base, **ident, "id": new_id,
                           "destination": dict(ident), "sources": list(old_sources),
                           "migrated_from": [old_id], "migrated_at": now})
        new_ids.append(new_id)
    old_doc["superseded_by"] = new_ids
    primary = new_ids[0]

    # re-point `sources` table rows (doc.campaign_id) that belonged to the old draft
    all_srcs = read_drafts(strict=True)
    touched = []
    for s in all_srcs:
        if str(s.get("campaign_id")) == str(old_id):
            s["campaign_id"] = primary
            if len(new_ids) > 1:
                s["campaign_ids"] = list(new_ids)
            touched.append(s)
    if touched:
        write_sources(touched)

    # re-point signal_sources.campaign_draft_id (relational column, not a doc field)
    sb("PATCH", f"signal_sources?campaign_draft_id=eq.{old_id}", {"campaign_draft_id": primary})

    return {"ok": True, "id": primary, "linked": new_ids}


def update_campaign_draft(p: dict) -> dict:
    from datetime import datetime
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    cid = p.get("id")
    if p.get("remove"):
        # SOFT delete: mark the campaign + its sources deleted and stop nothing
        # external. Everything stays intact so restore is lossless. The hard,
        # irreversible cascade (Trigify teardown + Supabase row deletion) only
        # runs on an explicit purge from the Recently-deleted area.
        now = datetime.now().isoformat(timespec="seconds")
        all_srcs = read_drafts(strict=True)
        touched = []
        for src in all_srcs:
            if str(src.get("campaign_id")) == str(cid):
                src["deleted_at"] = now
                touched.append(src)
        write_sources(touched)  # only this campaign's sources — siblings untouched
        for d in drafts:
            if d.get("id") == cid:
                d["deleted_at"] = now
        write_drafts(drafts, CAMPAIGN_DRAFTS)
        return {"ok": True, "soft_deleted": True}
    else:
        target = next((d for d in drafts if d.get("id") == cid), None)
        if "destination" in p and target is not None:
            new_dest = p["destination"] or {}
            cur_dest = target.get("destination") or {}
            is_unlinked = (str(cid).startswith("cdraft-") and not target.get("platform")
                          and not cur_dest.get("smartlead_campaign_id")
                          and not cur_dest.get("heyreach_list_id"))
            wants_platform = bool(new_dest.get("smartlead_campaign_id")
                                  or new_dest.get("heyreach_list_id")
                                  or new_dest.get("heyreach_list_name"))
            if is_unlinked and wants_platform:
                result = _link_unlinked_draft(target, new_dest, drafts)
                write_drafts(drafts, CAMPAIGN_DRAFTS)
                return result
        for d in drafts:
            if d.get("id") != cid:
                continue
            if "destination" in p:
                d["destination"] = p["destination"]
            if "autopilot" in p:
                d["autopilot"] = bool(p["autopilot"])
            if "paused" in p:
                d["paused"] = bool(p["paused"])  # paused campaigns are skipped by the daily run
            if str(p.get("name") or "").strip():
                d["name"] = str(p["name"]).strip()
    write_drafts(drafts, CAMPAIGN_DRAFTS)
    return {"ok": True}


def restore_campaign_draft(p: dict) -> dict:
    """Bring a soft-deleted campaign (and its sources) back to life. Lossless:
    nothing external was ever torn down, so monitoring + leads are intact."""
    cid = p.get("id")
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    found = False
    for d in drafts:
        if d.get("id") == cid and d.get("deleted_at"):
            d.pop("deleted_at", None)
            found = True
    if not found:
        return {"ok": False, "message": "Nothing to restore for this campaign."}
    write_drafts(drafts, CAMPAIGN_DRAFTS)
    srcs = read_drafts(strict=True)
    revived = []
    for s in srcs:
        if str(s.get("campaign_id")) == str(cid):
            s.pop("deleted_at", None)
            revived.append(s)
    write_sources(revived)
    return {"ok": True, "restored": True}


def purge_campaign_draft(p: dict) -> dict:
    """PERMANENT delete from the Recently-deleted area. This is the old hard
    cascade: stop the Trigify monitors and delete the Supabase rows. Irreversible."""
    cid = p.get("id")
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    all_srcs = read_drafts(strict=True)
    doomed = [x for x in all_srcs if str(x.get("campaign_id")) == str(cid)]
    for src in doomed:  # tear down each source's external + backend footprint
        if (src.get("mechanism") or src.get("type")) == "engagement":
            ent = ((src.get("config") or {}).get("engagement") or {}).get("trigify") or []
            if ent:
                _trigify_deprovision(ent)  # best-effort: stop the LinkedIn monitors
        sb_delete_source(src.get("id"))
        sb_delete_doc("sources", src.get("id"))  # explicit: drop the doc-table row too
    # safety net: clear any Supabase rows keyed straight to the campaign
    sb("DELETE", f"signal_sources?campaign_draft_id=eq.{cid}")
    sb("DELETE", f"engagement_events?campaign_draft_id=eq.{cid}")
    sb_delete_doc("campaign_drafts", cid)  # explicit: purge the campaign even if it was the last one
    # each doomed source's row is already gone (sb_delete_doc above); re-writing the
    # survivors here would upsert every one of them from a possibly-stale snapshot
    write_drafts([d for d in drafts if d.get("id") != cid], CAMPAIGN_DRAFTS)
    return {"ok": True, "purged": True}


def _copy_name(name: str) -> str:
    """'Foo' -> 'Foo (copy)', 'Foo (copy)' -> 'Foo (copy 2)', etc."""
    import re
    name = str(name or "Untitled")
    m = re.search(r" \(copy(?: (\d+))?\)$", name)
    if m:
        n = int(m.group(1) or 1) + 1
        return re.sub(r" \(copy(?: \d+)?\)$", f" (copy {n})", name)
    return name + " (copy)"


def _clone_source_dict(src: dict, new_campaign_id: str | None = None) -> dict:
    """Deep-copy a source keeping ALL targeting (config/params/titles/icebreaker/
    destination) but stripping per-run lead state and any external bindings, so the
    copy is a fresh, un-pulled source ready to find its own people."""
    import copy
    s = copy.deepcopy(src)
    for k in ("id", "prospects", "last_pull", "total", "broadened", "deleted_at"):
        s.pop(k, None)
    if new_campaign_id is not None:
        s["campaign_id"] = new_campaign_id
    # engagement: drop the Trigify workflow ids - they belong to the original's
    # monitors; the copy provisions its own when the user starts monitoring.
    eng = (s.get("config") or {}).get("engagement")
    if isinstance(eng, dict):
        eng.pop("trigify", None)
    return s


def duplicate_source(p: dict) -> dict:
    """Duplicate one draft source within the same campaign, keeping its targeting."""
    import uuid
    sid = p.get("id")
    drafts = read_drafts(strict=True)
    orig = next((d for d in drafts if d.get("id") == sid), None)
    if not orig:
        return {"ok": False, "message": "Source not found - refresh and try again."}
    s = _clone_source_dict(orig)
    s["id"] = f"draft-{uuid.uuid4().hex[:8]}"
    s["name"] = _copy_name(orig.get("name"))
    drafts.append(s)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_source(s)  # an append only adds a row — never rewrite the siblings
    sb_sync_source(s)
    return {"ok": True, "id": s["id"], "name": s["name"]}


def duplicate_campaign_draft(p: dict) -> dict:
    """Duplicate a whole campaign: the campaign draft plus every one of its live
    sources (targeting retained), under fresh ids, so it launches identically."""
    from datetime import datetime
    import uuid, copy
    cid = p.get("id")
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    orig = next((d for d in drafts if d.get("id") == cid), None)
    if not orig:
        return {"ok": False, "message": "Campaign not found - refresh and try again."}
    new = copy.deepcopy(orig)
    new_id = f"cdraft-{uuid.uuid4().hex[:8]}"
    new["id"] = new_id
    new["name"] = _copy_name(orig.get("name"))
    new["created_at"] = datetime.now().isoformat(timespec="seconds")
    new.pop("deleted_at", None)
    drafts.append(new)
    CAMPAIGN_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_drafts(drafts, CAMPAIGN_DRAFTS)
    all_srcs = read_drafts(strict=True)
    originals = [s for s in all_srcs
                 if str(s.get("campaign_id")) == str(cid) and not s.get("deleted_at")]
    new_srcs = []
    for src in originals:
        s = _clone_source_dict(src, new_campaign_id=new_id)
        s["id"] = f"draft-{uuid.uuid4().hex[:8]}"
        new_srcs.append(s)
    if new_srcs:
        all_srcs.extend(new_srcs)
        write_sources(new_srcs)  # only the clones are new — leave the originals alone
        for s in new_srcs:
            sb_sync_source(s)
    return {"ok": True, "id": new_id, "name": new["name"], "sources": len(new_srcs)}


_CAMP_KEY_RE = re.compile(r"^camp-(sl|hr)-[A-Za-z0-9_]+$")


def save_campaign_draft(p: dict) -> dict:
    from datetime import datetime
    import uuid
    drafts = read_json_list(CAMPAIGN_DRAFTS, strict=True)
    want_id = str(p.get("id") or "")
    if _CAMP_KEY_RE.match(want_id):
        # Platform-mirror row lazily materialising its state doc for the first
        # time (e.g. first add-source on a bare mirror row). Idempotent: if the
        # doc already exists, just hand back its id rather than duplicating it.
        existing = next((d for d in drafts if d.get("id") == want_id), None)
        if existing:
            return {"ok": True, "id": existing["id"]}
        p["id"] = want_id
    else:
        p["id"] = f"cdraft-{uuid.uuid4().hex[:8]}"  # never reuse ids (same lesson as sources)
    p["created_at"] = datetime.now().isoformat(timespec="seconds")
    drafts.append(p)
    CAMPAIGN_DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_drafts(drafts, CAMPAIGN_DRAFTS)
    return {"ok": True, "id": p["id"]}


def save_qa_run(p: dict) -> dict:
    from datetime import datetime
    runs = read_json_list(QA_HISTORY)
    p["ts"] = datetime.now().isoformat(timespec="seconds")
    runs.append(p)
    QA_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    QA_HISTORY.write_text(json.dumps(runs[-200:], indent=1))
    return {"ok": True, "ts": p["ts"]}


def cron_pull_all():
    """Pull every active source on every non-deleted signal campaign, then
    autopilot-push new leads (email -> Smartlead, else HeyReach). This is the
    exact `run_daily.py` pipeline, factored out so an external scheduler
    (pg_cron -> pg_net -> POST /api/cron/pull-all) can fire it every ~3h with
    no laptop awake. Idempotent — safe to re-run. Returns a summary dict.

    Bounded + non-wedging: each source is pulled in a watchdog thread with a
    hard timeout, and the whole run has a wall-clock ceiling, so one slow-drip
    provider call can never stall the 3-hourly tick. No `drafts_lock()` on this
    path — pulled leads/signals are upserted per-row in Supabase (authoritative;
    the Leads tab + verification read from there), so an abandoned worker can't
    corrupt shared state or block the next source."""
    from datetime import datetime
    import time as _time
    BUDGET_S = 1500  # whole-run wall-clock ceiling (bg thread, guarded by _CRON_LOCK;
                     # pg_cron fires every 3h so a longer run is safe and lets every
                     # source complete in one tick instead of perpetually deferring the tail)
    SOURCE_S = 300   # per-source hard timeout (engagement parallel-qualifies a big backlog)
    t0 = _time.monotonic()

    def _timed(fn):
        """Run fn() in a daemon thread; return (result, error, timed_out).

        On timeout the thread is abandoned but NOT killed (Python can't), so we
        flag it: write_source()/write_drafts() check thread_abandoned() and
        refuse to persist. Without that flag the zombie thread finishes minutes
        later and writes a snapshot older than the sources that ran after it."""
        box = {}
        abandoned = threading.Event()
        def _w():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e
        th = threading.Thread(target=_w, daemon=True)
        th._navreo_abandoned = abandoned  # read via thread_abandoned() inside fn
        th.start()
        th.join(SOURCE_S)
        if th.is_alive():
            abandoned.set()
            return None, None, True
        return box.get("r"), box.get("e"), False

    campaigns = {str(c.get("id")): c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if not c.get("deleted_at")}
    _active = [d for d in read_drafts()
               if d.get("active", True) and not d.get("deleted_at")
               and str(d.get("campaign_id")) in campaigns]
    # fairness: least-recently-pulled first (never-pulled = "" sorts first), so a
    # source deferred or timed-out last tick jumps to the front of the next tick
    # instead of being perpetually starved at the tail of a fixed order.
    _active.sort(key=lambda d: d.get("last_pull") or "")
    source_ids = [d["id"] for d in _active]
    out = {"ok": True, "ran_at": datetime.now().isoformat(timespec="seconds"),
           "sources": [], "signals": 0, "leads": 0, "errors": 0, "deferred": 0}
    for sid in source_ids:
        if _time.monotonic() - t0 > BUDGET_S:  # out of budget — leave the rest for the next tick
            out["sources"].append({"id": sid, "deferred": "budget"})
            out["deferred"] += 1
            continue
        entry = {"id": sid}
        _s0 = _time.monotonic()
        try:  # nothing per-source may escape — the run must always reach the summary insert
            r, err, timed_out = _timed(lambda: pull_source({"id": sid}))
            if timed_out:
                entry["error"] = f"timed out after {SOURCE_S}s (abandoned)"
                out["errors"] += 1
            elif err:
                entry["error"] = str(err)[:200]
                out["errors"] += 1
            else:
                r = r or {}
                entry["ok"] = bool(r.get("ok"))
                entry["note"] = r.get("note") or r.get("message") or ""
                entry["signals"] = r.get("signals") or 0
                entry["leads"] = len(r.get("prospects") or [])
                out["signals"] += entry["signals"]
                out["leads"] += entry["leads"]
                drafts = read_drafts()  # pull_source rewrote it; re-read for the push
                src = next((d for d in drafts if d.get("id") == sid), None)
                camp = campaigns.get(str((src or {}).get("campaign_id"))) or {}
                entry["campaign"] = camp.get("name")
                if src and camp.get("autopilot"):
                    _pr, _pe, _pt = _timed(lambda: auto_push_new_leads(src))
                    pushed = _pr or []
                    entry["autopushed"] = len([p for p in pushed if p.get("ok")])
                    entry["push_failed"] = len([p for p in pushed if not p.get("ok")])
                    if not _pt:  # persist pushed-state to the row the Leads tab reads
                        try:
                            write_source(src)
                        except Exception:  # noqa: BLE001
                            pass
                    if _pt or _pe:
                        entry["push_note"] = "push timed out" if _pt else str(_pe)[:120]
                else:
                    entry["autopilot"] = False
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:200]
            out["errors"] += 1
        entry["secs"] = round(_time.monotonic() - _s0, 1)
        out["sources"].append(entry)
    out["total_secs"] = round(_time.monotonic() - t0, 1)
    try:  # durable, queryable record of every scheduled run (best-effort)
        sb("POST", "signal_cron_runs", {"summary": out})
    except Exception:  # noqa: BLE001
        pass
    return out


_CRON_LOCK = threading.Lock()  # one batch pull at a time; overlapping ticks no-op


def _cron_pull_bg():
    if not _CRON_LOCK.acquire(blocking=False):
        return  # a prior tick is still running — skip this one
    try:
        cron_pull_all()
    finally:
        _CRON_LOCK.release()
        # the pull writes leads/sources — invalidate the UI read caches NOW
        # (at completion), not at kick time when nothing had changed yet
        _clear_ui_caches()


# ── HeyReach daily snapshot (pg_cron → pg_net → POST /api/cron/heyreach-sync) ─
# Mirrors everything the HeyReach API exposes into the heyreach_* tables.
# Those tables are hash-deduped append-only: unique (natural_key, content_hash)
# + ignore-duplicates upsert means a row lands ONLY when the object is new or
# its content changed — the tables ARE the HeyReach change ledger. Each run
# also writes one summary row to app_activity_log (actor='heyreach_sync').

_HEYREACH_SYNC_LOCK = threading.Lock()
_HEY_PAGE = 100          # HeyReach GetAll page size
_HEY_MAX_PAGES = 20      # per-object pagination ceiling (bounded batch)
_HEY_MAX_LEAD_CALLS = 200   # total lead-page requests across all lists per run
_HEY_SLEEP_S = 0.25      # ~240 req/min, under HeyReach's ~300/min cap


def _hey_row(natural: dict, payload: dict) -> dict:
    import hashlib
    from datetime import date
    return {**natural,
            "content_hash": hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
            "payload": payload, "snapshot_date": date.today().isoformat()}


def _hey_snap_many(table: str, conflict: str, rows: list) -> int:
    """Batch-insert snapshot rows; hash-dedup makes unchanged rows a no-op
    (ON CONFLICT DO NOTHING). Returns how many rows were NEW (new/changed)."""
    if not rows:
        return 0
    r = sb("POST", f"{table}?on_conflict={conflict}", rows,
           prefer="resolution=ignore-duplicates,return=representation")
    return len(r) if isinstance(r, list) else 0


def _hey_snap(table: str, conflict: str, natural: dict, payload: dict) -> bool:
    return _hey_snap_many(table, conflict, [_hey_row(natural, payload)]) > 0


def _hey_pages(path: str, body_extra: dict | None = None, max_pages: int = _HEY_MAX_PAGES):
    """Yield items across HeyReach's offset pagination, bounded."""
    off = 0
    for _ in range(max_pages):
        r = heyreach(path, {**(body_extra or {}), "offset": off, "limit": _HEY_PAGE})
        items = (r or {}).get("items") or []
        yield from items
        if len(items) < _HEY_PAGE:
            return
        off += _HEY_PAGE
        time.sleep(_HEY_SLEEP_S)


def heyreach_sync() -> dict:
    from datetime import datetime, timedelta, timezone
    out = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "scanned": {}, "changed": {}, "errors": []}

    def sweep(name, fn):
        try:
            scanned, changed = fn()
            out["scanned"][name], out["changed"][name] = scanned, changed
        except Exception as e:  # noqa: BLE001 — one object type failing must not kill the run
            out["errors"].append(f"{name}: {str(e)[:200]}")

    def _accounts():
        n = c = 0
        for it in _hey_pages("/li_account/GetAll"):
            n += 1
            c += _hey_snap("heyreach_accounts", "heyreach_id,content_hash",
                           {"heyreach_id": str(it.get("id"))}, it)
        return n, c

    def _lists():
        ids, n, c = [], 0, 0
        for it in _hey_pages("/list/GetAll"):
            n += 1
            ids.append(it.get("id"))
            c += _hey_snap("heyreach_lists", "heyreach_id,content_hash",
                           {"heyreach_id": str(it.get("id"))}, it)
        _lists.ids = ids  # reused by _leads without a second GetAll sweep
        return n, c

    def _campaigns():
        ids, n, c = [], 0, 0
        for it in _hey_pages("/campaign/GetAll"):
            n += 1
            ids.append(it.get("id"))
            c += _hey_snap("heyreach_campaigns", "heyreach_id,content_hash",
                           {"heyreach_id": str(it.get("id"))}, it)
        _campaigns.ids = ids
        return n, c

    def _stats():
        # account-wide rollup (campaign_id=0) + per-campaign, last 30 days;
        # content-hash dedup means unchanged stats cost zero new rows.
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        window = {"startDate": start.isoformat(timespec="seconds"),
                  "endDate": end.isoformat(timespec="seconds")}
        n = c = 0
        r = heyreach("/stats/GetOverallStats",
                     {**window, "accountIds": [], "campaignIds": []})
        if r is not None:
            n += 1
            c += _hey_snap("heyreach_campaign_stats", "campaign_id,content_hash",
                           {"campaign_id": 0}, r)
        for cid in (getattr(_campaigns, "ids", []) or [])[:100]:
            time.sleep(_HEY_SLEEP_S)
            r = heyreach("/stats/GetOverallStats",
                         {**window, "accountIds": [], "campaignIds": [int(cid)]})
            if r is not None:
                n += 1
                c += _hey_snap("heyreach_campaign_stats", "campaign_id,content_hash",
                               {"campaign_id": int(cid)}, r)
        return n, c

    def _member_key(it: dict) -> str:
        import hashlib
        return str(it.get("profileUrl") or it.get("linkedin_url")
                   or it.get("linkedInId") or it.get("id")
                   or hashlib.sha256(json.dumps(it, sort_keys=True,
                                                default=str).encode()).hexdigest()[:24])

    def _leads():
        n = c = calls = 0
        for lid in (getattr(_lists, "ids", []) or []):
            if calls >= _HEY_MAX_LEAD_CALLS:
                out["errors"].append(f"leads: call budget hit at list {lid} — rest next run")
                break
            off = 0
            while calls < _HEY_MAX_LEAD_CALLS:
                calls += 1
                try:
                    r = heyreach("/list/GetLeadsFromList",
                                 {"listId": int(lid), "offset": off, "limit": _HEY_PAGE})
                except Exception as e:  # noqa: BLE001 — one slow list must not kill the sweep
                    out["errors"].append(f"leads list {lid}@{off}: {str(e)[:120]}")
                    break
                items = (r or {}).get("items") or []
                n += len(items)
                c += _hey_snap_many("heyreach_leads",
                                    "container_type,container_id,member_key,content_hash",
                                    [_hey_row({"container_type": "list",
                                               "container_id": str(lid),
                                               "member_key": _member_key(it)}, it)
                                     for it in items])
                if len(items) < _HEY_PAGE:
                    break
                off += _HEY_PAGE
                time.sleep(_HEY_SLEEP_S)
        return n, c

    def _conversations():
        n = c = 0
        buf: list = []
        for it in _hey_pages("/inbox/GetConversationsV2", {"filters": {}}):
            n += 1
            buf.append(_hey_row({"conversation_key": str(it.get("id") or _member_key(it))}, it))
            if len(buf) >= _HEY_PAGE:
                c += _hey_snap_many("heyreach_conversations",
                                    "conversation_key,content_hash", buf)
                buf = []
        c += _hey_snap_many("heyreach_conversations", "conversation_key,content_hash", buf)
        return n, c

    sweep("accounts", _accounts)
    sweep("lists", _lists)
    sweep("campaigns", _campaigns)
    sweep("stats", _stats)
    sweep("leads", _leads)
    sweep("conversations", _conversations)
    out["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:  # durable, queryable record of every sync run (best-effort)
        sb("POST", "app_activity_log",
           {"actor": "heyreach_sync", "endpoint": "/api/cron/heyreach-sync",
            "action": "sync", "entity": "heyreach", "payload": out},
           prefer="return=representation")
    except Exception:  # noqa: BLE001
        pass
    return out


def _heyreach_sync_bg():
    if not _HEYREACH_SYNC_LOCK.acquire(blocking=False):
        return  # a prior sync is still running — skip this one
    try:
        heyreach_sync()
    finally:
        _HEYREACH_SYNC_LOCK.release()


# ── Smartlead mailbox → Supabase daily sweep (pg_cron → pg_net → POST
# /api/cron/mailbox-sync). Was a render.yaml cron job, but this service isn't
# Blueprint-managed so that job never existed in Render — it ran exactly once
# (the manual 2026-07-08 test) and then never again. Same fix as the signal
# autopull: schedule it through the mechanism that provably fires here.
_MAILBOX_SYNC_LOCK = threading.Lock()
# ── Backstop reply-sync (pg_cron → pg_net → POST /api/cron/reply-sync, ~3 min) ─
# Pulls the Smartlead master inbox for replies since a stored watermark and
# feeds each unseen one to the SAME Make categoriser the webhook uses, so
# Supabase `replies` becomes the complete single source of truth (incl.
# subsequence + webhook-lagged replies). Dedup is exact — see setter.run_reply_sync.
_REPLY_SYNC_LOCK = threading.Lock()


def _reply_sync_bg():
    if not _REPLY_SYNC_LOCK.acquire(blocking=False):
        return  # a prior pull is still running — skip this tick
    try:
        res = setter.run_reply_sync()
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/cron/reply-sync",
            "action": "reply_sync_done" if res.get("ok") else "reply_sync_failed",
            "entity": "replies", "payload": res})
        # Positive-thread re-reply sweep rides the same tick, self-throttled to
        # ~15 min inside run_positive_resweep (the watermark backstop above is
        # blind to NEW replies on OLD threads — Smartlead's replyTimeBetween
        # indexes threads by FIRST reply time; see setter.py for the proof).
        res2 = setter.run_positive_resweep()
        if not res2.get("skipped"):
            sb("POST", "app_activity_log",
               {"actor": "cron", "endpoint": "/api/cron/reply-sync",
                "action": ("positive_resweep_done" if res2.get("ok")
                           else "positive_resweep_failed"),
                "entity": "replies", "payload": res2})
    except Exception as e:  # noqa: BLE001 — record, never crash the thread
        print(f"[reply-sync] FAILED: {e}", file=sys.stderr)
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/cron/reply-sync",
            "action": "reply_sync_failed", "entity": "replies",
            "payload": {"error": str(e)[:300]}})
    finally:
        _REPLY_SYNC_LOCK.release()


# ── Positive-card notify (categoriser → client-card hook, Smartlead bypass) ──
# Smartlead's own LEAD_CATEGORY_UPDATED webhook delivery lags 50min–11h
# (measured 2026-07-15/16), so the client "New Positive Response" Slack cards
# (Make scenario 8946472, hook 4001002) arrived hours late or piled up. The
# Make categoriser (9251436) now calls this endpoint the moment it sets a
# positive category; we rebuild the same payload Smartlead would send — from
# live Smartlead data — stamped navreo_source=categoriser, and 8946472 drops
# unstamped LEAD_CATEGORY_UPDATED events so the laggy native deliveries can
# never double-post.
POSITIVE_CARD_HOOK = "https://hook.eu2.make.com/qt3b07kefg9ogusrgd044qh1uae7hu27"


def compose_positive_card_payload(lead: dict, history: list, campaign_id, category: str) -> dict:
    """Pure compose: Smartlead LEAD_CATEGORY_UPDATED shape from a /leads/
    lookup + message-history, covering every field scenario 8946472 reads
    (lead_data.*, campaign_name, client_id, history, last_reply, app_url,
    lead_id, from_email, lead_category.new_name)."""
    lcd = lead.get("lead_campaign_data") or []
    row = next((c for c in lcd if str(c.get("campaign_id")) == str(campaign_id)), {})
    hist = [{
        "type": str(m.get("type") or "").upper(),
        "time": m.get("time"),
        "subject": m.get("subject"),
        "email_body": m.get("email_body") or m.get("body") or "",
        "stats_id": m.get("stats_id"),
        "message_id": m.get("message_id"),
    } for m in history if isinstance(m, dict)]
    hist.sort(key=lambda m: m["time"] or "")
    replies = [m for m in hist if m["type"] == "REPLY"]
    last_reply = replies[-1] if replies else {}
    lead_map_id = row.get("campaign_lead_map_id")
    return {
        "event_type": "LEAD_CATEGORY_UPDATED",
        "navreo_source": "categoriser",
        "campaign_id": campaign_id,
        "campaign_name": row.get("campaign_name") or "",
        "campaign_status": row.get("campaign_status") or "",
        "client_id": row.get("client_id"),
        "lead_id": lead.get("id"),
        "sl_lead_email": lead.get("email") or "",
        "lead_email": lead.get("email") or "",
        # The sending-mailbox address isn't in the /leads/ or history payloads;
        # 8946472 only renders it, so an empty string degrades gracefully.
        "from_email": "",
        "app_url": (f"https://app.smartlead.ai/app/master-inbox?leadMap={lead_map_id}"
                    if lead_map_id else ""),
        "lead_category": {"old_id": None, "old_name": None,
                          "new_id": None, "new_name": category},
        "lead_data": {
            "email": lead.get("email") or "",
            "first_name": lead.get("first_name") or "",
            "last_name": lead.get("last_name") or "",
            "company_name": lead.get("company_name") or "",
            "website": lead.get("website") or "",
            "linkedin_profile": lead.get("linkedin_profile") or "",
            "location": lead.get("location") or "",
            "phone_number": lead.get("phone_number") or "",
            "custom_fields": lead.get("custom_fields") or {},
        },
        "history": hist[-50:],
        "last_reply": {
            "type": "REPLY",
            "time": last_reply.get("time"),
            "email_body": last_reply.get("email_body") or "",
            "stats_id": last_reply.get("stats_id"),
            "message_id": last_reply.get("message_id"),
        },
        "reply_message": {"time": last_reply.get("time"),
                          "text": setter.clean_body(last_reply.get("email_body") or "")[:4000]},
    }


def positive_card_notify(campaign_id, email: str, category: str) -> dict:
    """Fetch lead + thread from Smartlead, compose the card payload, POST it
    to the client-card hook. Two attempts; failures land in app_activity_log
    (actor='positive_card') so a miss is visible, never silent."""
    lead_resp = setter._sl_get("/leads/", {"email": email})
    lead = None
    if isinstance(lead_resp, dict):
        lead = lead_resp.get("lead") if isinstance(lead_resp.get("lead"), dict) else lead_resp
    elif isinstance(lead_resp, list) and lead_resp:
        first = lead_resp[0]
        lead = first.get("lead") if isinstance(first, dict) and isinstance(first.get("lead"), dict) else first
    if not isinstance(lead, dict) or not lead.get("id"):
        return {"ok": False, "error": "lead not found in Smartlead"}
    hist_resp = setter._sl_get(f"/campaigns/{campaign_id}/leads/{lead['id']}/message-history")
    hist = hist_resp.get("history") if isinstance(hist_resp, dict) else hist_resp
    payload = compose_positive_card_payload(lead, hist if isinstance(hist, list) else [],
                                            campaign_id, category)
    err = ""
    for _ in range(2):
        try:
            http_json("POST", POSITIVE_CARD_HOOK, {}, payload)
            return {"ok": True, "campaign_id": campaign_id, "email": email,
                    "category": category, "client_id": payload.get("client_id"),
                    "campaign_name": payload.get("campaign_name")}
        except ValueError:
            # Make webhooks answer a bare "Accepted" (non-JSON 2xx) — that IS success.
            return {"ok": True, "campaign_id": campaign_id, "email": email,
                    "category": category, "client_id": payload.get("client_id"),
                    "campaign_name": payload.get("campaign_name")}
        except Exception as e:  # noqa: BLE001 — retry once, then report
            err = str(e)[:300]
    sb("POST", "app_activity_log",
       {"actor": "positive_card", "endpoint": "/api/notify/positive-card",
        "action": "card_notify_failed", "entity": "replies",
        "payload": {"campaign_id": campaign_id, "email": email,
                    "category": category, "error": err}})
    return {"ok": False, "error": err}


def _mailbox_sync_bg():
    if not _MAILBOX_SYNC_LOCK.acquire(blocking=False):
        return  # a prior sweep is still running — skip this one
    try:
        import sync_mailboxes  # lazy: circular-safe (module imports server)
        try:
            sync_mailboxes.main()
            code = 0
        except SystemExit as se:  # main() ends via sys.exit(); 0 = verified success
            code = int(se.code or 0)
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/cron/mailbox-sync",
            "action": "mailbox_sync_done" if code == 0 else "mailbox_sync_failed",
            "entity": "mailboxes", "payload": {"exit": code}})
        # Going-forward capture of the fleet day-by-day record (sent / replies /
        # reply-rate / positives). Runs on the same daily schedule; refreshes a
        # trailing window so late-corrected days settle. Best-effort — a Smartlead
        # hiccup here never fails the mailbox sweep.
        try:
            fs = fleet_stats_sync_recent(14)
            sb("POST", "app_activity_log",
               {"actor": "cron", "endpoint": "/api/cron/mailbox-sync",
                "action": "fleet_stats_done" if fs.get("ok") else "fleet_stats_failed",
                "entity": "fleet_daily_stats", "payload": fs})
        except Exception as fe:  # noqa: BLE001
            print(f"[fleet-stats] FAILED: {fe}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — record, never crash the thread
        print(f"[mailbox-sync] FAILED: {e}", file=sys.stderr)
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/cron/mailbox-sync",
            "action": "mailbox_sync_failed", "entity": "mailboxes",
            "payload": {"error": str(e)[:300]}})
    finally:
        _MAILBOX_SYNC_LOCK.release()


_SETTER_POLL_LOCK = threading.Lock()


def _setter_poll_bg():
    if not _SETTER_POLL_LOCK.acquire(blocking=False):
        return  # a prior sweep is still running — skip this one
    try:
        summary = setter.run_poll()
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/setter/poll",
            "action": "setter_poll_done", "entity": "setter_queue", "payload": summary})
    except Exception as e:  # noqa: BLE001 — record, never crash the thread
        print(f"[setter-poll] FAILED: {e}", file=sys.stderr)
        sb("POST", "app_activity_log",
           {"actor": "cron", "endpoint": "/api/setter/poll",
            "action": "setter_poll_failed", "entity": "setter_queue",
            "payload": {"error": str(e)[:300]}})
    finally:
        _SETTER_POLL_LOCK.release()


# ── HTTP plumbing ────────────────────────────────────────────────────────

ROUTES = {
    "/api/preview/hiring": preview_hiring,
    "/api/preview/companies": preview_companies,
    "/api/preview/lookalike": preview_lookalike,
    "/api/preview/people": preview_people,
    "/api/suggest-location": suggest_location,
    "/api/tam-map": tam_map,
    "/api/strategy-map": strategy_map_start,
    "/api/clients": save_client,
    "/api/client-prefill": client_prefill,
    "/api/role-suggest": role_suggest,
    "/api/role-feedback": role_feedback,
    "/api/sources": save_draft,
    "/api/sources/duplicate": duplicate_source,
    "/api/sources/update": update_source,
    "/api/sources/pull": pull_source,
    "/api/sources/provision-engagement": provision_engagement_source,
    "/api/trigify-webhook": trigify_webhook,
    "/api/qa-history": save_qa_run,
    "/api/campaign-drafts": save_campaign_draft,
    "/api/campaign-drafts/duplicate": duplicate_campaign_draft,
    "/api/campaign-drafts/update": update_campaign_draft,
    "/api/campaign-drafts/restore": restore_campaign_draft,
    "/api/campaign-drafts/purge": purge_campaign_draft,
}


# ── Live deliverability audit cache (background runner) ──────────────────────
# The audit backend's POST /api/run does a full live Smartlead sweep and takes
# ~4 minutes — far too long to hold a browser->proxy request open. So we run it
# server-side in a daemon thread and cache the result: the tab reads the cached
# blob instantly via GET /api/deliverability/_audit and asks for a refresh via
# POST /api/deliverability/_audit/refresh only when it's stale/missing. All other
# /api/deliverability/* calls (inboxes, domain-health, actions…) still stream
# through the plain _proxy_deliverability() forwarder.
_DELIV_AUDIT = {"blob": None, "ts": 0.0, "running": False, "error": None, "restore_tried": False}
_DELIV_AUDIT_LOCK = threading.Lock()
_DELIV_AUDIT_TTL_S = 7200  # 2h refresh cadence (owner spec 2026-07-11); hourly cron tick no-ops while fresh


def _deliv_fix_batch_stats(blob):
    """Replace batchStats' sent/reply/bounce with sweep-delta truth.

    The audit backend derives per-batch Sent(7d)/Reply%/Bounce% from its
    domain-health row set, which is hard-capped at ~59 domains — verified live
    2026-07-10: batch sends summed to 18,765 while the fleet sent 85,292 in the
    same window (78% unattributed), and the navreo maildoso pool showed "—"
    while actually sending ~600/day across 38 small domains that never crack
    the top-59. Mailbox/warmup/blacklist columns are accurate; only the
    performance columns lie.

    Correction: per-mailbox deltas between the two most recent daily sweeps
    within the last 8 days (mailbox_stats_daily.sent_30d/replies_30d/
    bounces_30d are trailing-30d counters, so newest-minus-oldest ≈ sends in
    that gap; sends aging out of the 30d window can only UNDER-count, never
    invent). Pools are keyed person+provider, matched to the backend's batch
    names, which embed the same person slug + provider suffix. Skips silently
    (backend numbers kept) when fewer than 2 sweeps exist or Supabase is down.
    Stamps blob["batchWindowDays"] so the UI can label the real window."""
    try:
        from datetime import date, timedelta
        if not isinstance(blob, dict) or not isinstance(blob.get("batchStats"), list):
            return
        cutoff = (date.today() - timedelta(days=8)).isoformat()
        dates = sb("GET", f"mailbox_stats_daily?select=stat_date&stat_date=gte.{cutoff}"
                          "&order=stat_date.desc&limit=1", prefer="return=representation")
        if not dates:
            return
        newest = dates[0]["stat_date"]
        older = sb("GET", f"mailbox_stats_daily?select=stat_date&stat_date=gte.{cutoff}"
                          f"&stat_date=lt.{newest}&order=stat_date.asc&limit=1",
                   prefer="return=representation")
        if not older:
            return  # only one sweep so far — no delta window yet
        base = older[0]["stat_date"]
        stats = sb_get_all("mailbox_stats_daily?select=smartlead_id,stat_date,sent_30d,replies_30d,bounces_30d"
                           f"&stat_date=in.({base},{newest})")
        boxes = sb_get_all("mailboxes?select=smartlead_id,from_name,smtp_host,tags")
        if not stats or not boxes:
            return
        def pool_of(m):
            person = (m.get("from_name") or "?").strip().lower().replace(" ", "-")
            blobtags = str(m.get("tags") or "").lower()
            host = (m.get("smtp_host") or "").lower()
            if "maildoso" in host or "maildoso" in blobtags:
                prov = "maildoso"
            elif "boomerang" in blobtags:
                prov = "boomerang"
            else:
                prov = ""
            return person, prov
        pools = {m["smartlead_id"]: pool_of(m) for m in boxes}
        per_box = {}
        for s in stats:
            row = per_box.setdefault(s["smartlead_id"], {})
            row[s["stat_date"]] = s
        agg = {}
        for sid, by_date in per_box.items():
            a, b = by_date.get(base), by_date.get(newest)
            if not a or not b or sid not in pools:
                continue
            key = pools[sid]
            d = agg.setdefault(key, {"sent": 0, "replies": 0, "bounces": 0})
            d["sent"] += max(0, (b.get("sent_30d") or 0) - (a.get("sent_30d") or 0))
            d["replies"] += max(0, (b.get("replies_30d") or 0) - (a.get("replies_30d") or 0))
            d["bounces"] += max(0, (b.get("bounces_30d") or 0) - (a.get("bounces_30d") or 0))
        from datetime import datetime as _dt
        window_days = ( _dt.fromisoformat(newest) - _dt.fromisoformat(base) ).days or 1
        fixed = 0
        for row in blob["batchStats"]:
            name = str(row.get("batch") or "").lower()
            if name == "(no batch)":
                continue
            prov = "maildoso" if name.endswith("maildoso") else ("boomerang" if name.endswith("boomerang") else "")
            match = None
            for (person, p2), vals in agg.items():
                if p2 == prov and person and person in name:
                    match = vals
                    break
            if match is None:
                continue
            row["sent"] = match["sent"]
            row["reply_rate"] = round(100.0 * match["replies"] / match["sent"], 2) if match["sent"] else 0
            row["bounce_rate"] = round(100.0 * match["bounces"] / match["sent"], 2) if match["sent"] else 0
            fixed += 1
        blob["batchWindowDays"] = window_days
        print(f"[deliv] batchStats corrected from sweep deltas ({base}->{newest}, "
              f"{window_days}d window, {fixed} batches)", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — correction is best-effort, never break the audit
        print(f"[deliv] WARNING batchStats correction failed: {e}", file=sys.stderr)


def _deliv_audit_persist(blob):
    """Best-effort: mirror the finished audit blob to Supabase so it survives
    process restarts. Deploys restart the process and wiped the in-memory
    cache 8+ times on 2026-07-10 alone (two sessions shipping), each time
    costing a ~5-min re-audit and a 'no live data' page. sb() is already
    best-effort + retry-once, so an outage can never break the audit path."""
    from datetime import datetime, timezone
    try:
        sb("POST", "deliverability_audit_cache?on_conflict=id",
           {"id": "audit", "blob": blob, "ts": datetime.now(timezone.utc).isoformat()},
           prefer="resolution=merge-duplicates,return=minimal")
    except Exception as e:  # noqa: BLE001
        print(f"[deliv] WARNING audit persist failed: {e}", file=sys.stderr)


def _deliv_iso_epoch(ts: str) -> float:
    """Epoch seconds for a Supabase ISO timestamp, tolerant of fractional-
    second widths fromisoformat rejects on Python <3.11 (e.g. '.31426'). A
    silent 0.0 here made a restored bundle look infinitely stale — the
    freshness check then re-kicked a refresh on every GET."""
    from datetime import datetime
    s = (ts or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        import re
        try:
            s = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], s)
            return datetime.fromisoformat(s).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0


def _deliv_audit_restore():
    """One attempt per process lifetime: if the in-memory cache is empty (fresh
    process), pull the last persisted blob so the page has real data instantly
    instead of a 'no live data' gap until a ~5-min audit completes. Stale-ness
    still applies — the normal TTL logic decides whether to refresh."""
    with _DELIV_AUDIT_LOCK:
        if _DELIV_AUDIT["restore_tried"] or _DELIV_AUDIT["blob"] is not None or _deliv_mock_on():
            return
        # a FAILED restore must not consume the one shot (a Supabase blip at
        # boot used to mean an empty page until the next full audit) — retry
        # on later requests, but at most every 30s
        if time.time() - _DELIV_AUDIT.get("restore_last_try", 0.0) < 30:
            return
        _DELIV_AUDIT["restore_last_try"] = time.time()
    from datetime import datetime
    try:
        rows = sb("GET", "deliverability_audit_cache?id=eq.audit&select=blob,ts", prefer="return=representation")
        if rows is not None:  # sb() returns None (not an exception) on failure —
            # only a definitive read (row present or absent) stops the retries
            with _DELIV_AUDIT_LOCK:
                _DELIV_AUDIT["restore_tried"] = True
        if rows and isinstance(rows, list) and rows[0].get("blob"):
            ts = rows[0].get("ts") or ""
            epoch = _deliv_iso_epoch(ts)
            with _DELIV_AUDIT_LOCK:
                if _DELIV_AUDIT["blob"] is None:  # a live run may have landed meanwhile
                    _DELIV_AUDIT.update(blob=rows[0]["blob"], ts=epoch)
            print(f"[deliv] audit blob restored from Supabase (stored {ts})", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[deliv] WARNING audit restore failed: {e}", file=sys.stderr)


def _deliv_mock_on() -> bool:  # DELIV_MOCK
    """True only when DELIV_MOCK=1 is set in the environment — the single gate
    every mock hook below checks. Absent (prod default) → always False, so
    every gated block below is a dead no-op and behavior is byte-for-byte
    unchanged."""
    return os.environ.get("DELIV_MOCK") == "1"


_DELIV_REST_DAYS_MS = 7 * 86400 * 1000


def _deliv_fix_resting_due(dh):
    """The audit backend's `restingDue` map holds the timestamp a domain was
    PUT to rest (pause moment, ms) — not when the rest ends. The dashboard
    renders the value as a due-back date, so a freshly-rested domain flipped
    to "due now" as soon as a domain-health refetch replaced the client's
    local 7-day clock (verified live 2026-07-10: all 83 values sat in the
    past, each equal to its own pause moment). Shift every value to
    rested_at + 7 days on the way through, so all clients see the 7-day
    pause the warm-up dialog promises. If the backend ever starts sending
    real end dates, drop this shift."""
    if isinstance(dh, dict) and isinstance(dh.get("restingDue"), dict):
        dh["restingDue"] = {k: v + _DELIV_REST_DAYS_MS
                            for k, v in dh["restingDue"].items()
                            if isinstance(v, (int, float))}


def _deliv_audit_run_bg():
    """Fire the ~4-min live audit against the backend once; store blob or error."""
    if _deliv_mock_on():  # DELIV_MOCK — fake a short "run", then store a fresh mock blob
        try:
            secs = mock_deliv.scenario_get("audit_run_secs", 3) or 3
            time.sleep(secs)
            blob = mock_deliv.run_audit_blob()
            _deliv_fix_resting_due((blob or {}).get("domainHealth"))  # same shift as the live path
            with _DELIV_AUDIT_LOCK:
                _DELIV_AUDIT.update(blob=blob, ts=time.time(), running=False, error=None)
            _deliv_bundle_start(force=True)  # mock bundle rides the same refresh as prod
        except Exception as e:  # noqa: BLE001 — running=True must never outlive the thread
            with _DELIV_AUDIT_LOCK:
                _DELIV_AUDIT.update(running=False, error=str(e)[:300])
        return
    import base64, urllib.error  # noqa: F401 — urllib.error referenced via except below
    auth = os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or ""
    if ":" not in auth:
        with _DELIV_AUDIT_LOCK:
            _DELIV_AUDIT.update(running=False, error="unconfigured")
        return
    try:
        req = urllib.request.Request(
            "https://navreo-email-deliverability-audit.onrender.com/api/run", data=b"", method="POST")
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        req.add_header("Content-Type", "application/json")
        # 2026-07-09: full audits started overrunning the old 330s cap (Smartlead
        # slows under load), leaving the cache blob-less and the UI stuck kicking
        # refreshes forever — give the run real headroom.
        with urllib.request.urlopen(req, timeout=600, context=SSL_CTX) as resp:
            blob = json.loads(resp.read())
        _deliv_fix_resting_due((blob or {}).get("domainHealth"))
        _deliv_fix_batch_stats(blob)  # replace top-59-domain batch metrics with sweep-delta truth
        with _DELIV_AUDIT_LOCK:
            _DELIV_AUDIT.update(blob=blob, ts=time.time(), running=False, error=None)
        _deliv_audit_persist(blob)  # survives the next deploy/restart
        _snapshot_from_blob(blob)  # daily fleet-count row for the trends header
        _deliv_bundle_start(force=True)  # keep manager views/windows coherent with the fresh blob
    except Exception as e:  # noqa: BLE001 — record the failure for the UI; never crash the thread
        with _DELIV_AUDIT_LOCK:
            _DELIV_AUDIT.update(running=False, error=str(e)[:300])


def _deliv_audit_start(force=False):
    """Kick a background refresh unless one's already running (or cache is fresh
    and not forced). Returns a small state dict for the caller."""
    _deliv_audit_restore()  # fresh process: recover the last persisted blob first
    with _DELIV_AUDIT_LOCK:
        if _DELIV_AUDIT["running"]:
            return {"started": False, "running": True}
        fresh = _DELIV_AUDIT["blob"] is not None and (time.time() - _DELIV_AUDIT["ts"]) < _DELIV_AUDIT_TTL_S
        if fresh and not force:
            return {"started": False, "running": False, "fresh": True}
        _DELIV_AUDIT.update(running=True, error=None)
    threading.Thread(target=_deliv_audit_run_bg, daemon=True).start()
    return {"started": True, "running": True}


# ── Live deliverability BUNDLE cache (manager views + domain-health windows) ──
# The manager's per-view GET /inboxes and per-window GET /domain-health each
# round-trip the audit backend live (45s / 87s measured on prod 2026-07-11,
# worse while the ~4-min sweep runs) — that is what made sub-tab clicks look
# dead for minutes. Same medicine as _DELIV_AUDIT: pull everything the manager
# can show ONCE in a background thread, serve it from cache instantly, refresh
# behind the scenes. Re-pulled after every successful audit run (so blob and
# bundle stay coherent) and covered by the hourly /api/cron/audit-refresh kick.
# Views deliberately exclude "sending"/"all": the backend truncates at 2,000
# rows with no pagination (probed live: limit/offset are ignored; batch tags
# overlap so partitioning can't reach the 7,997-box fleet either) and the
# four manager flows only need the small actionable views.
_DELIV_BUNDLE_VIEWS = ("warmupoff", "inwarmup", "rested", "reconnect", "blocked")
_DELIV_BUNDLE_WINDOWS = (7, 14, 30)
_DELIV_BUNDLE = {"data": None, "ts": 0.0, "running": False, "error": None, "restore_tried": False}
_DELIV_BUNDLE_LOCK = threading.Lock()


def _deliv_backend_get(rest: str, timeout: int = 240):
    """Authed GET against the audit backend (or the mock fleet under
    DELIV_MOCK=1) from a background thread — the request-handler proxy can't
    be used off-request. Returns the parsed JSON body or raises."""
    if _deliv_mock_on():
        status, obj = mock_deliv.handle_proxy("GET", rest, None)
        if status != 200:
            raise RuntimeError(f"mock {rest} -> {status}")
        return obj
    import base64
    auth = os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or ""
    if ":" not in auth:
        raise RuntimeError("unconfigured")
    req = urllib.request.Request(
        "https://navreo-email-deliverability-audit.onrender.com/api/" + rest, method="GET")
    req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read())


def _deliv_bundle_persist(data):
    from datetime import datetime, timezone
    try:
        sb("POST", "deliverability_audit_cache?on_conflict=id",
           {"id": "bundle", "blob": data, "ts": datetime.now(timezone.utc).isoformat()},
           prefer="resolution=merge-duplicates,return=minimal")
    except Exception as e:  # noqa: BLE001
        print(f"[deliv] WARNING bundle persist failed: {e}", file=sys.stderr)


def _deliv_bundle_restore():
    with _DELIV_BUNDLE_LOCK:
        if _DELIV_BUNDLE["restore_tried"] or _DELIV_BUNDLE["data"] is not None or _deliv_mock_on():
            return
        # failed restores retry (see _deliv_audit_restore) — capped at every 30s
        if time.time() - _DELIV_BUNDLE.get("restore_last_try", 0.0) < 30:
            return
        _DELIV_BUNDLE["restore_last_try"] = time.time()
    from datetime import datetime
    try:
        rows = sb("GET", "deliverability_audit_cache?id=eq.bundle&select=blob,ts", prefer="return=representation")
        if rows is not None:  # sb() returns None on failure — see audit restore
            with _DELIV_BUNDLE_LOCK:
                _DELIV_BUNDLE["restore_tried"] = True
        if rows and isinstance(rows, list) and rows[0].get("blob"):
            # Belt-and-braces vs the mock-poisoning incident: refuse any
            # persisted bundle stamped mock, whatever wrote it.
            if isinstance(rows[0]["blob"], dict) and rows[0]["blob"].get("mock"):
                print("[deliv] ignoring mock-stamped bundle in Supabase", file=sys.stderr)
                return
            ts = rows[0].get("ts") or ""
            epoch = _deliv_iso_epoch(ts)
            with _DELIV_BUNDLE_LOCK:
                if _DELIV_BUNDLE["data"] is None:
                    _DELIV_BUNDLE.update(data=rows[0]["blob"], ts=epoch)
            print(f"[deliv] bundle restored from Supabase (stored {ts})", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[deliv] WARNING bundle restore failed: {e}", file=sys.stderr)


def _deliv_resting_ledger_sync(rested_doms, allow_delete=True):
    """Authoritative due-back dates. The audit backend RE-STAMPS its
    restedAt/restingDue values on every sweep (verified live 2026-07-11:
    1,997/2,000 rested mailboxes carried the latest sweep's timestamp), so a
    +7d shift of its values reads "due in 7d" forever and nothing ever comes
    due. This ledger records when WE first saw each domain rested and derives
    due = first_rested_at + 7d. Sync: new rested domains are inserted at now
    (accurate to one refresh interval); restored domains are deleted so a
    later re-rest starts a fresh clock (skipped when the rested view arrived
    truncated — a missing row must not reset a domain's clock).
    Returns {domain: due_epoch_ms}."""
    from datetime import datetime, timezone
    rows = sb_get_all("deliverability_resting_ledger?select=domain,first_rested_at") or []
    have = {str(r.get("domain") or "").lower(): r for r in rows}
    now_iso = datetime.now(timezone.utc).isoformat()
    new = sorted(d for d in rested_doms if d not in have)
    if new:
        sb("POST", "deliverability_resting_ledger?on_conflict=domain",
           [{"domain": d, "first_rested_at": now_iso, "approx": False, "last_seen_at": now_iso}
            for d in new],
           prefer="resolution=ignore-duplicates,return=minimal")
    if allow_delete:
        gone = _safe_domains(sorted(d for d in have if d not in rested_doms))
        for i in range(0, len(gone), 80):
            sb("DELETE", "deliverability_resting_ledger?domain=in.(%s)" % ",".join(gone[i:i + 80]))
    if new or (allow_delete and gone):
        _restore_plan_invalidate()  # ledger changed — restore-plan must re-read
    due = {}
    now_ms = int(time.time() * 1000)
    for d in rested_doms:
        fr = (have.get(d) or {}).get("first_rested_at")
        if fr:
            try:
                due[d] = int(datetime.fromisoformat(str(fr).replace("Z", "+00:00")).timestamp() * 1000) + _DELIV_REST_DAYS_MS
                continue
            except Exception:  # noqa: BLE001
                pass
        due[d] = now_ms + _DELIV_REST_DAYS_MS  # first seen this sweep
    return due


def _deliv_bundle_run_bg():
    """Thread entry — any escape from the inner run must still clear running,
    or the 2h refresh silently wedges forever (same pattern as
    _restore_sweep_run_bg)."""
    try:
        _deliv_bundle_run_bg_inner()
    except Exception as e:  # noqa: BLE001 — running=True must never outlive the thread
        with _DELIV_BUNDLE_LOCK:
            _DELIV_BUNDLE.update(running=False, error=str(e)[:300])


def _deliv_bundle_run_bg_inner():
    """Pull the manager's five actionable views + three domain-health windows
    from the backend, sequentially (its Smartlead budget is shared with the
    sweep — parallel fan-out is what used to starve it). Partial results are
    kept: one failed pull records its error but never voids the others."""
    from datetime import date, timedelta
    blob_dh = ((_DELIV_AUDIT.get("blob") or {}).get("domainHealth") or {})
    min_sent = blob_dh.get("minSent", 500)
    cutoff = blob_dh.get("cutoff", 0.8)
    out = {"views": {}, "dh": {}, "errors": {}, "minSent": min_sent, "cutoff": cutoff,
           "mock": _deliv_mock_on()}
    for v in _DELIV_BUNDLE_VIEWS:
        try:
            out["views"][v] = _deliv_backend_get(f"inboxes?view={v}&batch=")
        except Exception as e:  # noqa: BLE001
            out["errors"][v] = str(e)[:200]
    today = date.today()
    for days in _DELIV_BUNDLE_WINDOWS:
        try:
            dh = _deliv_backend_get(
                "domain-health?start=%s&end=%s&minSent=%s&cutoff=%s"
                % ((today - timedelta(days=days)).isoformat(), today.isoformat(), min_sent, cutoff))
            _deliv_fix_resting_due(dh)  # same pause-moment -> due-back shift as the blob path
            out["dh"][str(days)] = dh
        except Exception as e:  # noqa: BLE001
            out["errors"]["dh" + str(days)] = str(e)[:200]
    # Per-domain mailbox counts, so the floor view can show the blast radius
    # of "Warm up domain" BEFORE the click. The backend's inboxes endpoint
    # truncates at 2,000 rows, so live counts come from the Supabase mailboxes
    # mirror (full fleet, daily-synced); mock mode counts its own fake fleet.
    try:
        boxes = {}
        if _deliv_mock_on():
            for r in (_deliv_backend_get("inboxes?view=all&batch=").get("rows") or []):
                d = (r.get("domain") or "").lower()
                if d:
                    boxes[d] = boxes.get(d, 0) + 1
        else:
            for r in sb_get_all("mailboxes?select=domain") or []:
                d = (r.get("domain") or "").lower()
                if d:
                    boxes[d] = boxes.get(d, 0) + 1
        out["domainBoxes"] = boxes
    except Exception as e:  # noqa: BLE001
        out["errors"]["domainBoxes"] = str(e)[:200]
    # Due-back dates for every rested domain on display — ledger-derived in
    # live mode; in mock mode straight from the fake fleet's restedAt (those
    # ARE true pause moments, unlike the real backend's).
    try:
        rested_rows = ((out["views"].get("rested") or {}).get("rows")) or []
        if _deliv_mock_on():
            first = {}
            for r in rested_rows:
                d, ra = (r.get("domain") or "").lower(), r.get("restedAt")
                if d and ra:
                    first[d] = min(first.get(d, ra), ra)
            out["restDue"] = {d: v + _DELIV_REST_DAYS_MS for d, v in first.items()}
        else:
            rested_doms = {(r.get("domain") or "").lower() for r in rested_rows if r.get("domain")}
            blob_resting = ((_DELIV_AUDIT.get("blob") or {}).get("domainHealth") or {}).get("resting") or {}
            rested_doms |= {str(d).lower() for d in blob_resting}
            # Warm-up ENTRY stamps too (owner ruling 2026-07-15): freshly-warming
            # domains (inwarmup view — building reputation, never "rested") get a
            # ledger row the first sweep we see them, so EVERY domain in the
            # In-warm-up union carries due = first seen + 7d, one clock for the
            # whole tab. ignore-duplicates keeps established rest clocks intact.
            warming_rows = ((out["views"].get("inwarmup") or {}).get("rows")) or []
            union_doms = rested_doms | {(r.get("domain") or "").lower()
                                        for r in warming_rows if r.get("domain")}
            # A FAILED pull of EITHER view must never look like "those domains
            # left warm-up" — that path mass-deleted the ledger and reset every
            # domain's rest clock on one flaky backend refresh. Same guard for
            # truncation: a missing row must not reset a domain's clock.
            trunc = any(bool((out["views"].get(v) or {}).get("truncated"))
                        for v in ("rested", "inwarmup"))
            out["restDue"] = _deliv_resting_ledger_sync(
                union_doms,
                allow_delete=("rested" in out["views"]) and ("inwarmup" in out["views"]) and not trunc)
    except Exception as e:  # noqa: BLE001
        out["errors"]["restDue"] = str(e)[:200]
    # A partial refresh must not clobber keys the last complete bundle had:
    # carry forward every view/window that ERRORED this sweep (keyed on error
    # presence, never on emptiness, so a legitimately-emptied view is not
    # resurrected). Mock/live bundles never merge into each other.
    if out["errors"]:
        with _DELIV_BUNDLE_LOCK:
            prev = _DELIV_BUNDLE["data"] if isinstance(_DELIV_BUNDLE["data"], dict) else None
        if prev and bool(prev.get("mock")) == bool(out.get("mock")):
            for v in _DELIV_BUNDLE_VIEWS:
                if v in out["errors"] and v in (prev.get("views") or {}):
                    out["views"][v] = prev["views"][v]
            for dkey in (str(d) for d in _DELIV_BUNDLE_WINDOWS):
                if ("dh" + dkey) in out["errors"] and dkey in (prev.get("dh") or {}):
                    out["dh"][dkey] = prev["dh"][dkey]
            for k in ("domainBoxes", "restDue"):
                if k in out["errors"] and k in prev:
                    out[k] = prev[k]
    ok = bool(out["views"]) or bool(out["dh"])
    err = json.dumps(out["errors"])[:300] if out["errors"] else None
    with _DELIV_BUNDLE_LOCK:
        if ok:
            _DELIV_BUNDLE.update(data=out, ts=time.time(), running=False, error=err)
        else:
            _DELIV_BUNDLE.update(running=False, error=err or "empty bundle")
    # NEVER persist a mock-mode bundle: the Supabase cache row is shared with
    # production, and a local DELIV_MOCK=1 run writing here served fake
    # domains to the live manager (caught on the 2026-07-11 live verify).
    if ok and not _deliv_mock_on():
        _deliv_bundle_persist(out)


def _deliv_bundle_start(force=False):
    """Kick a background bundle refresh unless one's already running (or the
    cache is fresh and not forced). Mirrors _deliv_audit_start."""
    _deliv_bundle_restore()
    if not force and not _deliv_mock_on() and \
            ":" not in (os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or ""):
        return {"started": False, "running": False, "configured": False}
    with _DELIV_BUNDLE_LOCK:
        if _DELIV_BUNDLE["running"]:
            return {"started": False, "running": True}
        fresh = _DELIV_BUNDLE["data"] is not None and (time.time() - _DELIV_BUNDLE["ts"]) < _DELIV_AUDIT_TTL_S
        if fresh and not force:
            return {"started": False, "running": False, "fresh": True}
        # outage cooldown: after a FAILED attempt, unforced kicks (every 10s
        # poll tick hits this) wait 60s before spawning another doomed thread
        if not force and _DELIV_BUNDLE["error"] and \
                (time.time() - _DELIV_BUNDLE.get("last_attempt", 0.0)) < 60:
            return {"started": False, "running": False, "error": _DELIV_BUNDLE["error"]}
        _DELIV_BUNDLE.update(running=True, error=None, last_attempt=time.time())
    threading.Thread(target=_deliv_bundle_run_bg, daemon=True).start()
    return {"started": True, "running": True}


# ── Deliverability trends (30-day health series for the glance header) ──────
# Per-day sent / reply% / bounce% comes straight from Smartlead's day-wise
# analytics (backfills instantly); fleet counts Smartlead can't backfill
# (smtp/imap fails, real blocks, auth misses, blacklists) accrue one row per
# day in deliverability_daily_snapshots, written on every successful audit
# refresh — same writer, no extra cron.
import datetime as _dtmod

_DELIV_TRENDS = {}  # days -> {"data":…, "ts":…} so 7/14/30 toggles stop evicting each other
_DELIV_TRENDS_LOCK = threading.Lock()
_DELIV_TRENDS_BUILDING = set()  # days values with a build in flight (dedupe concurrent firsts)
_DELIV_TRENDS_TTL_S = 7200  # same 2h clock as the audit/bundle caches


def _snapshot_from_blob(blob: dict):
    """Upsert today's fleet-count snapshot from a fresh audit blob. Best-effort:
    a Supabase outage must never fail the audit refresh that carries it."""
    try:
        row = {
            "snapshot_date": _dtmod.date.today().isoformat(),
            "smtp_fails": int(blob.get("smtp") or 0),
            "imap_fails": int(blob.get("imap") or 0),
            "blocked_real": int(blob.get("blockedReal") or 0),
            "spf_miss": int(blob.get("spfMiss") or 0),
            "dkim_miss": int(blob.get("dkimMiss") or 0),
            "dmarc_miss": int(blob.get("dmarcMiss") or 0),
            "blacklisted": len(blob.get("blacklist") or []),
            "inboxes": blob.get("inboxes"), "domains": blob.get("domains"),
            "updated_at": _dtmod.datetime.utcnow().isoformat() + "Z",
        }
        sb("POST", "deliverability_daily_snapshots?on_conflict=snapshot_date", row,
           prefer="resolution=merge-duplicates,return=minimal")
    except Exception as e:  # noqa: BLE001
        print(f"[trends] snapshot write failed: {e}", file=sys.stderr)


def _deliv_trends_build(days: int) -> dict:
    """Fetch + shape the per-day series. Raises on Smartlead failure — the
    caller keeps serving the previous cached copy in that case."""
    end = _dtmod.date.today()
    start = end - _dtmod.timedelta(days=days - 1)
    url = (f"{SMARTLEAD_BASE}/analytics/day-wise-overall-stats"
           f"?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}"
           f"&start_date={start.isoformat()}&end_date={end.isoformat()}")
    data = http_json("GET", url, {}, timeout=30)
    raw = ((data or {}).get("data") or {}).get("day_wise_stats") or []
    # Smartlead dates come back as "10 Jun" (no year) — key on (day, month);
    # a ≤90-day window can't contain the same day+month twice.
    months = {m: i + 1 for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
    by_daymonth = {}
    for r in raw:
        try:
            d, mon = str(r.get("date", "")).split()
            m = r.get("email_engagement_metrics") or {}
            by_daymonth[(int(d), months.get(mon[:3], 0))] = m
        except (ValueError, AttributeError):
            continue
    # Snapshot rows for the same window (issues series — may be sparse at first).
    snaps = sb("GET", ("deliverability_daily_snapshots"
                       f"?snapshot_date=gte.{start.isoformat()}&order=snapshot_date.asc")) or []
    snap_by_date = {s.get("snapshot_date"): s for s in snaps if isinstance(s, dict)}
    days_out, sent, reply_pct, bounce_pct, issues = [], [], [], [], []
    cur = start
    while cur <= end:
        m = by_daymonth.get((cur.day, cur.month)) or {}
        s = int(m.get("sent") or 0)
        days_out.append(cur.isoformat())
        sent.append(s)
        reply_pct.append(round(int(m.get("replied") or 0) * 100.0 / s, 2) if s else None)
        bounce_pct.append(round(int(m.get("bounced") or 0) * 100.0 / s, 2) if s else None)
        sn = snap_by_date.get(cur.isoformat())
        issues.append(None if sn is None else
                      int(sn.get("smtp_fails") or 0) + int(sn.get("imap_fails") or 0)
                      + int(sn.get("blocked_real") or 0) + int(sn.get("spf_miss") or 0)
                      + int(sn.get("dkim_miss") or 0) + int(sn.get("dmarc_miss") or 0)
                      + int(sn.get("blacklisted") or 0))
        cur += _dtmod.timedelta(days=1)
    return {"series": {"days": days_out, "sent": sent, "reply_pct": reply_pct,
                       "bounce_pct": bounce_pct, "issues": issues},
            "asof": _dtmod.datetime.utcnow().isoformat() + "Z"}


def deliv_trends_get(days: int = 30) -> tuple[dict, int]:
    days = max(7, min(90, days))
    with _DELIV_TRENDS_LOCK:
        ent = _DELIV_TRENDS.get(days)
        if ent and (time.time() - ent["ts"]) < _DELIV_TRENDS_TTL_S:
            return ent["data"], 200
        if days in _DELIV_TRENDS_BUILDING:
            # a concurrent request is already building this window — serve the
            # stale copy if one exists rather than duplicating the Smartlead call
            if ent:
                return ent["data"], 200
        _DELIV_TRENDS_BUILDING.add(days)
    try:
        data = _deliv_trends_build(days)
    except Exception as e:  # noqa: BLE001 — serve stale over erroring if we have one
        with _DELIV_TRENDS_LOCK:
            _DELIV_TRENDS_BUILDING.discard(days)
            ent = _DELIV_TRENDS.get(days)
            if ent:
                return ent["data"], 200
        return {"error": "trends_unavailable", "message": str(e)[:200]}, 502
    with _DELIV_TRENDS_LOCK:
        _DELIV_TRENDS_BUILDING.discard(days)
        _DELIV_TRENDS[days] = {"data": data, "ts": time.time()}
    return data, 200


# ── Fleet daily stats: the permanent day-by-day record in Supabase ──────────
# Sent / replies / reply-rate / positives per calendar day, straight from
# Smartlead's OWN day-wise analytics (same source as the deliverability tab), so
# it's verifiable against Smartlead and outlives Smartlead's UI window. Backfill
# once with a wide range; the mailbox-sync cron re-upserts a trailing window
# every day (going-forward capture + late-correction). Idempotent upsert keyed
# on stat_date. Smartlead dates come back as "6 Jul" (no year) — a within-one-
# calendar-year call keeps (day,month) unique, so we walk the exact date range
# and match by (day,month).
_FLEET_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _fleet_daywise(path: str, start_iso: str, end_iso: str) -> dict:
    """{(day,month): email_engagement_metrics} for a Smartlead day-wise endpoint."""
    url = (f"{SMARTLEAD_BASE}/analytics/{path}"
           f"?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}"
           f"&start_date={start_iso}&end_date={end_iso}")
    data = http_json("GET", url, {}, timeout=45)
    out = {}
    for r in (((data or {}).get("data") or {}).get("day_wise_stats") or []):
        try:
            d, mon = str(r.get("date", "")).split()
            out[(int(d), _FLEET_MONTHS.get(mon[:3], 0))] = r.get("email_engagement_metrics") or {}
        except (ValueError, AttributeError):
            continue
    return out


def fleet_stats_sync(start_iso: str, end_iso: str) -> dict:
    """Pull Smartlead day-wise overall + positive stats for [start,end] (must be
    within ONE calendar year) and upsert public.fleet_daily_stats. Idempotent."""
    from datetime import date as _date, timedelta as _td2
    overall = _fleet_daywise("day-wise-overall-stats", start_iso, end_iso)
    positive = _fleet_daywise("day-wise-positive-reply-stats", start_iso, end_iso)
    if not overall:
        return {"ok": False, "error": "smartlead day-wise returned no data", "upserted": 0}
    start = _date.fromisoformat(start_iso[:10])
    end = _date.fromisoformat(end_iso[:10])
    rows, cur = [], start
    while cur <= end:
        k = (cur.day, cur.month)
        m = overall.get(k) or {}
        sent = int(m.get("sent") or 0)
        replied = int(m.get("replied") or 0)
        bounced = int(m.get("bounced") or 0)
        pos = int((positive.get(k) or {}).get("positive_replied") or 0)
        rows.append({"stat_date": cur.isoformat(), "sent": sent, "replies": replied,
                     "positives": pos, "bounced": bounced,
                     "reply_rate": round(replied * 100.0 / sent, 2) if sent else None,
                     "updated_at": _dtmod.datetime.utcnow().isoformat() + "Z"})
        cur += _td2(days=1)
    n = 0
    for i in range(0, len(rows), 300):
        chunk = rows[i:i + 300]
        r = sb("POST", "fleet_daily_stats?on_conflict=stat_date", chunk,
               prefer="resolution=merge-duplicates,return=minimal")
        if r is None:
            return {"ok": False, "error": "supabase upsert failed", "upserted": n}
        n += len(chunk)
    return {"ok": True, "upserted": n, "start": start.isoformat(), "end": end.isoformat()}


def fleet_stats_sync_recent(days: int = 14) -> dict:
    """Trailing-window refresh for the daily cron. Splits across a year boundary
    if the window straddles Jan 1 (keeps each Smartlead call within one year so
    the yearless 'day month' labels stay unambiguous)."""
    from datetime import date as _date, timedelta as _td2
    end = _date.today()
    start = end - _td2(days=max(1, days) - 1)
    if start.year != end.year:
        a = fleet_stats_sync(start.isoformat(), _date(start.year, 12, 31).isoformat())
        b = fleet_stats_sync(_date(end.year, 1, 1).isoformat(), end.isoformat())
        return {"ok": a.get("ok") and b.get("ok"), "upserted": a.get("upserted", 0) + b.get("upserted", 0)}
    return fleet_stats_sync(start.isoformat(), end.isoformat())


# ── Restore queue + warm-up capacity forecast ────────────────────────────────
# Powers the deliverability page's rebuilt "Restore reminders" tab:
#   GET  /api/restore-plan  — pending restore entries ranked by due date +
#                             per-client 14-day sending-capacity forecast
#   POST /api/restore-live  — one-click return-to-sending: audit-service
#                             warmup-resume + Smartlead campaign attach +
#                             reminder-done + app_activity_log row
# Design facts proven live 2026-07-11:
#   - "Rested" domains come in two shapes: cap-zeroed (saved cap held INSIDE
#     the audit service; its warmup-resume restores it) and warm-up-recovery
#     (caps already live, e.g. Outlook 2/day, but ZERO campaign attachment —
#     attachment is the real sending gate). Restore = warmup-resume + attach.
#   - Smartlead's account list carries no campaign membership; the only truth
#     is GET /campaigns/{id}/email-accounts per ACTIVE campaign (~110 calls),
#     so membership is swept in a background thread and cached below.
#   - No client_id is populated anywhere on accounts (the mailboxes table's
#     campaign_count/client_id columns are all-zero/null) — client is inferred
#     from domain + batch tags by keyword, most-specific first, navreo last.

_RESTORE_SWEEP = {"data": None, "ts": 0.0, "running": False, "error": None}
_RESTORE_SWEEP_LOCK = threading.Lock()
_RESTORE_SWEEP_TTL_S = 30 * 60
_RESTORE_MBX = {"data": None, "ts": 0.0}
_RESTORE_MBX_TTL_S = 15 * 60
# GET /api/restore-plan used to round-trip the audit backend (reminders) and
# Supabase (ledger) on EVERY request — the page's slowest data call (~1.0s,
# 60s-timeout hazard). Both inputs only change via this app's own POSTs
# (restore-live, restore-dismiss) or the bundle refresh, all of which
# invalidate below — so a short TTL cache is safe and drops it to ~ms.
_RESTORE_REM_SWR = {"rems": None, "src": None, "ts": 0.0}
_RESTORE_LEDGER_SWR = {"rows": None, "ts": 0.0}
_RESTORE_PLAN_TTL_S = 300


def _restore_plan_invalidate():
    _RESTORE_REM_SWR.update(rems=None, src=None, ts=0.0)
    _RESTORE_LEDGER_SWR.update(rows=None, ts=0.0)


_DOMAIN_RE = __import__("re").compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def _safe_domains(doms):
    """Strict-hostname filter for values that get joined into PostgREST in.()
    filters — anything else could smuggle filter syntax into the query."""
    return [d for d in doms if isinstance(d, str) and len(d) < 254 and _DOMAIN_RE.match(d)]
_RESTORE_FORECAST_DAYS = 14

_RESTORE_CLIENT_KEYWORDS = (  # order matters — navreo LAST (shared batch tags carry it)
    ("amplif", "Amplifyy"), ("arnic", "Arnic"), ("qwintiq", "Qwintiq"),
    ("heygrand", "HeyGrand"), ("wordbank", "WordBank"), ("asteri", "Asteri"),
    ("grout", "Grout"), ("insurance", "Insurance"), ("boomerang", "Boomerang"),
    ("navreo", "Navreo"),
)


def _restore_client_of(domain: str, tags=None) -> str:
    for hay in ((domain or "").lower(), " ".join(str(t) for t in (tags or [])).lower()):
        for kw, label in _RESTORE_CLIENT_KEYWORDS:
            if kw in hay:
                return label
    return "Other"


def _deliv_backend_json(method: str, rest: str, timeout: float = 60):
    """Server-to-server call to the standalone audit service — same target as
    _proxy_deliverability, minus the HTTP-handler plumbing. Raises on
    missing config so callers can fall back to the cached blob."""
    if _deliv_mock_on():  # DELIV_MOCK — fake fleet, zero network
        status, obj = mock_deliv.handle_proxy(method, rest, b"")
        if status >= 400:
            raise RuntimeError(f"mock deliv {rest} -> {status}")
        return obj
    import base64
    auth = os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or ""
    if ":" not in auth:
        raise RuntimeError("deliverability backend unconfigured (DELIV_AUDIT_AUTH)")
    return http_json(method, "https://navreo-email-deliverability-audit.onrender.com/api/" + rest,
                     {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()},
                     body={} if method == "POST" else None, timeout=timeout)


def _restore_blob() -> dict:
    _deliv_audit_restore()
    with _DELIV_AUDIT_LOCK:
        return _DELIV_AUDIT["blob"] or {}


def _restore_mailboxes():
    """domain -> {accounts:[{id,email,cap}], cap_sum, zero_cap, tags, maildoso}
    from the Supabase `mailboxes` snapshot (daily sweep). Cached 15 min."""
    now = time.time()
    if _RESTORE_MBX["data"] is not None and now - _RESTORE_MBX["ts"] < _RESTORE_MBX_TTL_S:
        return _RESTORE_MBX["data"]
    rows = sb_get_all("mailboxes?select=smartlead_id,email,domain,tags,message_per_day,smtp_host")
    if rows is None:
        return _RESTORE_MBX["data"]  # Supabase outage: stale beats none
    out = {}
    for r in rows:
        dom = (r.get("domain") or "").lower()
        if not dom:
            continue
        m = out.setdefault(dom, {"accounts": [], "cap_sum": 0, "zero_cap": 0,
                                 "tags": set(), "maildoso": False})
        cap = r.get("message_per_day") or 0
        m["accounts"].append({"id": r.get("smartlead_id"), "email": r.get("email"), "cap": cap})
        m["cap_sum"] += cap
        if not cap:
            m["zero_cap"] += 1
        for t in (r.get("tags") or []):
            m["tags"].add(str(t))
        if "maildoso" in ((r.get("smtp_host") or "") + " ".join(m["tags"])).lower():
            m["maildoso"] = True
    for m in out.values():
        m["tags"] = sorted(m["tags"])
    _RESTORE_MBX.update(data=out, ts=now)
    return out


def _restore_sweep_run_bg():
    """Campaign-membership sweep: which accounts sit in which ACTIVE campaigns.
    ~1 call per active campaign, throttled well under the 200/min cap."""
    try:
        camps = _smartlead_json("GET", "/campaigns") or []
        active = [c for c in camps if c.get("status") == "ACTIVE"]
        att = {}   # email(lower) -> {"cap": n, "camps": [ids]}
        for c in active:
            rows = _smartlead_json("GET", f"/campaigns/{c['id']}/email-accounts", timeout=120)
            for a in rows if isinstance(rows, list) else []:
                e = (a.get("from_email") or "").lower()
                if not e:
                    continue
                rec = att.setdefault(e, {"cap": a.get("message_per_day") or 0, "camps": []})
                rec["camps"].append(c["id"])
            time.sleep(0.35)
        data = {"accounts": att,
                "campaigns": {str(c["id"]): (c.get("name") or "").strip() for c in active}}
        with _RESTORE_SWEEP_LOCK:
            _RESTORE_SWEEP.update(data=data, ts=time.time(), running=False, error=None)
    except Exception as e:  # noqa: BLE001 — record, never crash the thread
        print(f"[restore-sweep] FAILED: {e}", file=sys.stderr)
        with _RESTORE_SWEEP_LOCK:
            _RESTORE_SWEEP.update(running=False, error=str(e)[:300])


def _restore_sweep_start(force: bool = False):
    with _RESTORE_SWEEP_LOCK:
        if _RESTORE_SWEEP["running"]:
            return {"started": False, "running": True}
        fresh = _RESTORE_SWEEP["data"] is not None and \
            (time.time() - _RESTORE_SWEEP["ts"]) < _RESTORE_SWEEP_TTL_S
        if fresh and not force:
            return {"started": False, "running": False, "fresh": True}
        _RESTORE_SWEEP.update(running=True, error=None)
    threading.Thread(target=_restore_sweep_run_bg, daemon=True).start()
    return {"started": True, "running": True}


def _restore_reminders():
    """Live reminders from the audit service, cached-blob fallback. Returns
    (reminders, source) — source is 'live' or 'cached'. TTL-cached (5 min,
    invalidated by this app's own reminder-mutating POSTs) so every
    /api/restore-plan GET stops paying a live backend round-trip."""
    if _RESTORE_REM_SWR["rems"] is not None and \
            (time.time() - _RESTORE_REM_SWR["ts"]) < _RESTORE_PLAN_TTL_S:
        return _RESTORE_REM_SWR["rems"], _RESTORE_REM_SWR["src"]
    try:
        rems = _deliv_backend_json("GET", "reminders")
        if isinstance(rems, list):
            _RESTORE_REM_SWR.update(rems=rems, src="live", ts=time.time())
            return rems, "live"
    except Exception as e:  # noqa: BLE001 — unconfigured/down: stale cache, then blob
        print(f"[restore-plan] live reminders unavailable: {e}", file=sys.stderr)
        if _RESTORE_REM_SWR["rems"] is not None:
            return _RESTORE_REM_SWR["rems"], _RESTORE_REM_SWR["src"]
    return (_restore_blob().get("reminders") or []), "cached"


_RESTORE_DISMISS_MOCK = set()  # DELIV_MOCK-only: in-memory stand-in for ledger.dismissed


def _restore_entries():
    """The merged, enriched, due-date-sorted queue. Also returns lookup maps
    reused by restore-live (blacklist rows, mailbox aggregates)."""
    from datetime import date, datetime, timezone
    rems, rem_src = _restore_reminders()
    blob = _restore_blob()
    mbx = _restore_mailboxes() or {}
    bl_doms = {(b.get("domain") or "").lower()
               for b in (blob.get("blacklist") or []) if isinstance(b, dict)}
    pending = [r for r in rems if not r.get("done")]
    covered = {d.lower() for r in rems for d in (r.get("domains") or [])}

    def iso(ms):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()

    entries = []
    for r in pending:
        entries.append({"id": r.get("id"), "domains": r.get("domains") or [],
                        "restoredDate": r.get("restoredDate"), "dueDate": r.get("dueDate"),
                        "source": "reminder"})
    # auto entries: domains resting right now with no reminder row of their
    # own. Dates come from the app's rest LEDGER (first time WE saw the domain
    # rested) — the blob's restingDue is a due date built on backend values
    # that get re-stamped every sweep, which is what produced future
    # "restored" dates and doubled dues on the queue (owner-reported bug,
    # 2026-07-11). Rows the owner dismissed via "Mark added" are skipped; the
    # dismissal dies with the ledger row when the domain stops resting.
    ledger = []
    if not _deliv_mock_on():
        if _RESTORE_LEDGER_SWR["rows"] is not None and \
                (time.time() - _RESTORE_LEDGER_SWR["ts"]) < _RESTORE_PLAN_TTL_S:
            ledger = _RESTORE_LEDGER_SWR["rows"]
        else:
            try:
                ledger = sb_get_all("deliverability_resting_ledger?select=domain,first_rested_at,dismissed") or []
                _RESTORE_LEDGER_SWR.update(rows=ledger, ts=time.time())
            except Exception as e:  # noqa: BLE001 — fall through to the blob path
                print(f"[restore-plan] ledger unavailable: {e}", file=sys.stderr)
    if ledger:
        from datetime import timedelta
        for row in sorted(ledger, key=lambda r: str(r.get("domain") or "")):
            dom = str(row.get("domain") or "").lower()
            if not dom or dom in covered or row.get("dismissed"):
                continue
            try:
                rested = datetime.fromisoformat(str(row["first_rested_at"]).replace("Z", "+00:00")).date()
            except Exception:  # noqa: BLE001
                continue
            entries.append({"id": "auto-" + dom, "domains": [dom],
                            "restoredDate": rested.isoformat(),
                            "dueDate": (rested + timedelta(days=7)).isoformat(),
                            "source": "auto"})
    else:
        # No ledger (mock mode / Supabase down): blob restingDue values are
        # rest+7d due dates — un-shift for the rest date instead of doubling.
        resting = ((blob.get("domainHealth") or {}).get("restingDue") or {})
        for dom, ts in sorted(resting.items()):
            if not isinstance(ts, (int, float)) or dom.lower() in covered \
                    or dom.lower() in _RESTORE_DISMISS_MOCK:
                continue
            entries.append({"id": "auto-" + dom.lower(), "domains": [dom],
                            "restoredDate": iso(ts - _DELIV_REST_DAYS_MS), "dueDate": iso(ts),
                            "source": "auto"})
    today = date.today()
    sweep = None
    with _RESTORE_SWEEP_LOCK:
        if _RESTORE_SWEEP["data"] is not None:
            sweep = _RESTORE_SWEEP["data"]
    for e in entries:
        boxes = cap = zero = attached = 0
        tags, maildoso = [], False
        for d in e["domains"]:
            m = mbx.get(d.lower())
            if not m:
                continue
            boxes += len(m["accounts"])
            cap += m["cap_sum"]
            zero += m["zero_cap"]
            tags += m["tags"]
            maildoso = maildoso or m["maildoso"]
            if sweep:
                attached += sum(1 for a in m["accounts"]
                                if (a.get("email") or "").lower() in sweep["accounts"])
        e.update(mailboxes=boxes, parked_capacity=cap, zero_cap_boxes=zero,
                 maildoso=maildoso,
                 client=_restore_client_of(e["domains"][0] if e["domains"] else "", tags),
                 blacklisted=any(d.lower() in bl_doms for d in e["domains"]),
                 attached_boxes=(attached if sweep else None))
        try:
            due = date.fromisoformat(e.get("dueDate") or "")
            e["days_left"] = (due - today).days
            e["overdue"] = e["days_left"] <= 0
        except ValueError:
            e["days_left"], e["overdue"] = None, False
    entries.sort(key=lambda x: (x.get("dueDate") or "9999-99-99", -(x.get("parked_capacity") or 0)))
    return entries, rem_src, mbx, bl_doms


def _restore_forecast(entries, mbx):
    """Per-client daily projection for the next N days. sending_now = summed
    caps of accounts attached to >=1 ACTIVE campaign (from the sweep — the
    only real membership source); returning = parked caps of entries whose
    due date has passed by that day. Real caps only, never estimates."""
    from datetime import date, timedelta
    sweep = None
    with _RESTORE_SWEEP_LOCK:
        if _RESTORE_SWEEP["data"] is not None:
            sweep = _RESTORE_SWEEP["data"]
        err = _RESTORE_SWEEP["error"]
    if sweep is None:
        st = _restore_sweep_start()
        return {"status": "computing", "running": st.get("running", True), "error": err}
    _restore_sweep_start()  # kick a background refresh when stale; serve current data now
    dom_client = {d: _restore_client_of(d, m["tags"]) for d, m in (mbx or {}).items()}
    sending_now = {}
    for email, rec in sweep["accounts"].items():
        dom = email.rpartition("@")[2]
        c = dom_client.get(dom) or _restore_client_of(dom)
        sending_now[c] = sending_now.get(c, 0) + (rec.get("cap") or 0)
    pend = [e for e in entries if not e.get("blacklisted")]
    parked_now = {}
    for e in pend:
        parked_now[e["client"]] = parked_now.get(e["client"], 0) + (e.get("parked_capacity") or 0)
    clients = sorted(set(sending_now) | set(parked_now),
                     key=lambda c: -(sending_now.get(c, 0) + parked_now.get(c, 0)))
    today = date.today()
    days = []
    for i in range(_RESTORE_FORECAST_DAYS):
        d = today + timedelta(days=i)
        iso = d.isoformat()
        by_client = {}
        for c in clients:
            ret = sum((e.get("parked_capacity") or 0) for e in pend
                      if e["client"] == c and (e.get("dueDate") or "9999") <= iso)
            by_client[c] = {"projected": sending_now.get(c, 0) + ret, "returning": ret}
        days.append({"date": iso, "weekday": d.strftime("%a"), "weekend": d.weekday() >= 5,
                     "byClient": by_client,
                     "total": sum(v["projected"] for v in by_client.values())})
    return {"status": "ready", "clients": clients, "sending_now": sending_now,
            "parked_now": parked_now, "days": days,
            "sweep_age_sec": round(time.time() - _RESTORE_SWEEP["ts"]),
            "zero_cap_note": sum(e.get("zero_cap_boxes") or 0 for e in pend)}


def api_restore_plan():
    entries, rem_src, mbx, _bl = _restore_entries()
    forecast = _restore_forecast(entries, mbx)
    return {"reminders": entries, "forecast": forecast, "reminder_source": rem_src}, 200


def api_restore_live(p: dict):
    """Body {id?, domains?, campaign_ids?, dry_run?, force_early?}. dry_run
    returns the exact per-mailbox plan + campaign suggestions and mutates
    NOTHING. Real run: audit-service warmup-resume per domain, Smartlead
    campaign attach (chunks of 100, per proven process-new path), verified
    re-fetch, reminder-done, one activity-log row. Per-domain errors are
    reported individually — never rolled up as ok."""
    from urllib.parse import quote
    entries, _src, mbx, bl_doms = _restore_entries()
    rid = (p.get("id") or "").strip()
    entry = next((e for e in entries if e["id"] == rid), None) if rid else None
    domains = [d.strip().lower() for d in
               ((entry or {}).get("domains") or p.get("domains") or []) if d and d.strip()]
    if not domains:
        return {"ok": False, "error": "no_domains",
                "message": "No domains to restore — pass id or domains."}, 400
    # Owner ruling 2026-07-15: a blocklist hit FLAGS, it never blocks — the
    # restore proceeds and the response carries the listed domains so the UI
    # and the operator can see exactly what is still on a blocklist.
    blacklist_warning = [d for d in domains if d in bl_doms]
    plans = []
    for d in domains:
        m = (mbx or {}).get(d) or {"accounts": [], "cap_sum": 0, "zero_cap": 0, "tags": [], "maildoso": False}
        plans.append({"domain": d, "mailboxes": len(m["accounts"]),
                      "capacity": m["cap_sum"], "zero_cap_boxes": m["zero_cap"],
                      "maildoso": m["maildoso"],
                      "accounts": [{"id": a["id"], "email": a["email"], "cap": a["cap"]}
                                   for a in m["accounts"]]})
    early = bool(entry and not entry.get("overdue"))
    client = (entry or {}).get("client") or _restore_client_of(domains[0])
    # campaign suggestions: where this client's accounts already sit, biggest first
    suggestions, sweep = [], None
    with _RESTORE_SWEEP_LOCK:
        if _RESTORE_SWEEP["data"] is not None:
            sweep = _RESTORE_SWEEP["data"]
    if sweep:
        counts = {}
        dom_client = {dd: _restore_client_of(dd, mm["tags"]) for dd, mm in (mbx or {}).items()}
        for email, rec in sweep["accounts"].items():
            if (dom_client.get(email.rpartition("@")[2]) or "") != client:
                continue
            for cid in rec["camps"]:
                counts[cid] = counts.get(cid, 0) + 1
        suggestions = [{"id": cid, "name": sweep["campaigns"].get(str(cid), str(cid)),
                        "attached_accounts": n}
                       for cid, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12]]
    if p.get("dry_run"):
        return {"ok": True, "dry_run": True, "client": client, "early": early,
                "plans": plans, "suggestions": suggestions,
                "blacklist_warning": blacklist_warning,
                "entry": {k: entry.get(k) for k in ("id", "dueDate", "source", "attached_boxes")} if entry else None}, 200
    if early and not p.get("force_early"):
        return {"ok": False, "error": "before_due",
                "message": f"Due {entry.get('dueDate')} — not due yet. "
                           "Re-send with force_early to restore anyway."}, 409
    try:
        camp_ids = [int(x) for x in (p.get("campaign_ids") or [])]
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_campaign_ids"}, 400
    if not camp_ids:
        return {"ok": False, "error": "no_campaigns",
                "message": "Pick at least one campaign to restore into."}, 400
    results = []
    for pl in plans:
        r = {"domain": pl["domain"], "resumed": None, "attached_requested": 0,
             "verified_attached": None, "errors": []}
        try:  # 1. audit service clears rested state + restores any zeroed caps
            wr = _deliv_backend_json("POST", "warmup-resume?domain=" + quote(pl["domain"]), timeout=90)
            r["resumed"] = (wr or {}).get("resumed") or (wr or {}).get("reactivated") or 0
        except Exception as e:  # noqa: BLE001
            r["errors"].append("warmup-resume: " + str(e)[:160])
        ids = [a["id"] for a in pl["accounts"] if a.get("id")]
        for cid in camp_ids:  # 2. attach to the chosen campaigns
            try:
                for i in range(0, len(ids), 100):
                    _smartlead_json("POST", f"/campaigns/{cid}/email-accounts",
                                    {"email_account_ids": ids[i:i + 100]})
                r["attached_requested"] += len(ids)
            except Exception as e:  # noqa: BLE001
                r["errors"].append(f"attach {cid}: " + str(e)[:160])
        results.append(r)
    # 3. verify against Smartlead (one re-fetch per chosen campaign)
    try:
        present = set()
        for cid in camp_ids:
            rows = _smartlead_json("GET", f"/campaigns/{cid}/email-accounts", timeout=120)
            present.update(a.get("id") for a in rows if isinstance(rows, list))
        for pl, r in zip(plans, results):
            r["verified_attached"] = sum(1 for a in pl["accounts"] if a.get("id") in present)
    except Exception as e:  # noqa: BLE001
        for r in results:
            r["errors"].append("verify: " + str(e)[:160])
    done_ok = None
    if entry and entry.get("source") == "reminder":  # 4. tick the reminder off
        try:
            _deliv_backend_json("POST", "reminder-done?id=" + quote(str(entry["id"])))
            done_ok = True
        except Exception as e:  # noqa: BLE001
            done_ok = False
            results and results[0]["errors"].append("reminder-done: " + str(e)[:160])
    with _RESTORE_SWEEP_LOCK:  # force the next plan/forecast to re-sweep
        _RESTORE_SWEEP["ts"] = 0.0
    _restore_plan_invalidate()  # reminders/ledger just mutated — re-read on next GET
    total_cap = sum(pl["capacity"] for pl in plans)
    log_activity("/api/restore-live",
                 {"domains": domains, "campaign_ids": camp_ids,
                  "mailboxes": sum(pl["mailboxes"] for pl in plans),
                  "caps_restored_total": total_cap,
                  "resumed": sum(r["resumed"] or 0 for r in results),
                  "blacklist_warning": blacklist_warning,
                  "errors": [e for r in results for e in r["errors"]]},
                 action="restore_live", entity="deliverability",
                 entity_id=",".join(domains)[:120])
    ok = not any(r["errors"] for r in results)
    return {"ok": ok, "results": results, "reminder_done": done_ok,
            "blacklist_warning": blacklist_warning,
            "client": client, "capacity_restored": total_cap}, 200


# ── Login gate ──────────────────────────────────────────────────────────────
# Every page and API endpoint on this host requires a Navreo login — an
# email+password user in Supabase Auth on the same project that already backs
# the app. The server exchanges credentials via GoTrue's password grant, then
# issues its own stateless HMAC-signed cookie, so sessions survive deploys and
# no new secret is needed on Render: the signing key is derived from
# SUPABASE_SERVICE_ROLE_KEY, which is already in the environment.
# Exempt from the gate:
#   /healthz                      — Render's health check
#   /api/cron/*                   — self-guarded by the x-navreo-token header
#   /api/trigify-webhook          — external relay target; write-only staging
#                                   with its own dedupe (see trigify_webhook)
#   /app/login.html + its assets  — the login page itself
AUTH_COOKIE = "navreo_session"
AUTH_SESSION_DAYS = 30

_AUTH_PUBLIC_GET = {"/healthz", "/favicon.ico", "/app/login.html", "/app/navreo.css",
                    "/app/offer.html", "/app/setter-train.html", "/app/shell.js"}
_AUTH_PUBLIC_GET_PREFIX = ("/app/fonts/", "/app/icons/")
_AUTH_PUBLIC_POST = {"/api/auth/login", "/api/offer/generate", "/api/offer/start", "/api/offer/result", "/api/offer/email",
                     "/api/cron/pull-all", "/api/cron/heyreach-sync", "/api/cron/mailbox-sync", "/api/cron/audit-refresh",
                     "/api/cron/fleet-stats", "/api/cron/reply-sync",
                     "/api/notify/positive-card",
                     "/api/setter/poll", "/api/setter/inbound",
                     "/api/setter/training/answer", "/api/setter/training/generate",
                     "/api/setter/training/recheck", "/api/setter/agents/correction",
                     "/api/trigify-webhook", "/api/qa-gate/runs"}

# GET endpoints the public /app/setter-train.html share page calls WITHOUT a
# login - but only when the request carries a share=<token> query param. The
# token itself is what's actually load-bearing (verified inside setter.py's
# routes: verify_training_share); this set + the query check just decides
# whether do_GET's normal login gate is allowed to let the request through
# at all. No session, no share -> still gated exactly as before.
_TRAIN_SHARE_GET = {"/api/setter/training", "/api/setter/training/share-info"}


def _auth_secret() -> bytes:
    import hashlib
    srk = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return hashlib.sha256((srk + ":navreo-session-v1").encode()).digest()


def _mint_session(email: str) -> str:
    import hmac, hashlib, base64
    payload = f"{email}|{int(time.time()) + AUTH_SESSION_DAYS * 86400}".encode()
    sig = hmac.new(_auth_secret(), payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


def _session_email(cookie_header) -> str | None:
    """Email of the signed-in user, or None. Verifies signature + expiry."""
    import hmac, hashlib, base64
    val = None
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == AUTH_COOKIE:
            val = v.strip()
    if not val or "." not in val:
        return None
    b64, _, sig = val.rpartition(".")
    try:
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception:  # noqa: BLE001 — malformed cookie is just "not signed in"
        return None
    if not hmac.compare_digest(hmac.new(_auth_secret(), payload, hashlib.sha256).hexdigest(), sig):
        return None
    email, _, exp = payload.decode(errors="replace").rpartition("|")
    if not email or not exp.isdigit() or int(exp) < time.time():
        return None
    return email


def _session_cookie(value: str, max_age: int) -> str:
    # Secure only on Render — a Secure cookie would never be sent back over
    # plain-http localhost, which is how the server runs in local dev.
    secure = "; Secure" if os.environ.get("RENDER") else ""
    return (f"{AUTH_COOKIE}={value}; Path=/; Max-Age={max_age}; "
            f"HttpOnly; SameSite=Lax{secure}")


def auth_login(email: str, password: str):
    """GoTrue password grant — the actual 'is this a Navreo login' check.
    Returns (ok, message)."""
    url = f"{KEYS.get('SUPABASE_URL', '').rstrip('/')}/auth/v1/token?grant_type=password"
    key = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not key or not KEYS.get("SUPABASE_URL"):
        return False, "Auth backend is not configured on this server."
    try:
        data = http_json("POST", url, {"apikey": key},
                         {"email": email, "password": password}, timeout=15)
    except Exception:  # noqa: BLE001 — GoTrue unreachable
        return False, "Couldn't reach the login service - try again."
    if isinstance(data, dict) and data.get("access_token"):
        return True, "ok"
    msg = (data or {}).get("error_description") or (data or {}).get("msg") or ""
    return False, "Wrong email or password." if "credentials" in msg.lower() else (msg or "Login failed.")


# ── Offer Maker (public page /app/offer.html) ────────────────────────────────
# POST /api/offer/generate: fetch the visitor's website homepage, generate
# 12-18 cold-email offer ideas via gpt-5-mini. PUBLIC endpoint, so it is
# special-cased in do_POST (outside drafts_lock — a slow public call must never
# block the app) and hard rate-limited below. Nothing about the visitor or
# their URL is persisted — stdout only.

OFFER_RL_PER_IP_HOUR = 10       # successful generations (LLM calls) per IP per hour
OFFER_RL_ATTEMPTS_HOUR = 30     # any request per IP per hour (typos don't burn generations)
OFFER_RL_EMAIL_HOUR = 80        # per-offer worked-email writes per IP per hour (cheap, one email each)
OFFER_RL_GLOBAL_DAY = 200       # generations per UTC day across all visitors
_OFFER_RL_LOCK = threading.Lock()
_OFFER_RL_IP: dict = {}                    # ip -> {"gen": [ts], "try": [ts], "email": [ts]}
_OFFER_RL_DAY = {"date": "", "count": 0}   # global daily generation counter (UTC date)


def _offer_rate_check(ip: str, kind: str):
    """kind='try' debits one attempt (checked before the site fetch); kind='gen'
    debits one generation (checked only once the site fetched OK, right before
    the LLM call - a typo'd URL never burns a generation); kind='email' debits
    one worked-email write (its own generous per-IP bucket). Returns a
    plain-English refusal message if over the relevant cap, else None."""
    now = time.time()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _OFFER_RL_LOCK:
        if _OFFER_RL_DAY["date"] != today:
            _OFFER_RL_DAY["date"], _OFFER_RL_DAY["count"] = today, 0
        rec = _OFFER_RL_IP.setdefault(ip, {"gen": [], "try": [], "email": []})
        for k in ("gen", "try", "email"):
            rec[k] = [t for t in rec.get(k, []) if now - t < 3600]
        if kind == "try":
            if len(rec["try"]) >= OFFER_RL_ATTEMPTS_HOUR:
                return ("Too many tries from your connection in the last hour. "
                        "Please wait a little while and try again.")
            rec["try"].append(now)
        elif kind == "email":
            if len(rec["email"]) >= OFFER_RL_EMAIL_HOUR:
                return ("You've written a lot of emails in the last hour, which is the limit. "
                        "Please wait a little while and try again.")
            rec["email"].append(now)
        else:
            if _OFFER_RL_DAY["count"] >= OFFER_RL_GLOBAL_DAY:
                return ("The offer maker has hit its daily limit. "
                        "Please come back tomorrow, or email us and we'll run it for you.")
            if len(rec["gen"]) >= OFFER_RL_PER_IP_HOUR:
                return ("You've generated offers 10 times in the last hour, which is the limit. "
                        "Please wait a little while and try again.")
            rec["gen"].append(now)
            _OFFER_RL_DAY["count"] += 1
        if len(_OFFER_RL_IP) > 5000:  # bound memory on a public endpoint
            keep = _OFFER_RL_IP[ip]; _OFFER_RL_IP.clear(); _OFFER_RL_IP[ip] = keep
    return None


# Verbatim offer lines that actually drove positive replies (mined from the
# Supabase reply archive 2026-07-12; identities swapped for placeholders, copy
# untouched). Used as few-shot examples so generated offers sound like winners.
OFFER_WINNING_EXAMPLES = """\
1. "If it fits, we can build or run it for you guaranteeing 30 qualified leads in 90 days or we refund you." (guarantee + full refund; 30+ positive replies)
2. "You only pay after we've built it, so zero upfront amount." (pay after result; 12 positive replies)
3. "If it's useful, we run it for you on a pay-per-lead basis." (pay per result; 6 positive replies)
4. "If it lands, we can run it for you on a pay-per-lead basis, so you only pay for the leads we deliver." (pay per result, spelled out; 4 positive replies)
5. "You only pay once sales come through, so nothing out of pocket to start." (pay per result; 10 positive replies)
6. "I'd happily put together a mood board, a render, and a sourcing snapshot, and have it back within 48 hours, no charge or commitment." (free sample; 38 positive replies, the single best line mined)
7. "I've compiled a breakdown showing how we're using Claude Code to almost replace Clay in our outbound, reducing cost and complexity while improving results. Want me to send it across?" (free resource + ask-to-send CTA; 59 positive replies across variants)
8. "We've put together a quick breakdown of the exact campaigns we'd run to get {{company}} 30 qualified leads a month." (free custom sample; 7 positive replies)
9. "I recorded a Loom for {{company}} showing what we'd build to help you land more clients." (Loom CTA; 30+ positive replies)
10. "If we could build you an AI lead-generation engine that added 30+ qualified leads every month, without needing to hire a BDR team, would you be interested?" (problem + differentiator in one question; 12 positive replies)
11. "Most SaaS leaders we speak to find hiring and ramping SDRs burns months and budget before any pipeline shows up." (high-consequence problem statement; 6 positive replies)
12. "If we could help {{company}} book your sales team meetings with facility and property managers needing building services, and I showed you exactly how through a 2-minute video, would you be keen to see it?" (named buyer type + video CTA; 4 positive replies)"""

OFFER_FIELDS = ("name", "problem", "differentiator", "pricing", "risk_reversal",
                "mechanism", "stipulation", "opener", "why_cold_email")
# Exactly ONE mechanism per offer - a lead magnet OR one of the three risk
# reversals. Never stacked (user ruling 2026-07-16: no guarantee inside a
# lead-magnet offer).
OFFER_MECHANISMS = ("lead_magnet", "pay_after_result", "pay_per_result", "guarantee_refund")

# Subpages worth reading beyond the homepage (competitor auto-research pattern:
# scrape about/product/pricing/customers, write a company brief, THEN generate).
OFFER_EXTRA_PATHS = ("/about", "/about-us", "/product", "/products", "/pricing",
                     "/customers", "/case-studies", "/services", "/work", "/clients")
OFFER_PAGE_TIMEOUT_S = 8    # per extra page
OFFER_RESEARCH_BUDGET_S = 20  # hard cap on ALL extra-page fetching combined


def _offer_strip_html(raw: str) -> str:
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _offer_fetch_extra_pages(base: str, homepage_html: str):
    """Read up to 5 subpages (about/product/pricing/customers/...) in parallel,
    each with a short timeout, all inside a hard research budget so the single
    synchronous request stays far under the Render proxy timeout. Best-effort:
    a page that fails or misses the deadline is simply skipped."""
    hrefs = set(re.findall(r'href=["\']([^"\'#?]+)', homepage_html, re.I))
    candidates = []
    for path in OFFER_EXTRA_PATHS:
        linked = any(h.rstrip("/").lower().endswith(path) for h in hrefs)
        if linked and path not in candidates:
            candidates.append(path)
    for path in ("/about", "/pricing"):  # worth one blind try even if not linked
        if path not in candidates:
            candidates.append(path)
    candidates = candidates[:5]
    results: dict = {}

    def fetch(path: str):
        try:
            req = urllib.request.Request(base.rstrip("/") + path,
                                         headers={"User-Agent": "Mozilla/5.0 (compatible; NavreoOfferMaker)"})
            with urllib.request.urlopen(req, timeout=OFFER_PAGE_TIMEOUT_S, context=SSL_CTX) as resp:
                text = _offer_strip_html(resp.read(300_000).decode("utf-8", "ignore"))
            if len(text) > 150:
                results[path] = text[:2_000]
        except Exception:  # noqa: BLE001 — best-effort research, never fatal
            pass

    threads = [threading.Thread(target=fetch, args=(p,), daemon=True) for p in candidates]
    deadline = time.time() + OFFER_RESEARCH_BUDGET_S
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.1, deadline - time.time()))
    return [{"path": p, "text": results[p]} for p in candidates if p in results]


def _offer_fetch_site(url: str, deep: bool = True):
    """Fetch the homepage (and, when deep=True, a handful of subpages) and strip
    to text. Raises ValueError with a plain-English message on anything
    unreachable. Refuses private hosts (this is a public endpoint — never let
    it probe our own network)."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Please paste your website address first.")
    if not url.startswith("http"):
        url = "https://" + url
    host = url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    domain = host.removeprefix("www.")
    if "." not in domain:
        raise ValueError(f"'{domain}' doesn't look like a website address. Try something like yourcompany.com")
    import ipaddress, socket
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise ValueError(f"We couldn't find a website at {domain}. Check the spelling and try again.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"We couldn't reach {domain}. Check the address and try again.")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NavreoOfferMaker)"})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            raw = resp.read(500_000).decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"We couldn't open {domain} ({str(e)[:80]}). "
                         "Check the address works in your browser, then try again.")
    title = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.I)
    desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', raw, re.I)
    text = _offer_strip_html(raw)
    if len(text) < 200:
        raise ValueError(f"We reached {domain} but couldn't read enough of the page to work with. "
                         "If your site is mostly images or loads with JavaScript, email us the address instead.")
    base = url.split("//", 1)[0] + "//" + host
    pages = _offer_fetch_extra_pages(base, raw) if deep else []
    return {"domain": domain,
            "title": (title.group(1).strip() if title else domain),
            "description": (desc.group(1).strip() if desc else ""),
            # 6k chars of homepage text is plenty to understand a business, and
            # keeping the prompt small keeps gpt-5-mini comfortably under the
            # Render proxy timeout (heavy sites were pushing ~90s and 502ing).
            # Extra pages are capped at 2k chars each, max 5 pages.
            "text": text[:6_000],
            "pages": pages}


def _offer_scrub(s: str) -> str:
    """Backstop the style laws: no em-dashes, and normalise the fullwidth pound
    sign gpt-5-mini sometimes emits."""
    return re.sub(r"\s*[—–]\s*", " - ", str(s or "")).replace("￡", "£").strip()


def _offer_llm(site: dict, audience: str = "", seed: dict | None = None):
    """Run the gpt-5-mini generation for a fetched site. Returns (status, body).
    Blocking and slow (up to ~2 min) - callers run it either synchronously
    (offer_generate, for curl/tests) or in a background thread (offer_start).
    audience: optional plain-English description of who the business sells to,
    typed by the visitor. When given, every offer and opener is aimed at it.
    seed: optional {"mechanism","name","opener"} from a "More like this" click -
    when given, generate exactly 5 fresh offers of that one mechanism, in the
    same spirit as the seed offer."""
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        return 502, {"ok": False, "message": "The offer generator isn't configured right now. Please try again later."}
    audience = (audience or "").strip()[:300]
    if audience:
        audience_block = (f"WHO THEY SELL TO (given by the business owner - this is the buyer to aim EVERY "
                          f"offer and EVERY example first line at): {audience}\n"
                          "Every offer must target this exact buyer, and the {{company}} merge tag in each "
                          "opener refers to that buyer's company. Do not aim offers at any other kind of buyer.\n")
        who_line = "The buyer is given above - aim every offer at them."
    else:
        audience_block = ""
        who_line = "work out who buys it and aim the offers at that buyer."
    extra_pages = "\n".join(f"PAGE {p['path']}: {p['text']}" for p in site.get("pages", []))
    if seed:
        count_line = (f"Generate EXACTLY 5 fresh offer ideas, every one using the mechanism "
                      f"\"{seed.get('mechanism','')}\", in the same spirit as this offer the owner liked: "
                      f"\"{str(seed.get('name',''))[:120]}\" (opener: \"{str(seed.get('opener',''))[:200]}\"). "
                      "Do not repeat that offer; give 5 genuinely different takes on it.")
        mix_line = "All 5 offers use the seed mechanism above."
        n_expect = "5 objects"
    else:
        count_line = "Generate EXACTLY 15 distinct offer ideas this business could use in cold emails to win NEW customers."
        mix_line = "Across the 15 offers, EVERY one of the four mechanisms must appear at least 3 times."
        n_expect = "15 objects"
    prompt = f"""You are an expert at designing cold-email OFFERS for a B2B lead-generation agency.

A business owner pasted their website. Here is what it says:
WEBSITE: {site['domain']}
TITLE: {site['title']}
DESCRIPTION: {site['description']}
HOMEPAGE TEXT (truncated): {site['text']}
{extra_pages}
{audience_block}
STEP 1 - THE COMPANY BRIEF. Before any offers, read every page above and write a short brief:
- what_they_do: 1-2 plain sentences on what this business actually sells.
- who_they_sell_to: one line naming the buyer ({who_line})
- proof_signals: up to 3 short facts from the pages that build trust (named clients, results, years, awards). Empty list if none.
- angles: up to 3 short outreach angles the pages suggest.
The brief must come from the pages above, not from guessing.

STEP 2 - THE OFFERS. {count_line}
GROUNDING RULE: every offer must be rooted in something concrete from the pages above - a named service, a named client type, a stated result, a pricing fact. An offer that could apply to any business in any industry is wrong; rewrite it until it could only belong to THIS business.
REAL SERVICES ONLY: every offer sells a service or product this business ACTUALLY provides according to the pages. NEVER invent a new line of business for them - a freight company does not "run outreach" or "deliver qualified leads", a cleaning company does not win tenders for its customers. The offers help them win new customers FOR WHAT THEY ALREADY SELL. Proof lines may only use results actually stated on the pages.

THE OFFER FRAMEWORK (every offer must have all four):
(a) PROBLEM: the specific NEW BUSINESS the recipient is MISSING OUT ON, and what that gap costs them. Phrase it as money they are NOT winning, e.g. "You are missing [new customers / new orders / new contracts / new tenants] because [reason], which costs you [amount] in sales you never make." Do NOT phrase the problem as a current operational pain, a risk of loss, downtime, wasted spend, or something breaking - if the problem is not about missed NEW revenue, the offer is wrong.
(b) DIFFERENTIATOR: what this business would do about it AND an explicit comparison to the usual way (the words "instead of" or "unlike" or "most" should appear: e.g. "unlike agencies that charge a retainer", "instead of waiting weeks for quotes", "most suppliers make you...").
(c) PRICING: a pricing angle that favours the buyer (fixed price, pay less than the alternative, price tied to results, free first step). For a lead_magnet offer the pricing angle IS the free first step.
(d) MECHANISM: exactly ONE per offer. {mix_line}
   - lead_magnet: you make something small, useful and FREE and offer to SEND it (a one-page breakdown, a short Loom, a worked sample, a plan). No strings attached.
   - pay_after_result: buyer pays nothing until the work is delivered or the result shows up.
   - pay_per_result: buyer pays per unit of result (per lead, per sale, per placement), not a retainer.
   - guarantee_refund: a concrete promise (number + deadline) with a full refund if missed. The word "refund" (or "money back") MUST appear in the risk_reversal field of every guarantee_refund offer.
The risk_reversal field spells the chosen mechanism out as a promise in the buyer's words (for lead_magnet: what the free thing is and that it costs nothing).

ONE MECHANISM ONLY (as important as the new-money rule): each offer picks its ONE mechanism and NOTHING from the other three appears anywhere in that offer. BANNED STACKING, no exceptions: a guarantee or refund inside a lead_magnet offer; a free sample or free resource bolted onto a pay_per_result or guarantee_refund offer; a guarantee added to a pay_after_result offer; any offer whose pricing, risk_reversal, opener or stipulation mentions a second mechanism. Simple offers get replies; stacked offers read as too good to be true and get deleted.
WATCH THE PRICING FIELD - it is where stacking sneaks in:
- lead_magnet pricing is ALWAYS a single sentence of the form "The <thing> costs nothing and there is no obligation." (vary the wording slightly, keep the meaning identical). NEVER a number, a currency symbol, a fee, a rate, a plan, or how any paid service would be priced - if a paid price appears in a lead_magnet offer, the offer is WRONG.
- guarantee_refund pricing is a normal fee paid the normal way; the refund is the safety net. NEVER also delay, waive or condition the payment (that would be pay_after_result on top).
- pay_after_result and pay_per_result pricing never mention a refund or a free deliverable.
(A Loom or one-pager that merely EXPLAINS the offer is a CTA, not a second mechanism - that is fine.)
WATCH THE OPENER TOO: in pay_after_result, pay_per_result and guarantee_refund offers, the small thing the opener offers to send may only DESCRIBE the offer (a short Loom about it, a one-page plan of what we would do). NEVER offer a free sample, free unit, free trial or free version of the deliverable itself ("a sample of the work we'd build for you", "the exact posts we'd publish", "an example lead we'd deliver", "the checklist we use") - a free taste of the deliverable or a standalone useful asset IS the lead_magnet mechanism and belongs only in lead_magnet offers.

DELIVERABILITY LAW (the sender must be able to keep every promise):
- The PROBLEM names the new money the recipient is missing. The PROMISE (risk_reversal, opener, pricing trigger) names ONLY what the sender delivers and can measure itself: work completed, stock landed, a space made viewing-ready, meetings booked, leads delivered to agreed criteria.
- Unless winning customers is literally this business's service (a lead-generation or marketing agency), NEVER promise or gate payment on the recipient's own sales outcomes - their orders won, contracts signed, tenants moved in, store opened, bookings taken. Promise the deliverable that unlocks those, not the outcome itself. Even a lead-gen agency's deliverable ends at leads or booked meetings - never "customers won" or "closed deals" (closing is the client's job).
- NEVER promise platform metrics that cannot be verified per person (impressions, followers, views by job title), and NEVER guarantee counted results from ORGANIC social content (inbound replies or messages from posts) - organic reach is not controllable. A content service either uses the lead_magnet mechanism, or promises the publishing deliverable itself (posts written and published on schedule).
- Repeat business, rebookings, renewals and upsells from EXISTING customers are NOT new money - only brand-new customers, orders and contracts count.
- Keep every number modest and honest: a promise the business would miss more often than hit is a broken offer.
- Recovery framing is BANNED everywhere: "stop losing", "recover lost", "recover missed", "win back", income "leaking". The benefit is always new money coming in, said that way.

HARD RULES:
- BREVITY LAW (a buyer must grasp the offer at a glance): every field is ONE short sentence. problem max 15 words. differentiator max 20 words. pricing max 12 words. risk_reversal max 14 words. stipulation max 14 words. problem + differentiator together must read in UNDER 40 WORDS. If a field needs a second sentence, the offer is too complicated - simplify the offer, don't add words.
- NEW MONEY ONLY (the single most important rule): every offer must promise the RECIPIENT brand-new revenue - new customers, new sales, new orders, new markets, new booked work, new tenants, new contracts they currently lose. The main benefit to the recipient must be MORE MONEY COMING IN, never money saved or a loss avoided. BANNED offer types, no matter how the business is described: preventing downtime, avoiding losses, cutting or saving costs, staying compliant, protecting or keeping existing revenue, reducing risk on things they already do, optimising/auditing/refreshing/speeding up/tidying up something they already run. Recovering money the recipient is already owed (tax refunds, duty drawbacks, rebates, overcharges, chargebacks) is NOT new money - it is found money, and it is BANNED as an offer. If this business sells repairs, maintenance, logistics, cleaning, compliance, efficiency or cost-saving, you MUST recast every offer as a NEW-revenue win for the recipient. Example: a handyman must NOT offer "emergency repairs to prevent downtime" (that is avoiding a loss); instead offer "get your empty units rented faster by making them move-in ready in 48 hours" (that is NEW rental income). A logistics firm must NOT offer "cut your shipping costs" (saving); instead offer "get your product onto shelves in three new states" (NEW orders).
- FINAL SELF-CHECK before you answer: re-read every offer and ask TWO questions. One: "does the recipient make NEW money from this, or does it only save money / avoid a loss / keep what they have?" If it is not clearly NEW money coming in, DELETE that offer and replace it. Two: "does this offer contain exactly ONE mechanism, or has a second one crept in anywhere?" If any part of the offer mentions a second mechanism, strip it out or replace the offer. Every offer in your final answer must pass both tests.
- WHO THE EMAIL GOES TO: cold email is business-to-business. If this business sells to consumers, aim every offer at business buyers instead (retailers who could stock the product, distributors, corporate accounts, partners), never at individual consumers.
- LOW-RISK CTA: the example opener must offer to SEND something small (a short Loom video, a free sample, a one-page breakdown, a worked example) - never "book a call" or "hop on a call".
- STIPULATION: each offer includes one fair condition that protects the seller (e.g. "leads must match an agreed target list", "guarantee starts after onboarding is complete", "capped at N per month").
- PLAIN ENGLISH: no marketing jargon and no industry shorthand. Banned words and phrases: synergy, ROI, ROI-driven, cutting-edge, leverage, solutions, streamline, seamless, robust, scalable, best-in-class, end-to-end, ICP, SDR, BDR, GTM, go-to-market, pipeline, funnel, outbound, conversion, engagement. Say it the way a shop owner would: "your ideal customers", "a salesperson", "steady flow of new deals". A 12-year-old should understand every sentence. NEVER use an em-dash anywhere.
- ENGLISH ONLY: every single word in every field is English. Numbers in names must match the numbers in the body of the offer. Never leave a placeholder like "X days" or "N leads" - always pick a real, sensible number.
- The opener is ONE sentence, 20 words or fewer, written as the first line of a cold email from this business to its buyer. Use {{{{company}}}} where the prospect's company name would go.
- why_cold_email: one or two plain sentences explaining to a beginner WHY this offer works on cold strangers (e.g. it removes their risk, it asks for a tiny yes, it names their exact problem).
- opener writing rule: the opener is the FIRST line of the email and must offer to SEND something small (a short Loom, a one-page plan, a sample). The page wraps it into a full ready-to-send email around it, so make it read as a natural, complete opening line.

REAL OFFER LINES THAT GOT POSITIVE REPLIES (mined from real campaigns - match this energy and concreteness, do not copy them word for word unless they genuinely fit):
{OFFER_WINNING_EXAMPLES}

Reply with ONLY a JSON object, no fences, no commentary:
{{"brief": {{"what_they_do": "<1-2 sentences>", "who_they_sell_to": "<one line>", "proof_signals": ["<fact>"], "angles": ["<angle>"]}}, "offers": [<exactly {n_expect}, each: {{"name": "<3-6 word plain name for the offer>", "problem": "<the specific high-consequence problem, 1-2 sentences>", "differentiator": "<what you do and why it beats the usual way, 1-2 sentences>", "pricing": "<the buyer-favouring pricing angle, 1 sentence>", "risk_reversal": "<the one mechanism written out as a promise, 1 sentence>", "mechanism": "<lead_magnet|pay_after_result|pay_per_result|guarantee_refund>", "stipulation": "<the fair protective condition, 1 sentence>", "opener": "<one-line example cold email opener, max 20 words>", "why_cold_email": "<plain-English reason this works on cold email, 1-2 sentences>"}}>]}}"""
    offers = None
    err = ""
    for attempt in (1, 2):  # one retry on a malformed reply
        try:
            # reasoning_effort=low keeps generation well under the Render proxy
            # timeout (~30-50s vs 90-130s at default), so the whole thing fits in
            # one synchronous request - no cross-instance job store to go stale.
            r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                          {"Authorization": f"Bearer {key}"},
                          {"model": "gpt-5-mini", "reasoning_effort": "low",
                           "messages": [{"role": "user", "content": prompt}]},
                          timeout=120)
            if r.get("error"):
                raise RuntimeError(str(r["error"].get("message", r["error"]))[:200])
            text = (r["choices"][0]["message"]["content"] or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            doc = json.loads(m.group(0) if m else text)
            brief_raw = doc.get("brief") or {}
            cand = doc.get("offers")
            lo, hi = (4, 6) if seed else (12, 18)
            if not isinstance(cand, list) or not lo <= len(cand) <= hi:
                raise ValueError(f"got {len(cand) if isinstance(cand, list) else 'non-list'} offers")
            if not str(brief_raw.get("what_they_do") or "").strip() \
                    or not str(brief_raw.get("who_they_sell_to") or "").strip():
                raise ValueError("brief missing what_they_do / who_they_sell_to")
            for o in cand:
                for f in OFFER_FIELDS:
                    if not str(o.get(f) or "").strip():
                        raise ValueError(f"offer missing {f}")
                if o["mechanism"] not in OFFER_MECHANISMS:
                    raise ValueError(f"bad mechanism {o['mechanism']!r}")
                # Anti-stacking guard: a lead-magnet offer must never carry a
                # paid price - that is a second mechanism sneaking in.
                if o["mechanism"] == "lead_magnet" and re.search(
                        r"[£$€]|\bbilled|\b(?:fixed|one.off|weekly|monthly) (?:price|fee|rate)|(?<!no )\bfee\b",
                        str(o.get("pricing") or ""), re.I):
                    raise ValueError(f"lead_magnet offer {o.get('name','')!r} has paid pricing")
            # Deterministic anti-stacking drops (the model occasionally leaks a
            # second mechanism despite the prompt; one bad offer must not sink
            # the whole generation, so drop the offender instead):
            def _stacked(o):
                # Brevity law: the visible offer (problem + differentiator) must
                # be scannable. Drop bloated offers rather than failing the run.
                if len(str(o.get("problem") or "").split()) \
                        + len(str(o.get("differentiator") or "").split()) > 44:
                    return "too wordy"
                blob = " ".join(str(o.get(f) or "") for f in
                                ("pricing", "risk_reversal", "opener", "stipulation"))
                if o["mechanism"] != "lead_magnet" and re.search(
                        r"\bfree (?:sample|trial|unit|version|clean|month|week)\b|\bsample of the\b"
                        r"|\bthe exact (?:posts?|emails?|sequences?|copy|lists?|companies|accounts|prospects|leads)\b"
                        r"|\bchecklist we use\b|\bunless you (?:sign|buy|purchase)\b"
                        r"|\bposts we(?:'d| would) publish\b", blob, re.I):
                    return "free-sample leak"
                if re.search(r"\bwin back\b|\brecover(?:ed|ing)? (?:lost|missed)\b|\bstop losing\b"
                             r"|\bleak(?:ing|s)? (?:revenue|income|rent)\b"
                             r"|\brenewals?\b|\brepeat business\b|\brebook(?:ing|ings)?\b",
                             " ".join(str(o.get(f) or "") for f in OFFER_FIELDS), re.I):
                    return "recovery framing"
                if o["mechanism"] == "guarantee_refund" and re.search(
                        r"\binbound (?:replies|messages|leads)\b.{0,80}\bposts?\b|\bposts?\b.{0,80}\binbound (?:replies|messages|leads)\b",
                        str(o.get("risk_reversal") or "") + " " + str(o.get("problem") or ""), re.I):
                    return "organic-social guarantee"
                if o["mechanism"] in ("pay_after_result", "pay_per_result") and re.search(
                        r"\bguarantee|\brefund|\bmoney.?back", blob, re.I):
                    return "guarantee leak in pay offer"
                if o["mechanism"] == "guarantee_refund" and not re.search(
                        r"refund|money.?back", str(o.get("risk_reversal") or ""), re.I):
                    return "guarantee without refund"
                if o["mechanism"] == "guarantee_refund" and re.search(
                        r"\b(?:paid|invoiced?|charged?|payable)\b[^.]{0,40}\bafter\b|\bafter launch\b",
                        str(o.get("pricing") or ""), re.I):
                    return "guarantee with delayed payment"
                return None
            dropped = [(o.get("name", "?"), why) for o in cand if (why := _stacked(o))]
            cand = [o for o in cand if not _stacked(o)]
            if dropped:
                print(f"OFFER GEN dropped {len(dropped)} stacked offers for {site['domain']}: {dropped}")
            if seed:
                if any(o["mechanism"] != seed.get("mechanism") for o in cand):
                    raise ValueError("seed run returned a different mechanism")
                if len(cand) < 3:
                    raise ValueError("too few clean seed offers after drops")
            else:
                mechs = {o["mechanism"] for o in cand}
                if mechs != set(OFFER_MECHANISMS):
                    raise ValueError(f"missing mechanisms: {set(OFFER_MECHANISMS) - mechs}")
                if len(cand) < 10:
                    raise ValueError(f"only {len(cand)} clean offers after drops")
            offers = [{f: _offer_scrub(o[f]) for f in OFFER_FIELDS} for o in cand]
            brief = {"what_they_do": _offer_scrub(brief_raw.get("what_they_do")),
                     "who_they_sell_to": _offer_scrub(brief_raw.get("who_they_sell_to")),
                     "proof_signals": [_offer_scrub(s) for s in (brief_raw.get("proof_signals") or [])[:3]],
                     "angles": [_offer_scrub(s) for s in (brief_raw.get("angles") or [])[:3]]}
            break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"OFFER GEN attempt {attempt} failed for {site['domain']}: {err}")
    if offers is None:
        return 502, {"ok": False, "message":
                     "The offer generator hit a problem and couldn't finish. Please try again in a minute."}
    print(f"OFFER GEN ok: {site['domain']} -> {len(offers)} offers, "
          f"{len(site.get('pages', []))} extra pages read"
          + (f" (audience: {audience})" if audience else "") + (" [more-like]" if seed else ""))
    return 200, {"ok": True, "domain": site["domain"], "site_name": site["title"],
                 "audience": audience, "brief": brief,
                 "pages_read": ["/"] + [p["path"] for p in site.get("pages", [])],
                 "offers": offers}


def offer_generate(p: dict, ip: str):
    """Synchronous path (browser + curl). Returns (status, body).
    Optional p["seed"] = {"mechanism","name","opener"} makes this a "More like
    this" run: homepage-only fetch (fast) and 5 offers of that one mechanism."""
    refusal = _offer_rate_check(ip, "try")
    if refusal:
        return 429, {"ok": False, "message": refusal}
    seed = p.get("seed") if isinstance(p.get("seed"), dict) else None
    if seed and seed.get("mechanism") not in OFFER_MECHANISMS:
        seed = None
    try:
        site = _offer_fetch_site(p.get("url") or "", deep=not seed)
    except ValueError as e:
        return 400, {"ok": False, "message": str(e)}
    refusal = _offer_rate_check(ip, "gen")
    if refusal:
        return 429, {"ok": False, "message": refusal}
    return _offer_llm(site, p.get("audience") or "", seed)


def offer_email(p: dict, ip: str):
    """Write ONE fully-worked, standalone cold email for a single offer, at the
    claude-breakdown level: concrete example recipient, a concrete icebreaker,
    the offer in the body, and a concrete P.S. proof line. No merge tags, no
    square-bracket blanks. Fast (one email, low reasoning). Returns (status, body)."""
    refusal = _offer_rate_check(ip, "email")
    if refusal:
        return 429, {"ok": False, "message": refusal}
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        return 502, {"ok": False, "message": "The email writer isn't available right now. Please try again later."}
    o = p.get("offer") or {}
    fields = {k: str(o.get(k) or "").strip()[:600] for k in
              ("name", "problem", "differentiator", "pricing", "risk_reversal", "mechanism", "stipulation", "opener")}
    if not fields["problem"] or not fields["opener"]:
        return 400, {"ok": False, "message": "That offer looks incomplete, please generate the offers again."}
    audience = str(p.get("audience") or "").strip()[:300]
    domain = str(p.get("domain") or "").strip()[:120]
    who = f"The business sending this email is {domain}." if domain else ""
    aud = (f"They sell to: {audience}. Write the email to a realistic example person in that group."
           if audience else "Write the email to a realistic example person in the buyer group this offer targets.")
    # Template law: each mechanism maps to exactly ONE house template
    # (lilly-copywriter). Lead-magnet offers use the Lead Magnet template; the
    # three risk-reversal mechanisms use the Service Pitch template.
    lead_magnet = fields["mechanism"] == "lead_magnet"
    template_name = "lead_magnet" if lead_magnet else "service_pitch"
    if lead_magnet:
        template_block = """THE LEAD MAGNET TEMPLATE (follow this shape exactly, one blank line between each part):

Hi <recipient first name>,

<Icebreaker: ONE short line, either a concrete plausible trigger about the recipient's company, or a "most <their kind of company> find that <problem>" observation. Do not pitch here.>

<The offer, ONE or TWO sentences: name the free thing and offer it. If it is a ready-made resource: "We put together a <resource type> which I thought might be useful for <their company name>, it covers <what it covers, tied to the problem>." If making it needs their input: "We'd love to put together a <resource type> for <their company name> showing <outcome>." Never claim per-company work that was not done.>

<Soft CTA, one short question offering to SEND it: "Can I send it over?" or "Want me to send it across?">

<sender first name>

P.S - We've helped <a named example client or "companies like X"> who were struggling with <problem> <concrete result>.

HARD RULES FOR THIS TEMPLATE:
- The email ALWAYS starts with the icebreaker line. NEVER open with the CTA or the offer.
- The ONLY ask is permission to send the free thing. Exactly ONE question in the whole email. No call ask, no meeting, no second question.
- The CTA verb is send / share / give / show, and the buyer receives a ready-made thing, never work done to them.
- Honest tense: if the offer's stipulation depends on ANYTHING the recipient sends, approves or gives access to, the offer line MUST be future tense ("We'd love to put together..."). Only write "We put together..." or "I recorded..." (past) for a thing that can genuinely exist before ever speaking to them.
- Do NOT mention any guarantee, refund, pay-per-result or pay-after-result anywhere. Do NOT mention cost, charge, price, "no charge" or obligation at all - just offer the thing; the offer block is at most 2 sentences.
- The body between greeting and sign-off is 45-70 words. Count them."""
    else:
        template_block = """THE SERVICE PITCH TEMPLATE (follow this shape exactly, one blank line between each part):

Hi <recipient first name>,

<Icebreaker: ONE short line naming a concrete, plausible trigger about the recipient's company (a recent hire, a new office, a launch, a post) that ends with the exact words "so I wanted to reach out.". Do not pitch here.>

If we could <the new-money outcome they want> by <what we would do, in plain words>, <the promise woven in as a natural clause>, <a low-risk CTA question that offers to SEND something small like a short Loom, a one-page plan, or a worked example>?

Best,
<sender first name>

P.S - <one concrete line of proof: a named example client and a result>

HARD RULES FOR THIS TEMPLATE:
- The "If we could ... ?" part is ONE flowing sentence that ends on the question mark. Do NOT split the promise into its own separate sentence, and do NOT add any sentence after the question.
- The promise clause sits INSIDE that sentence joined naturally with "and" - never a spliced clause like "..., we will refund the fee, would you like...".
- Keep the "If we could ... ?" sentence between 45 and 70 words.
- The promise woven in is ONLY this offer's mechanism. Do NOT add a free resource, sample or any second promise on top of it. Use the words guarantee or refund ONLY if this offer's mechanism is guarantee_refund.
- The CTA offers to SEND something small (a short Loom, a one-page plan, a worked example). Never "book a call" or "hop on a call"."""
    prompt = f"""You are our house cold-email copywriter. Write ONE complete, ready-to-send cold email for the single offer below, using the template EXACTLY.

{who}
{aud}

THE OFFER (its one mechanism is: {fields['mechanism']}):
- Name: {fields['name']}
- Problem it solves (the NEW business the buyer is missing): {fields['problem']}
- What we would do and why it is better: {fields['differentiator']}
- Pricing angle: {fields['pricing']}
- The promise: {fields['risk_reversal']}
- One fair condition: {fields['stipulation']}
- Suggested opening line: {fields['opener']}

{template_block}

HARD RULES (always):
- Fill EVERY part with concrete, realistic values. Invent a realistic recipient first name, a realistic example company name, and a realistic sender first name. NEVER leave {{{{first_name}}}}, {{{{company}}}}, or any [square-bracket blank] in the email.
- The P.S proof line uses a PLAUSIBLE INVENTED client name - never the name of a real well-known company. The proof number must be something THIS business could measure ITSELF (days to turn a unit around, meetings booked, shipments delivered on time, cleans completed). NEVER the client's own downstream outcomes - their contract wins, bookings, footfall, viewing rates, or revenue - a vendor cannot know those numbers and readers smell it.
- Recovery framing is banned: never "win back", "recover lost", "stop losing", income "leaking". The benefit is always new money coming in.
- Before answering, COUNT THE WORDS of the body (service pitch: the "If we could ... ?" sentence; lead magnet: everything between greeting and sign-off). It must be 45-70. If over, cut words - move any stipulation detail out of the sentence entirely.
- ONE mechanism only: the email expresses this offer's mechanism and nothing from any other (the P.S proof line is proof, not a promise).
- Plain English an 11th grader understands. No em-dashes, colons, semicolons or parentheses ANYWHERE in the email, including the P.S line. The P.S is one proof sentence only - never conditions or stipulations. No spam words (avoid the words free, trial, guaranteed, risk-free, today, urgent).
- Real line breaks between the parts, exactly as shown.

Reply with ONLY a JSON object, no fences, no commentary: {{"email": "<the full email, with real line breaks>"}}"""
    err = ""
    for attempt in (1, 2, 3):
        try:
            r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                          {"Authorization": f"Bearer {key}"},
                          {"model": "gpt-5-mini", "reasoning_effort": "low",
                           "messages": [{"role": "user", "content": prompt}]},
                          timeout=90)
            if r.get("error"):
                raise RuntimeError(str(r["error"].get("message", r["error"]))[:200])
            text = (r["choices"][0]["message"]["content"] or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            email = _offer_scrub(json.loads(m.group(0) if m else text).get("email", ""))
            if len(email) < 60 or "Hi " not in email[:8]:
                raise ValueError("email too short or malformed")
            # Deterministic template checks - the model occasionally leaks
            # these despite the prompt; a retry usually clears them.
            if re.search(r"[():;]", re.sub(r"^Hi [^,]+,", "", email)):
                raise ValueError("colon/semicolon/parenthesis in email")
            if lead_magnet:
                if re.search(r"no charge|no cost|for free|free of charge|obligation", email, re.I):
                    raise ValueError("cost language in lead magnet email")
                lines = [l.strip() for l in email.splitlines() if l.strip()]
                if len(lines) > 1 and (lines[1].endswith("?") or
                        re.match(r"(?:Can|May|Would|Want|Should) ", lines[1])):
                    raise ValueError("lead magnet opens with the CTA")
            return 200, {"ok": True, "email": email, "template": template_name}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"OFFER EMAIL attempt {attempt} failed: {err}")
    return 502, {"ok": False, "message": "Couldn't write that email just now. Please try again in a moment."}


# ── Async offer jobs ─────────────────────────────────────────────────────────
# Generation takes 40-130s (gpt-5-mini reasoning), which exceeds the Render
# proxy's request timeout, so heavy sites 502. offer_start returns a job id in a
# few seconds (just the site fetch) and runs the LLM in a daemon thread;
# offer_result is polled by the browser. Every HTTP request stays short.
# Jobs live in memory only (nothing persisted) with a short TTL sweep.
_OFFER_JOBS: dict = {}
_OFFER_JOBS_LOCK = threading.Lock()
_OFFER_JOB_TTL_S = 900  # a finished result is claimable for 15 min


def _offer_job_run(job_id: str, site: dict, audience: str = ""):
    status, body = 502, {"ok": False, "message":
                         "The offer generator hit a problem and couldn't finish. Please try again."}
    try:
        status, body = _offer_llm(site, audience)
    except Exception as e:  # noqa: BLE001 — never let a thread die silently
        print(f"OFFER JOB {job_id} crashed: {type(e).__name__}: {str(e)[:120]}")
    with _OFFER_JOBS_LOCK:
        job = _OFFER_JOBS.get(job_id)
        if job is not None:
            if body.get("ok"):
                job.update(status="done", domain=body["domain"], audience=body.get("audience", ""),
                           site_name=body["site_name"], offers=body["offers"], ts=time.time())
            else:
                job.update(status="error", message=body.get("message")
                           or "Something went wrong. Please try again.", ts=time.time())


def offer_start(p: dict, ip: str):
    """Kick off a generation. Fast: rate-check, fetch the site, spawn the LLM in
    a thread, return a job id. Returns (status, body)."""
    refusal = _offer_rate_check(ip, "try")
    if refusal:
        return 429, {"ok": False, "message": refusal}
    try:
        site = _offer_fetch_site(p.get("url") or "")
    except ValueError as e:
        return 400, {"ok": False, "message": str(e)}
    refusal = _offer_rate_check(ip, "gen")
    if refusal:
        return 429, {"ok": False, "message": refusal}
    if not KEYS.get("OPENAI_API_KEY"):
        return 502, {"ok": False, "message": "The offer generator isn't configured right now. Please try again later."}
    import uuid
    job_id = uuid.uuid4().hex
    now = time.time()
    with _OFFER_JOBS_LOCK:
        # prune expired / bound memory
        for jid in [j for j, v in _OFFER_JOBS.items() if now - v.get("ts", now) > _OFFER_JOB_TTL_S]:
            _OFFER_JOBS.pop(jid, None)
        if len(_OFFER_JOBS) > 500:
            _OFFER_JOBS.clear()
        _OFFER_JOBS[job_id] = {"status": "running", "ts": now}
    threading.Thread(target=_offer_job_run, args=(job_id, site, p.get("audience") or ""), daemon=True).start()
    return 200, {"ok": True, "job_id": job_id}


def offer_result(p: dict):
    """Poll a job. Always returns 200 with JSON so the browser never has to
    parse a gateway HTML page. Returns (status, body)."""
    job_id = str(p.get("job_id") or "")
    with _OFFER_JOBS_LOCK:
        job = _OFFER_JOBS.get(job_id)
        job = dict(job) if job else None
    if job is None:
        return 200, {"ok": False, "status": "error",
                     "message": "That result expired. Please make your offers again."}
    if job["status"] == "running":
        return 200, {"ok": True, "status": "running"}
    if job["status"] == "error":
        return 200, {"ok": False, "status": "error", "message": job.get("message")}
    return 200, {"ok": True, "status": "done", "domain": job["domain"],
                 "audience": job.get("audience", ""), "site_name": job["site_name"], "offers": job["offers"]}


class Handler(SimpleHTTPRequestHandler):
    # S3: HTTP/1.1 keep-alive. Safe only because every response-writing path in
    # this handler goes through one of: self._json() (always sets Content-Length,
    # see below), self._serve_static() (always sets Content-Length), or an
    # unmodified SimpleHTTPRequestHandler/BaseHTTPRequestHandler fallback (static
    # file GET/HEAD, directory listing, 404/redirect via send_error/send_response)
    # - the stdlib itself sets Content-Length on every one of those. There is no
    # chunked/streamed response anywhere in this file. See verification report
    # for the full audit list.
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def end_headers(self):
        # the app ships as static files - stale cached JS against a newer API
        # silently breaks flows (empty ideas table), so force revalidation.
        # EXCEPTION: /app/data/*.json are cron-refreshed snapshots (mailboxes,
        # meta, etc.) — a little staleness (<=60s) is fine per spec, and letting
        # the browser cache them for 60s avoids re-downloading on every nav.
        p = self.path.split("?")[0]
        if p.startswith("/app/data/") and p.endswith(".json"):
            self.send_header("Cache-Control", "max-age=60")
        else:
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter logs
        if "/api/" in str(args[0] if args else ""):  # args[0] can be an HTTPStatus on send_error
            super().log_message(fmt, *args)

    def _accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _json(self, obj, status=200):
        import gzip
        body = json.dumps(obj).encode()
        gz = self._accepts_gzip() and len(body) >= 512  # tiny payloads: framing overhead isn't worth it
        if gz:
            body = gzip.compress(body, 6)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # GET /_audit (~518KB) and /_bundle (~1.8MB) used to re-json.dumps +
    # re-gzip(level 6) their whole cache blob on EVERY request — including the
    # 10s poll ticks while a refresh runs. Memoize the serialized bytes per
    # endpoint (entry replaced atomically as one tuple) and 304 unchanged
    # polls via ETag. The etag folds in ts/running/error, so any state change
    # busts it; ageSec inside a memoized body is at most 30s stale, which the
    # UI only uses for a freshness label.
    _DELIV_RESP_MEMO = {"audit": {}, "bundle": {}}
    _STATIC_GZ_MEMO = {}  # fs_path -> ((mtime, size), gz_bytes) — see _serve_static

    def _json_deliv(self, key, etag, build):
        import gzip
        if self._if_none_match_hit(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        memo = Handler._DELIV_RESP_MEMO[key]
        ent = memo.get("entry")
        if not ent or ent[0] != etag or (time.time() - ent[3]) > 30:
            raw = json.dumps(build()).encode()
            ent = (etag, raw, gzip.compress(raw, 6), time.time())
            memo["entry"] = ent
        gz = self._accepts_gzip() and len(ent[1]) >= 512
        body = ent[2] if gz else ent[1]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", etag)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Static text assets (HTML/CSS/JS/SVG) are shipped uncompressed by the stdlib
    # handler; gzip them here. Binary assets (fonts, images), 404s, ranges and
    # conditional requests fall through to SimpleHTTPRequestHandler untouched.
    _GZIP_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".map", ".txt"}

    # Subresources that are safe to ETag/304 (never HTML — page navigations must
    # always revalidate the no-cache/must-revalidate way; see end_headers()).
    # This is JS/CSS/fonts/icons — the "static subresources" step 2 targets.
    # mtime+size is a cheap, good-enough fingerprint (no need to hash file
    # contents): any real edit changes at least one of the two.
    _ETAG_EXT = {".js", ".mjs", ".css", ".svg", ".map",
                 ".png", ".jpg", ".jpeg", ".gif", ".ico",
                 ".woff", ".woff2", ".ttf", ".eot"}

    def _etag_for(self, fs_path):
        try:
            st = os.stat(fs_path)
        except OSError:
            return None
        return f'"{int(st.st_mtime)}-{st.st_size}"'

    def _if_none_match_hit(self, etag):
        inm = self.headers.get("If-None-Match")
        if not inm or not etag:
            return False
        return etag in [t.strip() for t in inm.split(",")]

    def _serve_static(self):
        import os, gzip, mimetypes
        fs_path = self.translate_path(self.path.split("?")[0])
        ext = os.path.splitext(fs_path)[1].lower()
        if os.path.isdir(fs_path):
            return super().do_GET()

        # ETag/304 short-circuit for cacheable subresources — cheap mtime+size
        # fingerprint, checked BEFORE reading the file at all so a 304 never
        # pays the read/gzip cost. Runs for both the gzip and non-gzip paths
        # below (fonts/icons don't hit the _GZIP_EXT branch but still get ETags).
        etag = self._etag_for(fs_path) if ext in self._ETAG_EXT else None
        if etag and self._if_none_match_hit(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return

        use_gzip = self._accepts_gzip() and ext in self._GZIP_EXT
        if not use_gzip and not etag:
            return super().do_GET()  # unhandled extension — untouched fallback (ranges, 404s, etc.)
        try:
            with open(fs_path, "rb") as f:
                body = f.read()
        except OSError:
            return super().do_GET()  # let the default path emit the 404
        ctype = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ext in (".js", ".mjs", ".json", ".svg"):
            ctype += "; charset=utf-8"
        send_body = body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if etag:
            self.send_header("ETag", etag)
        if use_gzip:
            # memoized per (path, mtime, size): the 489KB deliverability-tab.js
            # was re-compressed on every cache-missing GET; the files only
            # change on deploy, which changes mtime and busts the entry
            try:
                st = os.stat(fs_path)
                st_key = (st.st_mtime, st.st_size)
            except OSError:
                st_key = None
            memo = Handler._STATIC_GZ_MEMO.get(fs_path)
            if memo and st_key and memo[0] == st_key:
                send_body = memo[1]
            else:
                send_body = gzip.compress(body, 6)
                if st_key:
                    if len(Handler._STATIC_GZ_MEMO) > 64:  # tiny fleet of assets; hard cap
                        Handler._STATIC_GZ_MEMO.clear()
                    Handler._STATIC_GZ_MEMO[fs_path] = (st_key, send_body)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(send_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(send_body)

    # ── Deliverability proxy ────────────────────────────────────────────────
    # Forwards /api/deliverability/<rest> to the standalone audit dashboard's
    # live /api/<rest> (which does the real Smartlead work), adding server-side
    # HTTP Basic Auth so the browser never sees the credentials and we avoid a
    # cross-origin call. Purely additive — touches no existing route. Needs
    # DELIV_AUDIT_AUTH="user:pass" in the environment (Render env var); without
    # it we return a clear 503 instead of a silently broken UI.
    _DELIV_AUDIT_BASE = "https://navreo-email-deliverability-audit.onrender.com/api/"

    def _proxy_deliverability(self, method):
        if _deliv_mock_on():  # DELIV_MOCK — serve from the fake fleet, zero network
            rest = self.path[len("/api/deliverability/"):]
            body = None
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                body = self._post_body
            status, obj = mock_deliv.handle_proxy(method, rest, body)
            return self._json(obj, status)
        import base64, urllib.error
        auth = os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or ""
        if ":" not in auth:
            return self._json({"error": "deliverability_backend_unconfigured",
                               "message": "Live deliverability backend isn't configured on this "
                                          "server yet (set the DELIV_AUDIT_AUTH env var)."}, 503)
        url = self._DELIV_AUDIT_BASE + self.path[len("/api/deliverability/"):]  # keeps query string
        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self._post_body
            # ledger: every proxied deliverability mutation (apply signatures,
            # process-new, warmup changes, ...) — previously invisible
            try:
                _pl = json.loads(body.decode() or "{}") if body else {}
            except (ValueError, UnicodeDecodeError):
                _pl = {"_raw_bytes": len(body or b"")}
            _rest = self.path.split("?")[0][len("/api/deliverability/"):]
            log_activity(self.path.split("?")[0], _pl,
                         action=_rest.strip("/") or "post", entity="deliverability")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        if method == "POST":
            req.add_header("Content-Type", self.headers.get("Content-Type") or "application/json")
        try:
            # /api/run kicks off a full live audit (~1-2 min) — give it headroom.
            with urllib.request.urlopen(req, timeout=180, context=SSL_CTX) as resp:
                data, ctype, status = resp.read(), resp.headers.get("Content-Type", "application/octet-stream"), resp.status
        except urllib.error.HTTPError as e:
            data = e.read()
            ctype = (e.headers.get("Content-Type", "text/plain") if e.headers else "text/plain")
            status = e.code
        except Exception as e:  # noqa: BLE001 — network/timeout: surface upstream failure as 502
            return self._json({"error": "deliverability_upstream_error", "message": str(e)[:300]}, 502)
        # restingDue arrives as the pause moment, not the due-back date — shift
        # it to +7d before it reaches any client (see _deliv_fix_resting_due).
        _rest_path = self.path[len("/api/deliverability/"):].split("?")[0].strip("/")
        if method == "GET" and status == 200 and _rest_path == "domain-health":
            try:
                obj = json.loads(data)
                _deliv_fix_resting_due(obj)
                data = json.dumps(obj).encode()
            except (ValueError, UnicodeDecodeError):
                pass  # non-JSON upstream reply — forward untouched
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── login gate plumbing ────────────────────────────────────────────────
    def _authed_email(self):
        return _session_email(self.headers.get("Cookie"))

    _MAX_POST_BODY = 32 * 1024 * 1024

    def _drain_request_body(self) -> bool:
        """Read the request body exactly ONCE, up front, into self._post_body.

        This server speaks HTTP/1.1 keep-alive. Any handler branch that
        responds WITHOUT reading the body (401 gates, cron kicks, early
        returns) leaves the body bytes on the socket — and the next request
        on that same connection parses them as a request line, which
        http.server answers with '501 Unsupported method'. That was the
        intermittent "Request failed (501)" the setter queue hit. Draining
        here makes desync impossible regardless of which branch answers.
        Returns False when the request was rejected (413 already written)."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._post_body = b""
            return True
        if length > self._MAX_POST_BODY:
            remaining = length
            while remaining > 0:  # keep the connection in sync even on reject
                chunk = self.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._post_body = b""
            self._json({"error": "payload too large"}, 413)
            return False
        self._post_body = self.rfile.read(length)
        return True

    def _gate(self, path) -> bool:
        """True → request may proceed. False → a 401/redirect was written."""
        if self._authed_email():
            return True
        if path.startswith("/api/"):
            self._json({"error": "auth_required", "message": "Sign in required."}, 401)
            return False
        # page navigation → login, preserving the destination
        from urllib.parse import quote
        self.send_response(302)
        self.send_header("Location", "/app/login.html?next=" + quote(self.path))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json_with_cookie(self, obj, cookie, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        path = self.path.split("?")[0]
        if path in _AUTH_PUBLIC_GET or path.startswith(_AUTH_PUBLIC_GET_PREFIX) \
                or self._authed_email():
            return super().do_HEAD()
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()


    # ── upload-gate reviews (lilly-upload-gate) — runs live in qa_gate_runs ──
    def _qa_token_ok(self):
        import hashlib
        want = os.environ.get("SIGNAL_PULL_TOKEN") or KEYS.get("SIGNAL_PULL_TOKEN")
        if not want:
            srk = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
            want = hashlib.sha256((srk + ":signal-pull-v1").encode()).hexdigest()[:40] if srk else None
        return bool(want) and self.headers.get("x-navreo-token") == want

    def _qa_row(self, rid):
        if not rid.replace("-", "").isalnum():
            return None
        rows = sb("GET", f"qa_gate_runs?id=eq.{rid}&select=*")
        return rows[0] if isinstance(rows, list) and rows else None

    def _qa_gate_get(self, path):
        try:
            return self._qa_gate_get_inner(path)
        except Exception as e:  # noqa: BLE001 — a bad run must 500, never kill the connection (Render shows that as 502)
            print(f"[qa-gate] GET {path} crashed: {type(e).__name__}: {e}", file=sys.stderr)
            return self._json({"error": f"qa-gate render failed: {type(e).__name__}"}, 500)

    def _qa_gate_get_inner(self, path):
        import qa_gate
        from urllib.parse import parse_qs, urlparse
        parts = path.strip("/").split("/")
        if parts[:2] == ["api", "qa-gate"] and len(parts) == 3 and parts[2] == "receipts":
            q = parse_qs(urlparse(self.path).query)
            lid = (q.get("list_id") or [""])[0].strip()
            camp = (q.get("campaign_id") or [""])[0].strip()
            if not lid and not camp:
                return self._json({"error": "list_id or campaign_id required"}, 400)
            flt = f"list_id=eq.{lid}" if lid else f"campaign_id=eq.{camp}"
            rows = sb("GET", f"qa_gate_runs?{flt}&select=id,created_at,campaign_id,"
                             f"campaign_name,run,decisions&order=created_at.desc&limit=20")
            if not isinstance(rows, list):
                return self._json({"error": "db unavailable"}, 503)
            out = []
            for r in rows:
                dec = r.get("decisions") or []
                up = next((x for x in dec if x.get("action") == "upload"), None)
                out.append({"id": r["id"], "created_at": r["created_at"],
                            "campaign_name": r.get("campaign_name"),
                            "rows_in": (r.get("run") or {}).get("rows_in"),
                            "flags": len((r.get("run") or {}).get("flags") or []),
                            "gate": qa_gate.gate_state(r["run"], dec),
                            "upload": ({"mode": up["mode"], "by": up.get("by"), "at": up.get("at")}
                                       if up else None),
                            "url": f"/qa-gate/{r['id']}"})
            return self._json({"receipts": out})
        if parts[0] == "qa-gate" and len(parts) == 2:
            row = self._qa_row(parts[1])
            if not row:
                return self._json({"error": "run not found"}, 404)
            html = qa_gate.render(row["run"], row.get("decisions") or [], live=True,
                                  api_base=f"/api/qa-gate/{parts[1]}",
                                  list_id=row.get("list_id"))
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parts[:2] == ["api", "qa-gate"] and len(parts) == 4:
            rid, tail = parts[2], parts[3]
            row = self._qa_row(rid)
            if not row:
                return self._json({"error": "run not found"}, 404)
            run, dec = row["run"], row.get("decisions") or []
            if tail == "state":
                state, dropped, _ = qa_gate.resolve(run, dec)
                return self._json({"decisions": dec, "gate": qa_gate.gate_state(run, dec),
                                   "open": sum(1 for s2, _ in state.values() if s2 == "open"),
                                   "dropped": sorted(dropped),
                                   "upload": next((x for x in dec if x.get("action") == "upload"), None)})
            if tail == "rows":
                return self._json(qa_gate.working_rows(run, dec))
        return self._json({"error": "not found"}, 404)

    def _qa_gate_post(self, path):
        try:
            return self._qa_gate_post_inner(path)
        except Exception as e:  # noqa: BLE001
            print(f"[qa-gate] POST {path} crashed: {type(e).__name__}: {e}", file=sys.stderr)
            return self._json({"error": f"qa-gate action failed: {type(e).__name__}"}, 500)

    def _qa_gate_post_inner(self, path):
        import qa_gate, datetime
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8_000_000:
            return self._json({"error": "payload too large"}, 413)
        try:
            body = json.loads(self._post_body.decode() or "{}")
        except ValueError:
            return self._json({"error": "invalid JSON body"}, 400)
        if path == "/api/qa-gate/runs":
            if not self._qa_token_ok():
                return self._json({"error": "unauthorized"}, 401)
            run = body.get("run")
            if not isinstance(run, dict) or "flags" not in run or "results" not in run:
                return self._json({"error": "body.run must be a gate run object (flags+results)"}, 400)
            row = {"campaign_id": str((run.get("campaign") or {}).get("id") or ""),
                   "campaign_name": (run.get("campaign") or {}).get("name"),
                   "list_id": body.get("list_id"), "run": run, "decisions": []}
            res = sb("POST", "qa_gate_runs", row, prefer="return=representation")
            if not isinstance(res, list) or not res:
                return self._json({"error": "db write failed"}, 503)
            rid = res[0]["id"]
            log_activity(path, {"campaign": row["campaign_name"], "rows": run.get("rows_in")},
                         action="create", entity="qa_gate_run", entity_id=str(rid))
            return self._json({"ok": True, "id": rid, "url": f"/qa-gate/{rid}"})
        parts = path.strip("/").split("/")
        if parts[:2] == ["api", "qa-gate"] and len(parts) == 4:
            rid, action = parts[2], parts[3]
            row = self._qa_row(rid)
            if not row:
                return self._json({"error": "run not found"}, 404)
            status, payload, newdec = qa_gate.apply_action(
                row["run"], row.get("decisions") or [], action, body)
            if newdec is not None:
                res = sb("PATCH", f"qa_gate_runs?id=eq.{rid}",
                         {"decisions": newdec,
                          "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                if action == "upload":
                    up = next((x for x in newdec if x.get("action") == "upload"), {})
                    log_activity(path, {"mode": up.get("mode"), "by": up.get("by")},
                                 action="upload", entity="qa_gate_run", entity_id=str(rid))
            return self._json(payload, status)
        return self._json({"error": "not found"}, 404)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":  # liveness only — NO DB call, so the health check can't flap
            return self._json({"ok": True})
        if path == "/api/auth/me":  # who am I (login page uses it to skip itself)
            return self._json({"email": self._authed_email()})
        if path == "/api/auth/logout":
            self.send_response(302)
            self.send_header("Location", "/app/login.html")
            self.send_header("Set-Cookie", _session_cookie("", 0))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.startswith("/api/qa-gate/") and self._qa_token_ok():
            return self._qa_gate_get(path)
        if path not in _AUTH_PUBLIC_GET and not path.startswith(_AUTH_PUBLIC_GET_PREFIX):
            # Public training-share reads: only when a share=<token> is
            # actually present on the query string - the token's validity is
            # then enforced inside setter.py's own routes (verify_training_share).
            if not (path in _TRAIN_SHARE_GET and "share=" in self.path):
                if not self._gate(path):
                    return
        if path.startswith("/qa-gate/") or path.startswith("/api/qa-gate/"):
            return self._qa_gate_get(path)
        if path.startswith("/recontact/") and len(path) > len("/recontact/"):
            # Recontact review page (tier1-live-ship) - behind the normal login
            # gate above (this path is deliberately NOT in _AUTH_PUBLIC_GET).
            # Follows the /qa-gate/<id> pattern: server.py owns the
            # recontact_runs row, recontact.py owns rendering only.
            run_id = path[len("/recontact/"):].strip("/")
            if not run_id.replace("-", "").isalnum():
                return self._json({"error": "invalid run id"}, 400)
            existing = sb("GET", f"recontact_runs?id=eq.{run_id}&limit=1")
            if not (isinstance(existing, list) and existing):
                sb("POST", "recontact_runs?on_conflict=id", {"id": run_id, "payload": {}},
                   prefer="resolution=merge-duplicates,return=minimal")
            import recontact
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            seed = (q.get("campaign_id") or [""])[0]
            html_out = recontact.render(run_id, seed).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(html_out)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(html_out)
            return
        if path == "/api/insights":  # Today homepage: daily insight feed (generated on first request, cached per day)
            import insights_engine
            payload = insights_engine.api_insights(sb)
            if payload:
                return self._json(payload)
            return self._json({"error": "insights_unavailable"}, 503)
        if path == "/api/cron/last-run":  # observability: latest scheduled batch-pull summary
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            kind = (q.get("kind") or [""])[0].strip()
            qs = "signal_cron_runs?order=id.desc&limit=1"
            if kind:
                # summary is a jsonb column; ->> pulls "kind" out as text for the filter.
                qs = f"signal_cron_runs?summary->>kind=eq.{kind}&order=id.desc&limit=1"
            rows = sb("GET", qs)
            return self._json((rows or [{}])[0])
        if path == "/api/sources":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            srcs, fetch_failed = _cached_sources_full()
            if fetch_failed and not srcs:
                # Supabase errored AND the file fallback yielded nothing - an honest
                # 503 beats a 200-[] that the UI would render as "no campaigns".
                return self._json({"error": "supabase_unavailable",
                                    "message": "Couldn't reach the database - try again."}, 503)
            # Optional ?client_id= narrows to that client's sources. Sources don't
            # reliably carry their own client_id (see _campaign_client_map), so this
            # joins through campaign_id -> the owning campaign draft's client_id,
            # falling back to a direct client_id match if a row happens to have one.
            # Filtered from the same cached full list — no extra Supabase round-trip,
            # and the no-param case (the common path) is byte-identical to today.
            cid = (q.get("client_id") or [""])[0].strip()
            if cid:
                cmap = _campaign_client_map()
                srcs = [s for s in srcs if s.get("client_id") == cid
                        or cmap.get(str(s.get("campaign_id"))) == cid]
            if (q.get("slim") or [""])[0].lower() in ("1", "true", "yes"):
                # List-view callers only read source meta/counts (name, type,
                # campaign_id, total, last_pull, destination, _count_stale, etc.)
                # - never the per-source `prospects` array, which is what makes
                # this endpoint's payload heavy (baseline ~222KB). Strip just
                # that one key; every other field is untouched so counts/meta
                # stay byte-identical to the non-slim response. Derived from the
                # same cached full result above - no second Supabase fetch.
                srcs = [{k: v for k, v in s.items() if k != "prospects"} for s in srcs]
            return self._json(srcs)
        if path == "/api/leads":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            cid = (q.get("campaign_id") or [""])[0]
            lim = (q.get("limit") or [""])[0]
            if lim.isdigit():
                # Leads tab: incremental server-side page (offset/limit). Absent
                # limit keeps the legacy all-rows path (Overview/velocity/batch).
                off = (q.get("offset") or ["0"])[0]
                return self._json(_leads_page_for_campaign(cid, int(off) if off.lstrip("-").isdigit() else 0, int(lim)))
            return self._json(api_leads(cid))
        if path == "/api/leads-batch":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_leads_batch((q.get("campaign_ids") or [""])[0]))
        if path == "/api/lead-counts":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            counts = api_lead_counts()
            # Optional ?client_id= narrows to that client's campaigns. Keyed by
            # campaign_id (a signal_leads aggregate, no client dimension of its
            # own), so filtering joins through the same campaign_id -> client_id
            # map /api/sources uses. `_degraded` is a top-level flag, not a
            # campaign entry - always pass it through untouched. Filtered from the
            # same cached payload — no extra Supabase round-trip, and the
            # no-param case (the common path) is byte-identical to today.
            cid = (q.get("client_id") or [""])[0].strip()
            if cid:
                cmap = _campaign_client_map()
                counts = {k: v for k, v in counts.items() if k == "_degraded" or cmap.get(k) == cid}
            return self._json(counts)
        if path == "/api/strategy-result":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(strategy_map_result((q.get("job") or [""])[0]))
        if path == "/api/engagement-verdicts":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(engagement_verdicts((q.get("source_id") or [""])[0],
                                                  (q.get("verdict") or ["unqualified"])[0]))
        if path == "/api/qa-history":
            return self._json(read_json_list(QA_HISTORY))
        if path == "/api/campaign-drafts":
            drafts, fetch_failed = _cached_campaign_drafts()
            if fetch_failed and not drafts:
                return self._json({"error": "supabase_unavailable",
                                    "message": "Couldn't reach the database - try again."}, 503)
            # Optional ?client_id= narrows the response to that client's drafts.
            # campaign_drafts.doc already carries a real client_id (no alias
            # mapping needed, unlike notifications' free-text `client` column).
            # Filtered from the same 30s-TTL cached full list — no extra
            # Supabase round-trip per client, and the no-param case (the
            # common path) is untouched: same object, same bytes, as today.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            cid = (q.get("client_id") or [""])[0].strip()
            if cid:
                drafts = [d for d in drafts if d.get("client_id") == cid]
            # Tombstoned docs (superseded by a platform-keyed camp-* doc during
            # the mirror migration) must never surface — the platform mirror
            # row is the only visible representation of that campaign now.
            drafts = [d for d in drafts if not d.get("superseded_by")]
            return self._json(drafts)
        if path == "/api/notifications":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_notifications(q))
        if path == "/api/clients":
            clients, _fetch_failed = _cached_clients()
            return self._json(clients)
        if path == "/api/outreach-destinations":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            refresh = (q.get("refresh") or [""])[0].lower() in ("1", "true", "yes")
            return self._json(outreach_destinations({"refresh": refresh}))
        if path == "/api/campaign-scorecard":
            # Real per-campaign performance for EVERY campaign in the list, read
            # from the background-synced campaign_scorecard cache (Smartlead's own
            # numbers) + HeyReach LinkedIn progress. SWR ~2min over a cheap
            # Supabase read; the slow /analytics fetches happen in the bg thread.
            return self._json(_CAMPAIGN_SCORECARD_ALL_SWR.get())
        if path == "/api/campaigns-unified":
            # ONE row per outbound campaign account-wide (Smartlead + HeyReach
            # + unlinked drafts). Homepage list source. SWR-cached ~10min.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            refresh = (q.get("refresh") or [""])[0].lower() in ("1", "true", "yes")
            return self._json(campaigns_unified({"refresh": refresh}))
        if path == "/api/perf-daily":
            # Homepage 5-line graph: per-day sent / leads-added / reply-rate /
            # positives / meetings from the Supabase data layer. Optional
            # ?campaign=<smartlead_id> (default fleet) and ?days=N or
            # ?start=&end=. Nulls (labelled absent), never fake zeros.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(perf_daily({
                "days": (q.get("days") or ["30"])[0],
                "start": (q.get("start") or [None])[0],
                "end": (q.get("end") or [None])[0],
                "campaign": (q.get("campaign") or [None])[0]}))
        if path == "/api/collective-30d":
            # Homepage strip's LAST-30-DAYS top line (sent/reply/positives/meetings/
            # signals) — one cheap DB round-trip via rpc/collective_30d, SWR-cached.
            return self._json(_COLLECTIVE_30D_SWR.get())
        if path == "/api/campaign-platform-leads":
            # One page of a campaign's real platform leads for the detail Leads tab.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(campaign_platform_leads({
                "platform": (q.get("platform") or [""])[0], "id": (q.get("id") or [""])[0],
                "offset": (q.get("offset") or ["0"])[0], "limit": (q.get("limit") or ["50"])[0]}))
        if path == "/api/campaign-readonly":
            # Read-only live snapshot of ONE external campaign (not set up in
            # this tool), so clicking it on the homepage opens a view instead of
            # a dead row. Smartlead = live /analytics; HeyReach = latest snapshot.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(campaign_readonly({"platform": (q.get("platform") or [""])[0],
                                                 "id": (q.get("id") or [""])[0]}))
        if path == "/api/campaign-insights":
            # tier1-live-ship: PROXY per-source attribution + deterministic
            # findings for one Smartlead campaign. platform=smartlead only.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_campaign_insights({"platform": (q.get("platform") or [""])[0],
                                                      "id": (q.get("id") or [""])[0]}))
        if path == "/api/campaign-ideas":
            # Pure read - generation only ever happens via POST (see
            # api_campaign_ideas_start). Excludes dismissed ideas.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_campaign_ideas_get({"campaign_id": (q.get("campaign_id") or [""])[0]}))
        if path == "/api/recontact/scan":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            result = api_recontact_scan((q.get("campaign_id") or [""])[0])
            if isinstance(result, dict) and result.get("error"):
                return self._json(result, 404)
            return self._json(result)
        if path == "/api/recontact/job":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_recontact_job((q.get("id") or [""])[0]))
        if path == "/api/version":
            # Deploy verification: which commit/instance is actually serving.
            return self._json({"commit": _GIT_COMMIT or None,
                               "server_instance": _SERVER_INSTANCE,
                               "render_instance_id": os.environ.get("RENDER_INSTANCE_ID"),
                               "on_render": _ON_RENDER,
                               "uptime_seconds": round(time.time() - _BOOT_AT)})
        if path == "/api/jobs":
            # Memory first (live progress), then union in durable app_jobs rows
            # that aren't in memory (recent history + jobs from before a restart).
            with JOBS_LOCK:
                mem = list(reversed(JOBS.values()))
            seen = {j["id"] for j in mem}
            db = sb("GET", "app_jobs?order=created_at.desc&limit=50") or []
            merged = mem + [r for r in db if r.get("id") not in seen]
            return self._json({"jobs": merged[:50]})
        if path == "/api/campaign-lead-counts":
            # "How many leads will a verify cover?" — Smartlead's total_leads via
            # a limit=1 page per campaign, cached 1hr so repaints don't re-pay
            # the round-trips. The count is the campaign's FULL lead list
            # (verify scope), not the sent count shown on the audit rows.
            # Smartlead 429s under load, so each id gets up to 3 attempts
            # (3s, then 8s backoff) with a generous per-request timeout before
            # this gives up and reports "unknown" for that one id.
            from urllib.parse import parse_qs, urlparse
            ids = [s for s in (parse_qs(urlparse(self.path).query).get("ids") or [""])[0]
                   .split(",") if s.strip()][:25]
            sl_key = KEYS.get("SMARTLEAD_API_KEY") or os.environ.get("SMARTLEAD_API_KEY") or ""
            out = {}
            budget_t0 = time.time()  # hard handler budget: a Smartlead brown-out
            # must not hold a UI repaint (and a server thread) for minutes —
            # unfinished ids return null; the UI already renders "unknown" and
            # a later repaint retries against the warm cache.
            for cid in ids:
                cached = _LEAD_COUNT_CACHE.get(cid)
                if cached and time.time() - cached[1] < 3600:
                    out[cid] = cached[0]
                    continue
                if time.time() - budget_t0 > 8:
                    out[cid] = None
                    continue
                n = None
                for attempt, backoff in enumerate((0, 2)):
                    if backoff:
                        time.sleep(backoff)
                    try:
                        page = http_json("GET", f"{SMARTLEAD_BASE}/campaigns/{cid}/leads"
                                                f"?api_key={sl_key}&offset=0&limit=1", {},
                                         timeout=10)
                        n = int((page or {}).get("total_leads") or 0)
                        break
                    except Exception:  # noqa: BLE001 — retry, then "unknown" not a 500
                        continue
                # "Leads to verify" excludes leads already verified within
                # _VERIFY_TTL_DAYS. A verify run's cache lookup spans TWO
                # tiers (people.email_verification + email_verifications), so
                # the discount must too — the old email_verifications-only
                # subtraction undercounted whenever verdicts landed on people
                # rows (the primary tier). campaign_verified_count() is a
                # Postgres function doing the distinct-email union across both
                # tiers, using contact_history to know which emails belong to
                # this campaign.
                if n:
                    try:
                        _vc = sb("POST", "rpc/campaign_verified_count",
                                 {"cid": str(cid), "ttl_days": _VERIFY_TTL_DAYS})
                        if isinstance(_vc, (int, float)):
                            n = max(0, n - int(_vc))
                    except Exception:  # noqa: BLE001 — best-effort discount; raw total beats a 500
                        pass
                if n is not None:
                    _LEAD_COUNT_CACHE[cid] = (n, time.time())
                out[cid] = n
            return self._json({"counts": out})
        if path == "/api/verify-status":
            from urllib.parse import parse_qs, urlparse
            ids = [s for s in (parse_qs(urlparse(self.path).query).get("ids") or [""])[0]
                   .split(",") if s.strip()]
            return self._json(api_verify_status(ids))
        if path == "/api/mailbox-tag-names":
            # Existing Smartlead tag names for the Process-new modal's tag
            # autocomplete — a typo there silently creates a brand-new tag
            # object (which the API can't delete), so offer the real names.
            # 1h TTL cache (tags change rarely, autocomplete tolerates lag);
            # stale-on-error beats the old 502 during Smartlead 429s.
            if _TAG_NAMES_SWR["names"] is not None and \
                    (time.time() - _TAG_NAMES_SWR["ts"]) < 3600:
                return self._json({"ok": True, "names": _TAG_NAMES_SWR["names"]})
            try:
                tags = _smartlead_json("GET", "/email-accounts/tags") or []
                names = sorted({(t.get("name") or "").strip() for t in tags
                                if isinstance(t, dict)} - {""}, key=str.lower)
                _TAG_NAMES_SWR.update(names=names, ts=time.time())
            except Exception as e:  # noqa: BLE001 — autocomplete is best-effort
                if _TAG_NAMES_SWR["names"] is not None:
                    return self._json({"ok": True, "names": _TAG_NAMES_SWR["names"], "stale": True})
                return self._json({"ok": False, "message": str(e)[:200]}, 502)
            return self._json({"ok": True, "names": names})
        if path.startswith("/api/jobs/"):
            jid = path[len("/api/jobs/"):]
            job = _job_get(jid)  # memory first, then durable app_jobs (survives restart)
            if not job:
                return self._json({"error": "not_found"}, 404)
            return self._json(job)
        if path == "/api/deliverability/_mock/state":  # DELIV_MOCK — mock-only, 404 outside mock mode
            if not _deliv_mock_on():
                return self._json({"error": "not_found"}, 404)
            return self._json(mock_deliv.control("get-state", {}))
        if path == "/api/deliverability/_audit":
            # Cached live-audit blob (instant). The tab polls this while a
            # background run is in flight; it triggers the run via the refresh POST.
            _deliv_audit_restore()  # fresh process: serve the persisted blob instantly
            with _DELIV_AUDIT_LOCK:
                b, ts, running, err = (_DELIV_AUDIT["blob"], _DELIV_AUDIT["ts"],
                                       _DELIV_AUDIT["running"], _DELIV_AUDIT["error"])
            age = (time.time() - ts) if ts else None
            configured = True if _deliv_mock_on() else bool(
                (os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or "").count(":"))
            stale = bool(b is not None and age is not None and age >= _DELIV_AUDIT_TTL_S)
            etag = f'"dlv-a-{ts:.0f}-{int(bool(running))}-{int(bool(err))}-{int(configured)}-{int(stale)}"'
            return self._json_deliv("audit", etag, lambda: {
                "blob": b, "ts": ts, "ageSec": age, "running": running,
                "error": err, "configured": configured, "stale": stale})
        if path == "/api/deliverability/_bundle":
            # Cached manager views + domain-health windows (instant). Serving a
            # stale bundle beats serving none — the kick below refreshes it in
            # the background and the client polls while `running`.
            _deliv_bundle_restore()
            st = _deliv_bundle_start(force=False)  # no-ops while fresh
            with _DELIV_BUNDLE_LOCK:
                d, ts, running, err = (_DELIV_BUNDLE["data"], _DELIV_BUNDLE["ts"],
                                       _DELIV_BUNDLE["running"], _DELIV_BUNDLE["error"])
            age = (time.time() - ts) if ts else None
            running = running or bool(st.get("started"))
            configured = True if _deliv_mock_on() else bool(
                (os.environ.get("DELIV_AUDIT_AUTH") or KEYS.get("DELIV_AUDIT_AUTH") or "").count(":"))
            stale = bool(d is not None and age is not None and age >= _DELIV_AUDIT_TTL_S)
            etag = f'"dlv-b-{ts:.0f}-{int(bool(running))}-{int(bool(err))}-{int(configured)}-{int(stale)}"'
            return self._json_deliv("bundle", etag, lambda: {
                "bundle": d, "ts": ts, "ageSec": age, "running": running,
                "error": err, "configured": configured, "stale": stale})
        if path == "/api/deliverability-trends":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                days = int((q.get("days") or ["30"])[0])
            except ValueError:
                days = 30
            body, status = deliv_trends_get(days)
            return self._json(body, status)
        if path == "/api/restore-plan":
            body, status = api_restore_plan()
            return self._json(body, status)
        if path == "/api/deliverability/reminders":
            # Same data the plain proxy would return, but from the 5-min
            # _restore_reminders cache (invalidated by this app's own
            # reminder-mutating POSTs) — the boot-path GET stops paying a
            # 0.4-2.2s live round-trip. Mock mode rides the same helper.
            rems, _src = _restore_reminders()
            return self._json(rems if isinstance(rems, list) else [])
        if path.startswith("/api/deliverability/"):
            return self._proxy_deliverability("GET")
        if path == "/api/lists":
            status, body = api_lists_index()
            return self._json(body, status)
        if path == "/api/list_pulls":
            status, body = api_list_pulls_index()
            return self._json(body, status)
        if path == "/api/list_pulls/for_list":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_list_pull_for_list(q)
            return self._json(body, status)
        if path == "/api/list_pulls/campaigns":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_list_pull_campaigns(q)
            return self._json(body, status)
        if path == "/api/list_pulls/by_campaign":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_list_pulls_by_campaign(q)
            return self._json(body, status)
        if path == "/api/list_pulls/push_summary":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_list_pulls_push_summary(q)
            return self._json(body, status)
        if path == "/api/lists/rows":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_lists_rows(q)
            return self._json(body, status)
        if path == "/api/lists/distinct":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status, body = api_lists_distinct(q)
            return self._json(body, status)
        if path == "/api/lists/export":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            kind, a, b = api_lists_export_csv(q)
            if kind == "error":
                return self._json(b, a)
            filename, data = a, b
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            return
        if path.startswith("/api/setter/"):
            fn = setter.GET_ROUTES.get(path)
            if fn:
                from urllib.parse import parse_qs, urlparse
                status, body = fn(parse_qs(urlparse(self.path).query))
                return self._json(body, status)
        return self._serve_static()

    # POSTs that mutate NOTHING the UI caches read at request time — pure
    # kick/poll/login endpoints. Clearing on these defeated every SWR cache
    # each time a cron tick or refresh-kick landed (i.e. constantly), forcing
    # cold Supabase reads on the next page load for no correctness gain. The
    # cron pull's background job re-clears on COMPLETION (when data actually
    # changed) — see _cron_pull_bg.
    _CLEAR_CACHE_EXEMPT_POST = {
        "/api/auth/login", "/api/cron/pull-all", "/api/cron/heyreach-sync",
        "/api/cron/mailbox-sync", "/api/cron/audit-refresh", "/api/setter/poll",
        "/api/cron/reply-sync", "/api/notify/positive-card",
        "/api/deliverability/_audit/refresh", "/api/deliverability/_bundle/refresh",
    }

    def do_POST(self):
        if not self._drain_request_body():
            return
        path = self.path.split("?")[0]
        if path not in self._CLEAR_CACHE_EXEMPT_POST:
            _clear_ui_caches()  # G2: every other POST may mutate — never let a stale cached GET follow it
        if path == "/api/auth/login":
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4096:
                return self._json({"ok": False, "message": "payload too large"}, 413)
            try:
                p = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            email = (p.get("email") or "").strip().lower()
            password = p.get("password") or ""
            ok, msg = auth_login(email, password) if email and password \
                else (False, "Email and password are required.")
            # ledger: attempt + outcome, NEVER the password
            log_activity(path, {"email": email, "ok": ok}, action="login",
                         entity="auth", entity_id=email or None)
            if not ok:
                time.sleep(0.8)  # cheap brute-force drag
                return self._json({"ok": False, "message": msg}, 401)
            return self._json_with_cookie(
                {"ok": True, "email": email},
                _session_cookie(_mint_session(email), AUTH_SESSION_DAYS * 86400))
        if path in ("/api/offer/generate", "/api/offer/start", "/api/offer/result", "/api/offer/email"):
            # Public offer maker — no session, no drafts_lock (slow LLM call must
            # never block the app), no persistence of the visitor's URL. Rate
            # limits are enforced inside the handlers. /generate is the synchronous
            # offers path; /email writes one worked cold email for a single offer.
            length = int(self.headers.get("Content-Length") or 0)
            if length > 12288:  # /email carries a full offer object
                return self._json({"ok": False, "message": "payload too large"}, 413)
            try:
                p = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            ip = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() \
                or self.client_address[0]
            if path == "/api/offer/start":
                status, body = offer_start(p, ip)
            elif path == "/api/offer/result":
                status, body = offer_result(p)
            elif path == "/api/offer/email":
                status, body = offer_email(p, ip)
            else:
                status, body = offer_generate(p, ip)
            return self._json(body, status)
        if path.startswith("/api/qa-gate/") and path != "/api/qa-gate/runs" and self._qa_token_ok():
            return self._qa_gate_post(path)
        if path not in _AUTH_PUBLIC_POST and not self._gate(path):
            return
        if path.startswith("/api/qa-gate/"):
            return self._qa_gate_post(path)
        if path in ("/api/cron/pull-all", "/api/cron/heyreach-sync", "/api/cron/mailbox-sync", "/api/cron/audit-refresh",
                   "/api/cron/fleet-stats", "/api/cron/reply-sync", "/api/setter/poll",
                   "/api/notify/positive-card"):
            # External-scheduler endpoints. Token-guarded (header, not body) and
            # run OUTSIDE the global drafts_lock — each job takes its own locks
            # and the lock does not nest.
            want = os.environ.get("SIGNAL_PULL_TOKEN") or KEYS.get("SIGNAL_PULL_TOKEN")
            if not want:
                # No dedicated token set on this host: derive a stable one from a
                # secret already in the env (avoids a manual Render dashboard step).
                import hashlib
                srk = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
                want = hashlib.sha256((srk + ":signal-pull-v1").encode()).hexdigest()[:40] if srk else None
            got = self.headers.get("x-navreo-token")
            # /api/setter/poll doubles as the UI's "Check now" button, which is
            # session-authed rather than token-authed — accept either.
            if path == "/api/setter/poll":
                if not (self._authed_email() or (want and got == want)):
                    return self._json({"ok": False, "message": "unauthorized"}, 401)
            elif not want or got != want:
                return self._json({"ok": False, "message": "unauthorized"}, 401)
            # Fire-and-forget: both jobs run far longer than any HTTP/pg_net
            # timeout, so kick to a background thread and return immediately.
            # Pull summaries land in signal_cron_runs; HeyReach sync summaries
            # in app_activity_log (actor='heyreach_sync').
            if path == "/api/cron/audit-refresh":
                # True hourly audit: the client-side top-up only fires while a
                # page is open, so the snapshot aged 10h+ overnight. This kicks
                # the same refresh on a schedule; _deliv_audit_start(force=False)
                # no-ops while the cached blob is inside its 1h TTL.
                st = _deliv_audit_start(force=False)
                stb = _deliv_bundle_start(force=False)  # manager views/windows age on the same clock
                return self._json({"ok": True, **st, "bundle": stb}, 202 if st.get("started") else 200)
            if path == "/api/cron/mailbox-sync":
                if _MAILBOX_SYNC_LOCK.locked():
                    return self._json({"ok": True, "started": False, "busy": True}, 200)
                log_activity(path, actor="cron", action="sync", entity="mailboxes")
                threading.Thread(target=_mailbox_sync_bg, daemon=True).start()
                return self._json({"ok": True, "started": True}, 202)
            if path == "/api/notify/positive-card":
                # Categoriser → client-card hook bypass (query params only —
                # the POST body, if any, stays drained by _post_body upstream).
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                cid = (q.get("campaign_id") or [None])[0]
                email = ((q.get("email") or [""])[0]).strip().lower()
                category = (q.get("category") or [""])[0]
                if not (cid and email and category):
                    return self._json({"ok": False, "error": "campaign_id, email, category required"}, 400)
                log_activity(path, actor="categoriser", action="card_notify", entity="replies")
                res = positive_card_notify(cid, email, category)
                return self._json(res, 200 if res.get("ok") else 502)
            if path == "/api/cron/reply-sync":
                # Backstop: pull the master inbox and feed unseen replies to the
                # categoriser hook. Runs longer than pg_net's timeout under a
                # burst, so kick to a background thread and ack immediately. A
                # cap-hit lands as reply_sync_failed with the gap (never silent).
                if _REPLY_SYNC_LOCK.locked():
                    return self._json({"ok": True, "started": False, "busy": True}, 200)
                log_activity(path, actor="cron", action="reply_sync", entity="replies")
                threading.Thread(target=_reply_sync_bg, daemon=True).start()
                return self._json({"ok": True, "started": True}, 202)
            if path == "/api/cron/fleet-stats":
                # Fleet day-by-day record sync. Synchronous (a couple of Smartlead
                # calls + one upsert), so a manual backfill returns its counts:
                #   ?start=YYYY-MM-DD&end=YYYY-MM-DD  (backfill, one calendar year)
                #   ?days=N                            (trailing refresh, default 14)
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                start = (q.get("start") or [None])[0]
                end = (q.get("end") or [None])[0]
                try:
                    res = (fleet_stats_sync(start, end) if (start and end)
                           else fleet_stats_sync_recent(int((q.get("days") or ["14"])[0])))
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e)[:300]}, 500)
                sb("POST", "app_activity_log",
                   {"actor": "cron", "endpoint": "/api/cron/fleet-stats",
                    "action": "fleet_stats_done" if res.get("ok") else "fleet_stats_failed",
                    "entity": "fleet_daily_stats", "payload": res})
                return self._json(res, 200 if res.get("ok") else 502)
            if path == "/api/setter/poll":
                if _SETTER_POLL_LOCK.locked():
                    return self._json({"ok": True, "started": False, "busy": True}, 200)
                log_activity(path, actor="cron", action="poll", entity="setter_queue")
                threading.Thread(target=_setter_poll_bg, daemon=True).start()
                return self._json({"ok": True, "started": True}, 202)
            if path == "/api/cron/heyreach-sync":
                if _HEYREACH_SYNC_LOCK.locked():
                    return self._json({"ok": True, "started": False, "busy": True}, 200)
                log_activity(path, actor="cron", action="sync", entity="heyreach")
                threading.Thread(target=_heyreach_sync_bg, daemon=True).start()
                return self._json({"ok": True, "started": True}, 202)
            if _CRON_LOCK.locked():
                return self._json({"ok": True, "started": False, "busy": True}, 200)
            log_activity(path, actor="cron", action="pull", entity="signals_batch")
            threading.Thread(target=_cron_pull_bg, daemon=True).start()
            return self._json({"ok": True, "started": True}, 202)
        if path == "/api/setter/inbound":
            # Smartlead campaign webhook (EMAIL_REPLY) — instant Setter intake.
            # The token travels in the registered webhook URL's query string
            # (Smartlead can't send custom headers); header accepted too.
            want = os.environ.get("SIGNAL_PULL_TOKEN") or KEYS.get("SIGNAL_PULL_TOKEN")
            if not want:
                import hashlib
                srk = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
                want = hashlib.sha256((srk + ":signal-pull-v1").encode()).hexdigest()[:40] if srk else None
            from urllib.parse import parse_qs, urlparse
            got = (parse_qs(urlparse(self.path).query).get("token") or [""])[0] \
                or self.headers.get("x-navreo-token")
            if not want or got != want:
                return self._json({"ok": False, "message": "unauthorized"}, 401)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            log_activity(path, actor="webhook", action="inbound", entity="setter_queue")
            # Processing takes two model calls (~15s); ack the webhook now and
            # run the pipeline in the background. The poll sweep is the net if
            # this thread dies mid-flight.
            threading.Thread(target=setter.handle_inbound, args=(payload,), daemon=True).start()
            return self._json({"ok": True, "accepted": True}, 202)
        exec_prefix, exec_suffix = "/api/notifications/", "/execute"
        if path.startswith(exec_prefix) and path.endswith(exec_suffix) and \
                len(path) > len(exec_prefix) + len(exec_suffix):
            nid = path[len(exec_prefix):-len(exec_suffix)]
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            log_activity(path, payload, action="execute", entity="notification",
                         entity_id=nid)
            status, body = execute_notification_action(nid, payload)
            return self._json(body, status)
        draft_prefix, draft_suffix = "/api/notifications/", "/draft-fix"
        if path.startswith(draft_prefix) and path.endswith(draft_suffix) and \
                len(path) > len(draft_prefix) + len(draft_suffix):
            nid = path[len(draft_prefix):-len(draft_suffix)]
            status, body = api_notification_draft_fix(nid)
            # log_activity is a no-op-cost fire-and-forget thread (~841); skip it
            # on the cache-hit path so a re-render's re-POST doesn't pad the
            # ledger with a "draft" entry that generated nothing new — the
            # actual generation is already logged inside api_notification_draft_fix.
            return self._json(body, status)
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            jid = path[len("/api/jobs/"):-len("/cancel")]
            with JOBS_LOCK:
                job = JOBS.get(jid)
                if job:
                    if job["status"] not in ("queued", "running"):
                        return self._json({"error": "not_cancellable"}, 409)
                    job["cancel_requested"] = True
                    log_activity(path, action="cancel", entity="job", entity_id=jid)
                    return self._json({"ok": True})
            # Not in this process's memory: the sidebar may be showing a durable
            # app_jobs row (e.g. a zombie from a dead instance). There's no live
            # worker to signal, so "cancelling" it = marking it interrupted —
            # otherwise the Cancel button silently 404s (reviewer finding).
            row = _job_get(jid)
            if not row:
                return self._json({"error": "not_found"}, 404)
            if row.get("status") not in ("queued", "running"):
                return self._json({"error": "not_cancellable"}, 409)
            sb("PATCH", f"app_jobs?id=eq.{jid}",
               {"status": "interrupted",
                "error": "Cancelled — this task had no live worker (server restarted). "
                         "Click Resume if you want it to continue.",
                "finished_at": _now_iso()})
            log_activity(path, action="cancel", entity="job", entity_id=jid)
            return self._json({"ok": True})
        if path.startswith("/api/jobs/") and path.endswith("/resume"):
            jid = path[len("/api/jobs/"):-len("/resume")]
            body, status = resume_job(jid)
            return self._json(body, status)
        if path.startswith("/api/jobs/") and path.endswith("/dismiss"):
            jid = path[len("/api/jobs/"):-len("/dismiss")]
            body, status = dismiss_job(jid)
            return self._json(body, status)
        if path == "/api/jobs/dismiss-finished":
            return self._json(dismiss_finished_jobs())
        if path == "/api/campaign-ideas":
            # Starts an async job (JOBS/app_jobs pattern) - never generates
            # synchronously, and never on a GET (see api_campaign_ideas_get).
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_campaign_ideas_start(payload)
            return self._json(body, status)
        if path == "/api/campaign-ideas/dismiss":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_campaign_ideas_dismiss(payload)
            return self._json(body, status)
        if path == "/api/campaign-ideas/add":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_campaign_ideas_add(payload)
            return self._json(body, status)
        if path == "/api/recontact/buckets":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_recontact_buckets_start(payload)
            return self._json(body, status)
        if path == "/api/recontact/create":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_recontact_create_start(payload)
            return self._json(body, status)
        if path == "/api/verify-campaign":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            log_activity(path, payload)
            body, status = api_verify_campaign(payload)
            return self._json(body, status)
        if path == "/api/verify-remove":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            log_activity(path, payload)
            body, status = api_verify_remove(payload)
            return self._json(body, status)
        if path == "/api/verify-dismiss":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            log_activity(path, payload)
            body, status = api_verify_dismiss(payload)
            return self._json(body, status)
        if path == "/api/warmup-job":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            body, status = api_warmup_job(payload)
            return self._json(body, status)
        if path == "/api/process-new-selected":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            log_activity(path, payload)
            body, status = api_process_new_selected(payload)
            return self._json(body, status)
        if path == "/api/restore-live":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            if not payload.get("dry_run"):  # ledger: real restores only, not previews
                log_activity(path, payload)
            body, status = api_restore_live(payload)
            return self._json(body, status)
        if path == "/api/restore-dismiss":
            # "Mark added" on a detected-resting queue row: bookkeeping only —
            # hides the row (ledger.dismissed); nothing in Smartlead changes.
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            doms = _safe_domains([str(d).lower() for d in (payload.get("domains") or []) if d])
            if not doms:
                return self._json({"ok": False, "message": "no domains"}, 400)
            log_activity(path, payload, action="restore_dismiss", entity="resting_ledger")
            if _deliv_mock_on():
                _RESTORE_DISMISS_MOCK.update(doms)
            else:
                sb("PATCH", "deliverability_resting_ledger?domain=in.(%s)" % ",".join(doms),
                   {"dismissed": True}, prefer="return=minimal")
            _restore_plan_invalidate()  # next restore-plan GET re-reads the ledger
            return self._json({"ok": True, "dismissed": len(doms)})
        if path == "/api/deliverability/_mock/scenario":  # DELIV_MOCK — mock-only, 404 outside mock mode
            if not _deliv_mock_on():
                return self._json({"error": "not_found"}, 404)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}") if length else {}
            except ValueError:
                return self._json({"error": "invalid_json"}, 400)
            if payload.get("reset"):
                out = mock_deliv.control("reset", {})
                # Re-sync the cached audit blob so the UI's next paint reads
                # the pristine fleet instead of a pre-reset snapshot.
                with _DELIV_AUDIT_LOCK:
                    _DELIV_AUDIT.update(blob=mock_deliv.run_audit_blob(), ts=time.time(),
                                        running=False, error=None)
                return self._json(out)
            return self._json(mock_deliv.control("set-scenario", payload))
        if path == "/api/deliverability/_audit/refresh":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                force = bool(json.loads(self._post_body.decode() or "{}").get("force", True)) if length else True
            except ValueError:
                force = True
            log_activity(path, {"force": force}, action="audit_refresh",
                         entity="deliverability")
            return self._json(_deliv_audit_start(force=force))
        if path == "/api/deliverability/_bundle/refresh":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                force = bool(json.loads(self._post_body.decode() or "{}").get("force", True)) if length else True
            except ValueError:
                force = True
            log_activity(path, {"force": force}, action="bundle_refresh",
                         entity="deliverability")
            return self._json(_deliv_bundle_start(force=force))
        if path.startswith("/api/deliverability/reminder"):
            # reminder create / reminder-done / reminder-enable-warmup mutate
            # the reminders the 5-min cache serves — invalidate so the next
            # GET (page reload right after the click) re-reads live instead
            # of showing the pre-mutation list for up to 5 minutes
            self._proxy_deliverability("POST")
            _restore_plan_invalidate()
            return
        if path.startswith("/api/deliverability/"):
            return self._proxy_deliverability("POST")
        setter_route = setter.POST_ROUTES.get(path)
        if setter_route:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            # Only /api/setter/training/answer, /api/setter/training/generate,
            # /api/setter/training/recheck (Review mode) and
            # /api/setter/agents/correction (Review mode's "Teach it more")
            # are in _AUTH_PUBLIC_POST among the setter routes reaching this
            # generic dispatch (poll/inbound are special-cased earlier), so
            # this only ever fires for those public training endpoints -
            # never trust a client-supplied ___public, always set it from the
            # actual session state so a public caller can't spoof owner
            # scope. Guarded on isinstance so a malformed non-dict body (e.g.
            # a bare JSON list) falls through to the route's own try/except
            # exactly as it did before this flag existed, instead of a raw
            # TypeError here.
            if not self._authed_email() and isinstance(payload, dict):
                payload["___public"] = True
            # The training share token is a bearer credential - never persist
            # it to the activity ledger, even truncated.
            log_payload = {k: v for k, v in payload.items() if k != "share"} \
                if isinstance(payload, dict) else payload
            log_activity(path, log_payload, action=path.rsplit("/", 1)[-1], entity="setter")
            status, body = setter_route(payload)
            return self._json(body, status)
        lists_route = LISTS_POST_ROUTES.get(path)
        if lists_route:
            # (status, body) handlers — organisational metadata only; nothing
            # here can write list_rows (see the Lists API HARD RULE above).
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self._post_body.decode() or "{}")
            except ValueError:
                return self._json({"ok": False, "message": "invalid JSON body"}, 400)
            log_activity(path, payload, action=path.rsplit("/", 1)[-1],
                         entity="list", entity_id=payload.get("list_id") or payload.get("folder_id"))
            status, body = lists_route(payload)
            return self._json(body, status)
        route = ROUTES.get(path)
        if not route:
            return self._json({"ok": False, "message": "unknown endpoint"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self._post_body.decode() or "{}")
            log_activity(path, payload)  # ledger first — even a failing call is activity
            with drafts_lock():  # every POST may read-modify-write the drafts files
                return self._json(route(payload))
        except Exception as e:  # noqa: BLE001 — surface provider errors to the UI
            return self._json({"ok": False, "message": str(e)[:300]}, 200)

    def do_PATCH(self):
        if not self._drain_request_body():
            return
        _clear_ui_caches()  # G2: every PATCH may mutate — never let a stale cached GET follow it
        path = self.path.split("?")[0]
        if not self._gate(path):
            return
        prefix = "/api/notifications/"
        if not path.startswith(prefix) or len(path) <= len(prefix):
            return self._json({"ok": False, "message": "unknown endpoint"}, 404)
        nid = path[len(prefix):]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self._post_body.decode() or "{}")
        except ValueError:
            return self._json({"ok": False, "message": "invalid JSON body"}, 400)
        status = payload.get("status")
        if status not in NOTIFICATION_STATUSES:
            return self._json({"ok": False, "message":
                                f"status must be one of {NOTIFICATION_STATUSES}"}, 400)
        log_activity(path, payload, action="status", entity="notification",
                     entity_id=nid)
        try:
            row = update_notification_status(nid, status)
        except LookupError:
            return self._json({"ok": False, "message": "notification not found"}, 404)
        except Exception as e:  # noqa: BLE001 — surface Supabase errors to the caller
            return self._json({"ok": False, "message": str(e)[:300]}, 502)
        return self._json(row)


# ── S1: boot warm-up ───────────────────────────────────────────────────────
# Pre-populate every G1 endpoint cache BEFORE real traffic arrives, so the
# very first real request after boot hits a warm SWR cache instead of paying
# the cold synchronous Supabase round-trip. Runs once, sequentially (so it
# doesn't hammer Supabase with concurrent cold queries), in a daemon thread so
# a slow/unreachable Supabase never delays server startup. Any single step's
# failure is caught and logged — the affected cache is simply left empty and
# will read through honestly (503/_degraded) on the first real request, or
# populate on that request/a later successful background refresh.
def _boot_warmup():
    t0 = time.time()
    steps = [
        ("lead-counts", api_lead_counts),
        ("sources", _cached_sources_full),
        ("campaign-drafts", _cached_campaign_drafts),
        ("clients", _cached_clients),
        ("drafts-read", _cached_read_drafts),
        ("outreach-destinations", lambda: outreach_destinations({"refresh": False})),
    ]
    for name, fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - warm-up must never crash the server
            print(f"[warmup] {name} failed: {e}")
    # Per-campaign leads + the dashboard's batch call: keyed SWR caches, so the
    # first visitor to any campaign detail (or the list's chart) after a boot
    # would otherwise pay the one cold multi-second Supabase read per key.
    try:
        counts = api_lead_counts()
        cids = sorted(c for c in counts if not str(c).startswith("_"))
        for cid in cids:
            try:
                api_leads(cid)
            except Exception as e:  # noqa: BLE001
                print(f"[warmup] leads {cid} failed: {e}")
        # the list view requests leads-batch for the sorted NON-deleted id set —
        # warm that exact key so the dashboard chart is instant on first paint
        drafts, _ = _cached_campaign_drafts()
        live = sorted(str(d.get("id")) for d in (drafts or [])
                      if d.get("id") and not d.get("deleted_at"))
        if live:
            api_leads_batch(",".join(live))
    except Exception as e:  # noqa: BLE001
        print(f"[warmup] leads sweep failed: {e}")
    # Deliverability page caches: restore the persisted audit/bundle blobs
    # into memory and prime the small live caches, so the FIRST page load
    # after a deploy serves warm (<1s) instead of paying per-request restores
    # and live round-trips. All idempotent/locked; failures leave the lazy
    # in-handler paths as fallback.
    for name, fn in (
        ("deliv-audit-restore", _deliv_audit_restore),
        ("deliv-bundle-restore", _deliv_bundle_restore),
        ("deliv-trends", lambda: deliv_trends_get(30)),
        ("restore-mailboxes", _restore_mailboxes),
        ("restore-sweep", _restore_sweep_start),
        ("restore-reminders", _restore_reminders),
        ("tag-names", _warm_tag_names),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"[warmup] {name} failed: {e}")
    print(f"[warmup] complete in {time.time() - t0:.1f}s")


_BOOT_AT = time.time()
_GIT_COMMIT = os.environ.get("RENDER_GIT_COMMIT") or ""
_BOOT_LEDGER_ID = [None]  # set once _boot_ledger_start's insert lands


def _boot_ledger_start():
    """One server_boot_ledger row per process boot, plus a 60s heartbeat on
    that row's last_seen_at. The next boot reads the previous incarnation's
    row to compute how long it lived (prev_uptime_seconds) — that gap pattern
    is what lets a restart be attributed to redeploy vs idle spin-down vs
    crash without any Render API access. Best-effort: a Supabase outage must
    never block boot."""
    from datetime import datetime, timezone
    prev_uptime = None
    try:
        prev = sb("GET", f"server_boot_ledger?server_instance=eq.{_SERVER_INSTANCE}"
                         "&order=booted_at.desc&limit=1&select=booted_at,last_seen_at")
        if prev:
            b = datetime.fromisoformat(prev[0]["booted_at"].replace("Z", "+00:00"))
            s = datetime.fromisoformat(prev[0]["last_seen_at"].replace("Z", "+00:00"))
            prev_uptime = max(0.0, (s - b).total_seconds())
    except Exception as e:  # noqa: BLE001
        print(f"[boot-ledger] prev-uptime read failed: {e}")
    try:
        row = sb("POST", "server_boot_ledger",
                 {"booted_at": datetime.now(timezone.utc).isoformat(),
                  "server_instance": _SERVER_INSTANCE,
                  "render_instance_id": os.environ.get("RENDER_INSTANCE_ID"),
                  "git_commit": _GIT_COMMIT, "prev_uptime_seconds": prev_uptime},
                 prefer="return=representation")
        if row:
            _BOOT_LEDGER_ID[0] = row[0]["id"]
            print(f"[boot-ledger] row {row[0]['id']} (prev uptime "
                  f"{prev_uptime and round(prev_uptime) or 'unknown'}s)")
    except Exception as e:  # noqa: BLE001
        print(f"[boot-ledger] insert failed: {e}")

    def _heartbeat():
        from datetime import datetime, timezone
        while _BOOT_LEDGER_ID[0] is not None:
            time.sleep(60)
            try:
                sb("PATCH", f"server_boot_ledger?id=eq.{_BOOT_LEDGER_ID[0]}",
                   {"last_seen_at": datetime.now(timezone.utc).isoformat()})
            except Exception:  # noqa: BLE001 — the heartbeat must never die
                pass
    if _BOOT_LEDGER_ID[0] is not None:
        threading.Thread(target=_heartbeat, daemon=True).start()


if __name__ == "__main__":
    # Render injects $PORT and needs 0.0.0.0; locally, argv[1] or 7901 on 127.0.0.1.
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 7901))
    host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    print(f"Serving {PROJECT_DIR} + /api on http://{host}:{port}")
    threading.Thread(target=_boot_ledger_start, daemon=True).start()
    threading.Thread(target=_boot_warmup, daemon=True).start()
    # Serialise verify/remove jobs so multiple ListMint runs don't blow its rate
    # limit — extra jobs wait in `queued` until a worker frees.
    for _ in range(_JOB_WORKERS):
        threading.Thread(target=_job_dispatcher, daemon=True).start()
    # Mark dead in-flight jobs 'interrupted' (never re-run — the user resumes on
    # demand): once at boot with a short grace window, then a 5-minute sweeper
    # for zombies born during deploy overlap after this boot's pass ran.
    threading.Thread(target=_jobs_recover_orphans, daemon=True).start()
    threading.Thread(target=_job_zombie_sweeper, daemon=True).start()
    # campaigns-tab mirror: keep Smartlead campaigns + HeyReach lists ~10-min fresh
    threading.Thread(target=_outreach_sync_loop, daemon=True).start()
    # one-shot: materialise mirror lists for pre-existing sources (source→list bridge)
    threading.Thread(target=_backfill_source_lists, daemon=True).start()
    # hourly: cache every campaign's Smartlead analytics so the list shows real
    # per-campaign performance without 874 live calls per page load
    threading.Thread(target=_scorecard_sync_loop, daemon=True).start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
