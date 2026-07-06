#!/usr/bin/env python3
"""Platform diagnostic: checks every layer the signals tool depends on and
prints PASS/FAIL per layer with the actual error. Run any time:
  python3 app/diagnose.py
"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

RESULTS = []


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        RESULTS.append((name, True, detail or "ok", time.time() - t0))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, str(e)[:180], time.time() - t0))


def c_server():
    r = json.load(urllib.request.urlopen("http://localhost:7901/api/clients", timeout=5))
    return f"{len(r)} clients"


def c_keys():
    need = ["PROSPEO_API_KEY", "THEIRSTACK_API_KEY", "SMARTLEAD_API_KEY", "HEYREACH_API_KEY",
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [k for k in need if not server.KEYS.get(k)]
    if missing:
        raise RuntimeError(f"missing keys: {missing}")
    return "all 6 keys loaded"


def c_prospeo_free():
    d = server.http_json("POST", "https://api.prospeo.io/search-suggestions",
                         {"X-KEY": server.KEYS["PROSPEO_API_KEY"]}, {"location_search": "London"})
    if d.get("error"):
        raise RuntimeError(str(d)[:150])
    return "suggestions ok (free endpoint)"


def c_prospeo_search():
    d = server._search_person({"person_job_title": {"include": ["CEO"], "include_partial_match": True},
                               "company_location_search": {"include": ["United States"]},
                               "company_headcount_range": ["11-20"]})
    if d.get("error"):
        raise RuntimeError(f"{d.get('error_code') or ''} {str(d.get('message') or d)[:140]}")
    total = (d.get("pagination") or {}).get("total_count")
    return f"search-person ok · total {total}"


def c_prospeo_enrich():
    # deliberately obscure person -> NO_MATCH is a PASS (endpoint + credits work)
    d = server.http_json("POST", "https://api.prospeo.io/enrich-person",
                         {"X-KEY": server.KEYS["PROSPEO_API_KEY"]},
                         {"only_verified_email": True,
                          "data": {"first_name": "Zz", "last_name": "Qq", "company_website": "example.com"}})
    code = d.get("error_code") or ""
    if code in ("INSUFFICIENT_CREDITS", "INVALID_API_KEY", "RATE_LIMITED"):
        raise RuntimeError(code)
    return f"enrich-person ok ({code or 'match'})"


def c_theirstack():
    jobs, meta = server.theirstack_jobs(["Sales Development Representative"], ["US"], 11, 500, 14, 5)
    return f"{meta.get('total_results')} jobs visible"


def c_smartlead():
    d = server.http_json("GET", f"{server.SMARTLEAD_BASE}/campaigns?api_key={server.KEYS['SMARTLEAD_API_KEY']}", {})
    if not isinstance(d, list):
        raise RuntimeError(str(d)[:150])
    return f"{len(d)} campaigns"


def c_heyreach():
    lists = server.heyreach_lists(refresh=True)
    return f"{len(lists)} lists"


def c_supabase():
    r = server.sb("GET", "signal_sources?select=id&limit=1")
    if isinstance(r, dict) and r.get("message"):
        raise RuntimeError(str(r)[:150])
    return "signal_sources readable"


def c_claude():
    import shutil
    binp = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    out = subprocess.run([binp, "-p", "reply with exactly: ok", "--model", "claude-haiku-4-5-20251001"],
                         capture_output=True, text=True, timeout=60)
    txt = (out.stdout or "").strip()
    if "ok" not in txt.lower():
        raise RuntimeError(f"rc={out.returncode} out={txt[:100]} err={(out.stderr or '')[:80]}")
    return "headless ideation binary ok"


def c_launchd():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    agents = [ln for ln in out.splitlines() if "navreo" in ln]
    if not any("signals-server" in a for a in agents):
        raise RuntimeError("signals-server agent not loaded")
    if not any("signals-daily" in a for a in agents):
        raise RuntimeError("signals-daily agent not loaded")
    return "; ".join(a.split("\t")[-1] for a in agents)


def main():
    check("app server :7901", c_server)
    check("api keys", c_keys)
    check("prospeo (free)", c_prospeo_free)
    check("prospeo search-person", c_prospeo_search)
    check("prospeo enrich (email)", c_prospeo_enrich)
    check("theirstack jobs", c_theirstack)
    check("smartlead api", c_smartlead)
    check("heyreach api", c_heyreach)
    check("supabase", c_supabase)
    check("claude ideation bin", c_claude)
    check("launchd agents", c_launchd)
    print("\n== DIAGNOSTIC ==")
    for name, ok, detail, dt in RESULTS:
        print(f"{'PASS' if ok else 'FAIL':<5} {name:<24} {detail}  ({dt:.1f}s)")
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} layers healthy")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
