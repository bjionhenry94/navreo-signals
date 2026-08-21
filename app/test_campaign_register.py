"""Pure-python tests for the client-workspace reply-router webhook reconciler
(campaign_register.ensure_client_router_webhooks). NO network: `server` is
replaced with an in-memory fake and the module's Smartlead POST is captured, so
the test exercises the real reconcile logic without touching Smartlead/Supabase.
Run:  python3 test_campaign_register.py
Prints PASS/FAIL per case, exits 1 on any failure.

Covers the durable fix for the recurring 'client-workspace replies
uncategorised' incident (KRG 08-04/08-19/08-21, Grout 08-19):
  - a client campaign missing the router gets exactly one attach, payload shaped
    {name, webhook_url, event_types:[EMAIL_REPLY]} with NO `categories` key
  - a campaign that already carries the router is never re-POSTed (idempotent —
    the property that stops the cron spamming duplicate webhooks every tick)
  - navreo is never touched (its per-campaign webhooks would suppress the
    workspace categoriser), nor is any workspace absent from CLIENT_ROUTER_HOOKS
  - a webhook-GET failure (None) is recorded as an error and never attached
  - a long-finished campaign outside the window is skipped; ACTIVE/PAUSED/DRAFTED
    are always checked
  - only_ws restricts the run
"""

import datetime as dt
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Stub `server` BEFORE importing campaign_register so the heavy real module
# (which does live Supabase/Smartlead init on import) never loads — every test
# swaps in its own FakeServer at run time anyway. Keeps the suite hermetic: no
# network, no env, fast. Mirrors what the real server exposes to cr at module
# scope (nothing beyond the name), so the import is a no-op bind.
sys.modules.setdefault("server", types.ModuleType("server"))
import campaign_register as cr  # noqa: E402

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


def _iso(days_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


class FakeServer:
    """In-memory stand-in for the bits ensure_client_router_webhooks touches.

    `campaigns` maps workspace id -> list of campaign dicts. `webhooks` maps
    campaign id -> list of {webhook_url}. A campaign id present in `gets_fail`
    makes its webhook GET raise. `sb_posts` records the signal_cron_runs row."""

    SMARTLEAD_BASE = "https://sl.example/api/v1"
    UA = "test-ua"
    SSL_CTX = None

    def __init__(self, workspaces, campaigns, webhooks, gets_fail=None):
        self._ws = workspaces
        self._camps = campaigns
        self._webhooks = webhooks
        self._gets_fail = set(gets_fail or [])
        self.sb_posts = []

    def ws_enabled(self):
        return list(self._ws)

    def ws_key(self, wid):
        for w in self._ws:
            if w.get("id") == wid:
                return w.get("api_key") or ""
        return ""

    def _sl_campaigns_for_ws(self, wkey):
        for w in self._ws:
            if w.get("api_key") == wkey:
                return list(self._camps.get(w["id"], []))
        return []

    def _smartlead_get_retry(self, url):
        m = re.search(r"/campaigns/(\d+)/webhooks", url)
        cid = int(m.group(1)) if m else None
        if cid in self._gets_fail:
            raise RuntimeError("boom")
        return {"data": list(self._webhooks.get(cid, []))}

    def sb(self, method, path, body=None, prefer=""):
        if path == "signal_cron_runs":
            self.sb_posts.append(body)
        return []


def run_case(fake, posts_recorder, **kwargs):
    """Wire the fake, capture _attach_router's POST url+body, run the reconcile."""
    cr.server = fake
    calls = []

    def _capture(url, body, attempts=4):
        calls.append({"url": url, "body": body})
        return {"ok": True, "id": 999}

    orig = cr._smartlead_post
    cr._smartlead_post = _capture
    orig_pace = cr.ROUTER_ATTACH_PACE_S
    cr.ROUTER_ATTACH_PACE_S = 0  # no real sleeps in tests
    try:
        out = cr.ensure_client_router_webhooks(**kwargs)
    finally:
        cr._smartlead_post = orig
        cr.ROUTER_ATTACH_PACE_S = orig_pace
    posts_recorder.extend(calls)
    return out


KRG_URL = cr.CLIENT_ROUTER_HOOKS["krg"]


def test_missing_gets_attached_with_correct_payload():
    fake = FakeServer(
        workspaces=[{"id": "krg", "api_key": "KKEY", "status": "enabled"}],
        campaigns={"krg": [{"id": 111, "name": "KRG - New", "status": "ACTIVE",
                            "created_at": _iso(1)}]},
        webhooks={111: []},  # no router
    )
    posts = []
    out = run_case(fake, posts)
    check("missing: exactly one attach POST", len(posts) == 1, posts)
    if posts:
        b = posts[0]["body"]
        check("missing: POST url targets the campaign's webhooks",
              posts[0]["url"] == f"{fake.SMARTLEAD_BASE}/campaigns/111/webhooks?api_key=KKEY",
              posts[0]["url"])
        check("missing: webhook_url is the KRG router", b.get("webhook_url") == KRG_URL, b)
        check("missing: event_types == [EMAIL_REPLY]", b.get("event_types") == ["EMAIL_REPLY"], b)
        check("missing: name is the router name", b.get("name") == cr.ROUTER_WEBHOOK_NAME, b)
        check("missing: categories key is OMITTED (create API rejects [])",
              "categories" not in b, b)
    check("missing: summary counts one attach", len(out["attached"]) == 1, out)
    check("missing: summary records zero already", out["already"] == 0, out)


def test_already_present_is_idempotent():
    fake = FakeServer(
        workspaces=[{"id": "krg", "api_key": "KKEY", "status": "enabled"}],
        campaigns={"krg": [{"id": 222, "name": "KRG - Covered", "status": "ACTIVE",
                            "created_at": _iso(1)}]},
        webhooks={222: [{"webhook_url": KRG_URL}]},  # already has router
    )
    posts = []
    out = run_case(fake, posts)
    check("idempotent: NO attach POST when router already present", posts == [], posts)
    check("idempotent: summary counts one already-covered", out["already"] == 1, out)
    check("idempotent: nothing in attached", out["attached"] == [], out)


def test_navreo_never_touched():
    fake = FakeServer(
        workspaces=[{"id": "navreo", "api_key": "NKEY", "status": "enabled"},
                    {"id": "mystery", "api_key": "MKEY", "status": "enabled"}],
        campaigns={"navreo": [{"id": 1, "name": "n", "status": "ACTIVE", "created_at": _iso(1)}],
                   "mystery": [{"id": 2, "name": "m", "status": "ACTIVE", "created_at": _iso(1)}]},
        webhooks={1: [], 2: []},
    )
    posts = []
    out = run_case(fake, posts)
    check("navreo/unknown-ws: no POSTs at all", posts == [], posts)
    check("navreo/unknown-ws: no workspace processed", out["workspaces"] == [], out)


def test_get_failure_is_error_not_attach():
    fake = FakeServer(
        workspaces=[{"id": "krg", "api_key": "KKEY", "status": "enabled"}],
        campaigns={"krg": [{"id": 333, "name": "KRG - Blip", "status": "ACTIVE",
                            "created_at": _iso(1)}]},
        webhooks={333: []},
        gets_fail={333},
    )
    posts = []
    out = run_case(fake, posts)
    check("get-fail: never attaches on a fetch error", posts == [], posts)
    check("get-fail: recorded as an error", len(out["errors"]) == 1, out)


def test_window_skips_old_completed_checks_recent_and_draft():
    fake = FakeServer(
        workspaces=[{"id": "krg", "api_key": "KKEY", "status": "enabled"}],
        campaigns={"krg": [
            {"id": 401, "name": "old done", "status": "COMPLETED", "created_at": _iso(400)},
            {"id": 402, "name": "recent done", "status": "COMPLETED", "created_at": _iso(3)},
            {"id": 403, "name": "draft", "status": "DRAFTED", "created_at": _iso(400)},
        ]},
        webhooks={401: [], 402: [], 403: []},
    )
    posts = []
    out = run_case(fake, posts)
    attached_ids = {p["url"] for p in posts}
    check("window: old COMPLETED (>60d) not checked", out["checked"] == 2, out)
    check("window: recent COMPLETED attached",
          any("/campaigns/402/" in u for u in attached_ids), attached_ids)
    check("window: DRAFTED always attached regardless of age",
          any("/campaigns/403/" in u for u in attached_ids), attached_ids)
    check("window: old COMPLETED never attached",
          not any("/campaigns/401/" in u for u in attached_ids), attached_ids)


def test_only_ws_restricts():
    fake = FakeServer(
        workspaces=[{"id": "krg", "api_key": "KKEY", "status": "enabled"},
                    {"id": "grout", "api_key": "GKEY", "status": "enabled"}],
        campaigns={"krg": [{"id": 501, "name": "k", "status": "ACTIVE", "created_at": _iso(1)}],
                   "grout": [{"id": 601, "name": "g", "status": "ACTIVE", "created_at": _iso(1)}]},
        webhooks={501: [], 601: []},
    )
    posts = []
    out = run_case(fake, posts, only_ws=["krg"])
    check("only_ws: just the one workspace processed",
          [w["id"] for w in out["workspaces"]] == ["krg"], out)
    check("only_ws: grout campaign not attached",
          all("/campaigns/601/" not in p["url"] for p in posts), posts)
    check("only_ws: grout uses ITS OWN router url when run",
          cr.CLIENT_ROUTER_HOOKS["grout"] != KRG_URL)


if __name__ == "__main__":
    test_missing_gets_attached_with_correct_payload()
    test_already_present_is_idempotent()
    test_navreo_never_touched()
    test_get_failure_is_error_not_attach()
    test_window_skips_old_completed_checks_recent_and_draft()
    test_only_ws_restricts()
    sys.exit(1 if report() else 0)
