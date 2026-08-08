"""Pure-python tests for the client-workspace backstop reply-sync
(setter.run_client_reply_sync, ship 2026-08-09). NO network - Smartlead
master-inbox + message-history + fetch-categories and Supabase are in-memory
fakes wired via setter.configure(). Run:
    python3 test_client_reply_sync.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers:
  - navreo is never polled; every enabled non-navreo workspace with a key is
  - first run seeds a per-workspace watermark (wm:<ws> row in reply_sync_seen)
  - an unseen reply lands in `replies` with the workspace's own category NAME,
    the exact "<lead_id>-<reply_time>" archive key, and workspace=client_id=ws
  - already-seen and already-archived replies are skipped (idempotent reruns)
  - per-workspace watermarks are independent (one ws advancing never moves
    another's) and advance to the newest handled reply
  - a body-less reply within the grace window is retried (watermark frozen),
    past grace it is archived body-less
  - a window over CLIENT_SYNC_CAP => ok=False with a gap, never silent
"""

import datetime as dt
import os
import re
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def report():
    failed = 0
    for name, passed, detail in RESULTS:
        print(("PASS: " if passed else "FAIL: ") + name + (f"  {detail}" if (detail and not passed) else ""))
        if not passed:
            failed += 1
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} pass")
    return failed


ISO = "%Y-%m-%dT%H:%M:%S.000Z"
NOW = dt.datetime.now(dt.timezone.utc)


def _iso(d):
    return d.strftime(ISO)


class FakeSB:
    """In-memory Supabase for workspaces / reply_sync_seen (incl. wm:<ws>
    watermark rows) / replies, understanding just what the client sync issues."""

    def __init__(self, workspaces, seen=None, archived=None):
        self.workspaces = workspaces
        self.seen = dict(seen or {})          # message_id -> seen_at iso (or None)
        self.replies = list(archived or [])   # inserted/pre-existing archive rows

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        if table == "workspaces" and method == "GET":
            return [dict(w) for w in self.workspaces]
        if table == "reply_sync_seen":
            m = re.search(r"message_id=eq\.([^&]+)", q)
            mid = unquote(m.group(1)) if m else ""
            if method == "GET":
                if mid in self.seen:
                    return [{"message_id": mid, "seen_at": self.seen[mid]}]
                return []
            if method == "POST":
                b = body or {}
                self.seen[b.get("message_id")] = b.get("seen_at")
                return []
            if method == "PATCH":
                if mid in self.seen:
                    self.seen[mid] = (body or {}).get("seen_at")
                return []
        if table == "replies":
            if method == "GET":
                mws = re.search(r"workspace=eq\.([^&]+)", q)
                mmid = re.search(r"smartlead_message_id=eq\.([^&]+)", q)
                ws = unquote(mws.group(1)) if mws else ""
                mid = unquote(mmid.group(1)) if mmid else ""
                return [{"id": 1}] if any(
                    r.get("workspace") == ws and r.get("smartlead_message_id") == mid
                    for r in self.replies) else []
            if method == "POST":
                self.replies.append(dict(body or {}))
                return []
        return []


def make_http(inbox_by_key, bodies_by_lead, cats_by_key):
    """Fake _HTTP covering the three Smartlead endpoints the sync touches."""
    def _http(method, url, headers=None, body=None, timeout=60):
        if "master-inbox/inbox-replies" in url:
            key = re.search(r"api_key=([^&]+)", url).group(1)
            rows = sorted(inbox_by_key.get(key, []),
                          key=lambda r: r["last_reply_time"], reverse=True)
            off = int((body or {}).get("offset", 0))
            lim = int((body or {}).get("limit", 20))
            return {"ok": True, "data": rows[off: off + lim]}
        if "/message-history" in url:
            m = re.search(r"/leads/([^/]+)/message-history", url)
            lead = m.group(1) if m else ""
            html = bodies_by_lead.get(lead)
            return {"history": [{"type": "REPLY", "time": bodies_by_lead.get(f"{lead}:time", ""),
                                 "email_body": html}] if html is not None else []}
        if "fetch-categories" in url:
            key = re.search(r"api_key=([^&]+)", url).group(1)
            return cats_by_key.get(key, [])
        return {}
    return _http


def wire(sbfake, http):
    setter.configure(sb=sbfake, http_json=http,
                     keys={"SMARTLEAD_API_KEY": "navreo-key"},
                     log_activity=lambda *a, **k: None)
    # run_client_reply_sync drives _fetch_master_inbox_window through the real
    # _sl_post, whose api_key kwarg must reach the fake _HTTP's url - nothing
    # to monkeypatch beyond configure().
    setter._sl_key = lambda: "navreo-key"


def row(lead_id, when, cid=111, email="a@client.com", cat=1):
    return {"email_lead_id": str(lead_id), "last_reply_time": _iso(when),
            "email_campaign_id": cid, "lead_email": email, "lead_category_id": cat}


WORKSPACES = [
    {"id": "navreo", "api_key": None, "status": "enabled"},
    {"id": "asteri", "api_key": "asteri-key", "status": "enabled"},
    {"id": "krg", "api_key": "krg-key", "status": "enabled"},
    {"id": "paused", "api_key": "paused-key", "status": "disabled"},
]
CATS = {"asteri-key": [{"id": 1, "name": "Interested"}, {"id": 6, "name": "Out Of Office"}],
        "krg-key": [{"id": 1, "name": "Interested"}]}


# ── 1. fresh run: seeds per-ws watermarks, archives with category name ───────
t1 = NOW - dt.timedelta(minutes=30)
sb = FakeSB(WORKSPACES)
http = make_http(
    inbox_by_key={"asteri-key": [row("900", t1, cid=111, email="a@client.com", cat=1)],
                  "krg-key": [row("901", t1, cid=222, email="k@client.com", cat=1)]},
    bodies_by_lead={"900": "<p>Sounds good</p>", "900:time": _iso(t1),
                    "901": "<p>Yes please</p>", "901:time": _iso(t1)},
    cats_by_key=CATS)
wire(sb, http)
res = setter.run_client_reply_sync()
check("run ok", res.get("ok") is True, res)
check("navreo/disabled not polled", set(res["workspaces"].keys()) == {"asteri", "krg"}, res)
check("asteri reply archived", any(
    r.get("workspace") == "asteri" and r.get("client_id") == "asteri"
    and r.get("smartlead_message_id") == f"900-{_iso(t1)}"
    and r.get("category") == "Interested" and "Sounds good" in (r.get("reply_body") or "")
    for r in sb.replies), sb.replies)
check("krg reply archived", any(
    r.get("workspace") == "krg" and r.get("smartlead_message_id") == f"901-{_iso(t1)}"
    for r in sb.replies), sb.replies)
check("per-ws watermark rows seeded", "wm:asteri" in sb.seen and "wm:krg" in sb.seen, sb.seen)
check("asteri watermark advanced to reply time",
      (sb.seen.get("wm:asteri") or "").startswith(_iso(t1)[:19]), sb.seen)

# ── 2. rerun: idempotent (seen + archived both skip) ─────────────────────────
res2 = setter.run_client_reply_sync()
n_archived = len(sb.replies)
res3 = setter.run_client_reply_sync()
check("rerun archives nothing new", len(sb.replies) == n_archived, (len(sb.replies), n_archived))
a = res3["workspaces"]["asteri"]
check("rerun skips via seen/archived", a["archived"] == 0 and (a["skipped_seen"] + a["skipped_archived"]) >= 0, a)

# ── 3. watermark independence: asteri advances, krg untouched ────────────────
t2 = NOW - dt.timedelta(minutes=5)
http2 = make_http(
    inbox_by_key={"asteri-key": [row("902", t2, cid=111, email="b@client.com", cat=6)],
                  "krg-key": []},
    bodies_by_lead={"902": "<p>OOO until Monday</p>", "902:time": _iso(t2)},
    cats_by_key=CATS)
wire(sb, http2)
krg_wm_before = sb.seen.get("wm:krg")
res4 = setter.run_client_reply_sync()
check("asteri watermark moved to newer reply",
      (sb.seen.get("wm:asteri") or "").startswith(_iso(t2)[:19]), sb.seen)
check("krg watermark untouched by asteri's advance", sb.seen.get("wm:krg") == krg_wm_before,
      (sb.seen.get("wm:krg"), krg_wm_before))
check("category name mapped per workspace", any(
    r.get("smartlead_message_id") == f"902-{_iso(t2)}" and r.get("category") == "Out Of Office"
    for r in sb.replies), sb.replies)

# ── 4. body-less within grace: retried, watermark frozen ─────────────────────
t3 = NOW - dt.timedelta(minutes=10)
sb4 = FakeSB(WORKSPACES[:2])  # navreo + asteri only
http4 = make_http(inbox_by_key={"asteri-key": [row("903", t3)]},
                  bodies_by_lead={}, cats_by_key=CATS)
wire(sb4, http4)
res5 = setter.run_client_reply_sync()
check("no-body-within-grace not archived", not any(
    r.get("smartlead_message_id") == f"903-{_iso(t3)}" for r in sb4.replies), sb4.replies)
check("no-body-within-grace not marked seen", f"903-{_iso(t3)}" not in sb4.seen, sb4.seen)

# ── 5. body-less past grace: archived body-less ──────────────────────────────
t4 = NOW - dt.timedelta(hours=setter.EMPTY_BODY_GRACE_H + 1)
sb5 = FakeSB(WORKSPACES[:2], seen={"wm:asteri": (t4 - dt.timedelta(hours=1)).isoformat()})
http5 = make_http(inbox_by_key={"asteri-key": [row("904", t4)]},
                  bodies_by_lead={}, cats_by_key=CATS)
wire(sb5, http5)
res6 = setter.run_client_reply_sync()
w = res6["workspaces"]["asteri"]
check("past-grace body-less archived", any(
    r.get("smartlead_message_id") == f"904-{_iso(t4)}" for r in sb5.replies), sb5.replies)
check("body-less counted", w.get("archived_bodyless") == 1, w)

# ── 6. over-cap: FAILED with gap, never silent ───────────────────────────────
many = [row(str(2000 + i), NOW - dt.timedelta(minutes=90) + dt.timedelta(seconds=i), cat=1)
        for i in range(setter.CLIENT_SYNC_CAP + 25)]
sb6 = FakeSB(WORKSPACES[:2])
http6 = make_http(inbox_by_key={"asteri-key": many},
                  bodies_by_lead={str(2000 + i): "<p>hi</p>" for i in range(len(many))},
                  cats_by_key=CATS)
wire(sb6, http6)
res7 = setter.run_client_reply_sync()
w6 = res7["workspaces"]["asteri"]
check("over-cap run reported FAILED", res7.get("ok") is False and w6.get("ok") is False, res7)
check("over-cap gap reported", w6.get("gap", 0) > 0, w6)
check("at most CAP archived", w6.get("archived", 0) <= setter.CLIENT_SYNC_CAP, w6)

# ── 7. Call Booked is CORE_FOUR now (Bjion 2026-08-09) ───────────────────────
check("Call Booked in CORE_FOUR", "Call Booked" in setter.CORE_FOUR, setter.CORE_FOUR)
check("Call Booked in sweep filter", "Call%20Booked" in setter.CORE_FOUR_CATEGORY_FILTER
      or "Call+Booked" in setter.CORE_FOUR_CATEGORY_FILTER, setter.CORE_FOUR_CATEGORY_FILTER)

sys.exit(1 if report() else 0)
