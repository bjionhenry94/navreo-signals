"""Pure-python tests for "the client share token wins over the owner session"
and for the scoped pill counts a share LIST now carries (2026-09-05).

Proven live before the fix: GET /api/setter/queue?...&share=<touchpoint> WITH
a valid owner navreo_session cookie answered 177 rows over 50 campaigns in two
workspaces plus the account-wide kpis block; the same URL without the cookie
answered 29 rows on 9 campaigns and no kpis at all. A client link has to
resolve to the same view for everyone who opens it, and the client page's
filter chips need badges that match the list under them.

NO network: Supabase is an in-memory fake, exactly like test_client_share_links.
Run: python3 test_share_token_wins.py  (exit 1 on any failure)
"""
import sys

import server
import setter

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS: " if cond else "FAIL: ") + name + (f"  {extra}" if (extra and not cond) else ""))


# ── the fake corpus ────────────────────────────────────────────────────────
# Two clients' campaigns plus a Navreo-own one, so "did the scope actually
# apply?" is answerable by counting rows, not by trusting a flag.
DRAFTS = [
    {"id": "camp-sl-100", "client_id": "touchpoint", "name": "TouchPoint C3 - Shopping"},
    {"id": "camp-sl-101", "client_id": "touchpoint", "name": "TouchPoint C4 - Retail"},
    {"id": "camp-sl-200", "client_id": "grout", "name": "Grout - SaaS CEOs"},
    {"id": "camp-sl-900", "client_id": "navreo", "name": "Navreo | Agencies | v3"},
]

# id, campaign, status, category, is_test, last_type ("REPLY" = the lead spoke
# last -> Needs review; "SENT" = we answered it -> the Sent pill).
QUEUE = [
    # --- touchpoint (in scope for the token under test) ---
    {"id": 1, "smartlead_campaign_id": "100", "status": "needs_review",
     "category": "Interested", "lead_email": "a@x.com", "last_type": "REPLY"},
    {"id": 2, "smartlead_campaign_id": "100", "status": "needs_review",
     "category": "Meeting Request", "lead_email": "b@x.com", "last_type": "REPLY"},
    # answered, still stored needs_review -> counts as Sent, not Needs review
    {"id": 3, "smartlead_campaign_id": "101", "status": "needs_review",
     "category": "Interested", "lead_email": "c@x.com", "last_type": "SENT",
     "sent_at": "2026-09-04T10:00:00+00:00", "decision": "auto_send"},
    {"id": 4, "smartlead_campaign_id": "101", "status": "sent",
     "category": "Interested", "lead_email": "d@x.com"},
    {"id": 5, "smartlead_campaign_id": "100", "status": "auto_sent",
     "category": "Meeting Request", "lead_email": "e@x.com"},
    {"id": 6, "smartlead_campaign_id": "101", "status": "dismissed",
     "category": "Meeting Request", "lead_email": "f@x.com"},
    # older sibling of row 1's thread: collapsed away, must not be counted twice
    {"id": 7, "smartlead_campaign_id": "100", "status": "needs_review",
     "category": "Interested", "lead_email": "A@X.com", "last_type": "REPLY",
     "replied_at": "2026-09-01T09:00:00+00:00"},
    # test row: only a TEST-flagged token may see it
    {"id": 8, "smartlead_campaign_id": "100", "status": "needs_review",
     "category": "Interested", "lead_email": "t@x.com", "last_type": "REPLY",
     "is_test": True},
    # --- another client + Navreo-own: must never be counted or listed ---
    {"id": 20, "smartlead_campaign_id": "200", "status": "needs_review",
     "category": "Interested", "lead_email": "g@y.com", "last_type": "REPLY"},
    {"id": 21, "smartlead_campaign_id": "200", "status": "sent",
     "category": "Interested", "lead_email": "h@y.com"},
    {"id": 90, "smartlead_campaign_id": "900", "status": "needs_review",
     "category": "Interested", "lead_email": "i@z.com", "last_type": "REPLY"},
]


def _row(r):
    out = {"replied_at": "2026-09-05T10:00:00+00:00",
           "created_at": "2026-09-05T10:00:00+00:00",
           "workspace": "navreo", "is_test": False, "sent_at": None,
           "decision": None, "thread": None}
    out.update(r)
    return out


class FakeSB:
    """Answers the handful of PostgREST shapes this seam issues, honouring the
    filters that carry the scope (smartlead_campaign_id=in.(...), is_test,
    status) so a missing filter shows up as EXTRA ROWS, not as a pass."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None, prefer=""):
        self.calls.append((method, path))
        table, _, qs = path.partition("?")
        if table == "campaign_drafts":
            return [dict(d) for d in DRAFTS]
        if table == "campaigns":
            return []
        if table != setter.QUEUE_TABLE:
            return []
        from urllib.parse import unquote
        rows = [_row(r) for r in QUEUE]
        limit = offset = None
        for part in qs.split("&"):
            key, _, val = part.partition("=")
            if key == "limit":
                limit = int(val)
            elif key == "offset":
                offset = int(val)
            elif key == "id" and val.startswith("eq."):
                rows = [r for r in rows if str(r["id"]) == val[3:]]
            elif key == "lead_email" and val.startswith("ilike."):
                want = unquote(val[6:]).lower()
                rows = [r for r in rows if str(r.get("lead_email") or "").lower() == want]
            elif key == "message_id" and val.startswith("eq."):
                rows = [r for r in rows if str(r.get("message_id") or "") == unquote(val[3:])]
            elif key == "smartlead_campaign_id" and val.startswith("in."):
                ids = set(val[4:-1].split(","))
                rows = [r for r in rows if str(r["smartlead_campaign_id"]) in ids]
            elif key == "is_test" and val == "eq.false":
                rows = [r for r in rows if not r.get("is_test")]
            elif key == "status" and val.startswith("eq."):
                rows = [r for r in rows if r["status"] == val[3:]]
            elif key == "status" and val.startswith("in."):
                want = set(val[4:-1].split(","))
                rows = [r for r in rows if r["status"] in want]
            elif key == "status" and val.startswith("neq."):
                rows = [r for r in rows if r["status"] != val[4:]]
            elif key == "category" and val.startswith("eq."):
                rows = [r for r in rows if r.get("category") == unquote(val[3:])]
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows


def wire():
    """Fresh fake + every cache this seam reads, cleared. Also clears the
    share scope, so a test that forgot to enter one fails loudly."""
    sb = FakeSB()
    setter._SB = sb
    setter._SB_COUNT = None          # exercise the list-length fallback
    setter._KEYS = {"SUPABASE_SERVICE_ROLE_KEY": "test-secret"}
    setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})
    setter._PARENT_CACHE.update({"at": 0.0, "map": None})
    setter._REP_IDS_CACHE.update({"at": 0.0, "val": None, "rows": None,
                                  "rows_at": 0.0, "truncated_until": 0.0})
    setter._ROWS_CACHE.clear()
    setter.client_share_clear()
    return sb


# ── 1. the request gate: the token wins over the session ───────────────────
def test_gate_token_wins():
    g = server._in_client_share
    wire()
    tok = setter.mint_client_share("touchpoint", 1)   # a REAL client token
    junk = "some-token"                               # not a client token
    check("1a share= on an allowlisted GET enters the scope WITH an owner session",
          g("/api/setter/queue", tok, True) is True)
    check("1b same route, same token, no session -> unchanged",
          g("/api/setter/queue", tok, False) is True)
    check("1c owner GET with NO share= is untouched",
          g("/api/setter/queue", "", True) is False)
    check("1d logged-out GET with no token still reaches the 403 gate",
          g("/api/setter/queue", "", False) is True)
    check("1e a TRAINING token never enters the client share (different family)",
          g("/api/setter/training", setter.mint_training_share("agent-1"), True) is False
          and g("/api/setter/training", setter.mint_training_share("agent-1"), False) is False)
    check("1f a route with no token and no session is only 'share' when allowlisted",
          g("/api/setter/agents", "", False) is False
          and g("/api/setter/agents", junk, True) is False)
    # A VALID client token must never ride an OWNER-scoped answer, whatever the
    # route: it enters the share so client_share_enter 403s the non-allowlisted
    # ones. /api/setter/agents and the two Smartlead search routes answered
    # owner-wide to a logged-in owner before this clause (live matrix 2026-09-05).
    check("1k a valid client token on a NON-allowlisted setter route enters the share",
          g("/api/setter/agents", tok, True) is True
          and g("/api/setter/search-smartlead", tok, True) is True
          and g("/api/setter/smartlead-thread", tok, True) is True)
    check("1l ...and client_share_enter then 403s it",
          (setter.client_share_enter("/api/setter/agents", tok) or (0,))[0] == 403)
    setter.client_share_clear()
    check("1g the WRITE allowlist is the one consulted for writes",
          g("/api/setter/queue/action", junk, False, write=True) is True
          and g("/api/setter/queue/action", junk, True) is False)
    check("1h an unallowlisted verb/route pair is share-mode-then-403, never owner",
          g("/api/setter/queue", tok, True, write=True) is True
          and (setter.client_share_enter("/api/setter/queue", tok, write=True)
               or (0,))[0] == 403)
    check("1i /app/setter.html is handled by the STATIC gate, not this predicate",
          "/app/setter.html" in server._CLIENT_SHARE_GET
          and "/app/setter.html" not in setter.CLIENT_SHARE_GET)
    # A bad token is 403'd by client_share_enter, not waved through as owner.
    wire()
    check("1j gate says 'share' for a bad token; client_share_enter then 403s",
          g("/api/setter/queue", "not-a-token", True) is True
          and (setter.client_share_enter("/api/setter/queue", "not-a-token") or (0,))[0] == 403)
    setter.client_share_clear()


# ── 2. entering the scope actually scopes the read ─────────────────────────
def test_scope_applies():
    wire()
    tok = setter.mint_client_share("touchpoint", 1)
    check("2a a valid touchpoint token enters the scope",
          setter.client_share_enter("/api/setter/queue", tok) is None)
    check("2b scope is exactly touchpoint's two campaigns",
          setter._share_scope() == frozenset({"100", "101"}), str(setter._share_scope()))
    st, body = setter.route_queue_get({"status": [""], "limit": ["200"], "fields": ["list"]})
    ids = sorted(r["id"] for r in body["rows"])
    check("2c LIST returns only in-scope, non-test, thread-collapsed rows",
          st == 200 and ids == [1, 2, 3, 4, 5, 6], str(ids))
    check("2d no other client's row leaked", not any(i in ids for i in (20, 21, 90)))
    setter.client_share_clear()
    # The same call with NO scope is the owner's, and is unchanged: it still
    # carries the owner kpis + last_checked blocks, not the share's counts.
    st2, body2 = setter.route_queue_get({"status": [""], "limit": ["200"]})
    check("2e owner response (no share) still carries kpis + last_checked",
          st2 == 200 and "kpis" in body2 and "last_checked" in body2, str(sorted(body2)))
    check("2f owner kpis is the full account-wide block, not the five counts",
          "avg_response_mins_7d" in (body2.get("kpis") or {}), str(sorted(body2.get("kpis") or {})))


# ── 3. the five scoped counts ──────────────────────────────────────────────
def test_share_counts_shape_and_values():
    wire()
    tok = setter.mint_client_share("touchpoint", 1)
    setter.client_share_enter("/api/setter/queue", tok)
    st, body = setter.route_queue_get({"status": [""], "limit": ["200"], "fields": ["list"]})
    counts = ((body.get("kpis") or {}).get("counts") or {})
    check("3a share LIST carries kpis.counts", st == 200 and counts, str(body.get("kpis")))
    check("3b exactly the five client keys, nothing else",
          sorted(counts) == ["all", "dismissed", "meeting_request", "needs_review", "sent"],
          str(sorted(counts)))
    check("3c kpis carries ONLY counts (no ops telemetry)",
          sorted(body.get("kpis") or {}) == ["counts"], str(sorted(body.get("kpis") or {})))
    # rows 1,2 await us; 7 is 1's collapsed-away sibling; 8 is a test row.
    check("3d needs_review counts answered-away and collapsed rows out",
          counts["needs_review"] == 2, str(counts))
    # 4 (sent) + 5 (auto_sent, folded in) + 3 (answered needs_review)
    check("3e sent folds auto_sent and answered needs_review in",
          counts["sent"] == 3, str(counts))
    check("3f dismissed", counts["dismissed"] == 1, str(counts))
    # 2 and 5 are Meeting Request and not dismissed; 6 is dismissed -> out.
    check("3g meeting_request is cross-status but drops dismissed",
          counts["meeting_request"] == 2, str(counts))
    check("3h all = every in-scope representative row",
          counts["all"] == 6, str(counts))
    check("3i the badges add up to the list they sit over",
          counts["all"] == len(body["rows"]), f"{counts} vs {len(body['rows'])}")
    setter.client_share_clear()


def test_counts_are_scoped_per_client():
    wire()
    setter.client_share_enter("/api/setter/queue", setter.mint_client_share("grout", 1))
    _st, body = setter.route_queue_get({"status": [""], "limit": ["200"]})
    counts = body["kpis"]["counts"]
    check("4a grout's token counts only grout's rows",
          counts == {"needs_review": 1, "sent": 1, "meeting_request": 0,
                     "dismissed": 0, "all": 2}, str(counts))
    setter.client_share_clear()


def test_test_token_includes_test_rows():
    wire()
    setter.client_share_enter("/api/setter/queue", setter.mint_client_share("touchpoint", 1))
    plain = setter.route_queue_get({"status": [""], "limit": ["200"]})[1]["kpis"]["counts"]
    setter.client_share_clear()
    wire()
    qa_tok = setter.mint_client_share("touchpoint", 1, test=True)
    check("5a a test-flagged token verifies with the flag set",
          setter.verify_client_share(qa_tok) == ("touchpoint", True))
    setter.client_share_enter("/api/setter/queue", qa_tok)
    check("5b _share_test_ok is on inside a TEST share", setter._share_test_ok() is True)
    qa = setter.route_queue_get({"status": [""], "limit": ["200"]})[1]["kpis"]["counts"]
    setter.client_share_clear()
    check("5c a plain token does NOT count the is_test row",
          plain["needs_review"] == 2 and plain["all"] == 6, str(plain))
    check("5d a TEST token DOES count it (one extra needs_review, one extra all)",
          qa["needs_review"] == 3 and qa["all"] == 7, str(qa))
    check("5e the test row moves nothing else",
          {k: qa[k] for k in ("sent", "dismissed", "meeting_request")}
          == {k: plain[k] for k in ("sent", "dismissed", "meeting_request")}, str(qa))


# ── 6. the counts survive the share sanitiser ──────────────────────────────
def test_sanitise_keeps_counts():
    wire()
    setter.client_share_enter("/api/setter/queue", setter.mint_client_share("touchpoint", 1))
    _st, body = setter.route_queue_get({"status": [""], "limit": ["200"]})
    out = setter.share_sanitise(body)
    counts = ((out.get("kpis") or {}).get("counts") or {})
    check("6a share_sanitise does not strip kpis.counts",
          sorted(counts) == ["all", "dismissed", "meeting_request", "needs_review", "sent"],
          str(out.get("kpis")))
    check("6b the sanitised body still carries rows", bool(out.get("rows")))
    check("6c auto_sent rows are still served to a client as plain 'sent'",
          all(r.get("status") != "auto_sent" for r in out["rows"]),
          str([r.get("status") for r in out["rows"]]))
    # queue_response is the byte path the server actually serves.
    import json
    st, enc, raw = setter.queue_response({"status": [""], "limit": ["200"], "fields": ["list"]}, False)
    served = json.loads(raw.decode())
    check("6d queue_response serves the same five counts",
          st == 200 and enc is None
          and sorted(served["kpis"]["counts"]) == ["all", "dismissed", "meeting_request",
                                                   "needs_review", "sent"],
          str(served.get("kpis")))
    setter.client_share_clear()


# ── 7. degraded paths: a broken badge must never sink the list ─────────────
def test_counts_degrade_safely():
    wire()
    setter.client_share_enter("/api/setter/queue", setter.mint_client_share("touchpoint", 1))

    class DeadLight(FakeSB):
        """The 3-page light scan fails; the header-count fallback still works."""
        def __call__(self, method, path, body=None, prefer=""):
            if path.startswith(setter.QUEUE_TABLE + "?") and "&limit=1000&offset=" in path:
                return None
            return super().__call__(method, path, body, prefer)

    setter._SB = DeadLight()
    setter._REP_IDS_CACHE.update({"at": 0.0, "val": None, "rows": None, "rows_at": 0.0})
    counts = setter._share_counts()
    check("7a a failed light scan degrades to header counts, still five keys",
          sorted(counts) == ["all", "dismissed", "meeting_request", "needs_review", "sent"],
          str(counts))
    # Uncollapsed and un-reclassified by design (the owner's fallback is too):
    # in-scope non-test rows are 1-7, of which 1,2,3,7 are stored needs_review.
    check("7b the fallback stays inside the scope and off the test row",
          counts["all"] == 7 and counts["needs_review"] == 4
          and counts["sent"] == 2 and counts["dismissed"] == 1, str(counts))

    class Dead(FakeSB):
        def __call__(self, method, path, body=None, prefer=""):
            raise OSError("supabase down")

    setter._SB = Dead()
    setter._REP_IDS_CACHE.update({"at": 0.0, "val": None, "rows": None, "rows_at": 0.0})
    counts2 = setter._share_counts()
    check("7c a total outage answers five zeros, never raises",
          counts2 == {"needs_review": 0, "sent": 0, "meeting_request": 0,
                      "dismissed": 0, "all": 0}, str(counts2))
    setter.client_share_clear()
    check("7d outside a share the counts are all zero (owner path untouched)",
          setter._share_counts() == {"needs_review": 0, "sent": 0, "meeting_request": 0,
                                     "dismissed": 0, "all": 0})


# ── 8. search stays local to the scoped list ───────────────────────────────
def test_search_routes_not_allowlisted():
    check("8a /api/setter/search-smartlead is NOT share-allowlisted",
          "/api/setter/search-smartlead" not in setter.CLIENT_SHARE_GET
          and "/api/setter/search-smartlead" in setter.GET_ROUTES)
    check("8b /api/setter/smartlead-thread is NOT share-allowlisted",
          "/api/setter/smartlead-thread" not in setter.CLIENT_SHARE_GET
          and "/api/setter/smartlead-thread" in setter.GET_ROUTES)
    wire()
    tok = setter.mint_client_share("touchpoint", 1)
    check("8c a valid token on either search route is 403'd, never answered",
          (setter.client_share_enter("/api/setter/search-smartlead", tok) or (0,))[0] == 403
          and (setter.client_share_enter("/api/setter/smartlead-thread", tok) or (0,))[0] == 403)
    setter.client_share_clear()
    # /queue/locate IS allowlisted, and is scoped in the query AND in Python.
    wire()
    setter.client_share_enter("/api/setter/queue/locate", setter.mint_client_share("touchpoint", 1))
    st, body = setter.route_queue_locate_get({"email": ["a@x.com"]})
    check("8d locate resolves an in-scope lead", st == 200 and body["row"]["id"] == 1, str(body))
    st2, _ = setter.route_queue_locate_get({"email": ["g@y.com"]})
    check("8e locate 404s another client's lead (never 403 - ids stay unenumerable)", st2 == 404)
    setter.client_share_clear()


if __name__ == "__main__":
    test_gate_token_wins()
    test_scope_applies()
    test_share_counts_shape_and_values()
    test_counts_are_scoped_per_client()
    test_test_token_includes_test_rows()
    test_sanitise_keeps_counts()
    test_counts_degrade_safely()
    test_search_routes_not_allowlisted()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} pass")
    sys.exit(1 if failed else 0)
