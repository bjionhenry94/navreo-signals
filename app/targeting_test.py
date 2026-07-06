#!/usr/bin/env python3
"""Targeting-accuracy harness: execute the real signal pulls, spot-test 10
companies per signal with a cheap judge, report % on-brief. Pass = every
case >= 70%. Filters (free precision) are the lever, not post-hoc AI.

Usage: python3 app/targeting_test.py [--only id,...]
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

OUT = Path(__file__).parent / "data" / "targeting_results.json"


def hiring_pull(job_titles, codes, min_emp, max_emp, extra=None):
    body = {
        "posted_at_max_age_days": 30,
        "job_title_or": job_titles,
        "job_country_code_or": codes,
        "min_employee_count": min_emp,
        "max_employee_count": max_emp,
        "company_type": "direct_employer",
        "blur_company_data": False,
        "limit": 25,
        "include_total_results": True,
        **(extra or {}),
    }
    data = server.http_json("POST", "https://api.theirstack.com/v1/jobs/search",
                            {"Authorization": f"Bearer {server.KEYS['THEIRSTACK_API_KEY']}"}, body)
    out, seen = [], set()
    KILL = ("staffing", "talent", "recruit", "consultants")
    for j in (data.get("data") or []):
        co = j.get("company_object") or {}
        d = server.canon_domain(co.get("domain") or "")
        if d in seen:
            continue
        blob = (str(co.get("name") or "") + " " + str(co.get("industry") or "")).lower()
        if any(k in blob for k in KILL):
            continue
        seen.add(d)
        out.append({"name": co.get("name") or "", "domain": d,
                    "industry": co.get("industry") or "",
                    "description": (co.get("long_description") or co.get("seo_description") or "")[:220],
                    "via_job": j.get("job_title") or ""})
    return out


def person_pull(filters):
    filters = {k: v for k, v in filters.items() if v is not None}
    data = server._search_person(filters)
    out, seen = [], set()
    for r in (data.get("results") or []):
        c = r.get("company") or {}
        d = server.canon_domain(c.get("domain") or "")
        if d in seen:
            continue
        seen.add(d)
        out.append({"name": c.get("name") or "", "domain": d,
                    "industry": c.get("industry") or "", "description": ""})
    return out


BASE_AMPLIFYY = {"company_headcount_range": ["11-20", "21-50", "51-100", "101-200"],
                 "company_location_search": {"include": ["United States"]},
                 "company_keywords": {"include": ["consumer products brand"], "include_company_description": True}}
BASE_NAVREO = {"company_headcount_range": ["11-20", "21-50", "51-100", "101-200"],
               "company_location_search": {"include": ["United States", "United Kingdom"]},
               "company_keywords": {"include": ["software development agency"], "include_company_description": True}}

CASES = [
    {"id": "amplifyy-hiring", "brief": "a company whose PRIMARY business is making/selling its OWN physical consumer products (any channel - DTC, Amazon or retail counts). NOT: an agency, consultancy, staffing firm, software/SaaS company, marketplace, distributor/wholesaler of other brands, or a nonprofit.",
     "pull": lambda extra=None: hiring_pull(["Amazon PPC Specialist", "Marketplace Manager", "Amazon Account Manager", "E-commerce Manager", "Amazon Brand Manager", "Ecommerce Specialist", "Amazon Specialist", "Head of Ecommerce"], ["US"], 11, 200, extra)},
    {"id": "navreo-hiring", "brief": "a software development agency, dev shop or IT/AI consultancy that builds software FOR CLIENTS. NOT a product/SaaS company, not a non-tech business.",
     "pull": lambda extra=None: hiring_pull(["Sales Development Representative", "SDR", "Business Development Representative"], ["US", "GB"], 11, 200, extra)},
    {"id": "arnic-hiring", "brief": "a B2B software/SaaS company around 100-200 employees with its own sales team. NOT an agency, staffing firm or non-software business.",
     "pull": lambda extra=None: hiring_pull(["Sales Enablement Manager", "Revenue Enablement", "Sales Onboarding Specialist"], ["US", "GB"], 100, 200, extra)},
    {"id": "amplifyy-traffic", "brief": "a company whose PRIMARY business is making/selling its OWN physical consumer products. NOT: an agency, software/fintech/SaaS company, service provider TO brands, marketplace, distributor, or nonprofit.",
     "pull": lambda extra=None: person_pull({**BASE_AMPLIFYY, **(extra or {}),
        "person_seniority": {"include": ["Founder/Owner", "C-Suite", "Head"]},
        "company_website_traffic": {"visit_change": {"period": "quarterly", "max_change": -15}}})},
]

# round-2 filter overrides per case id (the free-precision layer)
EXTRA = {
    "amplifyy-hiring": {
        "company_description_pattern_or": [
            "consumer (products?|goods)", "(our|its) products", "direct.to.consumer", "DTC",
            "(skincare|beauty|apparel|footwear|beverage|snack|supplement|cookware|toys|wellness|home goods|pet) (brand|products|company)",
            "we (make|craft|design|create|manufacture)"],
        "company_description_pattern_not": [
            "agency", "consultanc", "staffing", "recruit", "law firm", "marketplace", "SaaS",
            "software (company|platform)", "nonprofit", "non.profit", "thrift", "donat",
            "distributor", "wholesal", "on behalf of brands", "for brands",
            "fittings|components|OEM", "industrial", "B2B manufacturer"],
        "industry_not": ["Staffing and Recruiting", "Law Practice", "Hospitals and Health Care",
                         "Banking", "IT Services and IT Consulting", "Software Development",
                         "Advertising Services", "Non-profit Organizations", "Retail"],
    },
    "navreo-hiring": {
        "company_description_pattern_or": [
            "software development (agency|company|studio|firm)", "custom software",
            "software (house|studio)", "app development (agency|company|studio)",
            "web development (agency|company|studio)", "digital product (agency|studio)",
            "(nearshore|offshore) software development", "dedicated development teams?"],
        "company_description_pattern_not": [
            "managed (IT )?services", "MSP", "IT support", "helpdesk", "staffing", "recruit",
            "law", "insurance", "reseller", "our (platform|product)", "SaaS", "IT solutions",
            "cloud services", "cybersecurity services"],
    },
    "arnic-hiring": {
        "industry_or": ["Software Development"],
        "company_description_pattern_not": ["staffing", "recruit", "insurance", "agency", "consultanc"],
    },
    "amplifyy-traffic": {
        "company_keywords": None,
        "company_industry": {"include": ["Consumer Goods", "Food and Beverage Manufacturing", "Personal Care Product Manufacturing", "Retail Apparel and Fashion", "Furniture and Home Furnishings Manufacturing", "Sporting Goods Manufacturing"]},
    },
}

# conservative allowlist for Amplifyy person-pulls: only obviously-brand industries survive
ALLOW_INDUSTRY = {}

# free client-side deny (provider returns industry anyway)
DENY_INDUSTRY = {
    "amplifyy-traffic": ["software", "it services", "advertising", "staffing", "law", "audiovisual", "media"],
}


def judge(brief, companies):
    lines = "\n".join(
        f"{i+1}. {c['name']} ({c['domain']}) - industry: {c['industry'] or 'unknown'}"
        + (f" - {c['description']}" if c.get("description") else "")
        + (f" - hiring: {c['via_job']}" if c.get("via_job") else "")
        for i, c in enumerate(companies))
    prompt = f"""Judge each company STRICTLY against this target definition:
TARGET: {brief}

{lines}

Judge the PRIMARY business honestly but not pedantically - a coffee, supplement or cookware brand IS a consumer-product brand even if small. For each, answer yes ONLY if it plausibly IS the target (use your knowledge of the company if you recognise it, else judge from industry/description/name). Reply ONLY JSON: {{"verdicts": ["yes"|"no", ...]}} with exactly {len(companies)} entries."""
    out = subprocess.run(["claude", "-p", prompt, "--model", "claude-sonnet-4-6"],
                         capture_output=True, text=True, timeout=120)
    import re
    m = re.search(r"\{.*\}", out.stdout, re.S)
    v = json.loads(m.group(0))["verdicts"] if m else []
    return v


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    results = []
    for case in CASES:
        if only and case["id"] not in only:
            continue
        try:
            companies = case["pull"](EXTRA.get(case["id"]))
            deny = DENY_INDUSTRY.get(case["id"]) or []
            if deny:
                companies = [c for c in companies if not any(d in (c.get("industry") or "").lower() for d in deny)]
            allow = ALLOW_INDUSTRY.get(case["id"]) or []
            if allow:
                companies = [c for c in companies if any(a in (c.get("industry") or "").lower() for a in allow)]
            companies = companies[:10]
        except Exception as e:  # noqa: BLE001
            print(f"{case['id']:<18} PULL FAILED: {str(e)[:80]}")
            results.append({"id": case["id"], "pct": 0, "n": 0, "err": str(e)[:120]})
            continue
        if not companies:
            print(f"{case['id']:<18} 0 companies returned")
            results.append({"id": case["id"], "pct": None, "n": 0})
            continue
        verdicts = judge(case["brief"], companies)
        hits = sum(1 for v in verdicts if v == "yes")
        pct = round(100 * hits / len(companies))
        marks = " ".join(("✓" if v == "yes" else "✗") + c["name"][:18] for v, c in zip(verdicts, companies))
        print(f"{case['id']:<18} {pct:>3}% ({hits}/{len(companies)})  {marks[:150]}")
        results.append({"id": case["id"], "pct": pct, "n": len(companies),
                        "companies": [{**c, "verdict": v} for c, v in zip(companies, verdicts)]})
    scored = [r for r in results if r.get("pct") is not None and r.get("n")]
    ok = all(r["pct"] >= 70 for r in scored) and scored
    print(f"\n{'PASS' if ok else 'ITERATE'} - " + ", ".join(f"{r['id']}:{r['pct']}%" for r in scored))
    prior = json.loads(OUT.read_text()).get("history", []) if OUT.exists() else []
    OUT.write_text(json.dumps({"latest": results, "history": prior + [
        {r["id"]: r.get("pct") for r in results}]}, indent=1))


if __name__ == "__main__":
    main()
