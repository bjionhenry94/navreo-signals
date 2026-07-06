#!/usr/bin/env python3
"""Run 50+ scenarios through the real wizard backend (/api/strategy-map:
ideation + live probes) and report what comes back: idea counts, top-idea
volume vs the 50-100 goal, mechanism mix, failures.

Usage: python3 app/scenario_test.py
"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://localhost:7901"
OUT = Path(__file__).parent / "data" / "scenario_results.json"

ARCHETYPES = [
    ("Amplifyy", "Amazon marketplace management for product brands, performance basis", "consumer products brand", ["Founder", "CEO", "Head of E-commerce"], ["United States"]),
    ("Navreo", "done-for-you cold email, pay per qualified lead", "software development agency", ["Founder", "CEO", "VP of Sales"], ["United States", "United Kingdom"]),
    ("Arnic", "sales onboarding software that cuts rep ramp time", "B2B software company", ["Head of Sales", "VP of Sales"], ["United States", "United Kingdom"]),
    ("FreightFlow", "freight cost reduction for shippers", "logistics company", ["Head of Sales", "Managing Director"], ["United States"]),
    ("BrightPR", "PR retainers for tech startups", "technology startup", ["Founder", "CEO"], ["United Kingdom"]),
    ("TalentStream", "recruitment process outsourcing", "recruitment agency", ["Managing Director", "Founder"], ["United Kingdom"]),
    ("CloudGuard", "SOC2 compliance automation", "B2B SaaS company", ["CEO", "CTO"], ["United States"]),
    ("ShopBoost", "conversion optimisation for online stores", "e-commerce brand", ["Founder", "Head of E-commerce"], ["United States", "United Kingdom"]),
    ("BuildRight", "construction project management software", "construction company", ["Managing Director", "Commercial Director"], ["United Kingdom"]),
    ("MedSupply", "medical device distribution partnerships", "medical device manufacturer", ["CEO", "Head of Sales"], ["United States"]),
    ("AgencyFuel", "white-label development for agencies", "marketing agency", ["Founder", "Managing Director"], ["United States"]),
    ("FinOptics", "spend management for mid-market companies", "professional services firm", ["CFO", "CEO"], ["United States"]),
    ("GreenPack", "sustainable packaging for consumer brands", "consumer goods brand", ["Founder", "Head of Operations"], ["United States", "United Kingdom"]),
    ("DataPilot", "analytics implementation for SaaS companies", "B2B SaaS company", ["Founder", "Head of Growth"], ["United States"]),
    ("RetailLink", "wholesale marketplace for independent retailers", "consumer products brand", ["Founder", "CEO"], ["United States"]),
    ("DevHire", "vetted developer placement", "software development agency", ["Founder", "CEO"], ["United States", "United Kingdom"]),
    ("HostPro", "managed hosting for digital agencies", "digital agency", ["Founder", "Managing Director"], ["United Kingdom"]),
    ("InsurTech", "embedded insurance for platforms", "B2B software company", ["CEO", "Head of Product"], ["United States"]),
]

GOALS = [
    ("ai", "", "find warm buyers showing timely signals"),
    ("ai", "", "companies hiring the roles we sell to"),
    ("direct", "hiring", "companies hiring {kw} relevant roles right now"),
]


def api(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=420).read())


def run_one(i, arch, goal_spec):
    name, offer, kw, titles, geos = arch
    mode, mech, goal_t = goal_spec
    goal = goal_t.format(kw=kw)
    try:
        r = api("/api/strategy-map", {
            "titles": titles, "keywords": [kw],
            "headcount": ["11-20", "21-50", "51-100", "101-200"],
            "countries": geos, "client_name": name, "client_offer": offer,
            "goal": goal, "mode": mode, "mechanism": mech, "force": True, "sync": True})
        rows = [x for x in (r.get("rows") or []) if x.get("estimated") or (x.get("dms") or 0) > 0]
        top = rows[0] if rows else None
        return {"i": i, "client": name, "mode": mode, "goal": goal, "ok": bool(rows),
                "n_ideas": len(rows),
                "top_idea": top and top["idea"], "top_mech": top and top["mechanism"],
                "top_companies": top and top.get("companies"),
                "top_dms": top and top.get("dms"),
                "mechs": sorted({x["mechanism"] for x in rows})}
    except Exception as e:  # noqa: BLE001
        return {"i": i, "client": name, "mode": mode, "goal": goal, "ok": False, "err": str(e)[:120]}


def main():
    import sys
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    jobs = []
    i = 0
    for arch in ARCHETYPES:
        for gs in GOALS:
            if only is None or i in only:
                jobs.append((i, arch, gs))
            i += 1
    print(f"{len(jobs)} scenarios")
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(lambda j: run_one(*j), jobs))

    ok = [r for r in results if r.get("ok")]
    fails = [r for r in results if not r.get("ok")]
    vols = [r["top_dms"] for r in ok if isinstance(r.get("top_dms"), int)]
    for r in results:
        print(f"{r['i']:>2} {r['client']:<12} {r['mode']:<6} -> " +
              (f"{r['n_ideas']} ideas · top: {r['top_idea']} [{r['top_mech']}] dms={r.get('top_dms')}"
               if r.get("ok") else f"FAIL {r.get('err', 'no sized ideas')}"))
    if vols:
        vols.sort()
        import statistics
        print(f"\nscenarios: {len(results)} · ok: {len(ok)} · failed: {len(fails)}")
        print(f"top-idea decision makers -> avg {statistics.mean(vols):.0f} · median {statistics.median(vols):.0f} "
              f"· min {vols[0]} · max {vols[-1]}")
        print(f">=50 available: {sum(1 for v in vols if v >= 50)}/{len(vols)} "
              f"· >=100: {sum(1 for v in vols if v >= 100)}/{len(vols)}")
    out = OUT if only is None else OUT.with_name("scenario_results_rerun.json")
    out.write_text(json.dumps({"results": results}, indent=1))


if __name__ == "__main__":
    main()
