"""Pure-python tests for the backstop reply-sync cron (setter.run_reply_sync).
NO network: Smartlead master-inbox + message-history, the Make categoriser
hook, and Supabase are all in-memory fakes wired via setter.configure() and a
couple of direct monkeypatches of setter's module globals. Run:
    python3 test_reply_sync.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers the loop's Step-3/Step-5 done-rules:
  - first run seeds the watermark at now-minus-2h and only scans that window
  - an unseen reply produces a correctly-shaped EMAIL_REPLY whose derived
    smartlead_message_id is byte-identical to the categoriser archive key
    "{sl_email_lead_id}-{reply_message.time}" (== what the webhook would write)
  - reply_message.text is the latest REPLY body with HTML stripped
  - an already-seen reply (and one already in `replies`) is skipped: exactly
    one hook POST across two back-to-back runs (dedup / idempotent)
  - the watermark advances to the newest handled reply time
  - a window over the 300 cap => run reported FAILED (ok=False) with a gap,
    never silently truncated; at most 300 posted
"""

import datetime as dt
import os
import re
import sys

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


def _iso(d):
    return d.strftime(ISO)


class FakeState:
    """In-memory Supabase stand-in for reply_sync_state / reply_sync_seen /
    replies, understanding just the queries run_reply_sync issues."""

    def __init__(self, watermark=None, seen=None, archived=None):
        self.state = {"watermark": watermark} if watermark else None
        self.seen = set(seen or [])
        self.archived = set(archived or [])   # smartlead_message_ids already in `replies`
        self.patches = []

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        if table == "reply_sync_state":
            if method == "GET":
                return [dict(self.state)] if self.state else []
            if method == "POST":
                # upsert id=1
                if self.state is None:
                    self.state = {"watermark": (body or {}).get("watermark")}
                return []
            if method == "PATCH":
                self.state = {"watermark": (body or {}).get("watermark")}
                self.patches.append(body)
                return []
        if table == "reply_sync_seen":
            if method == "GET":
                m = re.search(r"message_id=eq\.([^&]+)", q)
                mid = _unq(m.group(1)) if m else ""
                return [{"message_id": mid}] if mid in self.seen else []
            if method == "POST":
                self.seen.add((body or {}).get("message_id"))
                return []
        if table == "replies" and method == "GET":
            m = re.search(r"smartlead_message_id=eq\.([^&]+)", q)
            mid = _unq(m.group(1)) if m else ""
            return [{"id": 1}] if mid in self.archived else []
        return []


def _unq(s):
    from urllib.parse import unquote
    return unquote(s)


def make_master_inbox(rows):
    """rows: list of dicts with email_lead_id, last_reply_time, email_campaign_id,
    lead_email. Returns a fake _sl_post that paginates newest-first."""
    ordered = sorted(rows, key=lambda r: r["last_reply_time"], reverse=True)

    def _sl_post(path, body, params=None):
        if "master-inbox/inbox-replies" in path:
            off = int(body.get("offset", 0))
            lim = int(body.get("limit", 20))
            return {"ok": True, "data": ordered[off: off + lim]}
        return {}
    return _sl_post


class HookRecorder:
    def __init__(self):
        self.posts = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        if url == setter.CATEGORISER_HOOK:
            self.posts.append(body)
            raise ValueError("Accepted")  # Make returns non-JSON 2xx, as in prod
        return {}


def wire(state, rows, hook):
    setter.configure(sb=state, http_json=hook,
                     keys={"SMARTLEAD_API_KEY": "y"}, log_activity=lambda *a, **k: None)
    setter._sl_post = make_master_inbox(rows)
    setter._sl_key = lambda: "y"
    # every lead hydrates to a full-HTML reply so clean_body() has work to do
    setter.hydrate_lead = lambda cid, email, mid: (
        True, {"reply_email_body": "<html><body><p>Hi&nbsp;there, sounds great.</p></body></html>"}, "")


def base_row(lead_id, when, cid=3477410, email="lead@acme.com"):
    return {"email_lead_id": lead_id, "last_reply_time": _iso(when),
            "email_campaign_id": cid, "lead_email": email,
            "belongs_to_sub_sequence": True, "sub_sequence_id": 555}


# ── 1. first run: now-2h window + shape + dedup key + HTML strip ──────────────

def test_first_run_shape_and_key():
    now = dt.datetime.now(dt.timezone.utc)
    r = base_row(3510403675, now - dt.timedelta(minutes=30))
    state = FakeState()               # empty => first run, seeds now-2h
    hook = HookRecorder()
    wire(state, [r], hook)
    s = setter.run_reply_sync()

    check("first run flagged", s["first_run"] is True)
    # watermark seeded within a hair of now-2h
    before = setter._parse_iso(s["watermark_before"])
    drift = abs((before - (now - dt.timedelta(hours=2))).total_seconds())
    check("first run seeds watermark at now-minus-2h", drift < 90, f"drift={drift:.0f}s")

    check("exactly one hook POST", len(hook.posts) == 1, f"got {len(hook.posts)}")
    p = hook.posts[0] if hook.posts else {}
    check("payload event_type EMAIL_REPLY", p.get("event_type") == "EMAIL_REPLY")
    check("payload carries sl_email_lead_id", p.get("sl_email_lead_id") == 3510403675)
    check("payload campaign_id from row", p.get("campaign_id") == 3477410)
    rm = p.get("reply_message", {})
    check("reply_message.time == row last_reply_time", rm.get("time") == r["last_reply_time"])
    check("reply_message.text HTML-stripped", "<" not in (rm.get("text") or "") and "sounds great" in (rm.get("text") or ""),
          repr(rm.get("text")))
    check("reply_message.text entities unescaped", "&nbsp;" not in (rm.get("text") or ""))

    # the derived archive key MUST equal what the categoriser (module 60) writes
    derived = f"{p.get('sl_email_lead_id')}-{rm.get('time')}"
    check("derived message_id == archive-key format",
          derived == f"3510403675-{r['last_reply_time']}", derived)

    check("watermark advanced to the reply time", s["watermark_after"][:19] == _iso(now - dt.timedelta(minutes=30))[:19],
          s["watermark_after"])
    check("run ok (no cap hit)", s["ok"] is True and s["gap"] == 0)


# ── 2. dedup / idempotent: same reply twice => one POST ──────────────────────

def test_dedup_second_run_noop():
    now = dt.datetime.now(dt.timezone.utc)
    r = base_row(4001, now - dt.timedelta(minutes=10))
    state = FakeState()
    hook = HookRecorder()
    wire(state, [r], hook)

    s1 = setter.run_reply_sync()
    # second run: same window/rows; the seen-set must suppress a re-POST
    setter._sl_post = make_master_inbox([r])   # re-wire (wire() mutated globals; rows unchanged)
    s2 = setter.run_reply_sync()

    check("run1 posted once", s1["posted"] == 1, f"{s1}")
    check("run2 posts nothing (dedup)", s2["posted"] == 0, f"{s2}")
    check("run2 counts the reply as skipped_seen", s2["skipped_seen"] == 1, f"{s2}")
    check("still exactly one hook POST total", len(hook.posts) == 1, f"{len(hook.posts)}")


def test_skip_when_already_in_replies():
    now = dt.datetime.now(dt.timezone.utc)
    r = base_row(4002, now - dt.timedelta(minutes=5))
    mid = f"4002-{r['last_reply_time']}"
    state = FakeState(archived=[mid])          # webhook already archived it
    hook = HookRecorder()
    wire(state, [r], hook)
    s = setter.run_reply_sync()
    check("reply already in `replies` is not re-posted", len(hook.posts) == 0, f"{len(hook.posts)}")
    check("counted as skipped_archived", s["skipped_archived"] == 1, f"{s}")


# ── 3. cap: >300 in window => FAILED with gap, never silent ──────────────────

def test_cap_hit_reports_failed_with_gap():
    now = dt.datetime.now(dt.timezone.utc)
    # >ceiling (cap+page) so pagination stops early => overflow (lower-bound gap)
    rows = [base_row(5000 + i, now - dt.timedelta(minutes=100) + dt.timedelta(seconds=i))
            for i in range(350)]
    state = FakeState()
    hook = HookRecorder()
    wire(state, rows, hook)
    s = setter.run_reply_sync()
    check("cap-hit => run reported FAILED (ok False)", s["ok"] is False, f"{s['ok']}")
    check("cap-hit => gap reported > 0", s["gap"] > 0, f"gap={s['gap']}")
    check("cap-hit => at most 300 posted (no flood)", s["posted"] <= 300, f"posted={s['posted']}")
    check("cap-hit => overflow flagged (pagination truncated)", s["overflow"] is True)


# ── 4. empty window advances nothing, stays ok ───────────────────────────────

def test_empty_window_noop():
    state = FakeState(watermark=_iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)))
    hook = HookRecorder()
    wire(state, [], hook)
    s = setter.run_reply_sync()
    check("empty window: nothing posted", s["posted"] == 0)
    check("empty window: ok", s["ok"] is True and s["gap"] == 0)


# ── 5. empty-body reply: retries within grace, marked seen past it ───────────
# (the melissa@infiuss.com incident: a blank send whose HTML strips to ""
#  pinned the watermark for 3 days, 2026-07-21 → 2026-07-24)

EMPTY_HTML = "<html><body><div dir=\"ltr\"><br></div></body></html>"


def test_empty_body_young_stays_unseen_and_freezes_watermark():
    now = dt.datetime.now(dt.timezone.utc)
    young = base_row("77", now - dt.timedelta(minutes=30))
    state = FakeState(watermark=_iso(now - dt.timedelta(hours=1)))
    hook = HookRecorder()
    wire(state, [young], hook)
    setter.hydrate_lead = lambda cid, email, mid: (True, {"reply_email_body": EMPTY_HTML}, "")
    s = setter.run_reply_sync()
    check("young empty body: counted as error, not skipped_empty",
          s["errors"] == 1 and s["skipped_empty"] == 0)
    check("young empty body: NOT marked seen", f"77-{young['last_reply_time']}" not in state.seen)
    check("young empty body: watermark frozen",
          setter._parse_iso(s["watermark_after"]) == setter._parse_iso(s["watermark_before"]))
    check("young empty body: nothing posted", len(hook.posts) == 0)


def test_empty_body_past_grace_marked_seen_watermark_advances():
    now = dt.datetime.now(dt.timezone.utc)
    stale = base_row("99", now - dt.timedelta(hours=setter.EMPTY_BODY_GRACE_H + 1))
    state = FakeState(watermark=_iso(now - dt.timedelta(hours=setter.EMPTY_BODY_GRACE_H + 2)))
    hook = HookRecorder()
    wire(state, [stale], hook)
    setter.hydrate_lead = lambda cid, email, mid: (True, {"reply_email_body": EMPTY_HTML}, "")
    s = setter.run_reply_sync()
    mid = f"99-{stale['last_reply_time']}"
    check("stale empty body: marked seen", mid in state.seen)
    check("stale empty body: skipped_empty=1, no errors",
          s["skipped_empty"] == 1 and s["errors"] == 0)
    check("stale empty body: watermark advanced past it",
          setter._parse_iso(s["watermark_after"]) > setter._parse_iso(s["watermark_before"]))
    check("stale empty body: nothing posted", len(hook.posts) == 0)


if __name__ == "__main__":
    test_first_run_shape_and_key()
    test_dedup_second_run_noop()
    test_skip_when_already_in_replies()
    test_cap_hit_reports_failed_with_gap()
    test_empty_window_noop()
    test_empty_body_young_stays_unseen_and_freezes_watermark()
    test_empty_body_past_grace_marked_seen_watermark_advances()
    sys.exit(1 if report() else 0)
