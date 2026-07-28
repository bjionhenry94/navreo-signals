#!/usr/bin/env python3
"""Workspace mailbox parity harness.

Runs ONE assertion battery against EVERY enabled workspace, including
'navreo'. Navreo is the control: any check navreo passes that a client
workspace fails is the bug. Re-runnable — this is the standing regression
test for every workspace added later.

Read-only. Never writes to Supabase, never writes to Smartlead, and never
calls the reply-caps apply path.

    python3 app/test_workspace_parity.py            # ingestion + keys + ledger
    python3 app/test_workspace_parity.py --live     # + live bundle/audit coverage

Exits non-zero if any check FAILs.
"""
import argparse
import base64
import collections
import datetime as dt
import hashlib
import hmac
import json
import sys
import time
import os
import urllib.request

os.environ.setdefault("NAVREO_NO_BG", "1")  # read-only harness: no background jobs

import server  # noqa: E402

LIVE = "https://navreo-signals.onrender.com"
FRESH_HOURS = 36          # a sweep older than this is a broken cron
NULL_RATE_BAND_PP = 10    # client non-null% must be within this of navreo's
STAT_DAYS = 2             # stats must exist for the last N stat dates

results = []              # (workspace, check, ok, detail)


def record(ws, check, ok, detail=""):
    results.append((ws, check, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {ws:<8} {check:<28} {detail}")


def pull(path, attempts=3):
    """Paginated GET. Returns None on failure (never a silent partial).

    Supabase read timeouts are common on the big mailbox tables, and a single
    dropped page would otherwise read as "this workspace has no mailboxes" —
    a false FAIL. Each page gets its own retries."""
    out, off = [], 0
    while True:
        page = None
        for i in range(attempts):
            page = server.sb("GET", path, headers={"Range-Unit": "items",
                                                   "Range": f"{off}-{off + 999}"})
            if isinstance(page, list):
                break
            time.sleep(2 * (i + 1))
        if not isinstance(page, list):
            return None
        out += page
        if len(page) < 1000:
            return out
        off += 1000


def mint_cookie():
    key = server.KEYS.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not key:
        return None
    secret = hashlib.sha256((key + ":navreo-session-v1").encode()).digest()
    payload = b"bjion@navreo.ai|" + str(int(time.time()) + 3600).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


def live_get(path, cookie, timeout=240):
    req = urllib.request.Request(LIVE + path,
                                 headers={"Cookie": f"navreo_session={cookie}"})
    with urllib.request.urlopen(req, timeout=timeout, context=server.SSL_CTX) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also check the live domain-manager + audit payloads")
    args = ap.parse_args()

    workspaces = [w.get("id") for w in server.ws_enabled()]
    if "navreo" not in workspaces:
        print("FATAL: 'navreo' is not enabled — no control to compare against")
        return 2
    print(f"Workspaces under test: {', '.join(workspaces)}\n")

    # ---- pull once -------------------------------------------------------
    mb = pull("mailboxes?select=workspace,domain,smartlead_id,message_per_day,"
              "warmup_enabled,warmup_status,account_type,last_synced_at")
    if mb is None:
        print("FATAL: could not read `mailboxes`")
        return 2
    since = (dt.date.today() - dt.timedelta(days=STAT_DAYS + 2)).isoformat()
    st = pull(f"mailbox_stats_daily?select=workspace,stat_date,smartlead_id,"
              f"reply_rate_pct,sent_30d&stat_date=gte.{since}")
    if st is None:
        print("FATAL: could not read `mailbox_stats_daily`")
        return 2

    by_ws = collections.defaultdict(list)
    for r in mb:
        by_ws[r.get("workspace") or "NULL"].append(r)
    stat_days = collections.defaultdict(set)
    for r in st:
        stat_days[r.get("workspace") or "NULL"].add(r.get("stat_date"))
    recent_days = sorted({r.get("stat_date") for r in st})[-STAT_DAYS:]

    def nonnull_pct(rows, col):
        return (sum(1 for r in rows if r.get(col) is not None) * 100.0 / len(rows)) if rows else 0.0

    ctrl = by_ws.get("navreo", [])
    ctrl_rates = {c: nonnull_pct(ctrl, c)
                  for c in ("message_per_day", "warmup_enabled", "warmup_status")}

    # ---- per-workspace battery ------------------------------------------
    now = dt.datetime.now(dt.timezone.utc)
    print("INGESTION + KEYS")
    for ws in workspaces:
        rows = by_ws.get(ws, [])

        record(ws, "mailbox rows present", bool(rows), f"rows={len(rows)}")
        if not rows:
            continue

        last = max((r.get("last_synced_at") or "") for r in rows)
        try:
            age_h = (now - dt.datetime.fromisoformat(last)).total_seconds() / 3600
            record(ws, f"sweep fresh (<{FRESH_HOURS}h)", age_h < FRESH_HOURS,
                   f"last_synced={last[:19]} age={age_h:.1f}h")
        except Exception:
            record(ws, f"sweep fresh (<{FRESH_HOURS}h)", False, f"unparseable last_synced_at={last!r}")

        have = stat_days.get(ws, set())
        missing = [d for d in recent_days if d not in have]
        record(ws, f"stats last {STAT_DAYS} days", not missing,
               f"have={sorted(have)[-STAT_DAYS:]} missing={missing}")

        for col, base in ctrl_rates.items():
            got = nonnull_pct(rows, col)
            record(ws, f"non-null {col}", abs(got - base) <= NULL_RATE_BAND_PP,
                   f"{got:.0f}% (navreo {base:.0f}%)")

        key = server.ws_key(ws) or ""
        if ws == "navreo":
            record(ws, "smartlead key resolves", bool(key), f"len={len(key)}")
        else:
            record(ws, "smartlead key resolves", bool(key), f"len={len(key)}")
            record(ws, "key distinct from navreo",
                   bool(key) and key != (server.ws_key("navreo") or ""),
                   "own workspace key" if key != (server.ws_key("navreo") or "")
                   else "SHARES navreo's key — writes would hit the wrong account")

    # ---- resting ledger workspace dimension ------------------------------
    print("\nSHARED STATE")
    led = server.sb("GET", "deliverability_resting_ledger?select=*&limit=1")
    has_ws_col = bool(led) and "workspace" in (led[0] or {})
    record("(all)", "resting ledger scoped", has_ws_col,
           "has workspace column" if has_ws_col
           else "domain-keyed only — rest state is GLOBAL across workspaces")

    # ---- live payload coverage -------------------------------------------
    if args.live:
        print("\nLIVE PAYLOAD COVERAGE")
        cookie = mint_cookie()
        if not cookie:
            record("(all)", "live session", False, "cannot mint cookie")
        else:
            doms = collections.defaultdict(set)
            for r in mb:
                if r.get("domain"):
                    doms[r.get("workspace") or "NULL"].add(r["domain"])
            for ep, label in (("_bundle", "domain manager"), ("_audit", "domain audit")):
                try:
                    status, body = live_get(f"/api/deliverability/{ep}", cookie)
                except Exception as e:
                    record("(all)", f"{label} reachable", False, f"{e!r}"[:80])
                    continue
                if status != 200:
                    record("(all)", f"{label} reachable", False, f"HTTP {status}")
                    continue
                for ws in workspaces:
                    want = doms.get(ws, set())
                    hit = sum(1 for d in want if d in body)
                    record(ws, f"{label} coverage", want and hit == len(want),
                           f"{hit}/{len(want)} domains present")
                record("(all)", f"{label} labels workspace", '"workspace"' in body,
                       "workspace field present" if '"workspace"' in body
                       else "no workspace field — client rows are unattributable in the UI")

    # ---- summary ----------------------------------------------------------
    fails = [r for r in results if not r[2]]
    print("\n" + "=" * 72)
    print(f"{len(results) - len(fails)} passed, {len(fails)} failed")
    if fails:
        print("\nFAILURES")
        for ws, check, _, detail in fails:
            print(f"  {ws:<8} {check:<28} {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
