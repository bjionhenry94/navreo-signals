"""Pure-python tests for the positive-thread re-reply sweep
(setter.run_positive_resweep). NO network: the Smartlead master inbox, the
Make categoriser hook, and Supabase are all in-memory fakes wired via
setter.configure() plus direct monkeypatches of setter's module globals. Run:
    python3 test_positive_resweep.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers the guarantee's done-rules:
  - the sweep queries by leadCategories.categoryIdsIn (positive ids), NOT by
    a replyTimeBetween window (which indexes threads by FIRST reply time and
    is therefore blind to re-replies — the Zayn miss, 2026-07-15)
  - FIRST run seeds: every current mid marked seen, ZERO hook posts, and the
    would-post count/sample records what the sweep would have fired
  - a fresh last_reply_time on an already-seen thread => exactly one hook
    POST with the categoriser-archive-exact mid, then marked seen (idempotent
    across back-to-back runs)
  - a mid already in `replies` (webhook fast-path won) => marked seen, no post
  - the RESWEEP_POST_CAP tripwire caps posts and reports FAILED, never silent
  - the ~15-min self-throttle skips a run that follows too soon; force=True
    overrides it
"""

import datetime as dt
import json
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


def _unq(s):
    from urllib.parse import unquote
    return unquote(s)


class FakeSB:
    """In-memory Supabase stand-in for reply_sync_state (id=2 row),
    reply_sync_seen (incl. bulk in.() GETs and list-body POSTs) and `replies`
    archive lookups — just the queries run_positive_resweep issues."""

    def __init__(self, last_sweep=None, seen=None, archived=None):
        self.state2 = {"watermark": last_sweep} if last_sweep else None
        self.seen = set(seen or [])
        self.archived = set(archived or [])
        self.state_writes = []

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        if table == "reply_sync_state":
            if method == "GET" and "id=eq.2" in q:
                return [dict(self.state2)] if self.state2 else []
            if method == "POST":
                self.state2 = {"watermark": (body or {}).get("watermark")}
                self.state_writes.append(body)
                return []
        if table == "reply_sync_seen":
            if method == "GET":
                m = re.search(r"message_id=in\.\(([^)]*)\)", q)
                if m:
                    asked = {_unq(x) for x in m.group(1).split(",") if x}
                    return [{"message_id": mid} for mid in asked & self.seen]
                m = re.search(r"message_id=eq\.([^&]+)", q)
                mid = _unq(m.group(1)) if m else ""
                return [{"message_id": mid}] if mid in self.seen else []
            if method == "POST":
                items = body if isinstance(body, list) else [body]
                for it in items:
                    self.seen.add((it or {}).get("message_id"))
                return []
        if table == "replies" and method == "GET":
            m = re.search(r"smartlead_message_id=eq\.([^&]+)", q)
            mid = _unq(m.group(1)) if m else ""
            return [{"id": 1}] if mid in self.archived else []
        return []


class FakeInbox:
    """Fake _sl_post for /master-inbox/inbox-replies. Records the filters each
    call used so tests can assert the category-filter (not window) is in play."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.filters_seen = []

    def __call__(self, path, body, params=None):
        if "master-inbox/inbox-replies" in path:
            self.filters_seen.append(body.get("filters"))
            off = int(body.get("offset", 0))
            lim = int(body.get("limit", 20))
            return {"ok": True, "data": self.rows[off: off + lim]}
        return {}


class HookRecorder:
    def __init__(self):
        self.posts = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        if url == setter.CATEGORISER_HOOK:
            self.posts.append(body)
            raise ValueError("Accepted")  # Make returns non-JSON 2xx, as in prod
        return {}


def wire(sb, inbox, hook):
    setter.configure(sb=sb, http_json=hook,
                     keys={"SMARTLEAD_API_KEY": "y"}, log_activity=lambda *a, **k: None)
    setter._sl_post = inbox
    setter._sl_key = lambda: "y"
    setter.hydrate_lead = lambda cid, email, mid: (
        True, {"reply_email_body": "<html><body><p>Sounds&nbsp;great, let's talk.</p></body></html>"}, "")


def row(lead_id, when, cid=3506959, email="lead@acme.com", cat=2):
    return {"email_lead_id": str(lead_id), "last_reply_time": _iso(when),
            "email_campaign_id": cid, "lead_email": email, "lead_category_id": cat}


NOW = dt.datetime.now(dt.timezone.utc)


# ── 1. seed run: marks all seen, posts nothing, records would-post ────────────

def test_seed_run():
    rows = [row(101, NOW - dt.timedelta(days=10), email="a@x.com"),
            row(102, NOW - dt.timedelta(days=5), email="b@x.com"),
            row(103, NOW - dt.timedelta(hours=1), email="c@x.com")]
    mid_archived = f"102-{_iso(NOW - dt.timedelta(days=5))}"
    sb = FakeSB(archived={mid_archived})          # one already webhook-archived
    inbox, hook = FakeInbox(rows), HookRecorder()
    wire(sb, inbox, hook)
    s = setter.run_positive_resweep()
    check("seed: reported seeded", s["seeded"] is True)
    check("seed: zero hook posts", len(hook.posts) == 0, str(hook.posts))
    check("seed: all mids marked seen", len(sb.seen) == 3, str(sb.seen))
    check("seed: would_post counts only unarchived", s["would_post"] == 2, str(s))
    check("seed: sample lists the would-fire mids",
          len(s["would_post_sample"]) == 2 and mid_archived not in s["would_post_sample"],
          str(s["would_post_sample"]))
    check("seed: state row written", len(sb.state_writes) == 1)
    check("seed: category filter used (not a time window)",
          all(f and "leadCategories" in f and "replyTimeBetween" not in f
              for f in inbox.filters_seen), str(inbox.filters_seen))
    check("seed: ok", s["ok"] is True, str(s))


# ── 2. steady state: a NEW reply on an old thread fires exactly once ──────────

def test_new_re_reply_posts_once():
    old_time = NOW - dt.timedelta(days=14)
    new_time = NOW - dt.timedelta(minutes=20)
    old_mid = f"201-{_iso(old_time)}"
    r = row(201, new_time, cid=3477409, email="gerry@incentco.com")
    sb = FakeSB(last_sweep=(NOW - dt.timedelta(minutes=30)).isoformat(),
                seen={old_mid})                   # thread known by its OLD reply only
    inbox, hook = FakeInbox([r]), HookRecorder()
    wire(sb, inbox, hook)
    s = setter.run_positive_resweep()
    check("re-reply: exactly one hook post", len(hook.posts) == 1, str(s))
    if hook.posts:
        p = hook.posts[0]
        check("re-reply: payload shape", p.get("event_type") == "EMAIL_REPLY"
              and p.get("campaign_id") == 3477409
              and p.get("sl_lead_email") == "gerry@incentco.com", json.dumps(p))
        check("re-reply: mid == categoriser archive key",
              f"{p['sl_email_lead_id']}-{p['reply_message']['time']}" == f"201-{_iso(new_time)}",
              json.dumps(p))
        check("re-reply: body html-stripped",
              "Sounds" in p["reply_message"]["text"] and "<" not in p["reply_message"]["text"],
              p["reply_message"]["text"])
    check("re-reply: new mid marked seen", f"201-{_iso(new_time)}" in sb.seen)
    # run again straight away (force past throttle): no double post
    s2 = setter.run_positive_resweep(force=True)
    check("re-reply: idempotent across runs", len(hook.posts) == 1, str(s2))


# ── 3. webhook already archived it => marked seen, never posted ───────────────

def test_archived_skipped():
    t = NOW - dt.timedelta(minutes=10)
    mid = f"301-{_iso(t)}"
    sb = FakeSB(last_sweep=(NOW - dt.timedelta(minutes=30)).isoformat(), archived={mid})
    inbox, hook = FakeInbox([row(301, t)]), HookRecorder()
    wire(sb, inbox, hook)
    s = setter.run_positive_resweep()
    check("archived: no hook post", len(hook.posts) == 0, str(s))
    check("archived: marked seen", mid in sb.seen)
    check("archived: counted", s["marked_archived"] == 1, str(s))


# ── 4. post-cap tripwire ──────────────────────────────────────────────────────

def test_post_cap():
    rows = [row(400 + i, NOW - dt.timedelta(minutes=i + 1), email=f"l{i}@x.com")
            for i in range(setter.RESWEEP_POST_CAP + 5)]
    sb = FakeSB(last_sweep=(NOW - dt.timedelta(minutes=30)).isoformat())
    inbox, hook = FakeInbox(rows), HookRecorder()
    wire(sb, inbox, hook)
    s = setter.run_positive_resweep()
    check("cap: posts stop at RESWEEP_POST_CAP",
          len(hook.posts) == setter.RESWEEP_POST_CAP, f"{len(hook.posts)} {s}")
    check("cap: reported FAILED + capped", s["ok"] is False and s["capped"] is True, str(s))


# ── 5. throttle: too-soon run skips; force overrides ──────────────────────────

def test_throttle():
    sb = FakeSB(last_sweep=(NOW - dt.timedelta(minutes=5)).isoformat())
    inbox, hook = FakeInbox([row(501, NOW - dt.timedelta(minutes=2))]), HookRecorder()
    wire(sb, inbox, hook)
    s = setter.run_positive_resweep()
    check("throttle: skipped within 13 min", s["skipped"] is True and len(hook.posts) == 0, str(s))
    s2 = setter.run_positive_resweep(force=True)
    check("throttle: force runs anyway", s2["skipped"] is False and len(hook.posts) == 1, str(s2))


if __name__ == "__main__":
    test_seed_run()
    test_new_re_reply_posts_once()
    test_archived_skipped()
    test_post_cap()
    test_throttle()
    sys.exit(1 if report() else 0)
