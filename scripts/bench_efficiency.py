#!/usr/bin/env python3
"""Reproducible efficiency benchmark for the Navreo signals tool.

Boots against an already-running local dev server (default :7901) started with
`NAVREO_NO_BG=1 DELIV_MOCK=1 python3 app/server.py 7901`. Mints a local session
cookie via the server's own _mint_session so authed pages/endpoints are reachable
without hitting live login. Read-only: only GETs the safe read endpoints below.

Usage:  python3 scripts/bench_efficiency.py [--port 7901] [--reps 12] [--out docs/bench] [--label baseline]
Writes  <out>/<label>.json  (raw samples + p50/p95 per target)
        <out>/<label>.md    (human table)
"""
import argparse, json, statistics, time, urllib.request, importlib.util, sys, os
from pathlib import Path

PAGES = ["setter", "campaigns", "deliverability", "optimise", "lists",
         "strategy", "report", "mailboxes-hub", "infrastructure"]
# Safe, read-only endpoints. Params chosen to match what the pages actually call.
ENDPOINTS = [
    "/api/collisions", "/api/notifications", "/api/sources?slim=1", "/api/sources",
    "/api/campaigns-unified", "/api/analytics-hub", "/api/clients",
    "/api/workspaces", "/api/deliverability-trends",
]


def mint_cookie():
    here = Path(__file__).resolve().parent.parent / "app"
    spec = importlib.util.spec_from_file_location("srv", here / "server.py")
    srv = importlib.util.module_from_spec(spec); sys.modules["srv"] = srv
    os.chdir(here)                       # server.py imports sibling modules
    sys.path.insert(0, str(here))        # so `import mock_deliv` etc resolve
    spec.loader.exec_module(srv)
    return srv._mint_session("admin@navreo.ai")


def timed_get(url, cookie):
    req = urllib.request.Request(url, headers={"Cookie": f"navreo_session={cookie}",
                                               "Accept-Encoding": "gzip"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            return r.status, len(body), (time.perf_counter() - t0)
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}", 0, (time.perf_counter() - t0)


def pctile(xs, p):
    if not xs:
        return None
    xs = sorted(xs); k = (len(xs) - 1) * p
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 4)


def bench_target(base, path, cookie, reps):
    url = base + path
    # cold = very first call (SWR cold compute); warm = subsequent
    cs, cb, ct = timed_get(url, cookie)
    warm = [timed_get(url, cookie) for _ in range(reps)]
    status = warm[-1][0] if warm else cs
    bytes_ = warm[-1][1] if warm else cb
    wt = [t for (_, _, t) in warm]
    return {
        "target": path, "status": status, "bytes": bytes_,
        "cold_s": round(ct, 4),
        "warm_p50_s": pctile(wt, 0.5), "warm_p95_s": pctile(wt, 0.95),
        "warm_min_s": round(min(wt), 4) if wt else None,
        "reps": reps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="7901")
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--out", default="docs/bench")
    ap.add_argument("--label", default="baseline")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    cookie = mint_cookie()
    base = f"http://localhost:{a.port}"
    rows = []
    for p in PAGES:
        rows.append(bench_target(base, f"/app/{p}.html", cookie, a.reps))
    for e in ENDPOINTS:
        rows.append(bench_target(base, e, cookie, a.reps))
    outdir = root / a.out; outdir.mkdir(parents=True, exist_ok=True)
    payload = {"label": a.label, "port": a.port, "reps": a.reps,
               "ts": int(time.time()), "rows": rows}
    (outdir / f"{a.label}.json").write_text(json.dumps(payload, indent=2))
    lines = [f"# Benchmark: {a.label} (reps={a.reps})", "",
             "| Target | Status | Bytes | Cold s | Warm p50 | Warm p95 |",
             "|--------|--------|-------|--------|----------|----------|"]
    for r in rows:
        lines.append(f"| {r['target']} | {r['status']} | {r['bytes']:,} | "
                     f"{r['cold_s']} | {r['warm_p50_s']} | {r['warm_p95_s']} |")
    (outdir / f"{a.label}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWrote {outdir/(a.label+'.json')} and .md")


if __name__ == "__main__":
    main()
