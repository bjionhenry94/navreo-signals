"""Pure-python tests for NAVREO_HOSTED_CLIENTS - the ONE registry every
navreo-hosted client routing map derives from (Bjion 2026-09-16: "whenever we
onboard any client, they're also onboarded to this").

Locks: (1) a client is either fully wired or absent - every marker has a share
client_id, a shared channel, a flip channel, and its channel is client-facing;
(2) a client whose FRESH positives Make 8946472 already cards ("make" lane) is
never double-carded by the app lane, but its positive RE-REPLIES (which routeB
labels and Make never sees - the Komal Vaish / ThunderBird gap) DO reach the
shared channel; (3) an "app" lane client (REViVE) still gets fresh positives
from the app lane. NO network. Run: python3 test_client_routing_registry.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setter  # noqa: E402
from test_ever_positive import (FakeSB, FakeHTTP, wire, _iso, _stamped,  # noqa: E402
                                check, report)

TB_SHARED = "C0BFDEF6388"     # #thunderbirdleadership-navreo
REVIVE_SHARED = "C0BP9A6D28H"  # #revive-navreo
TB_CAMP = {"workspace": "navreo", "smartlead_campaign_id": 3800129, "client_id": "navreo",
           "name": "Thunderbird Campaign 4 (financial services)"}
REVIVE_CAMP = {"workspace": "navreo", "smartlead_campaign_id": 3879940, "client_id": "navreo",
               "name": "REViVE | Beauty & Personal Care | Cold - Aug26"}


def _rows(camp_id, category, with_prior=True):
    rows = []
    if with_prior:
        rows.append({"id": 1, "workspace": "navreo", "smartlead_campaign_id": camp_id,
                     "email": "komal@loanfactory.com", "replied_at": _iso(hours_ago=40),
                     "category": "Interested", "reply_body": "sure, send it",
                     "notify_alerted_at": "2026-09-10T00:00:00+00:00"})
    rows.append({"id": 21, "workspace": "navreo", "smartlead_campaign_id": camp_id,
                 "email": "komal@loanfactory.com", "replied_at": _iso(hours_ago=1),
                 "category": category, "reply_body": "please send me the video",
                 "notify_alerted_at": None})
    return rows


def _run(camp, category, verdict=None, with_prior=True):
    sb = FakeSB(_rows(camp["smartlead_campaign_id"], category, with_prior), campaigns=[dict(camp)])
    http = FakeHTTP()
    wire(sb, http)
    # share-link minting needs the signing key + a cold campaign->client cache
    setter._KEYS = {"SUPABASE_SERVICE_ROLE_KEY": "test-secret"}
    setter._CLIENT_CAMPAIGNS_CACHE.update({"at": 0.0, "map": None})
    setter._PARENT_CACHE.update({"at": 0.0, "map": None})
    real = setter._ep_classify_re_reply
    if verdict is not None:
        setter._ep_classify_re_reply = lambda row: verdict
    try:
        res = setter.run_ever_positive_alerts()
    finally:
        setter._ep_classify_re_reply = real
    return sb, http, res


def test_registry_is_complete():
    reg = setter.NAVREO_HOSTED_CLIENTS
    ids = dict(setter.CLIENT_NAME_CLIENT_IDS)
    check("1a registry is non-empty", len(reg) >= 5, str(len(reg)))
    for c in reg:
        t = c["token"]
        check(f"1b {t}: token is a lowercase name marker", t == t.lower().strip() and " " not in t)
        check(f"1c {t}: in CLIENT_NAME_MARKERS", t in setter.CLIENT_NAME_MARKERS)
        check(f"1d {t}: has a share client_id", ids.get(t) == c["client_id"] and bool(c["client_id"]))
        check(f"1e {t}: has a real Slack channel id", bool(re.fullmatch(r"C[A-Z0-9]{8,}", c["shared"])), c["shared"])
        check(f"1f {t}: fresh positives -> POSITIVE_SHARED_CHANNELS", setter.POSITIVE_SHARED_CHANNELS.get(t) == c["shared"])
        check(f"1g {t}: churn flips -> FLIP_NAME_CHANNELS", setter.FLIP_NAME_CHANNELS.get(t) == c["shared"])
        check(f"1h {t}: channel is client-facing (card link = share link)", c["shared"] in setter.CLIENT_FACING_CHANNELS)
        check(f"1i {t}: fresh_lane is make|app", c["fresh_lane"] in ("make", "app"), c["fresh_lane"])
    check("1j every marker comes from the registry (no orphan marker)",
          set(setter.CLIENT_NAME_MARKERS) == {c["token"] for c in reg})
    check("1k tokens are unique", len({c["token"] for c in reg}) == len(reg))
    check("1l shared channels are unique", len({c["shared"] for c in reg}) == len(reg))
    check("1m internal channel never in the registry",
          setter.CLIENT_INTERNAL_CHANNEL not in {c["shared"] for c in reg})
    check("1n ThunderBird is wired to #thunderbirdleadership-navreo",
          setter.POSITIVE_SHARED_CHANNELS.get("thunderbird") == TB_SHARED)
    check("1o Make-owned fresh lanes are exactly the 8946472 name routes",
          set(setter.POSITIVE_FRESH_MAKE_OWNED) == {"thunderbird", "touchpoint", "altius"},
          str(sorted(setter.POSITIVE_FRESH_MAKE_OWNED)))


def test_make_lane_fresh_positive_not_double_carded():
    sb, http, res = _run(TB_CAMP, "Interested", with_prior=False)
    check("2a ThunderBird fresh positive: app lane posts nothing (Make 8946472 route 220 cards it)",
          len(http.posts) == 0, str(http.posts)[:200])
    check("2b ...row stamped positive-covered", _stamped(sb, 21, "positive-covered"), str(sb.patches))


def test_make_lane_re_reply_reaches_shared_channel():
    sb, http, res = _run(TB_CAMP, "positive-re-reply", verdict="Interested")
    body = http.posts[0][1] if http.posts else {}
    text = body.get("text", "")
    check("3a ThunderBird positive re-reply posts exactly once", len(http.posts) == 1 and res["alerted"] == 1, str(res))
    check("3b ...into #thunderbirdleadership-navreo", body.get("channel") == TB_SHARED, str(body.get("channel")))
    check("3c ...as the client-safe conversation frame",
          text.startswith("*\U0001F501 Reply in ongoing conversation") and "positive-re-reply" not in text, text[:120])
    check("3d ...card link is the client share link, not the owner permalink",
          "?share=" in text and "setter.html#/r/" not in text, text[-200:])
    check("3e ...stamped positive-shared", _stamped(sb, 21, "positive-shared"), str(sb.patches))


def test_make_lane_re_reply_flip_reaches_shared_channel():
    sb, http, res = _run(TB_CAMP, "positive-re-reply", verdict="Not Interested")
    body = http.posts[0][1] if http.posts else {}
    check("4a ThunderBird churn flip posts once", len(http.posts) == 1 and res.get("re_reply_flips") == 1, str(res))
    check("4b ...into #thunderbirdleadership-navreo", body.get("channel") == TB_SHARED, str(body.get("channel")))
    check("4c ...stamped re-reply-flip-alerted", _stamped(sb, 21, "re-reply-flip-alerted"), str(sb.patches))


def test_app_lane_fresh_positive_still_posts():
    sb, http, res = _run(REVIVE_CAMP, "Interested", with_prior=False)
    body = http.posts[0][1] if http.posts else {}
    check("5a REViVE fresh positive still posts once from the app lane", len(http.posts) == 1, str(res))
    check("5b ...into #revive-navreo", body.get("channel") == REVIVE_SHARED, str(body.get("channel")))
    check("5c ...stamped positive-shared", _stamped(sb, 21, "positive-shared"), str(sb.patches))


def test_unregistered_name_stays_internal():
    camp = {"workspace": "navreo", "smartlead_campaign_id": 1, "client_id": "navreo", "name": "Navreo | Agencies | v3"}
    sb, http, res = _run(camp, "Interested", with_prior=False)
    check("6a Navreo-own fresh positive: nothing from the app lane", len(http.posts) == 0, str(http.posts)[:120])
    check("6b ...stamped positive-covered", _stamped(sb, 21, "positive-covered"), str(sb.patches))


if __name__ == "__main__":
    for fn in (test_registry_is_complete, test_make_lane_fresh_positive_not_double_carded,
               test_make_lane_re_reply_reaches_shared_channel,
               test_make_lane_re_reply_flip_reaches_shared_channel,
               test_app_lane_fresh_positive_still_posts, test_unregistered_name_stays_internal):
        fn()
    sys.exit(1 if report() else 0)
