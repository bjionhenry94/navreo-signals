"""Pure-python tests for the client-workspace category fill
(setter.run_client_category_fill, ship 2026-09-16). NO network: Supabase,
Smartlead, OpenAI and the Make alert hook are in-memory fakes wired via
setter.configure(). Run:
    python3 test_client_category_fill.py
Prints PASS/FAIL per case, exits 1 on any failure.

The fill closes the KRG / david.wilkins@northernpowergrid.com miss: the
client-channel positive card is category-driven, KRG's own categoriser (the
Make reply-router) was down, the backstop archived the reply with NO category,
and the poll's deterministic pass never labels a positive - so the card only
fired 1h41m later, after a human picked "Meeting Request" by hand.

Covers:
  1. an uncategorised client positive past the grace window is labelled by the
     model, written to the SENDABLE client's Smartlead, stamped in the archive,
     and carded by run_client_positive_alerts in the same tick
  2. a reply inside the grace window is untouched (the workspace's own
     categoriser gets first go)
  3. a label the workspace's Smartlead already carries is adopted without a
     model call (default id -> canonical name; custom positive id -> Interested)
  4. plainly automated mail is labelled by the rules pass, no model call
  5. a low-confidence verdict leaves the reply with a human and is not re-asked
     within the retry window
  6. a model failure is loud (ok=False), leaves the archive untouched and is
     retried only after the failure window
  7. navreo, disabled and keyless workspaces are never touched
  8. the per-workspace model cap trips and leaves the rest for a later tick
  9. a body-less reply is left alone (nothing to judge yet)
 10. a monitor-only workspace gets the archive stamp but NO Smartlead write
 11. the legacy "Uncategorizable by Ai" label counts as uncategorised
 12. no Supabase -> skipped, no crash
 13. helper edges: off-list model answer -> None; category id lookup is
     case-insensitive
"""

import datetime as dt
import json
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


def _iso(minutes_ago=0.0, hours_ago=0.0):
    return (NOW - dt.timedelta(minutes=minutes_ago, hours=hours_ago)).isoformat()


def _params(q):
    out = {}
    for part in q.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            out.setdefault(k, []).append(v)
    return out


class FakeSB:
    """In-memory Supabase understanding the queries the fill AND the client
    positive sweep issue (workspaces, replies GET/PATCH, campaigns)."""

    def __init__(self, workspaces, replies):
        self.workspaces = [dict(w) for w in workspaces]
        self.replies = [dict(r) for r in replies]
        self.patches = []

    def row(self, rid):
        for r in self.replies:
            if r["id"] == rid:
                return r
        return None

    def __call__(self, method, path, body=None, prefer=""):
        table = path.split("?", 1)[0]
        q = path.split("?", 1)[1] if "?" in path else ""
        p = _params(q)
        if table == "workspaces" and method == "GET":
            return [dict(w) for w in self.workspaces]
        if table == "replies" and method == "GET":
            rows = [dict(r) for r in self.replies]
            for ws in p.get("workspace", []):
                if ws.startswith("not.in.("):
                    blocked = ws[8:-1].split(",")
                    rows = [r for r in rows if r.get("workspace") not in blocked]
                elif ws.startswith("eq."):
                    rows = [r for r in rows if r.get("workspace") == ws[3:]]
            for c in p.get("category", []):
                if c == "is.null":
                    rows = [r for r in rows if r.get("category") is None]
                elif c.startswith("in.("):
                    cats = [unquote(x) for x in c[4:-1].split(",")]
                    rows = [r for r in rows if r.get("category") in cats]
                elif c.startswith("eq."):
                    want = unquote(c[3:])
                    rows = [r for r in rows if (r.get("category") or "") == want]
            for ra in p.get("replied_at", []):
                if ra.startswith("gte."):
                    rows = [r for r in rows if (r.get("replied_at") or "") >= unquote(ra[4:])]
                elif ra.startswith("lte."):
                    rows = [r for r in rows if (r.get("replied_at") or "") <= unquote(ra[4:])]
                elif ra.startswith("lt."):
                    rows = [r for r in rows if (r.get("replied_at") or "") < unquote(ra[3:])]
            if p.get("notify_alerted_at") == ["is.null"]:
                rows = [r for r in rows if not r.get("notify_alerted_at")]
            for em in p.get("email", []):
                if em.startswith("ilike."):
                    want = unquote(em[6:]).lower()
                    rows = [r for r in rows if (r.get("email") or "").lower() == want]
            order = (p.get("order") or [""])[0]
            rows.sort(key=lambda r: r.get("replied_at") or "", reverse=order.endswith("desc"))
            if p.get("limit"):
                rows = rows[:int(p["limit"][0])]
            return rows
        if table == "replies" and method == "PATCH":
            m = re.search(r"id=eq\.(\d+)", q)
            rid = int(m.group(1)) if m else None
            row = self.row(rid)
            if row is not None:
                row.update(body or {})
            self.patches.append((rid, dict(body or {})))
            return []
        return []


DEFAULT_CATS = [{"id": 1, "name": "Interested"}, {"id": 2, "name": "Meeting Request"},
                {"id": 3, "name": "Not Interested"}, {"id": 5, "name": "Information Request"},
                {"id": 6, "name": "Out Of Office"}, {"id": 7, "name": "Wrong Person"},
                {"id": 78386, "name": "Hot lead"}]


def lead(email, cid, cat_id=None, lead_id=4405199849):
    return {"id": lead_id, "first_name": "David", "last_name": "Wilkins",
            "company_name": "Northern Powergrid", "linkedin_profile": "",
            "custom_fields": {"title": "Head of External Affairs"},
            "lead_campaign_data": [{"campaign_id": cid, "lead_category_id": cat_id}]}


class FakeHTTP:
    """OpenAI + Smartlead (leads / fetch-categories / category write /
    message-history) + the Make alert hook."""

    def __init__(self, verdict=None, leads=None, cats=None, fail_model=False):
        self.verdict = verdict if verdict is not None else {"category": "Meeting Request", "confidence": 0.93}
        self.leads = {k.lower(): v for k, v in (leads or {}).items()}
        self.cats = list(cats if cats is not None else DEFAULT_CATS)
        self.fail_model = fail_model
        self.model_calls, self.category_posts, self.hook_posts = [], [], []

    def __call__(self, method, url, headers=None, body=None, timeout=60):
        if "api.openai.com" in url:
            if self.fail_model:
                raise OSError("model down")
            text = (body or {}).get("messages", [{}, {}])[1].get("content", "")
            self.model_calls.append(text)
            v = self.verdict(text) if callable(self.verdict) else self.verdict
            return {"choices": [{"message": {"content": json.dumps(v)}}]}
        if "/leads/fetch-categories" in url:
            return list(self.cats)
        if "/leads/?" in url and method == "GET":
            m = re.search(r"email=([^&]+)", url)
            em = unquote(m.group(1)).lower() if m else ""
            return dict(self.leads.get(em) or {})
        if "/category?" in url and method == "POST":
            self.category_posts.append((url, dict(body or {})))
            return {}
        if "hook.eu2.make.com" in url:
            self.hook_posts.append(dict(body or {}))
            return {}
        if "/message-history" in url:
            return {"history": []}
        return {}


def wire(sbfake, http):
    setter.configure(sb=sbfake, http_json=http,
                     keys={"OPENAI_API_KEY": "test-openai", "SMARTLEAD_API_KEY": "navreo-key"},
                     log_activity=lambda *a, **k: None)
    setter._sl_key = lambda: "navreo-key"
    setter._WS_KEY_FOR_CAMPAIGN = lambda cid: "krg-key"
    setter._CAT_FILL_TRIED.clear()
    try:
        setter._FACTS_CACHE.clear()
    except AttributeError:
        pass


WS = [{"id": "navreo", "api_key": None, "status": "enabled"},
      {"id": "krg", "api_key": "krg-key", "status": "enabled"},
      {"id": "asteri", "api_key": "asteri-key", "status": "enabled"},
      {"id": "paused", "api_key": "paused-key", "status": "disabled"},
      {"id": "nokey", "api_key": None, "status": "enabled"}]

EMAIL = "david.wilkins@northernpowergrid.com"
CID = 3824548
POSITIVE = "Hi Jane - happy to set something up for a quick chat.\n\nWhen were you thinking?\n\nThanks\nDave"


def reply(rid, ws="krg", cat=None, body=POSITIVE, minutes_ago=20.0, email=EMAIL, cid=CID):
    return {"id": rid, "workspace": ws, "smartlead_campaign_id": cid, "email": email,
            "replied_at": _iso(minutes_ago=minutes_ago), "category": cat, "reply_body": body,
            "smartlead_message_id": f"4405199849-{rid}", "notify_alerted_at": None,
            "notify_kind": None}


# ── 1. the David Wilkins case: model label -> Smartlead -> archive -> card, one tick ──
def test_positive_filled_and_carded_same_tick():
    sb = FakeSB(WS, [reply(1)])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("1a fill ok, one model call, filled from the model",
          res["ok"] and res["filled"] == 1 and res["from_model"] == 1 and res["model_calls"] == 1, res)
    check("1b archive row now carries Meeting Request",
          sb.row(1)["category"] == "Meeting Request", sb.row(1))
    check("1c the SENDABLE client's Smartlead got category id 2 on the right lead + campaign",
          len(http.category_posts) == 1
          and f"/campaigns/{CID}/leads/4405199849/category" in http.category_posts[0][0]
          and "api_key=krg-key" in http.category_posts[0][0]
          and http.category_posts[0][1] == {"category_id": 2}, http.category_posts)
    check("1d the model saw the prospect's text, not a quoted thread",
          "happy to set something up" in http.model_calls[0], http.model_calls)
    # the positive sweep that follows on the same tick cards it
    res2 = setter.run_client_positive_alerts()
    check("1e client positive sweep alerted exactly once", res2["alerted"] == 1 and res2["ok"], res2)
    post = http.hook_posts[0] if http.hook_posts else {}
    check("1f card went to #krg-advisors-navreo as a NEW positive",
          post.get("channel") == "C0A7EJ4DL9K" and "New positive reply" in post.get("text", ""), post)
    check("1g row stamped client-positive-alerted",
          sb.row(1)["notify_kind"] == "client-positive-alerted", sb.row(1))
    # a second tick finds nothing left to fill or card
    res3 = setter.run_client_category_fill()
    check("1h second tick: nothing to fill", res3["checked"] == 0 and res3["filled"] == 0, res3)


# ── 2. inside the grace window: the workspace's own categoriser goes first ──
def test_inside_grace_untouched():
    sb = FakeSB(WS, [reply(2, minutes_ago=3)])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("2 fresh reply not selected, no model call, archive untouched",
          res["checked"] == 0 and not http.model_calls and sb.row(2)["category"] is None, res)


# ── 3. Smartlead already carries a label -> adopt it, no model ──
def test_adopts_smartlead_label():
    sb = FakeSB(WS, [reply(3), reply(4, email="hot@lead.com")])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID, cat_id=2),
                           "hot@lead.com": lead("hot@lead.com", CID, cat_id=78386, lead_id=99)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("3a both filled from Smartlead, zero model calls",
          res["filled"] == 2 and res["from_smartlead"] == 2 and not http.model_calls, res)
    check("3b default id 2 -> Meeting Request", sb.row(3)["category"] == "Meeting Request", sb.row(3))
    check("3c custom positive id -> canonical Interested", sb.row(4)["category"] == "Interested", sb.row(4))
    check("3d nothing written back to Smartlead (it already has the label)",
          not http.category_posts, http.category_posts)


# ── 4. plainly automated mail: the rules pass labels it for free ──
def test_rules_label_machine_mail():
    ooo = "Thank you for your email. I am out of office until Monday 22 September with limited access to email."
    sb = FakeSB(WS, [reply(5, body=ooo)])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("4a labelled Out Of Office by rules, no model call",
          res["from_rules"] == 1 and sb.row(5)["category"] == "Out Of Office" and not http.model_calls, res)
    check("4b sendable client's Smartlead got the OOO id",
          http.category_posts and http.category_posts[0][1] == {"category_id": 6}, http.category_posts)


# ── 5. low confidence stays with a human, not re-asked every tick ──
def test_low_confidence_left_and_not_reasked():
    sb = FakeSB(WS, [reply(6, body="Hmm. Maybe. Who are you again?")])
    http = FakeHTTP(verdict={"category": "Interested", "confidence": 0.4},
                    leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("5a low confidence: left, not filled, archive untouched, still ok",
          res["ok"] and res["left"] == 1 and res["filled"] == 0 and sb.row(6)["category"] is None, res)
    res2 = setter.run_client_category_fill()
    check("5b next tick does not re-ask the model", len(http.model_calls) == 1 and res2["left"] == 1, res2)
    check("5c nothing written to Smartlead", not http.category_posts)


# ── 6. model down: loud, untouched, retried later ──
def test_model_failure_is_loud_and_retried_later():
    sb = FakeSB(WS, [reply(7)])
    http = FakeHTTP(fail_model=True, leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("6a model failure -> ok False, errors 1, no fill",
          not res["ok"] and res["errors"] == 1 and res["filled"] == 0 and sb.row(7)["category"] is None, res)
    res2 = setter.run_client_category_fill()
    check("6b not re-asked within the failure window", res2["model_calls"] == 0, res2)
    setter._CAT_FILL_TRIED[7] = (0.0, setter.CLIENT_CAT_FILL_FAIL_RETRY_MIN)   # window elapsed
    http.fail_model = False
    res3 = setter.run_client_category_fill()
    check("6c after the window it is asked again and filled",
          res3["filled"] == 1 and sb.row(7)["category"] == "Meeting Request", res3)


# ── 7. navreo / disabled / keyless workspaces are never touched ──
def test_other_workspaces_untouched():
    sb = FakeSB(WS, [reply(8, ws="navreo"), reply(9, ws="paused"), reply(10, ws="nokey")])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("7 no model calls, no patches, nothing checked",
          not http.model_calls and not sb.patches and res["checked"] == 0
          and set(res["workspaces"]) == {"krg", "asteri"}, res)


# ── 8. per-workspace model cap ──
def test_model_cap_per_tick():
    rows = [reply(100 + i, email=f"p{i}@x.com") for i in range(10)]
    sb = FakeSB(WS, rows)
    http = FakeHTTP(leads={f"p{i}@x.com": lead(f"p{i}@x.com", CID, lead_id=500 + i) for i in range(10)})
    wire(sb, http)
    old = setter.CLIENT_CAT_FILL_MODEL_CAP
    setter.CLIENT_CAT_FILL_MODEL_CAP = 8
    try:
        res = setter.run_client_category_fill()
    finally:
        setter.CLIENT_CAT_FILL_MODEL_CAP = old
    check("8 eight model calls, capped, two left for a later tick, still ok",
          res["ok"] and res["model_calls"] == 8 and res["filled"] == 8 and res["left"] == 2
          and res["workspaces"]["krg"]["capped"], res)


# ── 9. body-less reply: nothing to judge yet ──
def test_bodyless_left_alone():
    sb = FakeSB(WS, [reply(11, body="")])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("9 body-less: left, no model call, no patch",
          res["left"] == 1 and not http.model_calls and not sb.patches, res)


# ── 10. monitor-only workspace: archive yes, client's Smartlead never ──
def test_monitor_only_workspace_never_writes_smartlead():
    sb = FakeSB(WS, [reply(12, ws="asteri", email="tom@cultiv8.com")])
    http = FakeHTTP(leads={"tom@cultiv8.com": lead("tom@cultiv8.com", CID, lead_id=77)})
    wire(sb, http)
    check("10a asteri is monitor-only in this run", setter._is_monitor_ws("asteri"))
    res = setter.run_client_category_fill()
    check("10b archive stamped from the model", res["from_model"] == 1
          and sb.row(12)["category"] == "Meeting Request", res)
    check("10c no Smartlead category write for a monitor-only client", not http.category_posts,
          http.category_posts)


# ── 11. legacy uncategorised label is filled too ──
def test_legacy_label_is_uncategorised():
    sb = FakeSB(WS, [reply(13, cat=setter.UNCATEGORISED_LEGACY), reply(14, cat="")])
    http = FakeHTTP(leads={EMAIL: lead(EMAIL, CID)})
    wire(sb, http)
    res = setter.run_client_category_fill()
    check("11 legacy label + empty string both filled",
          res["filled"] == 2 and sb.row(13)["category"] == "Meeting Request"
          and sb.row(14)["category"] == "Meeting Request", res)


# ── 12. no Supabase ──
def test_no_supabase_skips():
    http = FakeHTTP()
    wire(FakeSB(WS, []), http)
    setter._SB = None
    try:
        res = setter.run_client_category_fill()
    finally:
        wire(FakeSB(WS, []), http)
    check("12 skipped without Supabase", res["skipped"] and res["ok"], res)


# ── 14. TypeSafe auto-reply gate ──
AUTOACK = "Hi Customer, thank you for reaching out. We will get back to you within 24 hours."


def _ts_http(p=None, fail=False, verdict=None):
    http = FakeHTTP(verdict=verdict or {"category": "Interested", "confidence": 0.9})
    inner = http.__call__
    http.ts_calls = []

    def call(method, url, headers=None, body=None, timeout=60):
        if "api.typesafe.ai" in url:
            http.ts_calls.append(body)
            if fail:
                raise OSError("typesafe down")
            return {"answers": {"automated": {"type": "noul", "noul": p}}}
        return inner(method, url, headers, body, timeout)
    return http, call


def _wire_ts(call, key="ts-key"):
    setter.configure(sb=FakeSB(WS, []), http_json=call,
                     keys={"OPENAI_API_KEY": "test-openai", "TYPESAFE_API_KEY": key},
                     log_activity=lambda *a, **k: None)


def test_typesafe_gate():
    http, call = _ts_http(p=0.95)
    _wire_ts(call)
    check("14a automated positive -> Out Of Office",
          setter._classify_client_reply(AUTOACK) == ("Out Of Office", 0.9))
    http, call = _ts_http(p=0.2)
    _wire_ts(call)
    check("14b human positive stays positive",
          setter._classify_client_reply(POSITIVE) == ("Interested", 0.9))
    http, call = _ts_http(p=0.95, verdict={"category": "Not Interested", "confidence": 0.9})
    _wire_ts(call)
    check("14c non-positive untouched, TypeSafe not asked",
          setter._classify_client_reply(AUTOACK) == ("Not Interested", 0.9) and not http.ts_calls)
    http, call = _ts_http(fail=True)
    _wire_ts(call)
    check("14d TypeSafe down -> gpt label kept",
          setter._classify_client_reply(AUTOACK) == ("Interested", 0.9))
    http, call = _ts_http(p=0.95)
    _wire_ts(call, key="")
    check("14e no TypeSafe key -> gpt label kept, no call",
          setter._classify_client_reply(AUTOACK) == ("Interested", 0.9) and not http.ts_calls)


# ── 13. helper edges ──
def test_helper_edges():
    http = FakeHTTP(verdict={"category": "Banana", "confidence": 0.99})
    wire(FakeSB(WS, []), http)
    check("13a off-list model answer -> None", setter._classify_client_reply(POSITIVE) is None)
    cats = {6: "Out Of Office", 2: "meeting request"}
    check("13b category id lookup is case-insensitive",
          setter._category_id_for_name(cats, "Meeting Request") == 2
          and setter._category_id_for_name(cats, "Call Booked") is None)
    before = len(http.model_calls)
    setter._KEYS = {}
    check("13c no OpenAI key -> None, no call", setter._classify_client_reply(POSITIVE) is None
          and len(http.model_calls) == before)


if __name__ == "__main__":
    for fn in (test_positive_filled_and_carded_same_tick, test_inside_grace_untouched,
               test_adopts_smartlead_label, test_rules_label_machine_mail,
               test_low_confidence_left_and_not_reasked, test_model_failure_is_loud_and_retried_later,
               test_other_workspaces_untouched, test_model_cap_per_tick, test_bodyless_left_alone,
               test_monitor_only_workspace_never_writes_smartlead, test_legacy_label_is_uncategorised,
               test_no_supabase_skips, test_helper_edges, test_typesafe_gate):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failing case
            check(f"{fn.__name__} crashed", False, f"{type(e).__name__}: {e}")
    sys.exit(1 if report() else 0)
