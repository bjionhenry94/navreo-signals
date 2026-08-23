"""Pure-python regression tests for the 2026-08-23 threaded-reply accuracy
fixes. NO network — Supabase, Smartlead and the categoriser hook are all
in-memory fakes. Run:
    python3 test_reply_threaded_accuracy.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers three proven live defects:
  F1 — a sweep/poll intake whose synthetic claim key hydration could NOT
       resolve to a real message id must stand down when a sibling row (any
       status) already carries the same reply INSTANT (±30s slack): the
       tareq@zeda.ai / aboubakar@egtmea.com duplicate needs_review rows.
  F2 — POSITIVE_CATEGORY_IDS carries 113398 ("[Manual] Sending meeting
       request follow-up") so relabelled positives stay inside the sweep.
  F3 — run_positive_resweep's authoritative top-up: when the master-inbox
       row's last_reply_time lags the real thread (proven 2h on aboubakar),
       the per-campaign message-history of recently-active setter threads
       supplies the newer reply instant; exactly one categoriser post, then
       idempotent across back-to-back sweeps.
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


def _unq(s):
    from urllib.parse import unquote
    return unquote(s)


def _epoch(ts):
    s = _unq(str(ts)).replace(".000Z", "+00:00")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"\.(\d{1,6})\d*(?=[+-])", lambda m: "." + m.group(1).ljust(6, "0"), s)
    return dt.datetime.fromisoformat(s).timestamp()


NOW = dt.datetime.now(dt.timezone.utc)


# ── shared fakes ─────────────────────────────────────────────────────────────

class FakeSB:
    """In-memory Supabase covering exactly the queries the paths under test
    issue: setter_queue claim/read/delete, reply_sync_state id=2,
    reply_sync_seen (bulk + single), replies archive instant-lookups."""

    def __init__(self, queue_rows=None, last_sweep=None, seen=None, archived=None):
        self.queue = list(queue_rows or [])   # dicts with at least id/…/replied_at
        self.next_id = 9000
        self.deleted_ids = []
        self.state2 = {"watermark": last_sweep} if last_sweep else None
        self.seen = set(seen or [])
        self.archived = set(archived or [])   # (campaign_id, email_lower, epoch)
        self.state_writes = []

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        if table == setter.QUEUE_TABLE:
            if method == "POST":
                self.next_id += 1
                row = dict(body or {})
                row["id"] = self.next_id
                self.queue.append(row)
                return [dict(row)]
            if method == "DELETE":
                m = re.search(r"id=eq\.(\d+)", q)
                if m:
                    rid = int(m.group(1))
                    self.deleted_ids.append(rid)
                    self.queue = [r for r in self.queue if int(r.get("id") or 0) != rid]
                return []
            if method == "GET":
                out = list(self.queue)
                m = re.search(r"lead_email=eq\.([^&]+)", q)
                if m:
                    em = _unq(m.group(1)).lower()
                    out = [r for r in out if str(r.get("lead_email") or "").lower() == em]
                m = re.search(r"smartlead_campaign_id=eq\.([^&]+)", q)
                if m:
                    out = [r for r in out if str(r.get("smartlead_campaign_id")) == m.group(1)]
                m = re.search(r"message_id=eq\.([^&]+)", q)
                if m:
                    mid = _unq(m.group(1))
                    out = [r for r in out if str(r.get("message_id")) == mid]
                m = re.search(r"source_message_id=eq\.([^&]+)", q)
                if m:
                    mid = _unq(m.group(1))
                    out = [r for r in out if str(r.get("source_message_id")) == mid]
                m = re.search(r"replied_at=gte\.([^&]+)", q)
                if m:
                    lo = _epoch(m.group(1))
                    out = [r for r in out if r.get("replied_at") and _epoch(r["replied_at"]) >= lo]
                m = re.search(r"replied_at=lte\.([^&]+)", q)
                if m:
                    hi = _epoch(m.group(1))
                    out = [r for r in out if r.get("replied_at") and _epoch(r["replied_at"]) <= hi]
                m = re.search(r"id=neq\.(\d+)", q)
                if m:
                    out = [r for r in out if int(r.get("id") or 0) != int(m.group(1))]
                # the resweep's active-thread read filters on sent_at/replied_at or=()
                if "or=(sent_at" in q:
                    m = re.search(r"or=\(sent_at\.gte\.([^,]+),replied_at\.gte\.([^)]+)\)", q)
                    if m:
                        cut = _epoch(m.group(1))
                        out = [r for r in out
                               if (r.get("sent_at") and _epoch(r["sent_at"]) >= cut)
                               or (r.get("replied_at") and _epoch(r["replied_at"]) >= cut)]
                    out = [r for r in out if r.get("smartlead_lead_id")]
                m = re.search(r"limit=(\d+)", q)
                if m:
                    out = out[: int(m.group(1))]
                return [dict(r) for r in out]
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
            mc = re.search(r"smartlead_campaign_id=eq\.([^&]+)", q)
            me = re.search(r"email=ilike\.([^&]+)", q)
            mt = re.search(r"replied_at=eq\.([^&]+)", q)
            if mc and me and mt:
                key = (int(mc.group(1)), _unq(me.group(1)).lower(), _epoch(mt.group(1)))
                return [{"id": 1}] if key in self.archived else []
            return []
        return []


class FakeInbox:
    def __init__(self, rows):
        self.rows = list(rows)

    def __call__(self, path, body, params=None):
        if "master-inbox/inbox-replies" in path:
            off = int(body.get("offset", 0))
            lim = int(body.get("limit", 20))
            return {"ok": True, "data": self.rows[off: off + lim]}
        return {}


class FakeHistory:
    """Fake _sl_get for /campaigns/{cid}/leads/{lid}/message-history."""

    def __init__(self, by_thread):
        self.by_thread = by_thread   # (str(cid), str(lid)) -> [msg dicts]
        self.calls = []

    def __call__(self, path, params=None, campaign_id=None):
        m = re.search(r"/campaigns/([^/]+)/leads/([^/]+)/message-history", path)
        if m:
            self.calls.append((m.group(1), m.group(2)))
            return {"history": self.by_thread.get((m.group(1), m.group(2)), [])}
        return {}


class HookRecorder:
    def __init__(self):
        self.posts = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        if url == setter.CATEGORISER_HOOK:
            self.posts.append(body)
            raise ValueError("Accepted")
        return {}


class Sentinel(Exception):
    """Raised when _process_reply_inner runs PAST the dedup stand-down."""


# ── F2: the relabel category id is inside the sweep set ──────────────────────

def test_f2_manual_followup_id_in_sweep_set():
    check("F2: 113398 ([Manual] Sending meeting request follow-up) swept",
          113398 in setter.POSITIVE_CATEGORY_IDS, str(setter.POSITIVE_CATEGORY_IDS))


# ── F1: same-instant sibling => stand down, no duplicate row ─────────────────

def _wire_intake(sb):
    setter.configure(sb=sb, http_json=lambda *a, **k: {},
                     keys={"SMARTLEAD_API_KEY": "y"}, log_activity=lambda *a, **k: None)
    setter._sl_key = lambda: "y"
    # hydration resolves NO real message id for the re-reply (the proven live
    # shape: history omits ids on deep re-replies) — reply fields still fill.
    setter.hydrate_lead = lambda cid, email, mid: (True, {
        "smartlead_lead_id": "4267350060", "email_stats_id": None,
        "reply_message_id": None, "reply_subject": "Re: intro",
        "reply_email_body": "sounds good", "reply_email_time": None,
        "thread": [], "first_name": "Tareq", "last_name": "", "sender_first": "",
        "answered_since_reply": False, "first_outbound": "",
    }, "")
    # anything PAST the stand-down explodes loudly => test fails closed
    setter._sender_first_for = lambda *a, **k: (_ for _ in ()).throw(Sentinel())


def test_f1_same_instant_dedup_stands_down():
    rt_existing = _iso(NOW - dt.timedelta(minutes=90))
    # the sweep feeds the SAME physical reply 11s later (master-inbox clock)
    rt_sweep = _iso(NOW - dt.timedelta(minutes=90) + dt.timedelta(seconds=11))
    existing = {"id": 2312, "workspace": "navreo", "smartlead_campaign_id": 3742182,
                "lead_email": "tareq@zeda.ai", "status": "sent",
                "message_id": "<real-rfc-id@mail.gmail.com>",
                "source_message_id": f"4267350060-{rt_existing}",
                "replied_at": rt_existing}
    sb = FakeSB(queue_rows=[existing])
    _wire_intake(sb)
    reply = {"workspace": "navreo", "campaign_id": 3742182, "email": "tareq@zeda.ai",
             "message_id": f"4267350060-{rt_sweep}", "replied_at": rt_sweep,
             "body": "sounds good", "category": "Meeting Request"}
    try:
        out = setter._process_reply_inner(reply, {"id": "agent-1"}, {})
        ran_past = False
    except Sentinel:
        out, ran_past = None, True
    check("F1: intake stands down instead of drafting a duplicate", not ran_past)
    check("F1: the sibling row is returned", bool(out) and out.get("id") == 2312, str(out))
    check("F1: claim husk deleted", sb.deleted_ids and all(i != 2312 for i in sb.deleted_ids),
          str(sb.deleted_ids))
    check("F1: queue holds exactly the original row",
          [r.get("id") for r in sb.queue] == [2312], str([r.get("id") for r in sb.queue]))


def test_f1_distinct_instant_still_processes():
    rt_existing = _iso(NOW - dt.timedelta(hours=5))
    rt_new = _iso(NOW - dt.timedelta(minutes=30))   # genuinely NEW reply, far apart
    existing = {"id": 2297, "workspace": "navreo", "smartlead_campaign_id": 3285066,
                "lead_email": "aboubakar@egtmea.com", "status": "sent",
                "message_id": "<old-rfc@outlook.com>",
                "source_message_id": f"4271487725-{rt_existing}",
                "replied_at": rt_existing}
    sb = FakeSB(queue_rows=[existing])
    _wire_intake(sb)
    reply = {"workspace": "navreo", "campaign_id": 3285066, "email": "aboubakar@egtmea.com",
             "message_id": f"4271487725-{rt_new}", "replied_at": rt_new,
             "body": "yes let's book it", "category": "Meeting Request"}
    try:
        setter._process_reply_inner(reply, {"id": "agent-1"}, {})
        ran_past = False
    except Sentinel:
        ran_past = True
    check("F1: a genuinely new reply instant still processes", ran_past)
    check("F1: new-claim row kept (not deleted)", not sb.deleted_ids, str(sb.deleted_ids))


# ── F3: history top-up sees the reply the master inbox hasn't indexed yet ────

def _wire_resweep(sb, inbox, history, hook):
    setter.configure(sb=sb, http_json=hook,
                     keys={"SMARTLEAD_API_KEY": "y"}, log_activity=lambda *a, **k: None)
    setter._sl_post = inbox
    setter._sl_get = history
    setter._sl_key = lambda: "y"
    setter.hydrate_lead = lambda cid, email, mid: (
        True, {"reply_email_body": "<p>see you tomorrow</p>"}, "")


def test_f3_history_topup_posts_lagged_re_reply():
    stale = _iso(NOW - dt.timedelta(days=2))          # what the master inbox still shows
    fresh = _iso(NOW - dt.timedelta(minutes=20))      # the real latest reply (history)
    stale_mid = f"555-{stale}"
    fresh_mid = f"555-{fresh}"
    inbox_row = {"email_lead_id": "555", "last_reply_time": stale,
                 "email_campaign_id": 42, "lead_email": "lead@acme.com",
                 "lead_category_id": 2}
    active_q = {"id": 1, "workspace": "navreo", "smartlead_campaign_id": 42,
                "lead_email": "lead@acme.com", "smartlead_lead_id": "555",
                "status": "sent", "sent_at": _iso(NOW - dt.timedelta(hours=3)),
                "replied_at": stale, "is_test": False,
                "message_id": "<x@y>", "source_message_id": stale_mid}
    history = FakeHistory({("42", "555"): [
        {"type": "SENT", "time": _iso(NOW - dt.timedelta(days=3))},
        {"type": "REPLY", "time": stale},
        {"type": "SENT", "time": _iso(NOW - dt.timedelta(hours=3))},
        {"type": "REPLY", "time": fresh},
    ]})
    sb = FakeSB(queue_rows=[active_q],
                last_sweep=(NOW - dt.timedelta(minutes=20)).isoformat(),
                seen={stale_mid})
    hook = HookRecorder()
    _wire_resweep(sb, FakeInbox([inbox_row]), history, hook)
    s = setter.run_positive_resweep(force=True)
    check("F3: sweep read the active thread's history", history.calls == [("42", "555")],
          str(history.calls))
    check("F3: exactly one categoriser post", len(hook.posts) == 1, str(hook.posts))
    check("F3: post carries the FRESH reply instant",
          hook.posts and hook.posts[0].get("reply_message", {}).get("time") == fresh,
          str(hook.posts))
    check("F3: fresh mid marked seen", fresh_mid in sb.seen, str(sb.seen))
    check("F3: sweep ok with active_threads counted",
          s.get("ok") is True and s.get("active_threads") == 1, str(s))
    # idempotency: an identical second sweep must post nothing new
    s2 = setter.run_positive_resweep(force=True)
    check("F3: second sweep posts nothing (idempotent)", len(hook.posts) == 1,
          str(hook.posts))
    check("F3: second sweep still ok", s2.get("ok") is True, str(s2))


def test_f3_archived_fresh_reply_not_reposted():
    stale = _iso(NOW - dt.timedelta(days=2))
    fresh = _iso(NOW - dt.timedelta(minutes=20))
    inbox_row = {"email_lead_id": "556", "last_reply_time": stale,
                 "email_campaign_id": 43, "lead_email": "b@x.com",
                 "lead_category_id": 2}
    active_q = {"id": 2, "workspace": "navreo", "smartlead_campaign_id": 43,
                "lead_email": "b@x.com", "smartlead_lead_id": "556",
                "status": "sent", "sent_at": _iso(NOW - dt.timedelta(hours=3)),
                "replied_at": stale, "is_test": False,
                "message_id": "<z@y>", "source_message_id": f"556-{stale}"}
    history = FakeHistory({("43", "556"): [
        {"type": "REPLY", "time": stale},
        {"type": "REPLY", "time": fresh},
    ]})
    # the webhook fast-path already archived the fresh instant (any format)
    sb = FakeSB(queue_rows=[active_q],
                last_sweep=(NOW - dt.timedelta(minutes=20)).isoformat(),
                seen={f"556-{stale}"},
                archived={(43, "b@x.com", _epoch(fresh))})
    hook = HookRecorder()
    _wire_resweep(sb, FakeInbox([inbox_row]), history, hook)
    s = setter.run_positive_resweep(force=True)
    check("F3: already-archived fresh reply => zero posts", len(hook.posts) == 0,
          str(hook.posts))
    check("F3: archived instant marked seen, not errored",
          s.get("marked_archived") == 1 and s.get("errors") == 0, str(s))


def test_f3_rate_limit_bailout():
    """c146b74: 3 consecutive history-read failures end the top-up for the
    tick (Smartlead 429 storm — 37/40 failed on the first live tick), the
    failures land in active_errors (not the sweep's own errors), and the
    sweep itself stays ok."""
    stale = _iso(NOW - dt.timedelta(days=2))
    inbox_row = {"email_lead_id": "600", "last_reply_time": stale,
                 "email_campaign_id": 50, "lead_email": "ok@x.com",
                 "lead_category_id": 2}
    actives = [{"id": 10 + i, "workspace": "navreo", "smartlead_campaign_id": 50 + i,
                "lead_email": f"l{i}@x.com", "smartlead_lead_id": str(700 + i),
                "status": "sent", "sent_at": _iso(NOW - dt.timedelta(hours=2)),
                "replied_at": stale, "is_test": False,
                "message_id": f"<m{i}@y>", "source_message_id": f"{700+i}-{stale}"}
               for i in range(6)]

    class RateLimitedHistory:
        def __init__(self):
            self.calls = 0
        def __call__(self, path, params=None, campaign_id=None):
            self.calls += 1
            raise RuntimeError("HTTP Error 429: Too Many Requests")

    hist = RateLimitedHistory()
    sb = FakeSB(queue_rows=actives,
                last_sweep=(NOW - dt.timedelta(minutes=20)).isoformat(),
                seen={f"600-{stale}"})
    hook = HookRecorder()
    _wire_resweep(sb, FakeInbox([inbox_row]), hist, hook)
    s = setter.run_positive_resweep(force=True)
    check("F3-hardening: top-up stops after 3 consecutive failures",
          hist.calls == 3, f"calls={hist.calls}")
    check("F3-hardening: failures counted in active_errors, not errors",
          s.get("active_errors") == 3 and s.get("errors") == 0, str(s))
    check("F3-hardening: sweep itself still ok (fail-soft)",
          s.get("ok") is True, str(s))
    check("F3-hardening: no hook posts from the failed top-up",
          len(hook.posts) == 0, str(hook.posts))


if __name__ == "__main__":
    test_f2_manual_followup_id_in_sweep_set()
    test_f1_same_instant_dedup_stands_down()
    test_f1_distinct_instant_still_processes()
    test_f3_history_topup_posts_lagged_re_reply()
    test_f3_archived_fresh_reply_not_reposted()
    test_f3_rate_limit_bailout()
    sys.exit(1 if report() else 0)
