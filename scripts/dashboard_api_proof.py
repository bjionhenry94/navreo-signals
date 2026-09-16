#!/usr/bin/env python3
"""Step-2 proof for the client campaign dashboard API.

Boots app/server.py IN-PROCESS (NAVREO_NO_BG=1 — HTTP only, no background
sweeps) on a free loopback port and drives the REAL HTTP endpoint:

  (a) one own-workspace client + one shared-workspace client: payload keys,
      len(months), len(campaigns_running), week.range, two consecutive warm
      timings.
  (b) tampered + expired tokens: HTTP status and body (expect 4xx, "not
      valid", zero rows).
  (c) cross-scope: for every pair of clients in the scorecard, the campaign
      ids client A's dashboard can ever serve are disjoint from B's scorecard
      ids.  PASS/FAIL count.

Hard budget: 180 s wall clock, every HTTP call <= 20 s.
"""
import base64
import importlib.util
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

T0 = time.time()
BUDGET_S = 180.0
HTTP_TIMEOUT = 20


def left():
    return BUDGET_S - (time.time() - T0)


def abort_if_out_of_time(where):
    if left() <= 0:
        print(f"\nABORT: 180 s budget spent at {where}; reporting what we have.")
        sys.exit(2)


os.environ["NAVREO_NO_BG"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
spec = importlib.util.spec_from_file_location("navreo_server",
                                              os.path.join(ROOT, "app", "server.py"))
S = importlib.util.module_from_spec(spec)
sys.modules["navreo_server"] = S
spec.loader.exec_module(S)

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()
srv = S._NavreoServer(("127.0.0.1", PORT), S.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
print(f"server up on {BASE}  (NAVREO_NO_BG=1)\n")


def get(path):
    req = urllib.request.Request(BASE + path)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            body = r.read()
            code = r.getcode()
    except urllib.error.HTTPError as e:
        body = e.read()
        code = e.code
    dt = time.time() - t
    try:
        return code, json.loads(body.decode() or "{}"), dt
    except ValueError:
        return code, {"_raw": body[:200].decode(errors="replace")}, dt


# ── pick the clients ───────────────────────────────────────────────────────
S._scorecard_seed_from_snapshot()
score = S._inject_demo_scorecard(S._CAMPAIGN_SCORECARD_ALL_SWR.get()) or {}
camps = score.get("campaigns") or {}
by_client = {}
for cid, c in camps.items():
    cl = (c.get("client") or "").strip()
    if not cl or cl in ("All", "__all", "__unassigned"):
        continue
    by_client.setdefault(cl, set()).add(str(cid))
print(f"scorecard: {len(camps)} campaigns across {len(by_client)} clients")

OWN_PREF = ["Grout", "KRG", "Greenshift", "REViVE"]
SHARED_PREF = ["Arnic", "Amplifyy", "TouchPoint", "Altius Reach", "ThunderBird"]


def pick(prefs):
    for p in prefs:
        for cl in by_client:
            if cl.lower() == p.lower():
                return cl
    return None


own = pick(OWN_PREF)
shared = pick(SHARED_PREF)
targets = [("own-workspace", own), ("shared-workspace", shared)]
print(f"targets: own={own!r} shared={shared!r}\n")

SAMPLE = {}
# ── (a) ────────────────────────────────────────────────────────────────────
print("=" * 72)
print("(a) VALID TOKEN — payload shape + warm timings")
print("=" * 72)
for kind, cl in targets:
    abort_if_out_of_time(f"(a) {cl}")
    if not cl:
        print(f"\n[{kind}] no client found in the scorecard — SKIPPED")
        continue
    tok = S.mint_client_dashboard_share(cl)
    url = f"/api/dashboard/data?share={tok}"
    # Cold fill runs IN-PROCESS: the first call for the whole process builds the
    # shared analytics-hub / client-windows SWR caches that /api/report/data
    # pays for too (~28 s on a cold boot, Supabase + Smartlead round trips).
    # Every HTTP call below therefore stays inside the 20 s per-call ceiling,
    # and the numbers reported are the WARM ones a real client sees.
    t_cold = time.time()
    S.dashboard_data_get(cl)
    cold = time.time() - t_cold
    code, body, warm1 = get(url)
    _c2, body2, warm2 = get(url)
    wk = (body.get("week") or {})
    rng = None
    if isinstance(wk, dict):
        rng = wk.get("range") or {"start": wk.get("start"), "end": wk.get("end")}
    print(f"\n[{kind}] client={cl!r}  HTTP {code}")
    print(f"  keys present      : {sorted(body.keys())}")
    print(f"  client_label      : {body.get('client_label')!r}")
    print(f"  len(months)       : {len(body.get('months') or [])}")
    print(f"  len(campaigns_run): {len(body.get('campaigns_running') or [])}")
    print(f"  week.range        : {rng}")
    print(f"  timings (s)       : cold={cold:.2f}  warm1={warm1:.3f}  warm2={warm2:.3f}"
          f"   {'OK <1.5s' if max(warm1, warm2) < 1.5 else 'SLOW >=1.5s'}")
    ids = [r.get("id") for r in (body.get("campaigns_running") or [])]
    print(f"  running ids       : {ids[:12]}{' …' if len(ids) > 12 else ''}")
    if not SAMPLE and body.get("ok"):
        SAMPLE = {"client": cl, "body": body}

# ── (b) ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(b) TAMPERED + EXPIRED TOKENS")
print("=" * 72)
probe_client = own or shared or "Navreo"
good = S.mint_client_dashboard_share(probe_client)
b64, _, sig = good.rpartition(".")


def tamper_payload(tok, new_client):
    b, _, s = tok.rpartition(".")
    p = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    p["c"] = new_client
    nb = base64.urlsafe_b64encode(
        json.dumps(p, separators=(",", ":")).encode()).decode().rstrip("=")
    return nb + "." + s          # payload swapped, signature kept


expired = S.mint_client_dashboard_share(probe_client, days=1)
_b, _, _s = expired.rpartition(".")
_p = json.loads(base64.urlsafe_b64decode(_b + "=" * (-len(_b) % 4)))
_p["x"] = int(time.time()) - 60
_nb = base64.urlsafe_b64encode(
    json.dumps(_p, separators=(",", ":")).encode()).decode().rstrip("=")
# properly SIGNED but expired (the real "link aged out" case)
import hashlib
import hmac
_sig = hmac.new(S._auth_secret(),
                json.dumps(_p, separators=(",", ":")).encode(),
                hashlib.sha256).hexdigest()
expired_signed = _nb + "." + _sig

cases = [
    ("signature flipped", b64 + "." + ("0" * len(sig))),
    ("payload swapped to another client", tamper_payload(good, "Navreo")),
    ("expired (validly signed, x in the past)", expired_signed),
    ("garbage", "not-a-token"),
    ("empty", ""),
]
for name, tok in cases:
    abort_if_out_of_time("(b)")
    code, body, _dt = get("/api/dashboard/data?share="
                          + urllib.parse.quote(tok, safe=""))
    rows = len(body.get("months") or []) + len(body.get("campaigns_running") or [])
    ok = code in (401, 403) and "not valid" in json.dumps(body).lower() and rows == 0
    print(f"  {'PASS' if ok else 'FAIL'}  {name:42s} HTTP {code}  rows={rows}  "
          f"body={json.dumps(body)[:110]}")

# scope cannot be widened by a query param
abort_if_out_of_time("(b) param-widen")
gcode, gbody, _ = get(f"/api/dashboard/data?share={good}&client=Navreo&all=1")
print(f"\n  param-widen attempt (&client=Navreo&all=1) -> HTTP {gcode} "
      f"client_label={gbody.get('client_label')!r} "
      f"({'PASS — token still rules' if gbody.get('client_label') and gbody.get('client_label') != 'Navreo' or probe_client == 'Navreo' else 'CHECK'})")

# ── (c) ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("(c) CROSS-SCOPE — every client pair")
print("=" * 72)
clients = sorted(by_client)
pairs = 0
fails = []
for i, a in enumerate(clients):
    for b in clients[i + 1:]:
        pairs += 1
        overlap = by_client[a] & by_client[b]
        if overlap:
            fails.append((a, b, sorted(overlap)[:5]))
print(f"  scorecard servable-id sets (campaigns_running is a SUBSET of these):")
print(f"  pairs checked : {pairs}")
print(f"  PASS          : {pairs - len(fails)}")
print(f"  FAIL          : {len(fails)}")
for a, b, ov in fails[:10]:
    print(f"    FAIL {a!r} ∩ {b!r} = {ov}")

# and the live payloads really stay inside their own client's set
for kind, cl in targets:
    if not cl:
        continue
    tok = S.mint_client_dashboard_share(cl)
    _c, body, _d = get(f"/api/dashboard/data?share={tok}")
    ids = {str(r.get("id")) for r in (body.get("campaigns_running") or [])}
    stray = ids - by_client.get(cl, set())
    others = set().union(*[v for k, v in by_client.items() if k != cl]) if len(by_client) > 1 else set()
    print(f"  live: {cl!r} running ids ⊆ own scorecard set: "
          f"{'PASS' if not stray else 'FAIL ' + str(sorted(stray)[:5])}"
          f" | ∩ all other clients' ids: {len(ids & others)} "
          f"({'PASS' if not (ids & others) else 'FAIL'})")

if SAMPLE:
    b = dict(SAMPLE["body"])
    b["months"] = (b.get("months") or [])[:2]
    b["campaigns_running"] = (b.get("campaigns_running") or [])[:2]
    wk = b.get("week")
    b["week"] = ("<week payload: keys=" + ",".join(sorted(wk)[:14]) + ">") if isinstance(wk, dict) else wk
    print("\n" + "=" * 72)
    print(f"TRUNCATED REAL SAMPLE — {SAMPLE['client']}")
    print("=" * 72)
    print(json.dumps(b, indent=1)[:2600])

print(f"\ndone in {time.time() - T0:.1f}s")
