#!/usr/bin/env python3
"""
qualify.py, Reference implementation of Phase 1 + Phase 2 for lilly-trigify-data-processing.

Reads:
  * A CSV / TSV / on-disk markdown table of Engagers rows (Drive MCP read_file_content output).
  * A brief config JSON from ~/.claude/skills/lilly-trigify-setup/briefs/<brief_id>.json.
  * Optionally the per-brief state file from ~/.claude/skills/lilly-trigify-data-processing/state/<brief_id>.json.

Writes:
  * A verdict file at <output_dir>/<brief_id>.verdicts.json with three pots: qualified / borderline / off_brief.
  * Each row carries linkedin_url, verdict, reason, plus the full original row for downstream phases.

This is a DETERMINISTIC pass, pattern-matching on country, title keywords, and company avoid list.
Phases 2b (post-topic, LLM) and 2c (title pattern judgement) ideally invoke an LLM for ambiguous rows;
this reference falls back to keyword logic so it can run offline. Tag rows BORDERLINE when uncertain
so the orchestrating skill knows to escalate to LLM judgement OR to user verdict.

Usage:
  python3 qualify.py \\
    --brief ~/.claude/skills/lilly-trigify-setup/briefs/navreo-competitor-founder-engagers.json \\
    --engagers /path/to/engagers.csv \\
    --state ~/.claude/skills/lilly-trigify-data-processing/state/navreo-competitor-founder-engagers.json \\
    --out /tmp/verdicts.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ----- Country UI label -> ISO-2 mapping (Trigify writes UI labels into the Country column) ---------

COUNTRY_LABEL_TO_ISO = {
    "United States": "US",
    "United States of America": "US",
    "USA": "US",
    "Canada": "CA",
    "United Kingdom": "GB",
    "UK": "GB",
    "Australia": "AU",
    "Ireland": "IE",
    "New Zealand": "NZ",
    "Germany": "DE",
    "Netherlands": "NL",
    "Switzerland": "CH",
    "Sweden": "SE",
    "Norway": "NO",
    "Denmark": "DK",
    "Finland": "FI",
    "Singapore": "SG",
}


def to_iso(country_raw: str) -> str | None:
    """Normalise a Country column value to an ISO-2 code, or return None if missing/unknown."""
    if not country_raw or country_raw.strip().lower() in ("", "missing", "none", "null"):
        return None
    country_raw = country_raw.strip()
    # Already ISO-2?
    if len(country_raw) == 2 and country_raw.isupper():
        return country_raw
    return COUNTRY_LABEL_TO_ISO.get(country_raw)


# ----- LinkedIn URL canonicalisation -----------------------------------------------------------------

URL_TRAIL_RE = re.compile(r"[?#].*$")


def canonical_linkedin_url(url: str) -> str:
    """
    Normalise a LinkedIn URL for dedup:
      * strip query string + fragment
      * strip trailing slash
      * lowercase host

    Note: ACoAxxx URN-style URLs and slug-style URLs are NOT collapsed (they look different
    even when they point to the same profile). That's OK for dedup-within-a-run; cross-run
    overlap is rare because Trigify normalises to one or the other consistently per profile.
    """
    if not url:
        return ""
    url = URL_TRAIL_RE.sub("", url.strip())
    url = url.rstrip("/")
    # crude lowercase the host
    if url.startswith("https://"):
        path_idx = url.find("/", 8)
        if path_idx > 0:
            url = "https://" + url[8:path_idx].lower() + url[path_idx:]
    return url


# ----- Title pattern matching ------------------------------------------------------------------------

QUALIFIED_TITLE_KEYWORDS = {
    "cro": "C-suite",
    "cso": "C-suite",
    "chief revenue officer": "C-suite",
    "chief sales officer": "C-suite",
    "founder": "C-suite",
    "co-founder": "C-suite",
    "cofounder": "C-suite",
    "ceo": "C-suite",
    "vp sales": "VP",
    "vp revenue": "VP",
    "vp gtm": "VP",
    "vp growth": "VP",
    "vp marketing": "VP",
    "vice president of sales": "VP",
    "vice president sales": "VP",
    "head of sales": "Head/Director",
    "head of gtm": "Head/Director",
    "head of growth": "Head/Director",
    "head of marketing": "Head/Director",
    "head of revenue": "Head/Director",
    "head of revops": "Head/Director",
    "head of rev ops": "Head/Director",
    "head of partnerships": "Head/Director",
    "director of sales": "Head/Director",
    "director of bd": "Head/Director",
    "director of business development": "Head/Director",
    "director of partnerships": "Head/Director",
    "director of revenue operations": "Head/Director",
    "bd director": "BD",
}

DISQUALIFIED_TITLE_KEYWORDS = {
    "software engineer": "Technical IC",
    "backend engineer": "Technical IC",
    "frontend engineer": "Technical IC",
    "full stack engineer": "Technical IC",
    "full-stack engineer": "Technical IC",
    "devops": "Technical IC",
    "data engineer": "Technical IC",
    "ml engineer": "Technical IC",
    "machine learning engineer": "Technical IC",
    "intern": "Junior tier",
    "internship": "Junior tier",
    "junior": "Junior tier",
    "associate": "Junior tier",
    "assistant": "Junior tier",
    "coordinator": "Junior tier",
    "recruiter": "Wrong function",
    "talent acquisition": "Wrong function",
    "sourcer": "Wrong function",
    "hr manager": "Wrong function",
    "people ops": "Wrong function",
    "people operations": "Wrong function",
    "student": "Not B2B prospect",
    "freelancer": "Not B2B prospect",
    "career coach": "Not B2B prospect",
    "resume writer": "Not B2B prospect",
    "customer success manager": "Customer-facing IC",
    "customer success specialist": "Customer-facing IC",
    "customer success associate": "Customer-facing IC",
    "support engineer": "Customer-facing IC",
    "technical support": "Customer-facing IC",
    "creative director": "Wrong function (creative)",
    "data entry": "Wrong function (admin)",
    "social media manager": "Wrong function (marketing IC)",
    "copywriter": "Wrong function (content IC)",
    "operations associate": "Junior ops",
    "financial services associate": "Wrong function",
}

BORDERLINE_TITLE_KEYWORDS = {
    "sales manager": "Sales Manager (no Director title), could be first dedicated hire OR admin layer",
    "account executive": "Account Executive, sometimes founder-AE; verify by company size",
    "growth manager": "Growth Manager, tooling-buying influence but not always primary buyer",
    "demand gen manager": "Demand Gen Manager, influence not primary",
    "marketing ops manager": "Marketing Ops Manager, influence not primary",
    "general manager": "General Manager, could be GTM-aligned or unrelated to sales",
    "managing director": "Managing Director, could be senior or a UK-style title for an IC consultant",
    "managing partner": "Managing Partner, could be agency principal or VC partner",
    "gtm engineer": "GTM Engineer, could be relevant tech-buyer OR internal product engineer",
    "account manager": "Account Manager, usually disqualified (client-facing IC) but Director+ may qualify",
}


def classify_title(title: str) -> tuple[str, str]:
    """
    Return (verdict, reason) for the title gate.
    Verdict is one of: "QUALIFIED", "BORDERLINE", "OFF_BRIEF", "MISSING".
    """
    if not title or not title.strip() or title.strip().lower() in ("missing", "none", "null"):
        return "MISSING", "title=missing"

    title_l = title.lower().strip()

    # Disqualified wins over qualified (e.g. "Software Engineer / Founder" -> still off-brief)
    for kw, category in DISQUALIFIED_TITLE_KEYWORDS.items():
        if kw in title_l:
            return "OFF_BRIEF", f"title='{title}' ({category})"

    for kw, _ in QUALIFIED_TITLE_KEYWORDS.items():
        if kw in title_l:
            return "QUALIFIED", f"title='{title}' qualified"

    for kw, note in BORDERLINE_TITLE_KEYWORDS.items():
        if kw in title_l:
            return "BORDERLINE", f"title='{title}', {note}"

    return "BORDERLINE", f"title='{title}', unclassified, escalate to LLM"


# ----- Company avoid-list matching ------------------------------------------------------------------

DIRECT_COMPETITOR_KEYWORDS = [
    "smartlead", "instantly", "lemlist", "apollo", "mailshake", "reply.io", "reply io",
    "outreach.io", "outreach io", "salesloft", "lavender", "clay.com", "clay labs",
    "trigify", "coldiq", "cold iq", "stackoptimise", "stack optimise",
]

RECRUITING_KEYWORDS = [
    "recruiting", "staffing", "talent acquisition", "headhunter", "recruitment",
]


def classify_company(company: str | None, brief: dict) -> tuple[str, str]:
    """
    Return (verdict, reason) for the company gate.
    Verdict is one of: "QUALIFIED", "BORDERLINE", "OFF_BRIEF".

    Pattern-match against `brief.qualification.company_avoid_list` keywords. This is intentionally
    coarse: the LLM-judgement path is preferred for unknown companies (training-knowledge-first per
    the company-classification convention). When this script flags BORDERLINE for an unknown company,
    the orchestrator should escalate to LLM.
    """
    if not company or not company.strip() or company.strip().lower() in ("missing", "unknown", "no company", "none"):
        return "BORDERLINE", f"co={company or 'No company'}"

    company_l = company.lower().strip()

    for kw in DIRECT_COMPETITOR_KEYWORDS:
        if kw in company_l:
            return "OFF_BRIEF", f"co={company}, direct competitor"

    for kw in RECRUITING_KEYWORDS:
        if kw in company_l:
            return "OFF_BRIEF", f"co={company}, recruiting/staffing, avoid list"

    # Solo consultant heuristic: short company string + words like "consulting", "consultant"
    if "consultant" in company_l or "consulting" in company_l:
        if len(company_l) < 30:
            return "BORDERLINE", f"co={company}, possible solo consultant; escalate"

    return "QUALIFIED", f"co={company}"


# ----- Brief loading + per-row evaluation ------------------------------------------------------------

@dataclass
class Verdict:
    linkedin_url: str
    verdict: str
    reason: str
    row: dict = field(default_factory=dict)


def load_brief(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def load_state(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"processed_engagers": []}
    with path.open() as fh:
        return json.load(fh)


def already_processed(state: dict) -> set[str]:
    processed = set()
    for entry in state.get("processed_engagers", []) or []:
        if isinstance(entry, dict):
            url = entry.get("linkedin_url")
            if url:
                processed.add(canonical_linkedin_url(url))
        elif isinstance(entry, str):
            processed.add(canonical_linkedin_url(entry))
    return processed


# ----- CSV / TSV parsing -----------------------------------------------------------------------------

ENGAGERS_HEADERS_CANONICAL = [
    "Date Pulled", "Engaged At", "First Name", "Last Name", "Full Name",
    "LinkedIn URL", "Title", "Company", "Company Website", "Country",
    "Engagement Type", "Comment Text", "Post URL", "Post Author",
    "Post Author LinkedIn", "Post Snippet", "Status",
]


def read_engagers_table(path: Path) -> list[dict]:
    """
    Best-effort reader: detect delimiter, fall back to CSV. Returns list of {col: value} dicts
    keyed by canonical Engagers headers (case- and whitespace-tolerant).
    """
    with path.open(newline="", encoding="utf-8") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t|")
        except csv.Error:
            dialect = csv.get_dialect("excel")
        reader = csv.DictReader(fh, dialect=dialect)
        rows = []
        for raw in reader:
            normalised = {}
            for canonical in ENGAGERS_HEADERS_CANONICAL:
                value = ""
                for k, v in raw.items():
                    if k and k.strip().lower() == canonical.lower():
                        value = (v or "").strip()
                        break
                normalised[canonical] = value
            if any(normalised.values()):
                rows.append(normalised)
        return rows


# ----- Gate orchestration ----------------------------------------------------------------------------

def evaluate_row(row: dict, brief: dict) -> Verdict:
    """
    Apply gates 2a (location) -> 2c (title) -> 2d (company) in cheapness order.
    Skip 2b (post-topic LLM) for this deterministic reference, let the orchestrating skill
    LLM-judge any row that lands BORDERLINE on the cheap gates.

    The orchestrator should run gate 2b explicitly for rows whose:
      * post.author_name != brief.ideation.outreach_voice
      * AND title gate + company gate both PASS

    ...because those are the rows where the topic check is load-bearing.
    """
    url = canonical_linkedin_url(row.get("LinkedIn URL", ""))

    # Gate 2a, location
    qualified_iso = brief["qualification"]["location_gate"]["qualified_country_codes"]
    country_iso = to_iso(row.get("Country", ""))
    if country_iso is None:
        loc_reason = "loc=missing"
        loc_verdict = "BORDERLINE"
    elif country_iso in qualified_iso:
        loc_verdict = "PASS"
        loc_reason = ""
    else:
        return Verdict(url, "OFF_BRIEF", f"loc={row.get('Country', country_iso)}", row)

    # Gate 2c, title
    title_verdict, title_reason = classify_title(row.get("Title", ""))
    if title_verdict == "OFF_BRIEF":
        return Verdict(url, "OFF_BRIEF", title_reason, row)

    # Gate 2d, company
    co_verdict, co_reason = classify_company(row.get("Company", ""), brief)
    if co_verdict == "OFF_BRIEF":
        # Combine title context into the reason when both are informative
        if title_verdict != "QUALIFIED":
            return Verdict(url, "OFF_BRIEF", f"{title_reason} | {co_reason}", row)
        return Verdict(url, "OFF_BRIEF", co_reason, row)

    # Combine ambiguities
    if loc_verdict == "BORDERLINE" or title_verdict in {"BORDERLINE", "MISSING"} or co_verdict == "BORDERLINE":
        parts = [r for r in (loc_reason, title_reason if title_verdict != "QUALIFIED" else "", co_reason if co_verdict != "QUALIFIED" else "") if r]
        return Verdict(url, "BORDERLINE", " | ".join(parts), row)

    return Verdict(url, "QUALIFIED", "all gates pass", row)


def split_verdicts(verdicts: list[Verdict]) -> dict:
    out = {"qualified": [], "borderline": [], "off_brief": []}
    for v in verdicts:
        if v.verdict == "QUALIFIED":
            out["qualified"].append({"linkedin_url": v.linkedin_url, "verdict": v.verdict, "reason": v.reason, "row": v.row})
        elif v.verdict == "BORDERLINE":
            out["borderline"].append({"linkedin_url": v.linkedin_url, "verdict": v.verdict, "reason": v.reason, "row": v.row})
        else:
            out["off_brief"].append({"linkedin_url": v.linkedin_url, "verdict": v.verdict, "reason": v.reason, "row": v.row})
    return out


# ----- Main ------------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Phase 1 + 2 pass for lilly-trigify-data-processing")
    parser.add_argument("--brief", required=True, help="Path to brief config JSON")
    parser.add_argument("--engagers", required=True, help="Path to engagers CSV / TSV / parsed Drive output")
    parser.add_argument("--state", default=None, help="Optional state file to skip already-processed rows")
    parser.add_argument("--out", required=True, help="Output verdicts JSON path")
    args = parser.parse_args()

    brief_path = Path(os.path.expanduser(args.brief))
    engagers_path = Path(os.path.expanduser(args.engagers))
    state_path = Path(os.path.expanduser(args.state)) if args.state else None
    out_path = Path(os.path.expanduser(args.out))

    if not brief_path.exists():
        print(f"ERROR: brief config not found: {brief_path}", file=sys.stderr)
        return 1
    if not engagers_path.exists():
        print(f"ERROR: engagers file not found: {engagers_path}", file=sys.stderr)
        return 1

    brief = load_brief(brief_path)
    state = load_state(state_path)
    already = already_processed(state)

    rows = read_engagers_table(engagers_path)
    print(f"Read {len(rows)} rows from {engagers_path}")

    # Dedup vs state, also within-run by canonical URL
    seen: set[str] = set()
    new_rows: list[dict] = []
    skipped_processed = 0
    for row in rows:
        url = canonical_linkedin_url(row.get("LinkedIn URL", ""))
        if not url:
            continue
        if url in already:
            skipped_processed += 1
            continue
        if url in seen:
            continue
        # Defensive: skip rows whose Status is already PROCESSED / OFF_BRIEF / PUSHED
        status = (row.get("Status") or "").strip().upper()
        if status in {"PROCESSED", "OFF_BRIEF", "PUSHED", "PUSHED_SMARTLEAD", "PUSHED_HEYREACH", "OFF_BRIEF_NO_EMAIL"}:
            continue
        seen.add(url)
        new_rows.append(row)

    print(f"  Skipped {skipped_processed} already-processed (per state file)")
    print(f"  Processing {len(new_rows)} new rows")

    verdicts = [evaluate_row(row, brief) for row in new_rows]
    pots = split_verdicts(verdicts)

    summary = {
        "brief_id": brief.get("brief_id"),
        "total_rows_in_sheet": len(rows),
        "skipped_already_processed": skipped_processed,
        "new_rows_evaluated": len(new_rows),
        "verdicts": {
            "qualified": len(pots["qualified"]),
            "borderline": len(pots["borderline"]),
            "off_brief": len(pots["off_brief"]),
        },
        "pots": pots,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    print(f"\nWrote verdicts to {out_path}")
    print(f"  Qualified:  {summary['verdicts']['qualified']}")
    print(f"  Borderline: {summary['verdicts']['borderline']}")
    print(f"  Off-brief:  {summary['verdicts']['off_brief']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
