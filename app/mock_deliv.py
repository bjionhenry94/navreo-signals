"""In-memory fake mailbox fleet for DELIV_MOCK=1 end-to-end testing.

Lets the deliverability tab's three flaky flows (Fix signatures, Process new
mailboxes, Enable warmup) be exercised end-to-end with ZERO real network
calls to Smartlead or the external audit backend. Only ever imported/used
when os.environ.get("DELIV_MOCK") == "1" — server.py gates every call site
with that check (see the "# DELIV_MOCK" markers in app/server.py) so this
module has no effect whatsoever in prod.

Fleet shape (~40 mailboxes, 3 brands / 6 fake domains) is engineered so the
counts a fresh run_audit_blob() reports match a realistic dashboard:
  9  missing signature        (indices 0-8)
  5  signature mismatch       (indices 9-13)
  9  new/untagged             (indices 0-3, 14-18 — mixed tagged/inCampaign)
  14 warmup off               (indices 14-15, 19-30)
  8  warmup wrong-settings    (indices 31-38)
  1  fully healthy            (index 39)
Categories overlap on purpose (a brand-new mailbox commonly also lacks a
signature and hasn't started warming) — that overlap is realistic, not a bug.
"""

import base64
import threading
import time
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

_LOCK = threading.Lock()

# ── static fake rosters ──────────────────────────────────────────────────
DOMAINS = [
    "acme-mock-1.test", "acme-mock-2.test",
    "arnic-mock-1.test", "arnic-mock-2.test",
    "amplifyy-mock-1.test", "amplifyy-mock-2.test",
]
_BRAND_OF_DOMAIN = {
    "acme-mock-1.test": "navreo", "acme-mock-2.test": "navreo",
    "arnic-mock-1.test": "arnic", "arnic-mock-2.test": "arnic",
    "amplifyy-mock-1.test": "amplifyy", "amplifyy-mock-2.test": "amplifyy",
}
_BATCH_LABEL = {"navreo": "Navreo Mock", "arnic": "Arnic Mock", "amplifyy": "Amplifyy Mock"}
_NAMES = {
    "navreo": ["Bjion Henry", "Asad Rafique"],
    "arnic": ["Jacki Arnic", "Yasir Khan"],
    "amplifyy": ["Kevin Dormer", "Priya Patel"],
}
_WARMUP_ISSUES = [
    "reply-rate threshold too low (12%)",
    "per-day cap set to 60 (fleet standard is 35)",
    "ramp-up disabled",
]

FAKE_CAMPAIGNS = [
    {"id": 9001001, "name": "Navreo Mock - Campaign A"},
    {"id": 9001002, "name": "Navreo Mock - Campaign B"},
    {"id": 9001003, "name": "Arnic Mock - Campaign A"},
    {"id": 9001004, "name": "Amplifyy Mock - Campaign A"},
]
_CAMPAIGN_IDS = [c["id"] for c in FAKE_CAMPAIGNS]

_BASE_TAGS = [
    {"id": 1, "name": "Navreo Mock"},
    {"id": 2, "name": "Arnic Mock"},
    {"id": 3, "name": "Amplifyy Mock"},
]
_BRAND_TAG_ID = {"navreo": 1, "arnic": 2, "amplifyy": 3}

_DEFAULT_SCENARIO = {
    "stale_snapshot": False,   # fix-signatures/fix-warmup answer run_first until a fresh audit lands
    "rate429_next": 0,         # next N Smartlead calls raise 429 (Retry-After: 1)
    "fail_emails": [],         # addresses whose writes land in fails[]
    "slow_ms": 0,              # artificial per-call latency
    "audit_run_secs": 3,       # simulated /run duration
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def _pristine_fleet() -> dict:
    sig_missing = set(range(0, 9))     # 9
    sig_mismatch = set(range(9, 14))   # 5
    new_extra = set(range(14, 19))     # 5
    new_idx = set(range(0, 4)) | new_extra                      # 9
    warmup_off = {14, 15} | set(range(19, 31))                  # 14
    warmup_wrong = set(range(31, 39))                           # 8

    fleet = {}
    for i in range(40):
        domain = DOMAINS[i % 6]
        brand = _BRAND_OF_DOMAIN[domain]
        from_name = _NAMES[brand][(i // 6) % 2]
        email = f"user{i:02d}@{domain}"
        is_new = i in new_idx

        sig_state = "missing" if i in sig_missing else ("mismatch" if i in sig_mismatch else "ok")
        sig_issue = None
        if sig_state == "mismatch":
            short = from_name.split()[0][0] + ". " + from_name.split()[-1]
            sig_issue = f"signature says '{short}' — mismatched from_name"

        warmup_state = "off" if i in warmup_off else ("wrong" if i in warmup_wrong else "ok")
        warmup_issue = _WARMUP_ISSUES[i % len(_WARMUP_ISSUES)] if warmup_state == "wrong" else None
        cap = {31: 60, 32: 60, 33: 5, 34: 55, 35: 60, 36: 5, 37: 55, 38: 60}.get(i, 35)

        if is_new:
            tagged = [False, True, False][i % 3]
            in_campaign = [False, False, True][i % 3]
            created = _days_ago(1 + (i % 5))
        else:
            tagged = True
            in_campaign = True
            created = _days_ago(10 + (i % 20))

        campaign_id = _CAMPAIGN_IDS[i % len(_CAMPAIGN_IDS)] if in_campaign else None
        tag_ids = {_BRAND_TAG_ID[brand]} if tagged else set()

        fleet[email] = {
            "email": email, "domain": domain, "brand": brand,
            "batch": _BATCH_LABEL[brand], "from_name": from_name,
            "created": created, "tagged": tagged, "inCampaign": in_campaign,
            "campaign_id": campaign_id,
            "sig_state": sig_state, "sig_issue": sig_issue,
            "warmup_state": warmup_state, "warmup_issue": warmup_issue, "cap": cap,
            "email_account_id": 1000 + i, "tag_ids": tag_ids,
        }
    return fleet


def _pristine_state() -> dict:
    return {
        "fleet": _pristine_fleet(),
        "scenario": dict(_DEFAULT_SCENARIO),
        "tags": [dict(t) for t in _BASE_TAGS],
        "next_tag_id": 4,
        "stale": False,       # internal: set True by stale_snapshot scenario, cleared by a fresh audit run
        "reminders": [
            {"id": "mock-r1", "domains": ["acme-mock-1.test"], "note": "", "restoredDate": _days_ago(8),
             "dueDate": _days_ago(-6), "done": False, "ts": int(time.time() * 1000) - 8 * 86400000},
            {"id": "mock-r2", "domains": ["arnic-mock-2.test", "amplifyy-mock-1.test"], "note": "batch restore",
             "restoredDate": _days_ago(3), "dueDate": _days_ago(-11), "done": False,
             "ts": int(time.time() * 1000) - 3 * 86400000},
        ],
        "next_reminder_id": 3,
        "history": [],
    }


_STATE = _pristine_state()


def _get(): return _STATE


def scenario_get(key: str, default=None):
    """Public accessor for a single scenario value — used by server.py's
    DELIV_MOCK hooks so they don't reach into module-private state directly."""
    with _LOCK:
        return _STATE["scenario"].get(key, default)


# ── control API: reset / set-scenario / get-state ───────────────────────

def control(action: str, payload: dict) -> dict:
    with _LOCK:
        if action == "reset":
            _STATE.clear()
            _STATE.update(_pristine_state())
        elif action == "set-scenario":
            if payload.get("reset"):
                _STATE.clear()
                _STATE.update(_pristine_state())
            else:
                for k in ("stale_snapshot", "rate429_next", "fail_emails", "slow_ms", "audit_run_secs"):
                    if k in payload:
                        _STATE["scenario"][k] = payload[k]
                if payload.get("stale_snapshot") is True:
                    _STATE["stale"] = True
                elif payload.get("stale_snapshot") is False:
                    _STATE["stale"] = False
        return _state_snapshot()


def _state_snapshot() -> dict:
    f = _STATE["fleet"]
    counts = {
        "total": len(f),
        "sig_missing": sum(1 for r in f.values() if r["sig_state"] == "missing"),
        "sig_mismatch": sum(1 for r in f.values() if r["sig_state"] == "mismatch"),
        "new_untagged": sum(1 for r in f.values() if r["created"] and (not r["tagged"] or not r["inCampaign"])
                            and _is_new_row(r)),
        "warmup_off": sum(1 for r in f.values() if r["warmup_state"] == "off"),
        "warmup_wrong": sum(1 for r in f.values() if r["warmup_state"] == "wrong"),
        "healthy": sum(1 for r in f.values() if r["sig_state"] == "ok" and r["warmup_state"] == "ok"
                       and r["tagged"] and r["inCampaign"]),
    }
    return {
        "scenario": dict(_STATE["scenario"]), "stale": _STATE["stale"],
        "fleet_counts": counts, "tags": list(_STATE["tags"]),
        "campaigns": list(FAKE_CAMPAIGNS),
    }


def _is_new_row(r) -> bool:
    # newUnprocessed in the real system = created recently AND not fully
    # processed; the pristine builder's `new_idx` rows are exactly the ones
    # with a short `created` age, so re-derive the same set from state here.
    try:
        days = (datetime.now(timezone.utc) - datetime.strptime(r["created"], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
    except Exception:
        return False
    return days <= 5 and (not r["tagged"] or not r["inCampaign"])


# ── query-string helpers (mirror the JS side's b64u()) ──────────────────

def _b64u_decode(s: str) -> str:
    if not s:
        return ""
    pad = "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s + pad).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse(rest: str):
    path, _, qs = rest.partition("?")
    q = urllib.parse.parse_qs(qs, keep_blank_values=True)
    return path, {k: v[0] for k, v in q.items()}


def _sleep_if_slow():
    ms = _STATE["scenario"].get("slow_ms") or 0
    if ms:
        time.sleep(ms / 1000.0)


# ── audit-backend endpoints (via /api/deliverability/<rest>) ────────────

def handle_proxy(method: str, rest: str, body: bytes | None):
    """rest = self.path[len('/api/deliverability/'):], INCLUDING query string.
    Returns (status, json_obj)."""
    _sleep_if_slow()
    path, q = _parse(rest)
    payload = {}
    if body:
        import json
        try:
            payload = json.loads(body.decode() or "{}")
        except Exception:
            payload = {}

    with _LOCK:
        if path == "campaigns":
            return 200, list(FAKE_CAMPAIGNS)
        if path == "reminders":
            return 200, list(_STATE["reminders"])
        if path == "fix-signatures" and method == "POST":
            return _fix_signatures(q)
        if path == "fix-warmup" and method == "POST":
            return _fix_warmup(q)
        if path == "inboxes" and method == "GET":
            return _inboxes(q)
        if path == "domain-health" and method == "GET":
            return _domain_health(q)
        if path == "reply-caps" and method == "POST":
            mode = q.get("mode")
            if mode == "preview":
                return 200, {"tiers": [], "rows": [], "count": 0}
            return 200, {"ok": True, "applied": 0}
        if path == "ack" and method == "POST":
            return 200, {"ok": True}
        if path == "pause-blacklisted" and method == "POST":
            return 200, {"paused": 0}
        if path == "reactivate-blacklisted" and method == "POST":
            return 200, {"reactivated": 0}
        if path == "delisting" and method == "POST":
            return 200, {"ok": True}
        if path == "reminder" and method == "POST":
            return _reminder_add(q)
        if path == "reminder-done" and method == "POST":
            return 200, {"ok": True}
        if path == "reminder-enable-warmup" and method == "POST":
            return 200, {"ok": 0, "failed": 0}
        if path == "notion-sync" and method == "POST":
            return 200, {"ok": True, "count": 0}
        if path == "slack" and method == "POST":
            return 200, {"ok": True}
        if path == "mailboxes" and method == "GET":
            return _inboxes(q)
        # Anything else the tab might probe: benign empty stub, never an error.
        return 200, {"ok": True}


def _fix_signatures(q: dict):
    tpl = _b64u_decode(q.get("tpl", ""))
    batch = _b64u_decode(q.get("batch", ""))
    filt = _b64u_decode(q.get("filter", ""))
    if _STATE["stale"]:
        return 200, {"ok": False, "reason": "run_first"}
    if not tpl.strip():
        return 200, {"ok": False, "reason": "empty_template"}
    fail_set = set(_STATE["scenario"].get("fail_emails") or [])
    targets = [r for r in _STATE["fleet"].values() if r["sig_state"] in ("missing", "mismatch")]
    if batch:
        targets = [r for r in targets if r["brand"] == batch]
    if filt:
        fl = filt.lower()
        targets = [r for r in targets if fl in r["email"].lower()]
    ok, failed, fails = 0, 0, []
    for r in targets:
        if r["email"] in fail_set:
            failed += 1
            fails.append({"email": r["email"], "error": "mailbox write rejected (mock)"})
            continue
        r["sig_state"] = "ok"
        r["sig_issue"] = None
        ok += 1
    return 200, {"attempted": len(targets), "ok": ok, "failed": failed, "fails": fails}


def _fix_warmup(q: dict):
    per_day = q.get("perDay")
    filt = _b64u_decode(q.get("filter", ""))
    if _STATE["stale"]:
        return 200, {"ok": False, "reason": "run_first"}
    fail_set = set(_STATE["scenario"].get("fail_emails") or [])
    # Both broken groups: "off" gets enabled, "wrong" gets its settings
    # rewritten — the UI sends both through the same fix-warmup call.
    targets = [r for r in _STATE["fleet"].values() if r["warmup_state"] in ("off", "wrong")]
    if filt:
        fl = filt.lower()
        targets = [r for r in targets if fl in r["email"].lower()]
    ok, failed, fails = 0, 0, []
    try:
        cap = int(float(per_day)) if per_day else 35
    except (TypeError, ValueError):
        cap = 35
    for r in targets:
        if r["email"] in fail_set:
            failed += 1
            fails.append({"email": r["email"], "error": "warmup enable rejected (mock)"})
            continue
        r["warmup_state"] = "ok"
        r["cap"] = cap
        ok += 1
    return 200, {"attempted": len(targets), "ok": ok, "failed": failed, "fails": fails}


def _inboxes(q: dict):
    view = q.get("view") or "all"
    batch = q.get("batch") or ""
    rows = list(_STATE["fleet"].values())
    if batch:
        rows = [r for r in rows if r["brand"] == batch]

    def kind_of(r):
        if r["warmup_state"] == "off":
            return "warmupoff"
        if r["warmup_state"] == "wrong":
            return "sending"
        return "ok" if r["sig_state"] == "ok" else "sending"

    if view != "all" and view != "domain":
        rows = [r for r in rows if kind_of(r) == view]
    out_rows = [{
        "email": r["email"], "domain": r["domain"], "provider": "mock",
        "kind": kind_of(r), "warmup_status": "ACTIVE" if r["warmup_state"] != "off" else "INACTIVE",
        "reason_category": r["warmup_issue"] or "", "cap": r["cap"], "reason": r["sig_issue"] or r["warmup_issue"] or "",
    } for r in rows]
    counts = {
        "reconnect": 0, "warmupoff": sum(1 for r in _STATE["fleet"].values() if r["warmup_state"] == "off"),
        "blocked": 0, "inwarmup": 0, "rested": 0,
        "sending": sum(1 for r in _STATE["fleet"].values() if r["warmup_state"] != "off"),
        "total": len(_STATE["fleet"]),
    }
    return 200, {"rows": out_rows, "counts": counts, "batches": list(_BATCH_LABEL.values()),
                "total": len(out_rows), "truncated": False}


def _domain_health(q: dict):
    rows = []
    for d in DOMAINS:
        dr = [r for r in _STATE["fleet"].values() if r["domain"] == d]
        sent = len(dr) * 120
        replied = max(1, len(dr) // 4)
        rows.append({
            "domain": d, "sent": sent, "lead": sent, "replied": replied,
            "reply_rate": round(100.0 * replied / max(sent, 1), 2), "positive": max(0, replied // 3),
            "bounce_rate": 1.5,
        })
    return 200, {"rows": rows, "resting": {}, "restingDue": {},
                "start": q.get("start") or _days_ago(7), "end": q.get("end") or _today(),
                "minSent": int(q.get("minSent") or 500), "cutoff": float(q.get("cutoff") or 0.8)}


def _reminder_add(q: dict):
    domains = _b64u_decode(q.get("domains", ""))
    date = q.get("date") or _today()
    doms = [d for d in domains.replace(";", ",").replace(" ", ",").split(",") if d]
    rid = f"mock-r{_STATE['next_reminder_id']}"
    _STATE["next_reminder_id"] += 1
    row = {"id": rid, "domains": doms, "note": "", "restoredDate": date,
           "dueDate": (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=14)).strftime("%Y-%m-%d")
           if _valid_date(date) else _today(),
           "done": False, "ts": int(time.time() * 1000)}
    _STATE["reminders"].insert(0, row)
    return 200, {"ok": True, "reminders": list(_STATE["reminders"])}


def _valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


# ── /run audit blob (mirrors app/deliverability-tab.js mapRunBlob()'s keep-list) ─

def run_audit_blob() -> dict:
    with _LOCK:
        f = _STATE["fleet"]
        _STATE["stale"] = False
        _STATE["scenario"]["stale_snapshot"] = False

        missing = [{"email": r["email"], "domain": r["domain"], "batch": r["batch"], "from_name": r["from_name"],
                    "created": r["created"]} for r in f.values() if r["sig_state"] == "missing"]
        mismatch = [{"email": r["email"], "domain": r["domain"], "batch": r["batch"], "from_name": r["from_name"],
                     "issue": r["sig_issue"], "created": r["created"]} for r in f.values() if r["sig_state"] == "mismatch"]
        not_warming = [{"email": r["email"], "domain": r["domain"], "batch": r["batch"], "created": r["created"]}
                       for r in f.values() if r["warmup_state"] == "off"]
        wrong_settings = [{"email": r["email"], "domain": r["domain"], "issue": r["warmup_issue"]}
                          for r in f.values() if r["warmup_state"] == "wrong"]
        new_unprocessed = [{"email": r["email"], "domain": r["domain"], "tagged": r["tagged"],
                            "inCampaign": r["inCampaign"], "created": r["created"]}
                          for r in f.values() if _is_new_row(r)]

        batch_stats = []
        for brand, label in _BATCH_LABEL.items():
            rows = [r for r in f.values() if r["brand"] == brand]
            batch_stats.append({
                "batch": label, "mailboxes": len(rows),
                "domains": len({r["domain"] for r in rows}),
                "sending": sum(1 for r in rows if r["warmup_state"] != "off"),
                "warmup": sum(1 for r in rows if r["warmup_state"] == "off"),
                "dead": 0, "blocked": 0, "blacklisted": 0,
                "sent": len(rows) * 120, "reply_rate": 1.1, "bounce_rate": 1.4, "positive_rate": 0.25,
            })

        blob = {
            "date": _today(),
            "inboxes": len(f), "domains": len(DOMAINS),
            "active": sum(1 for r in f.values() if r["warmup_state"] != "off"),
            "sent": len(f) * 120, "reply_pct": 1.1, "bounce_pct": 1.4,
            "replyTrend": {"wkRate": 1.1, "prevRate": 1.1, "drop": False},
            "campLow": 0, "highb": 0, "blacklistCleared": 0,
            "spfMiss": 0, "dkimMiss": 0, "dmarcMiss": 0, "noNS": 0,
            "quarantine": 0, "reject": 0, "none": 0, "smtp": 0, "imap": 0,
            "inactive": 0, "warmupResting": 0, "warmupDue": 0,
            "lifecycle": {"newUnprocessed": new_unprocessed, "untagged": [], "retired": []},
            "warmupConfig": {"notWarming": not_warming, "wrongSettings": wrong_settings, "standard": "38/35"},
            "signature": {"missing": missing, "mismatch": mismatch},
            "sendingDeviation": {"over": [], "under": []},
            "batchStats": batch_stats,
            "history": list(_STATE["history"]),
            "acks": [], "delisting": [],
            "reminders": list(_STATE["reminders"]),
            "domainHealth": _domain_health({})[1],
            "sigTemplates": {"navreo": "Best,\n{{name}}\nNavreo Growth Team",
                             "arnic": "Cheers,\n{{name}}\nArnic",
                             "amplifyy": "Thanks,\n{{name}}\nAmplifyy Team",
                             "_all": "Best,\n{{name}}"},
            "blocked": 0, "blockedReal": 0, "blockedSoft": 0, "reasons": {},
            "blacklist": [], "highbCamps": [],
        }
        return blob


# ── fake Smartlead endpoints (used by _smartlead_json call sites) ───────

def _maybe_429():
    n = _STATE["scenario"].get("rate429_next") or 0
    if n > 0:
        _STATE["scenario"]["rate429_next"] = n - 1
        raise urllib.error.HTTPError("mock://smartlead", 429, "Too Many Requests",
                                     {"Retry-After": "1"}, None)


def smartlead(method: str, path: str, body: dict | None):
    """Faithful-enough fake of the Smartlead endpoints api_process_new_selected
    and /api/mailbox-tag-names use. Raises urllib.error.HTTPError for injected
    429s/404s so callers' real retry/backoff logic is genuinely exercised."""
    _sleep_if_slow()
    with _LOCK:
        _maybe_429()
        f = _STATE["fleet"]
        body = body or {}

        if path == "/email-accounts/tag-list" and method == "POST":
            ids = body.get("email_ids") or []
            data = [{"email_id": e, "email_account_id": f[e]["email_account_id"]}
                    for e in ids if e in f]
            return {"data": data}

        if path == "/email-accounts/tags" and method == "GET":
            return list(_STATE["tags"])

        if path == "/tags" and method == "POST":
            name = (body.get("name") or "").strip()
            existing = next((t for t in _STATE["tags"] if t["name"].lower() == name.lower()), None)
            if existing:
                return {"data": existing}
            new_id = _STATE["next_tag_id"]
            _STATE["next_tag_id"] += 1
            tag = {"id": new_id, "name": name}
            _STATE["tags"].append(tag)
            return {"data": tag}

        if path == "/email-accounts/tag-mapping" and method == "POST":
            acct_ids = body.get("email_account_ids") or []
            tag_ids = body.get("tag_ids") or []
            assert len(acct_ids) <= 25, "tag-mapping must chunk to <=25 accounts/call"
            by_acct = {r["email_account_id"]: r for r in f.values()}
            for aid in acct_ids:
                r = by_acct.get(aid)
                if r:
                    r["tag_ids"] |= set(tag_ids)
                    r["tagged"] = True
            return {"ok": True}

        if path.startswith("/campaigns/") and path.endswith("/email-accounts") and method == "POST":
            try:
                cid = int(path.split("/")[2])
            except (IndexError, ValueError):
                cid = None
            if cid not in _CAMPAIGN_IDS:
                raise urllib.error.HTTPError(f"mock://smartlead{path}", 404, "campaign not found", {}, None)
            acct_ids = body.get("email_account_ids") or []
            by_acct = {r["email_account_id"]: r for r in f.values()}
            for aid in acct_ids:
                r = by_acct.get(aid)
                if r:
                    r["inCampaign"] = True
                    r["campaign_id"] = cid
            return {"ok": True}

        return {}
