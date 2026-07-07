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
import ssl
import sys
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certifi

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


def write_drafts(data, path: Path | None = None):
    """Persist a full source/campaign list to Postgres (routed by which legacy
    path constant the caller passed). Unknown paths fall back to a file."""
    p = path or DRAFTS
    if p == DRAFTS:
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


def http_json(method: str, url: str, headers: dict, body: dict | None = None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode())
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


def sb(method: str, path: str, body=None, prefer: str = ""):
    """Best-effort Supabase PostgREST call - an outage must never break the app."""
    url = KEYS.get("SUPABASE_URL")
    key = KEYS.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    if method in ("POST", "PATCH"):
        body = _normalise_company_fields(path, body)
    try:
        return http_json(method, f"{url}/rest/v1/{path}",
                         {"apikey": key, "Authorization": f"Bearer {key}",
                          "Prefer": prefer or "return=minimal"}, body)
    except Exception:  # noqa: BLE001
        return None


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
    system = (
        f"You help a B2B outbound operator set up a prospecting campaign. {spec['task']}\n"
        "The user has rejected everything in `declined` before: never suggest those or close "
        "variants, and steer away from their flavour. `kept` is what this user chooses to keep: "
        "lean that direction. Never repeat anything in `already_have`. Return exactly `count` "
        "unless the space is genuinely exhausted."
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
    r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                  {"Authorization": f"Bearer {key}"},
                  {"model": "gpt-5-mini", "reasoning_effort": "minimal",
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": spec["schema"], "strict": True, "schema": SUGGEST_SCHEMA}}})
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {r['error'].get('message', r['error'])[:200]}")
    out = json.loads(r["choices"][0]["message"]["content"])
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
    system = (
        "You suggest job titles for a B2B hiring-signal campaign. The signal: when a company "
        "posts certain job openings, it is a good moment for the client to reach out.\n"
        "Return two DISTINCT lists:\n"
        "1. trigger_roles - roles the TARGET company would be actively hiring that signal it "
        "needs the client's offer right now. Job-board titles, fully spelled out, no slashes, "
        "no abbreviations - one concrete title per entry.\n"
        "2. dm_titles - the people at that company the client should EMAIL about the offer: "
        "senior, budget-holding titles, matched to the company sizes given.\n"
        "The user has rejected everything in the declined lists before: never suggest those "
        "or close variants, and steer away from their flavour. The kept lists are what this "
        "user chooses to keep: suggest more in that direction. Never repeat anything in the "
        "already_have lists. Return exactly `count` per list unless the space is genuinely "
        "exhausted."
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
    r = http_json("POST", "https://api.openai.com/v1/chat/completions",
                  {"Authorization": f"Bearer {key}"},
                  {"model": "gpt-5-mini", "reasoning_effort": "minimal",
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": "role_suggestions", "strict": True, "schema": ROLE_SUGGEST_SCHEMA}}})
    if r.get("error"):
        raise RuntimeError(f"OpenAI: {r['error'].get('message', r['error'])[:200]}")
    out = json.loads(r["choices"][0]["message"]["content"])

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
[{{"idea": "<short PLAIN name a non-marketer instantly understands, e.g. 'Brands hiring Amazon roles' not 'Marketplace Talent Expansion'>", "why": "<under 15 words: why this signal means they need the offer. Plain punctuation, never an em-dash>", "icebreaker": "<the opening line: 10-15 words TOTAL, one short signal mention using {{company}}-style merge tags, MUST end with: and so I thought I'd reach out.>", "mechanism": "<one of hiring|engagement>", "params": {{...}}, "fit": n, "novelty": n, "intent": n}}]"""

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
            good.append(i)
        return good or None
    except Exception:  # noqa: BLE001 — any failure -> fallback catalogue
        return None


def _default_ideas(p: dict) -> list:
    """Fallback catalogue when headless ideation is unavailable — SIGNALS ONLY
    (static audiences are out of scope and fail the monthly-volume rule anyway)."""
    return [
        {"idea": "Hiring the roles you sell to", "why": "Live job posts signal the need", "mechanism": "hiring",
         "icebreaker": "I noticed {{company}} is hiring right now, and so I thought I'd reach out.",
         "params": {"job_titles": p.get("titles") or [], "days": 30}, "fit": 5, "novelty": 4, "intent": 5},
    ]


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
        # NEVER serve the static catalogue: it ignores the goal, so every
        # search "returns the same thing" and the tool feels broken. An honest
        # error + Try again beats silently wrong ideas. Nothing is cached.
        return {"ok": False, "rows": [],
                "message": "The idea engine didn't answer this time. Hit Try again - the second run almost always works."}
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


def read_drafts(strict: bool = False) -> list:
    r = _pg_docs("sources", strict=strict)
    return r if r is not None else _file_list(DRAFTS)


def _leads_for_sources(srcs: list) -> list:
    """Map signal_leads rows for a set of draft sources -> UI lead dicts. One
    Supabase query for the whole set; local prospect index attached so ✓/✕ work."""
    if not srcs:
        return []
    ids = ",".join(str(d["id"]) for d in srcs)
    rows = sb("GET", f"signal_leads?source_id=in.({ids})&order=pulled_at.desc") or []
    if not isinstance(rows, list):
        return []
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


def api_leads(campaign_id: str) -> list:
    """Every pulled lead for a campaign, straight from Supabase signal_leads —
    accumulates across pulls (the local file only holds the LAST pull). Newest first."""
    return _leads_for_sources([d for d in read_drafts() if str(d.get("campaign_id")) == str(campaign_id)])


def api_leads_batch(campaign_ids: str) -> list:
    """Leads for MANY campaigns in one shot — the dashboard needs every campaign's
    leads to draw the activity chart; a single read_drafts + one Supabase query
    replaces the old N-calls-one-per-campaign waterfall."""
    wanted = {c.strip() for c in (campaign_ids or "").split(",") if c.strip()}
    if not wanted:
        return []
    return _leads_for_sources([d for d in read_drafts() if str(d.get("campaign_id")) in wanted])


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
    rows = sb("GET", f"signal_leads?select=source_id&source_id=in.({','.join(ids)})")
    if not isinstance(rows, list):
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


def api_lead_counts() -> dict:
    """Per-campaign lead counts from the same signal_leads rows the Leads tab
    reads, so the campaign card and the tab always agree. One query for all
    campaigns; {campaign_id: {leads, sent}}."""
    by_src = {str(d["id"]): str(d.get("campaign_id"))
              for d in read_drafts() if d.get("id") and d.get("campaign_id")}
    if not by_src:
        return {}
    rows = sb("GET", f"signal_leads?select=source_id,status,pushed_to&source_id=in.({','.join(by_src)})")
    if not isinstance(rows, list):
        return {}
    out: dict = {}
    for r in rows:
        cid = by_src.get(str(r.get("source_id")))
        if not cid:
            continue
        c = out.setdefault(cid, {"leads": 0, "sent": 0})
        c["leads"] += 1
        if r.get("pushed_to") or r.get("status") == "pushed":
            c["sent"] += 1
    return out


def save_draft(p: dict) -> dict:
    if (p.get("type") or p.get("mechanism")) == "hiring" and not [t for t in (p.get("titles") or []) if str(t).strip()]:
        return {"ok": False, "message": "A hiring source needs decision-maker roles (who we email at these companies)."}
    drafts = read_drafts()
    # ids must NEVER be reused: Supabase rows (signals, signal_leads) are keyed
    # by source_id and outlive removed drafts — len()+1 recycled ids and
    # cross-contaminated old leads into new sources
    import uuid
    p["id"] = f"draft-{uuid.uuid4().hex[:8]}"
    drafts.append(p)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_drafts(drafts)
    sb_sync_source(p)
    return {"ok": True, "id": p["id"]}


def update_source(p: dict) -> dict:
    """Edit a draft source: include/exclude, remove, icebreaker, targeting
    (params/titles), name, or prospect verdicts (local file only)."""
    drafts = read_drafts()
    sid = p.get("id")
    push = None
    trigify_note = None
    if p.get("remove"):
        gone = next((d for d in drafts if d.get("id") == sid), None)
        if gone and (gone.get("mechanism") or gone.get("type")) == "engagement":
            ent = ((gone.get("config") or {}).get("engagement") or {}).get("trigify") or []
            if ent:
                left, removed, errs = _trigify_deprovision(ent)
                if errs:  # keep the source so the user can retry the teardown
                    ((gone.get("config") or {}).get("engagement") or {})["trigify"] = left
                    write_drafts(drafts)
                    return {"ok": False, "message":
                            f"Removed {len(removed)} Trigify workflow(s) but {len(errs)} failed "
                            f"({errs[0]['error']}). Source kept - try Remove again."}
                trigify_note = f"{len(removed)} Trigify workflow(s) stopped"
        sb_delete_source(sid)  # remove the source, its leads and events from Supabase too
        drafts = [d for d in drafts if d.get("id") != sid]
    else:
        for d in drafts:
            if d.get("id") != sid:
                continue
            if "active" in p:
                d["active"] = bool(p["active"])
            if p.get("refresh_total") is not None:
                d["total"] = p["refresh_total"]
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
                    dest = resolve_destination(d)
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
                        write_drafts(drafts)
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
                    write_drafts(drafts)
                    return {"ok": True, "push": push, "lead": pr}
            if any(k in p for k in ("icebreaker", "params", "titles", "name", "active", "destination", "config")):
                sb_sync_source(d)
    write_drafts(drafts)
    return {"ok": True, "push": push, **({"trigify": trigify_note} if trigify_note else {})}


# ── real outreach push (Smartlead + HeyReach) ────────────────────────────

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
HEYREACH_BASE = "https://api.heyreach.io/api/public"


def heyreach(path: str, body: dict):
    return http_json("POST", HEYREACH_BASE + path,
                     {"X-API-KEY": KEYS.get("HEYREACH_API_KEY", "")}, body)


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


def outreach_destinations(p: dict) -> dict:
    """Live pickers for the two outreach tools (header dropdowns)."""
    out: dict = {"smartlead": [], "heyreach": []}
    try:
        camps = http_json("GET", f"{SMARTLEAD_BASE}/campaigns?api_key={KEYS.get('SMARTLEAD_API_KEY', '')}", {})
        out["smartlead"] = [{"id": c.get("id"), "name": c.get("name") or "", "status": c.get("status")}
                            for c in (camps if isinstance(camps, list) else [])
                            if c.get("status") in ("ACTIVE", "PAUSED", "DRAFTED")][:100]
    except Exception as e:  # noqa: BLE001
        out["smartlead_error"] = str(e)[:150]
    try:
        out["heyreach"] = heyreach_lists()
    except Exception as e:  # noqa: BLE001
        out["heyreach_error"] = str(e)[:150]
    return out


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


def resolve_destination(src: dict) -> dict:
    """Where ✓'d people go: campaign-level destination first, source-level
    fallback. Accepts legacy {type, campaign_id} and the two-tool shape."""
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(src.get("campaign_id"))), {})
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
        if not sl:
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
        out.append({"name": pr.get("name"), "company": pr.get("company"), "email": pr.get("email"),
                    "ok": bool(sent), "tools": {k: v.get("message") for k, v in push["tools"].items()}})
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
    write_drafts(drafts)
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
    rows = sb("GET", f"engagement_events?source_id=eq.{quote(source_id, safe='')}"
                     f"&status=in.({statuses})&order=received_at.desc&limit=200"
                     "&select=engager_full_name,engager_job_title,engager_company_name,"
                     "engager_country,post_author_name,status,qualification,received_at") or []
    if not isinstance(rows, list):
        rows = []
    label = {"OFF_BRIEF": "rejected", "BORDERLINE": "needs review",
             "QUALIFIED": "qualified", "PUSHED": "sent"}
    out, seen = [], set()
    for r in rows:
        who = (r.get("engager_full_name"), r.get("engager_company_name"))
        if who in seen:  # same engager on multiple posts - newest row wins
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
ENG_STAGE_PER_RUN = 40  # engagers enriched+staged per source per run (credit bound)


def _activity_urn(post_url: str):
    mm = re.search(r"activity:(\d+)", post_url or "")
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


def stage_trigify_engagers(src: dict, cfg: dict, days: int = ENG_BACKFILL_DAYS,
                           per_post: int = ENG_COMMENTS_PER_POST,
                           per_run: int = ENG_STAGE_PER_RUN) -> int:
    """Pull recent-post engagers for a source and stage them as NEW
    engagement_events (deduped by post+engager). Returns the count staged."""
    eng = cfg.get("engagement") or {}
    searches = [t.get("search_id") for t in (eng.get("trigify") or []) if t.get("search_id")]
    if not searches:
        return 0
    seen = sb("GET", f"engagement_events?source_id=eq.{src['id']}&select=post_url,engager_linkedin_url") or []
    done_posts = {r.get("post_url") for r in seen}
    seen_pair = {(r.get("post_url"), r.get("engager_linkedin_url")) for r in seen}
    staged, batch = 0, []
    for sid in searches:
        if staged >= per_run:
            break
        for post in _trigify_recent_posts(sid, days):
            if staged >= per_run:
                break
            if post["post_url"] in done_posts:
                continue
            for e in _trigify_post_engagers(post["post_urn"], per_post):
                if staged >= per_run:
                    break
                key = (post["post_url"], e["linkedin"])
                if key in seen_pair:
                    continue
                seen_pair.add(key)
                pr = _trigify_enrich(e["linkedin"])
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
                staged += 1
            done_posts.add(post["post_url"])
    if batch:
        sb("POST", "engagement_events?on_conflict=source_id,engager_linkedin_url,post_url",
           batch, prefer="resolution=ignore-duplicates,return=minimal")
    return staged


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

    # tool-driven pull: stage fresh engagers before qualifying (no reliance on
    # the Trigify workflow trigger, which barely fires)
    try:
        stage_trigify_engagers(src, cfg)
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
                [{"source_id": src["id"], "full_name": pr.get("name"), "title": pr.get("title"),
                  "company": pr.get("company"), "domain": pr.get("domain"),
                  "linkedin_url": pr.get("linkedin"), "country": pr.get("country"),
                  "icebreaker": pr.get("icebreaker"), "email": pr.get("email"), "status": "new"}],
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
    src["mechanism"] = "engagement"
    src["last_pull"] = datetime.now().isoformat(timespec="seconds")
    write_drafts(drafts)
    sb_sync_source(src)

    # signal_leads are now written per-engager inside the loop above (survives an
    # abandoned run), so no end-of-run batch is needed here.
    sb("PATCH", f"signal_sources?id=eq.{src['id']}", {"last_pull_at": src["last_pull"]})

    # autopilot campaigns push immediately; manual campaigns leave ✓ to the user
    camp = next((c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if str(c.get("id")) == str(src.get("campaign_id"))), {})
    pushed = auto_push_new_leads(src) if camp.get("autopilot") else []
    if pushed:
        write_drafts(drafts)
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
    reps = {"company": company, "first_name": first_name}
    for k, v in reps.items():
        out = out.replace("{{" + k + "}}", v).replace("{" + k + "}", v)
    return email_safe(out)  # last line of defence: no special char can survive


def theirstack_jobs(job_titles, codes, min_emp, max_emp, days, limit=25, extra=None, negatives=None):
    """Unblurred TheirStack jobs search — real companies + domains (costs
    credits, so callers bound `limit`). Returns (jobs, metadata).
    `negatives`: keywords that must NOT appear in the post title/description —
    also enforced client-side because API-side pattern filters can miss."""
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
    data = http_json("POST", "https://api.theirstack.com/v1/jobs/search",
                     {"Authorization": f"Bearer {KEYS['THEIRSTACK_API_KEY']}"}, body)
    meta = data.get("metadata") or {}
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
    for j in (data.get("data") or []):
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
    r"\b(ceo|chief executive|founder|co-?founder|president|managing director|"
    r"gesch[aä]ftsf[uü]hrer|gr[uü]nder|prezes|directeur g[eé]n[eé]ral|"
    r"inhaber|eigenaar|proprietor|amministratore|owner)\b", re.I)


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


def pull_hiring_source(src: dict, drafts: list) -> dict:
    """The TheirStack hiring pipeline, server-side and idempotent:
    TheirStack jobs (unblurred) -> new companies -> Supabase signals+companies
    -> Prospeo DM-find per company -> signal_leads -> rendered in the tool.
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
    leads_per_day = max(1, int(cfg.get("leads_per_day") or 20))
    limit = min(leads_per_day * 6, 100)  # scan headroom for dedupe + no-DM + off-brief-skipped companies
    max_dms = 5                          # fixed: at most 5 decision makers per company

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
    filter_dropped = False
    jobs, meta = theirstack_jobs(job_titles, codes, min_emp, max_emp, days, limit, extra=precision, negatives=negatives)
    if not jobs and precision.get("company_description_pattern_or"):
        # the description REQUIRE gate starves niche roles to zero (most company
        # descriptions never contain the literal phrase). Drop it, keep the safe
        # NOT-excludes, and self-heal the source so probes and pulls agree.
        precision.pop("company_description_pattern_or")
        jobs, meta = theirstack_jobs(job_titles, codes, min_emp, max_emp, days, limit, extra=precision, negatives=negatives)
        if jobs:
            (src.setdefault("params", {})).pop("company_description_pattern_or", None)
            (src.get("config") or {}).pop("company_description_pattern_or", None)
            filter_dropped = True  # tell the user their REQUIRE-word filter was auto-removed
    total_jobs = meta.get("total_results") or len(jobs)
    if not jobs and meta.get("_error"):
        # a real provider error (bad filter/auth/rate-limit) — never report it as
        # the benign "no jobs today", or a broken signal looks like an idle one.
        return {"ok": False, "message":
                f"The hiring search couldn't run: {meta['_error']}. "
                "Your targeting is saved — fix the flagged issue and try again."}
    if not jobs:
        note = ("No live job posts match this signal today. That's normal for a hiring signal. "
                "It keeps checking daily and adds companies as they start hiring. "
                "Your campaign audience is unchanged.")
        if unmapped_countries:
            note += (" (Skipped unrecognised countries: "
                     f"{', '.join(unmapped_countries)}.)")
        return {"ok": False, "message": note}

    # freshness in code too: a post dated older than 30 days never acts
    from datetime import timedelta
    min_posted = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    jobs = [j for j in jobs if not j.get("date_posted") or j["date_posted"] >= min_posted]

    # newest first, one row per company
    jobs.sort(key=lambda j: j.get("date_posted") or "", reverse=True)
    uniq, seen = [], set()
    for j in jobs:
        if j["domain"] not in seen:
            seen.add(j["domain"])
            uniq.append(j)

    # Re-touch window: skip a company only if THIS source scanned it in the
    # last 90 days — a company that re-posts after 3 months is re-engaged.
    # NB: strftime with Z, not isoformat() — a literal '+' in the URL decodes
    # to a space and PostgREST rejects the timestamp (query would silently
    # return an error dict and nothing would ever be skipped)
    scan_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = sb("GET", f"signals?source=eq.theirstack&detail->>source_id=eq.{src['id']}"
                         f"&created_at=gte.{scan_cutoff}&select=company_domain") or []
    already = {r.get("company_domain") for r in existing if isinstance(r, dict)}
    fresh = [j for j in uniq if j["domain"] not in already]

    template = src.get("icebreaker") or "Saw {{company}} is hiring for {{role}}, and so I thought I'd reach out."
    now_iso = datetime.now(timezone.utc).isoformat()

    def lead_excluded(email, domain):
        return is_suppressed(client_id, email, domain)  # shared helper (also used at push time)

    prospects, signals_n, scanned, dropped = [], 0, 0, {"no_email": 0, "excluded": 0}
    for j in fresh:
        if len(prospects) >= leads_per_day:
            break  # pace hit - stop enriching, the rest waits for tomorrow
        scanned += 1
        domain = j["domain"]
        detected = (j["date_posted"] + "T00:00:00Z") if j.get("date_posted") else now_iso
        # company row FIRST — signals.company_domain has an FK to companies(domain)
        sb("POST", "companies?on_conflict=domain", {
            "domain": domain, "name": j["company"] or None,
            "industry": j["industry"] or None,
            "employee_count": j["employee_count"],
            "employee_range": j["employee_range"] or None,
            "country": j["country"] or None,
        }, prefer="resolution=merge-duplicates,return=minimal")
        # then the hiring signal (dedupe via the signals_dedupe unique index;
        # a genuine cross-source duplicate 409s and is harmlessly swallowed)
        sb("POST", "signals", {
            "signal_type": "hiring", "source": "theirstack", "company_domain": domain,
            "detected_at": detected,
            "detail": {"job_title": j["job_title"], "job_url": j["job_url"],
                       "company": j["company"], "source_id": src["id"]},
        }, prefer="resolution=ignore-duplicates,return=minimal")
        signals_n += 1

        # AI-ARK bills per person returned: never request more than the day still needs
        for person in dm_find_by_domain(domain, dm_titles, min(max_dms, leads_per_day - len(prospects))):
            if len(prospects) >= leads_per_day:
                break
            person["company"] = person.get("company") or j["company"]
            person["domain"] = person.get("domain") or domain
            # verified email is the keep-gate (Prospeo enrich-person)
            try:
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
            from name_hygiene import clean_job_title, email_safe
            role = clean_job_title(j["job_title"]) or ""  # email-ready: no emoji/pipe, tidy casing
            person["hiring_for"] = role
            person["job_url"] = j["job_url"]
            person["role"] = role
            ice = fill_icebreaker(template, person)
            # re-run email_safe AFTER the role merge so a raw title can't leak a special char
            person["icebreaker"] = email_safe(ice.replace("{{role}}", role).replace("{role}", role))
            person["verdict"] = None
            prospects.append(person)
    left_over = len(fresh) - scanned

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
    src["companies_scanned"] = len(uniq)
    src["left_for_next_run"] = left_over
    src["mechanism"] = "hiring"
    src["last_pull"] = datetime.now().isoformat(timespec="seconds")
    write_drafts(drafts)
    sb_sync_source(src)

    rows = [{"source_id": src["id"], "full_name": x.get("name"), "title": x.get("title"),
             "company": x.get("company"), "domain": x.get("domain"),
             "linkedin_url": x.get("linkedin") or f"unknown:{x.get('name')}",
             "country": x.get("country"), "icebreaker": x.get("icebreaker"),
             "email": x.get("email"), "status": "new"}
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
                "total": total_jobs, "signals": signals_n, "dropped": dropped}
    tail = f" ({left_over} more companies queued for the next run)" if left_over else ""
    dm_word = "decision-maker" if len(prospects) == 1 else "decision-makers"
    notices = []
    if filter_dropped:
        notices.append("Removed your 'description must contain' filter to get results "
                       "- it matched no live jobs. Targeting saved.")
    if unmapped_countries:
        notices.append("Skipped unrecognised countries: " + ", ".join(unmapped_countries) + ".")
    return {"ok": True, "total": total_jobs, "signals": signals_n,
            "companies_scanned": len(uniq), "prospects": prospects, "db_synced": True,
            "dropped": dropped,
            "notice": " ".join(notices) or None,
            "note": f"{signals_n} hiring companies, {len(prospects)} {dm_word}{tail}"
                    + (f" · {drop_note}" if drop_note else "")}


def pull_source(p: dict) -> dict:
    """Simulate the daily pull: fetch real prospects for a source using its
    own targeting, fill its icebreaker per person, store on the source."""
    drafts = read_drafts()
    src = next((d for d in drafts if d.get("id") == p.get("id")), None)
    if not src:
        return {"ok": False, "message": "Source not found"}
    if (src.get("mechanism") or src.get("type")) == "hiring":
        return pull_hiring_source(src, drafts)
    if (src.get("mechanism") or src.get("type")) == "engagement":
        return pull_engagement_source(src, drafts)
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
    write_drafts(drafts)
    sb_sync_source(src)
    rows = [{"source_id": src["id"], "full_name": x.get("name"), "title": x.get("title"),
             "company": x.get("company"), "domain": x.get("domain"),
             "linkedin_url": x.get("linkedin") or f"unknown:{x.get('name')}",
             "country": x.get("country"), "icebreaker": x.get("icebreaker"), "status": "new"}
            for x in prospects]
    sb("POST", "signal_leads?on_conflict=source_id,linkedin_url", rows,
       prefer="resolution=merge-duplicates,return=minimal")
    sb("PATCH", f"signal_sources?id=eq.{src['id']}", {"last_pull_at": src["last_pull"]})
    return {"ok": True, "total": total, "broadened": False, "prospects": prospects, "db_synced": True}


def update_campaign_draft(p: dict) -> dict:
    from datetime import datetime
    drafts = read_json_list(CAMPAIGN_DRAFTS)
    cid = p.get("id")
    if p.get("remove"):
        # SOFT delete: mark the campaign + its sources deleted and stop nothing
        # external. Everything stays intact so restore is lossless. The hard,
        # irreversible cascade (Trigify teardown + Supabase row deletion) only
        # runs on an explicit purge from the Recently-deleted area.
        now = datetime.now().isoformat(timespec="seconds")
        all_srcs = read_drafts()
        touched = False
        for src in all_srcs:
            if str(src.get("campaign_id")) == str(cid):
                src["deleted_at"] = now
                touched = True
        if touched:
            write_drafts(all_srcs)
        for d in drafts:
            if d.get("id") == cid:
                d["deleted_at"] = now
        write_drafts(drafts, CAMPAIGN_DRAFTS)
        return {"ok": True, "soft_deleted": True}
    else:
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
    drafts = read_json_list(CAMPAIGN_DRAFTS)
    found = False
    for d in drafts:
        if d.get("id") == cid and d.get("deleted_at"):
            d.pop("deleted_at", None)
            found = True
    if not found:
        return {"ok": False, "message": "Nothing to restore for this campaign."}
    write_drafts(drafts, CAMPAIGN_DRAFTS)
    srcs = read_drafts()
    for s in srcs:
        if str(s.get("campaign_id")) == str(cid):
            s.pop("deleted_at", None)
    write_drafts(srcs)
    return {"ok": True, "restored": True}


def purge_campaign_draft(p: dict) -> dict:
    """PERMANENT delete from the Recently-deleted area. This is the old hard
    cascade: stop the Trigify monitors and delete the Supabase rows. Irreversible."""
    cid = p.get("id")
    drafts = read_json_list(CAMPAIGN_DRAFTS)
    all_srcs = read_drafts()
    doomed = [x for x in all_srcs if str(x.get("campaign_id")) == str(cid)]
    for src in doomed:  # tear down each source's external + backend footprint
        if (src.get("mechanism") or src.get("type")) == "engagement":
            ent = ((src.get("config") or {}).get("engagement") or {}).get("trigify") or []
            if ent:
                _trigify_deprovision(ent)  # best-effort: stop the LinkedIn monitors
        sb_delete_source(src.get("id"))
    # safety net: clear any Supabase rows keyed straight to the campaign
    sb("DELETE", f"signal_sources?campaign_draft_id=eq.{cid}")
    sb("DELETE", f"engagement_events?campaign_draft_id=eq.{cid}")
    write_drafts([x for x in all_srcs if str(x.get("campaign_id")) != str(cid)])
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
    drafts = read_drafts()
    orig = next((d for d in drafts if d.get("id") == sid), None)
    if not orig:
        return {"ok": False, "message": "Source not found - refresh and try again."}
    s = _clone_source_dict(orig)
    s["id"] = f"draft-{uuid.uuid4().hex[:8]}"
    s["name"] = _copy_name(orig.get("name"))
    drafts.append(s)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    write_drafts(drafts)
    sb_sync_source(s)
    return {"ok": True, "id": s["id"], "name": s["name"]}


def duplicate_campaign_draft(p: dict) -> dict:
    """Duplicate a whole campaign: the campaign draft plus every one of its live
    sources (targeting retained), under fresh ids, so it launches identically."""
    from datetime import datetime
    import uuid, copy
    cid = p.get("id")
    drafts = read_json_list(CAMPAIGN_DRAFTS)
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
    all_srcs = read_drafts()
    originals = [s for s in all_srcs
                 if str(s.get("campaign_id")) == str(cid) and not s.get("deleted_at")]
    new_srcs = []
    for src in originals:
        s = _clone_source_dict(src, new_campaign_id=new_id)
        s["id"] = f"draft-{uuid.uuid4().hex[:8]}"
        new_srcs.append(s)
    if new_srcs:
        all_srcs.extend(new_srcs)
        write_drafts(all_srcs)
        for s in new_srcs:
            sb_sync_source(s)
    return {"ok": True, "id": new_id, "name": new["name"], "sources": len(new_srcs)}


def save_campaign_draft(p: dict) -> dict:
    from datetime import datetime
    import uuid
    drafts = read_json_list(CAMPAIGN_DRAFTS)
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
    BUDGET_S = 700   # whole-run wall-clock ceiling
    SOURCE_S = 300   # per-source hard timeout (engagement parallel-qualifies a big backlog)
    t0 = _time.monotonic()

    def _timed(fn):
        """Run fn() in a daemon thread; return (result, error, timed_out)."""
        box = {}
        def _w():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e
        th = threading.Thread(target=_w, daemon=True)
        th.start()
        th.join(SOURCE_S)
        if th.is_alive():
            return None, None, True
        return box.get("r"), box.get("e"), False

    campaigns = {str(c.get("id")): c for c in read_json_list(CAMPAIGN_DRAFTS)
                 if not c.get("deleted_at")}
    source_ids = [d["id"] for d in read_drafts()
                  if d.get("active", True) and not d.get("deleted_at")
                  and str(d.get("campaign_id")) in campaigns]
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
                    if not _pt:  # persist pushed-state to the file the Leads tab reads
                        try:
                            write_drafts(drafts)
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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def end_headers(self):
        # the app ships as static files - stale cached JS against a newer API
        # silently breaks flows (empty ideas table), so force revalidation
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

    # Static text assets (HTML/CSS/JS/SVG) are shipped uncompressed by the stdlib
    # handler; gzip them here. Binary assets (fonts, images), 404s, ranges and
    # conditional requests fall through to SimpleHTTPRequestHandler untouched.
    _GZIP_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".map", ".txt"}

    def _serve_static(self):
        import os, gzip, mimetypes
        fs_path = self.translate_path(self.path)
        ext = os.path.splitext(fs_path)[1].lower()
        if not self._accepts_gzip() or ext not in self._GZIP_EXT or os.path.isdir(fs_path):
            return super().do_GET()
        try:
            with open(fs_path, "rb") as f:
                body = f.read()
        except OSError:
            return super().do_GET()  # let the default path emit the 404
        ctype = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ext in (".js", ".mjs", ".json", ".svg"):
            ctype += "; charset=utf-8"
        gz = gzip.compress(body, 6)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(gz)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(gz)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":  # liveness only — NO DB call, so the health check can't flap
            return self._json({"ok": True})
        if path == "/api/cron/last-run":  # observability: latest scheduled batch-pull summary
            rows = sb("GET", "signal_cron_runs?order=id.desc&limit=1")
            return self._json((rows or [{}])[0])
        if path == "/api/sources":
            return self._json(sources_for_ui(read_drafts()))
        if path == "/api/leads":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_leads((q.get("campaign_id") or [""])[0]))
        if path == "/api/leads-batch":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._json(api_leads_batch((q.get("campaign_ids") or [""])[0]))
        if path == "/api/lead-counts":
            return self._json(api_lead_counts())
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
            return self._json(read_json_list(CAMPAIGN_DRAFTS))
        if path == "/api/clients":
            return self._json(read_json_list(CLIENTS))
        if path == "/api/outreach-destinations":
            return self._json(outreach_destinations({}))
        return self._serve_static()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/cron/pull-all":
            # External-scheduler batch pull. Token-guarded (header, not body) and
            # run OUTSIDE the global drafts_lock — cron_pull_all takes its own
            # per-source locks and the lock does not nest.
            want = os.environ.get("SIGNAL_PULL_TOKEN") or KEYS.get("SIGNAL_PULL_TOKEN")
            if not want:
                # No dedicated token set on this host: derive a stable one from a
                # secret already in the env (avoids a manual Render dashboard step).
                import hashlib
                srk = KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
                want = hashlib.sha256((srk + ":signal-pull-v1").encode()).hexdigest()[:40] if srk else None
            got = self.headers.get("x-navreo-token")
            if not want or got != want:
                return self._json({"ok": False, "message": "unauthorized"}, 401)
            # Fire-and-forget: the full pull over all sources runs far longer than
            # any HTTP/pg_net timeout, so kick it to a background thread and return
            # immediately. Each run's summary lands in signal_cron_runs (Supabase).
            if _CRON_LOCK.locked():
                return self._json({"ok": True, "started": False, "busy": True}, 200)
            threading.Thread(target=_cron_pull_bg, daemon=True).start()
            return self._json({"ok": True, "started": True}, 202)
        route = ROUTES.get(path)
        if not route:
            return self._json({"ok": False, "message": "unknown endpoint"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode() or "{}")
            with drafts_lock():  # every POST may read-modify-write the drafts files
                return self._json(route(payload))
        except Exception as e:  # noqa: BLE001 — surface provider errors to the UI
            return self._json({"ok": False, "message": str(e)[:300]}, 200)


if __name__ == "__main__":
    # Render injects $PORT and needs 0.0.0.0; locally, argv[1] or 7901 on 127.0.0.1.
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 7901))
    host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    print(f"Serving {PROJECT_DIR} + /api on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
