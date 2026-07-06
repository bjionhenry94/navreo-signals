#!/usr/bin/env python3
"""Precision-prompt bake-off: run each PRECISION_STYLES variant over the SAME
scenarios, execute the top idea as a real page-1 pull, judge 10 results for
on-brief quality (right company AND right decision maker), record volume.

Winner = the style where every scenario >= 70% accuracy, with the most volume.

Usage: python3 app/prompt_test.py [--styles balanced,loose] [--scenarios amplifyy,navreo]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

OUT = Path(__file__).parent / "data" / "prompt_test_results.json"

SCENARIOS = [
    {"id": "amplifyy",
     "brief_co": "a company whose PRIMARY business is making/selling its OWN physical consumer products (any channel - DTC, Amazon or retail). NOT: an agency, consultancy, staffing firm, software/SaaS company, marketplace, distributor of other brands, or a nonprofit.",
     "brief_dm": "a founder/CEO or a senior commercial/e-commerce leader who could buy marketplace management services",
     "p": {"titles": ["Founder", "CEO", "Head of E-commerce"], "keywords": ["consumer products brand"],
           "headcount": ["11-20", "21-50", "51-100", "101-200"], "countries": ["United States"],
           "client_name": "Amplifyy", "client_offer": "Amazon marketplace management for product brands, performance basis",
           "goal": "find warm buyers showing timely signals", "mode": "ai"}},
    {"id": "navreo",
     "brief_co": "a software development agency, dev shop or IT/AI consultancy that builds software FOR CLIENTS. NOT a product/SaaS company, not a non-tech business, not a staffing firm.",
     "brief_dm": "a founder/CEO or senior sales leader who could buy done-for-you outbound lead generation",
     "p": {"titles": ["Founder", "CEO", "VP of Sales"], "keywords": ["software development agency"],
           "headcount": ["11-20", "21-50", "51-100", "101-200"], "countries": ["United States", "United Kingdom"],
           "client_name": "Navreo", "client_offer": "done-for-you cold email, pay per qualified lead",
           "goal": "find warm buyers showing timely signals", "mode": "ai"}},
    {"id": "arnic",
     "brief_co": "a B2B software/SaaS company with its own sales team. NOT an agency, staffing firm or non-software business.",
     "brief_dm": "a senior sales leader (Head of Sales, VP Sales, CRO) who owns rep onboarding and ramp",
     "p": {"titles": ["Head of Sales", "VP of Sales"], "keywords": ["B2B software company"],
           "headcount": ["51-100", "101-200"], "countries": ["United States", "United Kingdom"],
           "client_name": "Arnic", "client_offer": "sales onboarding software that cuts rep ramp time",
           "goal": "companies hiring the roles we sell to", "mode": "ai"}},
    {"id": "freightflow",
     "brief_co": "a logistics, freight, transportation or supply-chain company that ships or moves goods. NOT a software company, staffing firm or consultancy.",
     "brief_dm": "a senior operations/commercial leader (MD, COO, Head of Ops/Sales) who owns freight spend",
     "p": {"titles": ["Head of Sales", "Managing Director"], "keywords": ["logistics company"],
           "headcount": ["21-50", "51-100", "101-200"], "countries": ["United States"],
           "client_name": "FreightFlow", "client_offer": "freight cost reduction for shippers",
           "goal": "find warm buyers showing timely signals", "mode": "ai"}},
    {"id": "greenpack",
     "brief_co": "a company whose PRIMARY business is making/selling its OWN consumer goods (food, beverage, personal care, apparel, home). NOT a packaging supplier, agency, software company or distributor.",
     "brief_dm": "a founder or senior operations/product leader who decides packaging suppliers",
     "p": {"titles": ["Founder", "Head of Operations"], "keywords": ["consumer goods brand"],
           "headcount": ["11-20", "21-50", "51-100", "101-200"], "countries": ["United States", "United Kingdom"],
           "client_name": "GreenPack", "client_offer": "sustainable packaging for consumer brands",
           "goal": "companies hiring the roles we sell to", "mode": "ai"}},
    {"id": "insurtech",
     "brief_co": "a B2B software platform or marketplace (software whose product connects users/businesses or processes transactions for them). NOT an insurance carrier/broker, agency or non-software business.",
     "brief_dm": "a CEO or senior product leader who owns the platform roadmap",
     "p": {"titles": ["CEO", "Head of Product"], "keywords": ["B2B software company"],
           "headcount": ["21-50", "51-100", "101-200"], "countries": ["United States"],
           "client_name": "InsurTech", "client_offer": "embedded insurance for platforms",
           "goal": "find warm buyers showing timely signals", "mode": "ai"}},
]


def top_sized(rows):
    for r in rows:
        if not r.get("estimated") and isinstance(r.get("dms"), int) and r["dms"] > 0:
            return r
    return None


def exec_hiring(sc, prm):
    """Page-1 of the exact pull: TheirStack jobs with the idea's precision layer."""
    codes = [server.COUNTRY_CODE.get(c, c) for c in (sc["p"].get("countries") or [])] or ["US"]
    lo, hi = server.emp_range(sc["p"].get("headcount"))
    extra = {k: prm[k] for k in ("company_description_pattern_or", "company_description_pattern_not",
                                 "industry_or", "industry_not") if prm.get(k)}
    jobs, _ = server.theirstack_jobs(prm.get("job_titles") or [], codes, lo, hi,
                                     prm.get("days") or 30, 25, extra=extra)
    out, seen = [], set()
    for j in jobs:
        if j["domain"] in seen:
            continue
        seen.add(j["domain"])
        out.append({"name": j.get("company") or "", "title": "(company-level judge)",
                    "company": j.get("company") or "", "industry": j.get("industry") or "",
                    "description": (j.get("description") or "")[:200], "via_job": j.get("job_title") or ""})
    return out, "company"


def exec_person(sc, idea):
    """Page-1 of the exact pull: Prospeo search-person with the idea's params."""
    prm = idea.get("params") or {}
    p = sc["p"]
    titles = server.expand_titles(prm.get("dm_titles") or p.get("titles") or [])
    f = {"person_job_title": {"include": titles, "include_partial_match": True}}
    kw = prm.get("keywords") or p.get("keywords")
    if kw:
        f["company_keywords"] = {"include": kw if isinstance(kw, list) else [kw],
                                 "include_company_description": True}
    if prm.get("industries"):
        f["company_industry"] = {"include": prm["industries"]}
    if p.get("headcount"):
        f["company_headcount_range"] = p["headcount"]
    if p.get("countries"):
        f["company_location_search"] = {"include": p["countries"]}
    extra = {
        "traffic_decline": {"company_website_traffic": {"visit_change": {"period": "quarterly", "max_change": prm.get("max_change") or -15}}},
    }.get(idea["mechanism"], {})
    d = server._search_person({**f, **extra})
    out = []
    if not d.get("error"):
        for r in (d.get("results") or []):
            person, comp = r.get("person") or {}, r.get("company") or {}
            out.append({"name": person.get("full_name") or "",
                        "title": person.get("current_job_title") or "",
                        "company": comp.get("name") or "", "industry": comp.get("industry") or "",
                        "description": (comp.get("description_ai") or comp.get("description") or "")[:200]})
    return out, "person"


def judge(sc, rows, level):
    lines = "\n".join(
        f"{i+1}. {r['title']} at {r['company']} - industry: {r['industry'] or 'unknown'}"
        + (f" - {r['description']}" if r.get("description") else "")
        + (f" - hiring: {r['via_job']}" if r.get("via_job") else "")
        for i, r in enumerate(rows))
    dm_line = f"\nAND the person's title must plausibly be {sc['brief_dm']}." if level == "person" else ""
    prompt = f"""Judge each entry STRICTLY against this target:
COMPANY TARGET: {sc['brief_co']}{dm_line}

{lines}

Judge the PRIMARY business honestly but not pedantically - a coffee, supplement or cookware brand IS a consumer-product brand even if small. When the description clearly matches the target, judge yes even if the LinkedIn industry label disagrees (industry labels are often stale or wrong); when they conflict, the description wins. Answer yes ONLY if the company plausibly IS the target{' and the title fits' if level == 'person' else ''}. Reply ONLY JSON: {{"verdicts": ["yes"|"no", ...]}} with exactly {len(rows)} entries."""
    out = subprocess.run(["claude", "-p", prompt, "--model", "claude-sonnet-4-6"],
                         capture_output=True, text=True, timeout=120)
    m = re.search(r"\{.*\}", out.stdout, re.S)
    return json.loads(m.group(0))["verdicts"] if m else []


def run_cell(style, sc):
    rows = server.strategy_map({**sc["p"], "force": True, "precision_style": style}).get("rows") or []
    if rows and rows[0].get("fallback"):  # ideation died -> catalogue rows test nothing
        rows = server.strategy_map({**sc["p"], "force": True, "precision_style": style}).get("rows") or []
    if rows and rows[0].get("fallback"):
        return {"style": style, "scenario": sc["id"], "ok": False, "err": "ideation fallback (style untested)"}
    idea = top_sized(rows)
    if not idea:
        return {"style": style, "scenario": sc["id"], "ok": False, "err": "no sized ideas"}
    prm = idea.get("params") or {}
    if idea["mechanism"] == "hiring":
        sample, level = exec_hiring(sc, prm)
    else:
        sample, level = exec_person(sc, idea)
    sample = sample[:10]
    if not sample:
        return {"style": style, "scenario": sc["id"], "ok": False, "err": "pull returned 0",
                "idea": idea["idea"], "mech": idea["mechanism"], "dms": idea.get("dms")}
    verdicts = judge(sc, sample, level)
    hits = sum(1 for v in verdicts if v == "yes")
    return {"style": style, "scenario": sc["id"], "ok": True,
            "idea": idea["idea"], "mech": idea["mechanism"], "dms": idea.get("dms"),
            "params": prm,
            "n": len(sample), "hits": hits, "acc": round(100 * hits / len(sample)),
            "sample": [{**r, "verdict": v} for r, v in zip(sample, verdicts)]}


def main():
    styles = list(server.PRECISION_STYLES)
    if "--styles" in sys.argv:
        styles = sys.argv[sys.argv.index("--styles") + 1].split(",")
    scenarios = SCENARIOS
    if "--scenarios" in sys.argv:
        want = set(sys.argv[sys.argv.index("--scenarios") + 1].split(","))
        scenarios = [s for s in SCENARIOS if s["id"] in want]

    prior = json.loads(OUT.read_text()).get("cells", []) if OUT.exists() else []
    cells = [c for c in prior if not (c["style"] in styles and c["scenario"] in {s["id"] for s in scenarios})]
    for style in styles:
        for sc in scenarios:
            c = run_cell(style, sc)
            cells.append(c)
            print(f"{style:<15} {sc['id']:<12} -> " +
                  (f"acc {c['acc']}% ({c['hits']}/{c['n']}) · dms {c['dms']} · [{c['mech']}] {c['idea'][:45]}"
                   if c.get("ok") else f"FAIL {c['err']}" + (f" · [{c.get('mech')}] {c.get('idea','')[:40]}" if c.get("idea") else "")))
            OUT.write_text(json.dumps({"cells": cells}, indent=1))

    print("\n== summary ==")
    import statistics
    for style in sorted({c["style"] for c in cells}):
        sc_cells = [c for c in cells if c["style"] == style]
        okc = [c for c in sc_cells if c.get("ok")]
        accs = [c["acc"] for c in okc]
        vols = [c["dms"] for c in okc if isinstance(c.get("dms"), int)]
        passing = len(okc) == len(sc_cells) and all(a >= 70 for a in accs)
        print(f"{style:<15} pass={passing} · acc avg {round(statistics.mean(accs)) if accs else '-'}% "
              f"min {min(accs) if accs else '-'}% · vol median {round(statistics.median(vols)) if vols else '-'} "
              f"· cells ok {len(okc)}/{len(sc_cells)}")


if __name__ == "__main__":
    main()
