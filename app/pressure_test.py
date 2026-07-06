#!/usr/bin/env python3
"""Pressure-test the Create-a-campaign / Add-a-source design with 30
realistic list-building briefs. Calls the same server functions the UI
uses. A brief PASSES when the design handles it cleanly:

  - ok:true with a non-empty sample whose titles fit the ask, OR
  - a graceful, helpful zero-results message (niche briefs can be empty;
    crashing or leaking raw errors is the failure, not emptiness).

FAIL = exception, HTTP error leaking through, empty-but-ok responses,
missing sample despite total>0, or off-brief samples (title fit < 40%).

Usage: python3 app/pressure_test.py [--only N,M,...]
Writes results to scratchpad state (path via $PRESSURE_STATE) and prints
a table.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402  (the same functions the UI hits)

STATE = Path(os.environ.get("PRESSURE_STATE",
             Path(__file__).parent / "data" / "pressure_state.json"))

BRIEFS = [
    # ── people briefs (preview_people) ──
    ("people", "Jamaica hotels & resorts - owners/GMs",
     {"titles": ["Owner", "General Manager", "Managing Director"], "keywords": ["hotel"], "countries": ["Jamaica"]}),
    ("people", "UK housebuilders - MDs/commercial directors",
     {"titles": ["Managing Director", "Commercial Director"], "keywords": ["housebuilder"], "countries": ["United Kingdom"], "headcount": ["21-50", "51-100", "101-200", "201-500"]}),
    ("people", "US consumer brands - founders/heads of ecom",
     {"titles": ["Founder", "Head of E-commerce", "CEO"], "keywords": ["consumer products brand"], "countries": ["United States"], "headcount": ["11-20", "21-50", "51-100"]}),
    ("people", "German manufacturers - Geschaftsfuhrer",
     {"titles": ["Geschäftsführer", "Managing Director"], "keywords": ["manufacturer"], "countries": ["Germany"], "headcount": ["51-100", "101-200", "201-500"]}),
    ("people", "Dev agencies US/UK - sales leaders (house ICP)",
     {"titles": ["VP of Sales", "Head of Sales"], "keywords": ["software development agency"], "countries": ["United States", "United Kingdom"], "headcount": ["51-100", "101-200"]}),
    ("people", "AI consultancies - founders",
     {"titles": ["Founder", "CEO"], "keywords": ["AI consultancy"], "countries": ["United States", "United Kingdom", "Canada"]}),
    ("people", "US freight forwarders - sales leaders",
     {"titles": ["Head of Sales", "VP of Sales", "Sales Director"], "keywords": ["freight forwarder"], "countries": ["United States"]}),
    ("people", "US MSPs - owners",
     {"titles": ["CEO", "Owner", "Founder"], "keywords": ["managed service provider"], "countries": ["United States"], "headcount": ["11-20", "21-50", "51-100"]}),
    ("people", "UK boutique PR agencies - founders",
     {"titles": ["Founder", "Managing Director"], "keywords": ["PR agency"], "countries": ["United Kingdom"], "headcount": ["1-10", "11-20", "21-50"]}),
    ("people", "AU/NZ recruitment agencies - directors",
     {"titles": ["Director", "Founder"], "keywords": ["recruitment agency"], "countries": ["Australia", "New Zealand"]}),
    ("people", "US SaaS 51-200 - sales leaders (industry filter)",
     {"titles": ["Head of Sales", "VP of Sales"], "industries": ["Software Development"], "countries": ["United States"], "headcount": ["51-100", "101-200"]}),
    ("people", "US dental clinics - owners",
     {"titles": ["Owner", "Practice Manager"], "keywords": ["dental clinic"], "countries": ["United States"]}),
    ("people", "Singapore fintechs - growth leaders",
     {"titles": ["CEO", "Head of Growth"], "keywords": ["fintech"], "countries": ["Singapore"]}),
    ("people", "Dutch logistics providers - commercial directors",
     {"titles": ["Commercial Director", "Managing Director"], "keywords": ["logistics provider"], "countries": ["Netherlands"]}),
    ("people", "Nigerian banks - digital leads (exotic geo)",
     {"titles": ["Head of Digital", "Chief Digital Officer"], "keywords": ["bank"], "countries": ["Nigeria"]}),
    ("people", "Game publishers - partnership leads",
     {"titles": ["Head of Partnerships", "Business Development Manager"], "keywords": ["game publisher"], "countries": ["United States", "United Kingdom"]}),
    ("people", "UK groundworks contractors - MDs",
     {"titles": ["Managing Director", "Owner"], "keywords": ["groundworks contractor"], "countries": ["United Kingdom"]}),
    ("people", "DACH/Benelux wholesale distributors - sales heads",
     {"titles": ["Head of Sales", "Sales Director"], "keywords": ["wholesale distributor"], "countries": ["Germany", "Netherlands", "United Kingdom"]}),
    ("people", "Named accounts only - hubspot.com + clay.com",
     {"titles": ["VP of Sales"], "domains": ["hubspot.com", "clay.com"]}),
    ("people", "Audience + named account mixed",
     {"titles": ["Founder", "CEO"], "keywords": ["app marketing agency"], "countries": ["United States", "United Kingdom"], "headcount": ["11-20", "21-50", "51-100"], "domains": ["moburst.com"]}),
    # ── hiring briefs (preview_hiring) ──
    ("hiring", "US cos hiring SDRs",
     {"job_titles": ["SDR", "Sales Development Representative"], "countries": ["US"], "min_emp": 11, "max_emp": 200, "days": 14}),
    ("hiring", "US cos hiring Head of Amazon (niche)",
     {"job_titles": ["Head of Amazon", "Amazon Marketplace Manager"], "countries": ["US"], "min_emp": 11, "max_emp": 500, "days": 30}),
    ("hiring", "DE cos hiring Geschaftsfuhrer (non-English)",
     {"job_titles": ["Geschäftsführer"], "countries": ["DE"], "min_emp": 11, "max_emp": 500, "days": 30}),
    ("hiring", "UK cos hiring VP Marketing",
     {"job_titles": ["VP Marketing", "Head of Marketing"], "countries": ["GB"], "min_emp": 11, "max_emp": 500, "days": 7}),
    ("hiring", "US/CA cos hiring CS managers",
     {"job_titles": ["Customer Success Manager"], "countries": ["US", "CA"], "min_emp": 11, "max_emp": 200, "days": 14}),
    # ── lookalike briefs (preview_lookalike) ──
    ("lookalike", "Lookalike: mid-market dev agency",
     {"icp_text": "B2B software development agency serving mid-market clients", "tier": "T2"}),
    ("lookalike", "Lookalike: boutique tech PR agency (UK)",
     {"icp_text": "boutique PR agency for technology startups", "tier": "T3", "countries": ["United Kingdom"]}),
    ("lookalike", "Lookalike: 3PL for e-commerce (US)",
     {"icp_text": "third-party logistics provider for e-commerce brands", "tier": "T2", "countries": ["United States"]}),
    ("lookalike", "Lookalike: Amazon marketplace agency (tight)",
     {"icp_text": "Amazon marketplace management agency", "tier": "T1"}),
    ("lookalike", "Lookalike: cold email lead gen agency",
     {"icp_text": "cold email lead generation agency", "tier": "T2", "countries": ["United States", "United Kingdom"]}),
]

GRACEFUL = re.compile(r"nothing matched|no location matched|widen|add at least", re.I)


def title_fit(brief_titles, sample):
    """Loose title match: sample rows (non-named) whose title shares a word
    with any requested title. Ignores rows with empty titles."""
    tokens = set()
    for t in brief_titles:
        tokens.update(w.lower() for w in re.split(r"[^A-Za-zÀ-ÿ]+", t) if len(w) > 2)
    rows = [s for s in sample if not s.get("named_account") and s.get("title")]
    if not rows:
        return None
    hits = sum(1 for s in rows if tokens & {w.lower() for w in re.split(r"[^A-Za-zÀ-ÿ]+", s["title"]) if len(w) > 2})
    return hits / len(rows)


def run_brief(kind, payload):
    fn = {"people": server.preview_people, "hiring": server.preview_hiring,
          "lookalike": server.preview_lookalike}[kind]
    try:
        r = fn(dict(payload))
    except Exception as e:  # noqa: BLE001 — an exception IS the failure signal here
        return "FAIL", f"exception: {str(e)[:120]}", None
    if not isinstance(r, dict):
        return "FAIL", "non-dict response", None
    if r.get("ok"):
        sample = r.get("sample") or []
        total = r.get("total_people") or r.get("total_companies") or r.get("total_jobs") or 0
        if total and not sample:
            return "FAIL", f"total={total} but empty sample (extraction bug)", r
        if not total and not sample:
            return "FAIL", "ok:true but zero everything (should be graceful-zero)", r
        if kind == "people":
            fit = title_fit(payload.get("titles", []), sample)
            if fit is not None and fit < 0.4:
                return "FAIL", f"title fit {fit:.0%} - filters not honoured", r
        return "PASS", f"total={total}, sample={len(sample)}", r
    msg = str(r.get("message") or "")
    if GRACEFUL.search(msg):
        return "PASS", f"graceful zero: {msg[:60]}", r
    return "FAIL", f"ugly error: {msg[:120] or 'empty message'}", r


def main():
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    results = []
    for i, (kind, desc, payload) in enumerate(BRIEFS, 1):
        if only and i not in only:
            continue
        verdict, note, _ = run_brief(kind, payload)
        results.append({"n": i, "kind": kind, "desc": desc, "verdict": verdict, "note": note})
        print(f"{i:2d} {verdict:4s} [{kind:9s}] {desc} -> {note}")
        time.sleep(0.4)

    # longest consecutive-pass streak
    streak = best = 0
    for r in results:
        streak = streak + 1 if r["verdict"] == "PASS" else 0
        best = max(best, streak)
    passes = sum(1 for r in results if r["verdict"] == "PASS")
    print(f"\n{passes}/{len(results)} passed · longest consecutive streak: {best}")

    state = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "passes": passes,
             "total": len(results), "best_streak": best, "results": results}
    prior = []
    if STATE.exists():
        try:
            prior = json.loads(STATE.read_text()).get("history", [])
        except ValueError:
            pass
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"latest": state, "history": (prior + [
        {"ts": state["ts"], "passes": passes, "best_streak": best}])[-20:]}, indent=1))


if __name__ == "__main__":
    main()
