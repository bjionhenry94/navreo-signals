"""Pure-python tests for the ever-positive alert sweep
(setter.run_ever_positive_alerts). NO network: Supabase, the Make alert hook
and Smartlead are in-memory fakes monkeypatched onto setter's module globals.
Run:
    python3 test_ever_positive.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers the loop's Goal scenarios:
  1. previously-positive -> negative reply alerts exactly once, and the row is
     stamped 'ever-positive-alerted' only AFTER the hook accepted
  2. previously-positive -> positive reply never alerts from this sweep
     (module 33 / routeB own that class) and is stamped 'positive-covered'
  3. never-positive -> negative stays silent, stamped 'no-positive-history'
  4. the same row delivered twice alerts once (marker holds across runs)
  plus: a hook failure leaves the row unstamped and a later run retries it;
  positive history in ANOTHER workspace does not trigger; a fresh
  null-category row is deferred inside the grace window while a stale one
  alerts as "uncategorised"; the per-tick post cap trips loudly.
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


NOW = dt.datetime.now(dt.timezone.utc)


def _iso(hours_ago=0.0, minutes_ago=0.0):
    return (NOW - dt.timedelta(hours=hours_ago, minutes=minutes_ago)).isoformat()


class FakeSB:
    """In-memory Supabase understanding just the queries the sweep issues."""

    def __init__(self, replies, campaigns=None):
        self.replies = [dict(r) for r in replies]
        self.campaigns = campaigns or []
        self.patches = []

    def _row(self, rid):
        for r in self.replies:
            if r["id"] == rid:
                return r
        return None

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        params = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
        if table == "replies" and method == "GET":
            rows = [dict(r) for r in self.replies]
            if params.get("notify_alerted_at") == "is.null":
                rows = [r for r in rows if not r.get("notify_alerted_at")]
            ws = params.get("workspace", "")
            if ws.startswith("in.("):
                allowed = ws[4:-1].split(",")
                rows = [r for r in rows if r.get("workspace") in allowed]
            elif ws.startswith("eq."):
                rows = [r for r in rows if r.get("workspace") == ws[3:]]
            if params.get("email", "").startswith("ilike."):
                em = unquote(params["email"][6:])
                rows = [r for r in rows if (r.get("email") or "").lower() == em.lower()]
            if params.get("category", "").startswith("in.("):
                cats = [unquote(c) for c in params["category"][4:-1].split(",")]
                rows = [r for r in rows if r.get("category") in cats]
            ra = params.get("replied_at", "")
            if ra.startswith("gte."):
                rows = [r for r in rows if (r.get("replied_at") or "") >= unquote(ra[4:])]
            elif ra.startswith("lt."):
                rows = [r for r in rows if (r.get("replied_at") or "") < unquote(ra[3:])]
            rows.sort(key=lambda r: r.get("replied_at") or "",
                      reverse=params.get("order", "").endswith("desc"))
            if params.get("limit"):
                rows = rows[:int(params["limit"])]
            return rows
        if table == "replies" and method == "PATCH":
            m = re.search(r"id=eq\.(\d+)", q)
            rid = int(m.group(1)) if m else None
            row = self._row(rid)
            if row is not None:
                row.update(body or {})
            self.patches.append((rid, dict(body or {})))
            return []
        if table == "campaigns" and method == "GET":
            return [dict(c) for c in self.campaigns]
        return []


class FakeHTTP:
    def __init__(self, fail=False):
        self.fail = fail
        self.posts = []

    def __call__(self, method, url, headers=None, body=None):
        if self.fail:
            raise OSError("hook down")
        self.posts.append((url, body))
        raise ValueError("Accepted")   # Make answers a non-JSON 2xx


def wire(sb, http):
    setter._SB = sb
    setter._HTTP = http
    setter._KEYS = {}          # no Smartlead key -> _sl_get returns None (link skipped)


NEG_ROW = {"id": 10, "workspace": "navreo", "smartlead_campaign_id": 222,
           "email": "lead@acme.com", "replied_at": _iso(hours_ago=1),
           "category": "Not Interested", "reply_body": "no thanks, but thanks",
           "notify_alerted_at": None}
POS_HISTORY = {"id": 1, "workspace": "navreo", "smartlead_campaign_id": 111,
               "email": "lead@acme.com", "replied_at": _iso(hours_ago=30),
               "category": "Information Request", "reply_body": "send me info",
               "notify_alerted_at": "2026-01-01T00:00:00+00:00"}


def test_prev_positive_negative_alerts_once():
    sb = FakeSB([dict(POS_HISTORY), dict(NEG_ROW)],
                campaigns=[{"smartlead_campaign_id": 222, "name": "Interested Reply"},
                           {"smartlead_campaign_id": 111, "name": "Parent Campaign"}])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_ever_positive_alerts()
    check("1a prev-pos->neg posts exactly one alert", len(http.posts) == 1, str(res))
    check("1b alert went to the ever-positive hook",
          http.posts and http.posts[0][0] == setter.EVER_POSITIVE_HOOK)
    body = (http.posts[0][1] or {}) if http.posts else {}
    check("1c payload is EVER_POSITIVE_ALERT", body.get("event_type") == "EVER_POSITIVE_ALERT")
    txt = body.get("text") or ""
    check("1d text names the new category", "Not Interested" in txt)
    check("1e text names the original positive",
          "Information Request" in txt and "Parent Campaign" in txt)
    check("1f subsequence campaign labelled", "Interested Reply (subsequence)" in txt)
    row = sb._row(10)
    check("1g row stamped ever-positive-alerted",
          row.get("notify_kind") == "ever-positive-alerted" and row.get("notify_alerted_at"))
    check("1h summary counts it", res.get("alerted") == 1 and res.get("ok") is True)


def test_prev_positive_positive_covered_elsewhere():
    pos_new = dict(NEG_ROW, id=11, category="Meeting Request")
    sb = FakeSB([dict(POS_HISTORY), pos_new])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_ever_positive_alerts()
    check("2a prev-pos->pos posts nothing", len(http.posts) == 0, str(res))
    check("2b row stamped positive-covered",
          sb._row(11).get("notify_kind") == "positive-covered")


def test_never_positive_stays_silent():
    sb = FakeSB([dict(NEG_ROW, id=12, email="fresh@nowhere.com")])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_ever_positive_alerts()
    check("3a never-pos->neg posts nothing", len(http.posts) == 0, str(res))
    check("3b row stamped no-positive-history",
          sb._row(12).get("notify_kind") == "no-positive-history")


def test_marker_holds_across_runs():
    sb = FakeSB([dict(POS_HISTORY), dict(NEG_ROW)])
    http = FakeHTTP()
    wire(sb, http)
    setter.run_ever_positive_alerts()
    setter.run_ever_positive_alerts()
    check("4 same row across two runs alerts once", len(http.posts) == 1)


def test_hook_failure_is_retried():
    sb = FakeSB([dict(POS_HISTORY), dict(NEG_ROW)])
    http = FakeHTTP(fail=True)
    wire(sb, http)
    res1 = setter.run_ever_positive_alerts()
    check("5a hook-down run reports failure",
          res1.get("failed_posts") == 1 and res1.get("ok") is False)
    check("5b row NOT stamped on failure", not sb._row(10).get("notify_alerted_at"))
    http.fail = False
    res2 = setter.run_ever_positive_alerts()
    check("5c next run retries and posts", len(http.posts) == 1 and res2.get("alerted") == 1)
    check("5d row stamped after success",
          sb._row(10).get("notify_kind") == "ever-positive-alerted")


def test_workspace_scoping():
    other_ws_pos = dict(POS_HISTORY, id=2, workspace="opan-test")
    sb = FakeSB([other_ws_pos, dict(NEG_ROW, id=13)])
    http = FakeHTTP()
    wire(sb, http)
    setter.run_ever_positive_alerts()
    check("6 positive history in another workspace does not trigger",
          len(http.posts) == 0 and sb._row(13).get("notify_kind") == "no-positive-history")


def test_null_category_grace_and_stale():
    fresh_null = dict(NEG_ROW, id=14, category=None,
                      replied_at=_iso(minutes_ago=10))
    stale_null = dict(NEG_ROW, id=15, category=None,
                      replied_at=_iso(minutes_ago=90))
    sb = FakeSB([dict(POS_HISTORY), fresh_null, stale_null])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_ever_positive_alerts()
    check("7a fresh null deferred, not stamped",
          res.get("deferred_null") == 1 and not sb._row(14).get("notify_alerted_at"))
    check("7b stale null alerts as uncategorised",
          len(http.posts) == 1 and "uncategorised" in (http.posts[0][1].get("text") or ""))
    check("7c stale null stamped", sb._row(15).get("notify_kind") == "ever-positive-alerted")


def test_post_cap_trips_loudly():
    rows = [dict(POS_HISTORY)]
    for i in range(12):
        rows.append(dict(NEG_ROW, id=100 + i,
                         replied_at=_iso(hours_ago=1, minutes_ago=i)))
    sb = FakeSB(rows)
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_ever_positive_alerts()
    check("8a cap posts exactly EP_POST_CAP", len(http.posts) == setter.EP_POST_CAP, str(res))
    check("8b capped reported loudly", res.get("capped") is True and res.get("ok") is False)
    unstamped = [r for r in sb.replies if not r.get("notify_alerted_at")]
    check("8c leftovers left unstamped for next tick", len(unstamped) == 2)


def test_no_supabase_skips():
    setter._SB = None
    setter._HTTP = FakeHTTP()
    res = setter.run_ever_positive_alerts()
    check("9 no Supabase -> skipped, no crash", res.get("skipped") is True)


if __name__ == "__main__":
    test_prev_positive_negative_alerts_once()
    test_prev_positive_positive_covered_elsewhere()
    test_never_positive_stays_silent()
    test_marker_holds_across_runs()
    test_hook_failure_is_retried()
    test_workspace_scoping()
    test_null_category_grace_and_stale()
    test_post_cap_trips_loudly()
    test_no_supabase_skips()
    sys.exit(1 if report() else 0)
