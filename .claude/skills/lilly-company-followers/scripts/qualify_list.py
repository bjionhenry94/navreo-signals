#!/usr/bin/env python3
"""Generalised prospect qualification pipeline.

Reads a CSV of prospects (any schema) + a JSON config file describing the
qualifying criteria for THIS upload, and outputs a Final Outreach List.

Unlike a Boomerang-specific run_pipeline.py, this script:

  * Auto-detects which qualifying signals are present in the input CSV
  * Applies only the criteria the file can support, and reports which ones
    it had to skip due to missing columns
  * Accepts custom role / location / size / avoid rules per run

USAGE
    python3 qualify_list.py --input <csv> --config <json>

CONFIG SCHEMA
    {
      "role_criteria": {
        "titles": ["CEO", "Head of Sales", ...],           # direct phrase match
        "senior_prefixes": ["Chief", "VP", "Head of", "Director"],
        "qualifying_domains": ["sales", "marketing", "revenue", "growth"],
        "excluded_titles": ["Assistant", "Associate", "Intern", "Junior"],
        "founder_tier_always_passes": true
      },
      "location_criteria": {
        "mode": "any" | "allowlist" | "high_gdp_preset",
        "countries": ["United States", "United Kingdom", ...],
        "match_field": "company" | "person"
      },
      "size_criteria": {
        "min_employees": 11,
        "us_min_age_years": 5,
        "skip_if_missing": false
      },
      "avoid_list": {
        "sender_description": "Navreo runs outbound sales campaigns...",
        "categories": ["sales enablement", "cold outbound", "lead generation", ...],
        "brand_names": ["Smartlead", "Apollo", "Clay", "Outreach", ...]
      },
      "output": {
        "dedupe_by_company": false
      }
    }
"""

import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

# ---------- Column auto-detection ----------

COLUMN_ALIASES: dict[str, list[str]] = {
    "first_name":   ["First Name", "first_name", "firstname"],
    "last_name":    ["Last Name",  "last_name",  "lastname"],
    "job_title":    ["Job Title",  "job_title",  "title"],
    "company":      ["Company",    "company_name", "company", "Account Name"],
    "company_id":   ["Company Linkedin Id", "company_id", "linkedin_company_id"],
    "company_domain": ["company_domain", "Corporate Website", "website", "domain"],
    "company_location": ["Linkedin Company Location", "company_location", "company_hq"],
    "person_location":  ["Location", "city", "person_location", "Linkedin Location"],
    "employees":    ["Linkedin Employees", "employees", "company_size", "employee_count"],
    "founded":      ["Linkedin Founded Year", "founded", "founded_year"],
    "industry":     ["Linkedin Industry", "industry"],
    "description":  ["Linkedin Description", "description", "company_description"],
    "specialities": ["Linkedin Specialities", "specialities", "specialties"],
    "email":        ["Email", "email", "email_first"],
    "email_alt":    ["email_second", "secondary_email"],
    "linkedin_url": ["Linkedin Url", "url", "linkedin_url", "linkedin_profile"],
}


def detect_columns(fieldnames: list[str]) -> dict[str, str | None]:
    """Map logical field -> actual CSV column name (or None if missing)."""
    lower = {f.lower(): f for f in fieldnames}
    resolved: dict[str, str | None] = {}
    for key, aliases in COLUMN_ALIASES.items():
        resolved[key] = None
        for a in aliases:
            if a in fieldnames:
                resolved[key] = a
                break
            if a.lower() in lower:
                resolved[key] = lower[a.lower()]
                break
    return resolved


# ---------- Role classifier ----------


def build_role_matcher(rc: dict):
    """Return a function title -> (bool, reason)."""
    titles = set(t.lower().strip() for t in rc.get("titles", []) or [])
    senior_prefixes = rc.get("senior_prefixes", []) or [
        "chief", "vp", "v.p.", "vice president", "head of", "head",
        "director of", "director", "senior director", "sr. director",
        "global director", "regional director", "managing director",
    ]
    domains = rc.get("qualifying_domains", []) or [
        "sales", "marketing", "revenue", "revops", "gtm", "go-to-market",
        "commercial", "growth", "brand", "communications", "demand gen",
        "demand generation", "partnerships", "sales development",
        "sales enablement", "sales operations", "field sales",
        "inside sales", "enterprise sales", "product marketing",
        "performance marketing", "digital marketing", "field marketing",
        "growth marketing", "strategic marketing", "marketing operations",
    ]
    excluded = rc.get("excluded_titles", []) or [
        "assistant", "associate", "intern", "trainee", "junior", "jr.",
        "analyst", "specialist", "coordinator", "executive", "representative",
        "manager", "senior manager",
    ]
    founder_tier = rc.get("founder_tier_always_passes", True)

    prefix_rx = re.compile(r"\b(" + "|".join(re.escape(p) for p in senior_prefixes) + r")\b", re.I)
    domain_rx = re.compile(r"\b(" + "|".join(re.escape(d) for d in domains) + r")\b", re.I)
    excluded_rx = re.compile(r"\b(" + "|".join(re.escape(e) for e in excluded) + r")\b", re.I)

    founder_rx = re.compile(
        r"\b(ceo|chief\s+executive\s+officer|founder|co[-\s]?founder|cofounder|"
        r"owner|co[-\s]?owner|proprietor|managing\s+partner|founding\s+partner|"
        r"founding\s+member|country\s+head|business\s+head)\b",
        re.I,
    ) if founder_tier else None

    direct_rx = re.compile(
        r"\b(cro|cso|cgo|cmo|cco|chief\s+(revenue|sales|growth|marketing|commercial)\s+officer)\b",
        re.I,
    )

    def check(title: str) -> tuple[bool, str]:
        if not title or not title.strip():
            return False, "missing title"
        t = title.strip()

        if titles:
            tl = t.lower()
            if tl in titles or any(qt in tl for qt in titles):
                return True, "direct title match"

        if direct_rx.search(t):
            return True, "C-suite direct match"

        if founder_rx and founder_rx.search(t):
            return True, "founder/CEO tier"

        if prefix_rx.search(t) and domain_rx.search(t):
            for m in prefix_rx.finditer(t):
                window = t[max(0, m.start() - 40): m.end() + 40]
                if domain_rx.search(window):
                    jm = excluded_rx.search(t)
                    if jm and jm.start() < m.start() and not re.search(r"[&/,]", t[: m.start()]):
                        continue
                    return True, "senior prefix + qualifying domain"

        return False, f"'{t}' does not match role criteria"

    return check


# ---------- Location ----------

HIGH_GDP_COUNTRIES = {
    "united states", "usa", "us", "canada", "united kingdom", "uk", "ireland",
    "germany", "switzerland", "austria", "sweden", "norway", "denmark",
    "finland", "netherlands", "belgium", "luxembourg", "france", "italy",
    "spain", "australia", "new zealand", "japan", "singapore", "hong kong",
    "united arab emirates", "uae", "saudi arabia", "israel", "qatar",
}


def location_matches(location_str: str, mode: str, countries: list[str]) -> tuple[bool, str]:
    if mode == "any":
        return True, "any-location mode"
    if not location_str:
        return False, "location missing"
    loc = " ".join(location_str.split()).lower()
    if mode == "high_gdp_preset":
        allowed = HIGH_GDP_COUNTRIES
    else:
        allowed = set(c.lower().strip() for c in (countries or []))
    for c in allowed:
        if c and c in loc:
            return True, f"matches {c}"
    return False, f"location '{location_str[:40]}' not in allowed set"


US_RX = re.compile(r"(,\s*US\s*$|,\s*USA\s*$|\bUnited\s+States\b)", re.I)


# ---------- Size & age ----------


def employees_ok(emp_str: str, min_employees: int) -> tuple[bool, str | None, int | None]:
    if not emp_str or not str(emp_str).strip():
        return False, "missing size", None
    s = str(emp_str).replace(",", "").strip()
    try:
        n = int(s)
    except ValueError:
        m = re.search(r"\d+", s)
        if not m:
            return False, "size not numeric", None
        n = int(m.group(0))
    if n < min_employees:
        return False, f"size {n} < {min_employees}", n
    return True, None, n


def founded_ok(year_str: str, cutoff_year: int) -> tuple[bool, str | None, int | None]:
    if not year_str or not str(year_str).strip():
        return False, "missing founded year", None
    try:
        y = int(str(year_str).strip())
    except ValueError:
        return False, "founded not numeric", None
    if y > cutoff_year:
        return False, f"founded {y} (≤5yrs)", y
    return True, None, y


# ---------- Avoid list ----------


def build_avoid_matcher(al: dict):
    categories = al.get("categories", []) or []
    brand_names = al.get("brand_names", []) or []

    pats: list[tuple[re.Pattern, str]] = []

    for phrase in categories:
        p = phrase.strip()
        if not p:
            continue
        esc = r"\s+".join(re.escape(w) for w in p.split())
        pats.append((re.compile(rf"\b{esc}\b", re.I), p))

    if brand_names:
        brand_rx = "|".join(re.escape(b) for b in brand_names)
        pats.append((re.compile(rf"\b({brand_rx})\b", re.I), "competitor brand mentioned"))

    def check(blob: str) -> tuple[int, str]:
        for rx, reason in pats:
            if rx.search(blob):
                return 1, f"{reason}"
        return 5, "no avoid-list signals matched"

    return check


# ---------- Main pipeline ----------


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read().replace("\x00", "")
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = [f for f in (reader.fieldnames or []) if f]
    return fieldnames, list(reader)


def run(input_path: Path, config: dict) -> None:
    fieldnames, rows = load_rows(input_path)
    cols = detect_columns(fieldnames)

    rc = config.get("role_criteria", {}) or {}
    lc = config.get("location_criteria", {}) or {"mode": "any"}
    sc = config.get("size_criteria", {}) or {}
    al = config.get("avoid_list", {}) or {}
    oc = config.get("output", {}) or {}

    role_check = build_role_matcher(rc)
    avoid_check = build_avoid_matcher(al)

    min_emp = sc.get("min_employees", None)
    us_age_years = sc.get("us_min_age_years", None)
    size_skip_if_missing = sc.get("skip_if_missing", False)
    age_cutoff = (date.today().year - int(us_age_years)) if us_age_years else None

    loc_mode = lc.get("mode", "any")
    loc_countries = lc.get("countries", [])
    loc_field_pref = lc.get("match_field", "company")
    loc_col = cols["company_location"] if loc_field_pref == "company" else cols["person_location"]
    if loc_col is None:
        loc_col = cols["person_location"] if loc_field_pref == "company" else cols["company_location"]

    applied: list[str] = ["role criteria"]
    skipped: list[str] = []
    if loc_mode != "any":
        if loc_col:
            applied.append(f"location criteria (using {loc_col})")
        else:
            skipped.append("location — no location column found in input")
    if min_emp is not None:
        if cols["employees"]:
            applied.append(f"company size (min {min_emp})")
        elif not size_skip_if_missing:
            skipped.append("size — input has no employee-count column; WILL DISQUALIFY missing rows")
        else:
            skipped.append("size — input has no employee-count column; skipping rule")
    if us_age_years is not None and cols["founded"]:
        applied.append(f"US ≥ {us_age_years}-year age rule")
    elif us_age_years is not None:
        skipped.append("US age rule — no founded-year column in input")
    applied.append("avoid-list scan")

    final_rows: list[dict] = []
    stats = {"total": len(rows), "qualified": 0, "avoided": 0,
             "role_fail": 0, "loc_fail": 0, "size_fail": 0, "age_fail": 0}
    disq_reasons: dict[str, int] = {}

    for r in rows:
        title = r.get(cols["job_title"] or "", "") if cols["job_title"] else ""
        ok, reason = role_check(title or "")
        if not ok:
            stats["role_fail"] += 1
            disq_reasons[reason] = disq_reasons.get(reason, 0) + 1
            continue

        if loc_mode != "any" and loc_col:
            loc_val = r.get(loc_col, "") or ""
            lok, lreason = location_matches(loc_val, loc_mode, loc_countries)
            if not lok:
                stats["loc_fail"] += 1
                disq_reasons[f"location: {lreason}"] = disq_reasons.get(f"location: {lreason}", 0) + 1
                continue

        if min_emp is not None and cols["employees"]:
            eok, ereason, _ = employees_ok(r.get(cols["employees"], "") or "", min_emp)
            if not eok:
                if not (size_skip_if_missing and ereason == "missing size"):
                    stats["size_fail"] += 1
                    disq_reasons[f"size: {ereason}"] = disq_reasons.get(f"size: {ereason}", 0) + 1
                    continue

        if us_age_years and age_cutoff and cols["founded"] and cols["company_location"]:
            loc_val = r.get(cols["company_location"], "") or ""
            if US_RX.search(" ".join(loc_val.split())):
                fok, freason, _ = founded_ok(r.get(cols["founded"], "") or "", age_cutoff)
                if not fok:
                    stats["age_fail"] += 1
                    disq_reasons[f"age: {freason}"] = disq_reasons.get(f"age: {freason}", 0) + 1
                    continue

        blob_fields = [cols["company"], cols["description"], cols["specialities"],
                       cols["industry"], cols["company_domain"]]
        blob = " | ".join((r.get(f, "") or "") for f in blob_fields if f)
        score, areason = avoid_check(blob)
        out = dict(r)
        out["Lead Score"] = f"{score} - {areason}"
        if score == 1:
            stats["avoided"] += 1
            continue

        stats["qualified"] += 1
        final_rows.append(out)

    stem = input_path.with_suffix("").name
    base = re.sub(r"\s*-\s*Main\s+File\s*$", "", stem).strip()
    out_path = input_path.parent / f"{base} - Final Outreach List.csv"

    if oc.get("dedupe_by_company") and cols["company"]:
        seen: set[str] = set()
        dedup: list[dict] = []
        for r in final_rows:
            key = (r.get(cols["company"], "") or "").strip().lower()
            if key and key in seen:
                continue
            seen.add(key)
            dedup.append(r)
        dropped = len(final_rows) - len(dedup)
        final_rows = dedup
        print(f"Deduped {dropped:,} rows by company")

    out_fields = fieldnames + ["Lead Score"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for r in final_rows:
            w.writerow({k: r.get(k, "") for k in out_fields})

    print("=" * 60)
    print(f"Input:        {input_path}")
    print(f"Rows:         {stats['total']:,}")
    print()
    print("Criteria applied:")
    for a in applied:
        print(f"  ✓ {a}")
    if skipped:
        print("Criteria skipped (data unavailable):")
        for s in skipped:
            print(f"  ✗ {s}")
    print()
    print(f"Role-fail:    {stats['role_fail']:,}")
    print(f"Loc-fail:     {stats['loc_fail']:,}")
    print(f"Size-fail:    {stats['size_fail']:,}")
    print(f"Age-fail:     {stats['age_fail']:,}")
    print(f"Avoided:      {stats['avoided']:,}")
    print(f"Qualified:    {stats['qualified']:,}")
    if stats['total']:
        print(f"Find rate:    {stats['qualified']/stats['total']:.1%}")
    print()
    print(f"Output:       {out_path}")
    print()
    print("Top disqualification reasons:")
    for k, v in sorted(disq_reasons.items(), key=lambda x: -x[1])[:8]:
        print(f"  {v:6,}  {k}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--config", type=Path, help="JSON config path", required=True)
    args = ap.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    run(args.input, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
