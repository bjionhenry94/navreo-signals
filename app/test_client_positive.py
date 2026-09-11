"""Pure-python tests for the client-workspace positive alert sweep
(setter.run_client_positive_alerts). NO network: Supabase, the Make alert hook
and Smartlead are in-memory fakes monkeypatched onto setter's module globals.
Run:
    python3 test_client_positive.py
Prints PASS/FAIL per case, exits 1 on any failure.

The sweep is the in-tool internal backstop for a NEW positive reply on a
NON-navreo (client) workspace — the ping navreo has via the Make categoriser
and clients lacked (the grout / sagar@eazybe.com "how much do u charge?" miss,
2026-08-05). It reads the workspace-complement of run_ever_positive_alerts, so
the two sweeps are disjoint and never double-fire.

Covers:
  1. a client positive (grout / Information Request) alerts exactly once,
     stamped 'client-positive-alerted' only AFTER the hook accepted, to the
     ever-positive hook, text naming workspace + category + campaign
  2. a navreo positive is NEVER touched here (that's the categoriser's job)
  3. an opan-test positive is NEVER touched (mock-isolation workspace)
  4. a client NEGATIVE stays silent (funnel not widened)
  5. the same row across two runs alerts once (marker holds)
  6. a hook failure leaves the row unstamped and a later run retries it
  7. a client positive older than the lookback window is not selected
  8. the per-tick post cap trips loudly and leaves leftovers for next tick
  9. no Supabase -> skipped, no crash
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
    """In-memory Supabase understanding just the queries this sweep issues —
    including workspace=not.in.(...), the complement ever-positive never uses."""

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
            if ws.startswith("not.in.("):
                blocked = ws[8:-1].split(",")
                rows = [r for r in rows if r.get("workspace") not in blocked]
            elif ws.startswith("in.("):
                allowed = ws[4:-1].split(",")
                rows = [r for r in rows if r.get("workspace") in allowed]
            elif ws.startswith("eq."):
                rows = [r for r in rows if r.get("workspace") == ws[3:]]
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

    def __call__(self, method, url, headers=None, body=None, timeout=60):
        if self.fail:
            raise OSError("hook down")
        self.posts.append((url, body))
        raise ValueError("Accepted")   # Make answers a non-JSON 2xx


def wire(sb, http):
    setter._SB = sb
    setter._HTTP = http
    setter._KEYS = {}          # no Smartlead key -> _sl_get returns None (link skipped)


GROUT_POS = {"id": 22872, "workspace": "grout", "smartlead_campaign_id": 3729147,
             "email": "sagar@eazybe.com", "replied_at": _iso(hours_ago=1),
             "category": "Information Request", "reply_body": "how much do u charge?",
             "notify_alerted_at": None}
CAMPS = [{"smartlead_campaign_id": 3729147, "name": "Campaign 1 (Roman's LinkedIn network)"}]


def test_client_positive_alerts_once():
    sb = FakeSB([dict(GROUT_POS)], campaigns=CAMPS)
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    # grout is in CLIENT_INTERNAL_MIRROR: one client-channel card + one
    # internal mirror (2026-09-11) — two posts, two different channels.
    check("1a grout positive posts client card + internal mirror", len(http.posts) == 2, str(res))
    check("1b alert went to the ever-positive hook",
          http.posts and http.posts[0][0] == setter.EVER_POSITIVE_HOOK)
    body = (http.posts[0][1] or {}) if http.posts else {}
    check("1c payload is EVER_POSITIVE_ALERT", body.get("event_type") == "EVER_POSITIVE_ALERT")
    check("1c2 grout routes to #grouts-navreo (C0BEGAKS8TX)",
          body.get("channel") == "C0BEGAKS8TX", str(body))
    txt = body.get("text") or ""
    # Client-safe card (design doc 2026-09-11): _cp_compose also lands in the
    # CLIENT's own channel, so our internal labelling never renders - no
    # workspace, no category taxonomy, no campaign.
    check("1d text carries NO workspace label", "grout" not in txt.lower(), txt)
    check("1e text carries NO internal category word",
          "Information Request" not in txt, txt)
    check("1f text carries NO campaign line",
          "Roman's LinkedIn network" not in txt and "Campaign" not in txt, txt)
    check("1f2 text is the positive card: header, lead, when, one link",
          txt.startswith("*\U0001F389 New positive reply")
          and txt.count("|Open conversation>") == 1
          and "smartlead.ai" not in txt and "---" not in txt, txt)
    check("1g reply body rides the threaded child field", body.get("reply_text") == "how much do u charge?", str(body))
    mbody = (http.posts[1][1] or {}) if len(http.posts) > 1 else {}
    check("1g2 mirror goes to #client-interested-replies (C0B96LNPWDB)",
          mbody.get("channel") == "C0B96LNPWDB", str(mbody))
    check("1g3 mirror is the same positive card as the client post",
          (mbody.get("text") or "").split("\n")[:2] == txt.split("\n")[:2]
          and (mbody.get("text") or "").startswith("*\U0001F389 New positive reply"),
          str(mbody.get("text"))[:200])
    check("1g4 mirror carries the owner link, not a client share",
          "setter.html#/r/" in (mbody.get("text") or "") and "share=" not in (mbody.get("text") or ""), str(mbody))
    row = sb._row(22872)
    check("1h row stamped client-positive-alerted",
          row.get("notify_kind") == "client-positive-alerted" and row.get("notify_alerted_at"))
    check("1i summary counts it", res.get("alerted") == 1 and res.get("ok") is True)


def test_navreo_positive_not_touched():
    navreo_pos = dict(GROUT_POS, id=1, workspace="navreo")
    sb = FakeSB([navreo_pos])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    check("2a navreo positive posts nothing here", len(http.posts) == 0, str(res))
    check("2b navreo row left unstamped for the categoriser",
          not sb._row(1).get("notify_alerted_at"))


def test_unmapped_client_uses_default_channel():
    # asteri has no CLIENT_ALERT_CHANNELS entry -> no channel key -> the hook
    # falls back to #interested-replies (internal, non-duplicate of its router card).
    asteri = dict(GROUT_POS, id=5, workspace="asteri", email="lead@asteri.com")
    sb = FakeSB([asteri])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    body = (http.posts[0][1] or {}) if http.posts else {}
    check("4a unmapped client still alerts", res.get("alerted") == 1)
    check("4b unmapped client routes to #client-interested-replies (C0B96LNPWDB)",
          body.get("channel") == "C0B96LNPWDB", str(body))
    check("4c unmapped client posts once (no mirror)", len(http.posts) == 1)


def test_opan_test_positive_not_touched():
    opan_pos = dict(GROUT_POS, id=2, workspace="opan-test")
    sb = FakeSB([opan_pos])
    http = FakeHTTP()
    wire(sb, http)
    setter.run_client_positive_alerts()
    check("3 opan-test positive posts nothing", len(http.posts) == 0)


def test_client_negative_stays_silent():
    neg = dict(GROUT_POS, id=3, category="Not Interested",
               reply_body="not interested, remove me")
    sb = FakeSB([neg])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    check("4a client negative posts nothing", len(http.posts) == 0, str(res))
    check("4b client negative left unstamped", not sb._row(3).get("notify_alerted_at"))


def test_marker_holds_across_runs():
    sb = FakeSB([dict(GROUT_POS)], campaigns=CAMPS)
    http = FakeHTTP()
    wire(sb, http)
    setter.run_client_positive_alerts()
    setter.run_client_positive_alerts()
    check("5 same row across two runs alerts once (card + mirror, no repeat)", len(http.posts) == 2)


def test_hook_failure_is_retried():
    sb = FakeSB([dict(GROUT_POS)], campaigns=CAMPS)
    http = FakeHTTP(fail=True)
    wire(sb, http)
    res1 = setter.run_client_positive_alerts()
    check("6a hook-down run reports failure",
          res1.get("failed_posts") == 1 and res1.get("ok") is False)
    check("6b row NOT stamped on failure", not sb._row(22872).get("notify_alerted_at"))
    http.fail = False
    res2 = setter.run_client_positive_alerts()
    check("6c next run retries and posts", len(http.posts) == 2 and res2.get("alerted") == 1)
    check("6d row stamped after success",
          sb._row(22872).get("notify_kind") == "client-positive-alerted")


def test_outside_lookback_not_selected():
    old = dict(GROUT_POS, id=7, replied_at=_iso(hours_ago=setter.CP_LOOKBACK_HOURS + 5))
    sb = FakeSB([old], campaigns=CAMPS)
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    check("7 positive older than the window is not selected",
          len(http.posts) == 0 and res.get("checked") == 0, str(res))


def test_post_cap_trips_loudly():
    rows = []
    for i in range(setter.CP_POST_CAP + 2):
        rows.append(dict(GROUT_POS, id=100 + i,
                         email=f"lead{i}@client.com",
                         replied_at=_iso(hours_ago=1, minutes_ago=i)))
    sb = FakeSB(rows, campaigns=CAMPS)
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    check("8a cap alerts exactly CP_POST_CAP rows (each = card + mirror)",
          res.get("alerted") == setter.CP_POST_CAP and len(http.posts) == 2 * setter.CP_POST_CAP, str(res))
    check("8b capped reported loudly", res.get("capped") is True and res.get("ok") is False)
    unstamped = [r for r in sb.replies if not r.get("notify_alerted_at")]
    check("8c leftovers left unstamped for next tick", len(unstamped) == 2)


def test_mapped_unmirrored_client_posts_once():
    # krg is mapped to its own channel but NOT in CLIENT_INTERNAL_MIRROR:
    # exactly one post, to #krg-advisors-navreo, no internal copy.
    krg = dict(GROUT_POS, id=7, workspace="krg", email="lead@krg.com")
    sb = FakeSB([krg])
    http = FakeHTTP()
    wire(sb, http)
    res = setter.run_client_positive_alerts()
    body = (http.posts[0][1] or {}) if http.posts else {}
    check("10a mapped, unmirrored client posts once", len(http.posts) == 1 and res.get("alerted") == 1, str(res))
    check("10b ... to its own channel", body.get("channel") == "C0A7EJ4DL9K", str(body))
    check("10c mirror set is grout only", setter.CLIENT_INTERNAL_MIRROR == frozenset({"grout"}))


def test_no_supabase_skips():
    setter._SB = None
    setter._HTTP = FakeHTTP()
    res = setter.run_client_positive_alerts()
    check("9 no Supabase -> skipped, no crash", res.get("skipped") is True)


if __name__ == "__main__":
    test_client_positive_alerts_once()
    test_navreo_positive_not_touched()
    test_unmapped_client_uses_default_channel()
    test_opan_test_positive_not_touched()
    test_client_negative_stays_silent()
    test_marker_holds_across_runs()
    test_hook_failure_is_retried()
    test_outside_lookback_not_selected()
    test_post_cap_trips_loudly()
    test_no_supabase_skips()
    test_mapped_unmirrored_client_posts_once()
    sys.exit(1 if report() else 0)
